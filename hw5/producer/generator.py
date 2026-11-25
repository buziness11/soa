"""Generate complete or abandoned playback sessions, with plausible event-time gaps."""
import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from confluent_kafka import KafkaException

from producer.events import Event
from producer.publisher import Publisher

logger = logging.getLogger(__name__)


def session_events(now: datetime, rng: random.Random) -> list[Event]:
    length = rng.randint(1200, 7200)
    pause_at = rng.randint(60, length // 2)
    pause_duration = rng.randint(10, 300)
    paused = rng.random() < 0.75
    finishes = rng.random() < 0.8
    # A mix of past and current sessions gives the demo D1/D7 cohorts.
    age_days = rng.choice([0, 0, 0, 1, 2, 7, 8])
    start = now - timedelta(days=age_days, seconds=length + pause_duration + 2)
    base = {
        "session_id": str(uuid4()), "user_id": f"demo-user-{rng.randrange(30)}",
        "movie_id": f"demo-movie-{rng.randrange(12)}", "device_type": rng.choice(["MOBILE", "DESKTOP", "TV", "TABLET"]),
    }
    events = []

    def add(kind: str, elapsed: int, progress: int | None = None):
        events.append(Event(
            **base, event_id=uuid4(), event_type=kind, timestamp=start + timedelta(seconds=elapsed),
            progress_seconds=progress,
        ))

    if rng.random() < 0.6:
        add("SEARCHED", -10)
    add("VIEW_STARTED", 0, 0)
    if paused:
        add("VIEW_PAUSED", pause_at, pause_at)
        add("VIEW_RESUMED", pause_at + pause_duration + 1, pause_at + 1)
    if finishes:
        end = length + (pause_duration if paused else 0)
        add("VIEW_FINISHED", end, length)
        if rng.random() < 0.5:
            add("LIKED", end + 1)
    return events


async def generate(publisher: Publisher, interval: float) -> None:
    rng = random.Random()
    while True:
        try:
            for event in session_events(datetime.now(timezone.utc), rng):
                # Confirm each publication before advancing the same session.
                await asyncio.to_thread(publisher.publish, event)
        except (KafkaException, BufferError, TimeoutError):
            logger.exception("generator abandoned this session after delivery failure")
        await asyncio.sleep(interval)
