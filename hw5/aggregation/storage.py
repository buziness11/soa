import json
import os
from datetime import date
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import psycopg


COMPUTE_SQL = Path(__file__).with_name("compute.sql").read_text()
SCALARS = ("dau", "avg_watch_seconds", "view_conversion", "retention_d1", "retention_d7")


def clickhouse(sql: str, **params: str) -> bytes:
    options = {
        "wait_end_of_query": "1",
        "output_format_json_quote_64bit_integers": "0",
        **{f"param_{key}": value for key, value in params.items()},
    }
    url = os.getenv("CLICKHOUSE_URL", "http://clickhouse:8123").rstrip("/")
    request = Request(f"{url}/?{urlencode(options)}", data=sql.encode(), headers={
        "X-ClickHouse-User": os.getenv("CLICKHOUSE_USER", "default"),
        "X-ClickHouse-Key": os.getenv("CLICKHOUSE_PASSWORD", ""),
    })
    try:
        with urlopen(request, timeout=120) as response:
            return response.read()
    except HTTPError as exc:
        detail = exc.read(2000).decode(errors="replace")
        raise RuntimeError(f"ClickHouse HTTP {exc.code}: {detail}") from exc


def scheduled_dates(today: date) -> list[date]:
    # Historical backfills can shift the date of a user's first-ever view.
    # Revisit every populated date, plus dates already shown to readers.
    query = """
        SELECT DISTINCT day FROM (
            SELECT toDate32(timestamp, 'UTC') AS day FROM cinema.raw_events
            UNION ALL
            SELECT metric_date AS day FROM cinema.daily_metrics
            UNION ALL
            SELECT {today:Date32} AS day
        ) WHERE day <= {today:Date32} ORDER BY day DESC FORMAT TSV
    """
    result = clickhouse(query, today=today.isoformat()).decode().splitlines()
    return [date.fromisoformat(day) for day in result]


def save_to_postgres(cursor, day: date, snapshot: dict) -> int:
    scores = snapshot["top_movies"]
    metrics = [(name, "", snapshot[name]) for name in SCALARS]
    metrics.extend(("top_movie_views", movie, views) for movie, views in scores)

    # Recalculation can push a former top-ten film out of the ranking.
    cursor.execute("""
        DELETE FROM daily_metrics WHERE metric_date = %s AND metric_name = 'top_movie_views'
        AND NOT (dimension = ANY(%s::text[]))
    """, (day, [movie for movie, _ in scores]))
    cursor.executemany("""
        INSERT INTO daily_metrics (metric_date, metric_name, dimension, value, computed_at)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (metric_date, metric_name, dimension)
        DO UPDATE SET value = EXCLUDED.value, computed_at = EXCLUDED.computed_at
    """, [(day, name, dimension, value, snapshot["computed_at"] + "+00")
          for name, dimension, value in metrics])
    return len(metrics)


def materialize_and_export(day: date) -> tuple[int, int]:
    # The transaction-scoped lock covers both stores. Concurrent HTTP calls
    # and scheduler processes cannot export older results over a newer cycle.
    with psycopg.connect(os.environ["POSTGRES_DSN"], connect_timeout=5) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", (503, day.toordinal()))
            cursor.execute("SELECT clock_timestamp() AT TIME ZONE 'UTC'")
            (computed_at,) = cursor.fetchone()
            clickhouse(COMPUTE_SQL, day=day.isoformat(), as_of=computed_at.date().isoformat(),
                       computed_at=computed_at.isoformat(sep=" ", timespec="microseconds"))
            result = clickhouse("""
                SELECT * FROM cinema.daily_metrics FINAL
                WHERE metric_date = {day:Date32} FORMAT JSONEachRow
            """, day=day.isoformat())
            snapshot = json.loads(result)
            written = save_to_postgres(cursor, day, snapshot)
    return snapshot["processed"], written
