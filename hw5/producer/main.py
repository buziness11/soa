import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress

from confluent_kafka import KafkaException
from fastapi import FastAPI, HTTPException, Request

from producer.bootstrap import lookup_schema_id
from producer.events import Event
from producer.generator import generate
from producer.publisher import Publisher

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    interval = float(os.getenv("GENERATOR_INTERVAL_SECONDS", "5"))
    if interval < 0:
        raise ValueError("GENERATOR_INTERVAL_SECONDS must be at least zero")
    publisher = Publisher(lookup_schema_id())
    app.state.publisher = publisher
    task = asyncio.create_task(generate(publisher, interval)) if interval > 0 else None
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await asyncio.to_thread(publisher.close)


app = FastAPI(title="Movie Service", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/events", status_code=201)
def submit(event: Event, request: Request):
    try:
        request.app.state.publisher.publish(event)
    except (KafkaException, BufferError, TimeoutError) as error:
        logger.exception("delivery failed event_id=%s", event.event_id)
        raise HTTPException(status_code=503, detail="Kafka delivery was not confirmed") from error
    return {"event_id": str(event.event_id)}
