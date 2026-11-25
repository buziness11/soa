"""End-to-end tests for a fresh Compose project; run ./test.sh."""
import json
import os
import time
import unittest
from datetime import date, datetime, timedelta
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

import psycopg
from confluent_kafka.admin import AdminClient

from aggregation.storage import clickhouse

MOVIE = "http://movie-service:8000"
AGGREGATION = "http://aggregation-service:8000"
REGISTRY = "http://schema-registry:8081"
DAY = date(2020, 1, 10)


def http(method, url, body=None):
    request = Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                      headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=60) as response:
        return response.status, json.load(response)


def event(user, movie, kind, day, progress=None):
    data = {
        "event_id": str(uuid4()), "user_id": user, "movie_id": movie,
        "session_id": f"{user}-{day}-{movie}", "device_type": "TV", "event_type": kind,
        "timestamp": f"{day}T09:10:11.123Z",
    }
    if progress is not None:
        data["progress_seconds"] = progress
    return data


def wait_raw(records):
    # Poll for the last stage of the asynchronous pipeline, without a fixed startup sleep.
    wanted = {row["event_id"] for row in records}
    ids = ",".join(f"toUUID('{key}')" for key in wanted)  # UUIDs created by this test.
    query = f"""
        SELECT toString(event_id) AS id, user_id, movie_id, session_id, event_type,
               device_type, progress_seconds, toUnixTimestamp64Milli(timestamp) AS millis
        FROM cinema.raw_events WHERE event_id IN ({ids}) FORMAT JSONEachRow
    """
    deadline = time.monotonic() + 75
    while True:
        rows = {row["id"]: row for row in map(json.loads, clickhouse(query).splitlines())}
        if set(rows) == wanted:
            return rows
        if time.monotonic() >= deadline:
            raise AssertionError(f"Missing events in ClickHouse: {wanted - rows.keys()}")
        time.sleep(0.3)


class PipelineTest(unittest.TestCase):
    def publish(self, data):
        self.assertEqual(http("POST", MOVIE + "/events", data), (201, {"event_id": data["event_id"]}))

    def test_topic_and_schema(self):
        meta = AdminClient({"bootstrap.servers": "kafka:9092"}).list_topics(timeout=10)
        self.assertGreaterEqual(len(meta.topics["movie-events"].partitions), 3)
        _, schema = http("GET", REGISTRY + "/subjects/movie-events-value/versions/1")
        self.assertEqual((schema["version"], schema["schemaType"]), (1, "PROTOBUF"))
        self.assertIn("message MovieEvent", schema["schema"])
        _, config = http("GET", REGISTRY + "/config/movie-events-value")
        self.assertEqual(config["compatibilityLevel"], "BACKWARD_TRANSITIVE")

    def test_http_kafka_clickhouse_fields(self):
        viewing = event("api-user", "test-film", "VIEW_PAUSED", DAY - timedelta(days=30), 17)
        viewing["timestamp"] = "2019-12-11T12:10:11.123+03:00"
        search = event("api-user", "test-film", "SEARCHED", DAY - timedelta(days=30))
        invalid = dict(viewing, event_id="bad-id")
        with self.assertRaises(HTTPError) as failure:
            http("POST", MOVIE + "/events", invalid)
        self.assertEqual(failure.exception.code, 422)
        for data in (viewing, search):
            self.publish(data)
        rows = wait_raw([viewing, search])
        for expected in (viewing, search):
            row = rows[expected["event_id"]]
            for field in ("user_id", "movie_id", "session_id", "event_type", "device_type"):
                self.assertEqual(row[field], expected[field])
            self.assertEqual(row["progress_seconds"], expected.get("progress_seconds"))
            instant = datetime.fromisoformat(expected["timestamp"])
            self.assertEqual(int(row["millis"]), int(instant.timestamp() * 1000))

    def test_daily_metrics_retention_and_upsert(self):
        # Two new viewers Alice/Bob, and a returning viewer Eve who is outside their cohort.
        previous, next_day, seventh = (DAY + timedelta(days=n) for n in (-1, 1, 7))
        records = [
            event("eve", "A", "VIEW_STARTED", previous, 0),
            event("alice", "A", "VIEW_STARTED", DAY, 0),
            event("alice", "A", "VIEW_FINISHED", DAY, 100),
            event("bob", "B", "VIEW_STARTED", DAY, 0),
            event("bob", "B", "VIEW_FINISHED", DAY, 200),
            event("eve", "A", "VIEW_STARTED", DAY, 0),
            event("extra", "A", "LIKED", DAY),
            event("alice", "B", "VIEW_STARTED", next_day, 0),
            event("alice", "B", "VIEW_STARTED", seventh, 0),
            event("bob", "A", "VIEW_STARTED", seventh, 0),
        ]
        for data in [*records, records[2]]:
            self.publish(data)
        wait_raw(records)
        expected = {
            ("dau", ""): 4, ("avg_watch_seconds", ""): 150, ("view_conversion", ""): 2 / 3,
            ("retention_d1", ""): 0.5, ("retention_d7", ""): 1,
            ("top_movie_views", "A"): 2, ("top_movie_views", "B"): 1,
        }

        def recalculate(processed):
            status, report = http("POST", f"{AGGREGATION}/recalculate/{DAY}")
            self.assertEqual((status, report["processed"], report["metrics_written"]), (200, processed, len(expected)))
            with psycopg.connect(os.environ["POSTGRES_DSN"]) as db:
                result = db.execute("SELECT metric_name, dimension, value FROM daily_metrics WHERE metric_date = %s", (DAY,)).fetchall()
            self.assertEqual(len(result), len(expected))
            self.assertEqual({(name, dim): val for name, dim, val in result}, expected)
            snapshot = json.loads(clickhouse("SELECT * FROM cinema.daily_metrics FINAL WHERE metric_date = {d:Date32} FORMAT JSONEachRow", d=DAY.isoformat()))
            self.assertEqual(snapshot["processed"], processed)
            self.assertEqual(snapshot["top_movies"], [[movie, expected["top_movie_views", movie]] for movie in ("A", "B")])
            for (name, dim), value in expected.items():
                if not dim:
                    self.assertEqual(snapshot[name], value)

        recalculate(6)
        recalculate(6)
        # Late start changes DAU, top and conversion, and expands the D1/D7 cohort.
        late = event("late", "B", "VIEW_STARTED", DAY, 0)
        self.publish(late)
        wait_raw([late])
        expected.update({("dau", ""): 5, ("view_conversion", ""): 0.5,
                         ("top_movie_views", "B"): 2, ("retention_d1", ""): 1 / 3,
                         ("retention_d7", ""): 2 / 3})
        recalculate(7)

    def test_scheduler_exports_without_http_recalculation(self):
        day = DAY + timedelta(days=60)
        data = event("scheduler-only", "A", "SEARCHED", day)
        self.publish(data)
        wait_raw([data])
        deadline = time.monotonic() + 45
        while True:
            with psycopg.connect(os.environ["POSTGRES_DSN"]) as db:
                values = dict(db.execute("""
                    SELECT metric_name, value FROM daily_metrics
                    WHERE metric_date = %s AND dimension = ''
                """, (day,)).fetchall())
            if values.get("dau") == 1:
                break
            if time.monotonic() >= deadline:
                self.fail(f"Scheduler did not export {day}: {values}")
            time.sleep(0.5)
        for name in ("avg_watch_seconds", "view_conversion", "retention_d1", "retention_d7"):
            self.assertIsNone(values[name])
