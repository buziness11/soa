import json
import random
import unittest
from datetime import datetime, timezone

from pydantic import ValidationError

from producer.events import Event
from producer.generator import session_events
from producer.movie_event_pb2 import EventType, MovieEvent


class ProducerContractTests(unittest.TestCase):
    def setUp(self):
        self.payload = {
            "event_id": "ac91d459-08a3-4131-a3c4-9e82c4225fb7",
            "user_id": "user-1", "movie_id": "movie-7", "session_id": "session-4",
            "timestamp": "2025-12-01T01:20:30.456789+03:00", "device_type": "TV",
            "event_type": "VIEW_STARTED", "progress_seconds": 0,
        }

    def test_protobuf_round_trip_and_utc(self):
        event = Event.model_validate_json(json.dumps(self.payload))
        decoded = MovieEvent.FromString(event.protobuf_bytes())
        self.assertTrue(decoded.IsInitialized())
        for field in ("event_id", "session_id", "user_id", "movie_id"):
            self.assertEqual(getattr(decoded, field), self.payload[field])
        self.assertEqual(decoded.timestamp, "2025-11-30T22:20:30.456Z")
        self.assertEqual(EventType.Name(decoded.event_type), "VIEW_STARTED")
        self.assertEqual(decoded.device_type, 3)  # TV in schema v1.
        self.assertTrue(decoded.HasField("progress_seconds"))
        self.assertEqual(decoded.progress_seconds, 0)

    def test_non_view_omits_progress_on_the_wire(self):
        del self.payload["progress_seconds"]
        for kind in ("SEARCHED", "LIKED"):
            with self.subTest(kind=kind):
                event = Event.model_validate(self.payload | {"event_type": kind})
                msg = MovieEvent.FromString(event.protobuf_bytes())
                self.assertFalse(msg.HasField("progress_seconds"))

    def test_invalid_http_payloads(self):
        invalid = [
            {"event_id": "invalid"}, {"session_id": " "}, {"extra_field": "unused"},
            {"event_type": "REWIND"}, {"device_type": "TOASTER"}, {"timestamp": "2026-01-01T10:30:00"},
            {"progress_seconds": True}, {"progress_seconds": -1}, {"progress_seconds": None},
            {"progress_seconds": 2**32}, {"event_type": "LIKED"},  # Inherits progress=0.
        ]
        for change in invalid:
            with self.subTest(change=change), self.assertRaises(ValidationError):
                Event.model_validate_json(json.dumps(self.payload | change))
        for field in self.payload:
            with self.subTest(missing=field), self.assertRaises(ValidationError):
                Event.model_validate({k: v for k, v in self.payload.items() if k != field})

    def test_generator_session_order_and_history(self):
        now = datetime(2026, 11, 25, 12, tzinfo=timezone.utc)
        rng = random.Random(23)
        kinds_seen, event_ages = set(), set()
        returning_users = {}
        saw_abandoned = False
        for _ in range(150):
            events = session_events(now, rng)
            self.assertEqual(len({(e.user_id, e.session_id, e.movie_id, e.device_type) for e in events}), 1)
            kinds = [e.event_type.value for e in events]
            kinds_seen.update(kinds)
            for left, right in zip(events, events[1:]):
                self.assertLess(left.timestamp, right.timestamp)
            self.assertLessEqual(events[-1].timestamp, now)
            viewing = [e for e in events if e.event_type.value.startswith("VIEW_")]
            self.assertEqual(viewing[0].event_type.value, "VIEW_STARTED")
            self.assertEqual(viewing[0].progress_seconds, 0)
            for before, after in zip(viewing, viewing[1:]):
                self.assertLess(before.progress_seconds, after.progress_seconds)
            if "SEARCHED" in kinds:
                self.assertEqual(kinds[0], "SEARCHED")
            if "VIEW_PAUSED" in kinds:
                self.assertEqual(kinds[kinds.index("VIEW_PAUSED") + 1], "VIEW_RESUMED")
            if "VIEW_FINISHED" in kinds:
                self.assertEqual(viewing[-1].event_type.value, "VIEW_FINISHED")
            else:
                saw_abandoned = True
            if "LIKED" in kinds:
                self.assertGreater(kinds.index("LIKED"), kinds.index("VIEW_FINISHED"))
            day = viewing[0].timestamp.date()
            returning_users.setdefault(viewing[0].user_id, set()).add(day)
            event_ages.add((now.date() - day).days)
        self.assertTrue(saw_abandoned)
        self.assertEqual(kinds_seen, set(EventType.keys()))
        self.assertEqual(event_ages, {0, 1, 2, 7, 8})
        self.assertTrue(any(len(days) > 1 for days in returning_users.values()))


if __name__ == "__main__":
    unittest.main()
