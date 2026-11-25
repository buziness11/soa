import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from threading import Event, Thread

import psycopg
from fastapi import FastAPI, HTTPException

from .storage import materialize_and_export, scheduled_dates


log = logging.getLogger("uvicorn.error.aggregation")


def run_cycle(day: date) -> dict:
    start = time.monotonic()
    log.info("cycle start date=%s", day)
    try:
        for attempt in range(1, 5):
            try:
                processed, written = materialize_and_export(day)
                break
            except (psycopg.OperationalError, psycopg.InterfaceError) as exc:
                if attempt == 4:
                    raise
                delay = 2 ** (attempt - 1)
                log.warning("PostgreSQL retry date=%s attempt=%d delay=%ds error=%s",
                            day, attempt, delay, exc)
                time.sleep(delay)
    except Exception:
        log.exception("cycle failed date=%s elapsed_seconds=%.3f", day, time.monotonic() - start)
        raise
    elapsed = round(time.monotonic() - start, 3)
    log.info("cycle completed date=%s processed=%d metrics_written=%d elapsed_seconds=%.3f",
             day, processed, written, elapsed)
    return {"date": day.isoformat(), "processed": processed,
            "metrics_written": written, "elapsed_seconds": elapsed}


def scheduler(stop: Event, interval: int) -> None:
    while not stop.is_set():
        try:
            days = scheduled_dates(datetime.now(timezone.utc).date())
        except Exception:
            log.exception("scheduler could not list dates")
        else:
            for day in days:
                if stop.is_set():
                    return
                try:
                    run_cycle(day)
                except Exception:
                    # run_cycle has logged the failure; other days can still complete.
                    continue
        stop.wait(interval)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    interval = int(os.getenv("AGGREGATION_INTERVAL_SECONDS", "300"))
    if interval < 1:
        raise ValueError("AGGREGATION_INTERVAL_SECONDS must be positive")
    stop = Event()
    worker = Thread(target=scheduler, args=(stop, interval), daemon=True)
    worker.start()
    try:
        yield
    finally:
        stop.set()
        worker.join(timeout=5)


app = FastAPI(title="Cinema aggregation", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/recalculate/{day}")
def recalculate(day: date):
    if not date(1900, 1, 1) <= day <= datetime.now(timezone.utc).date():
        raise HTTPException(422, "Choose a UTC date between 1900-01-01 and today")
    try:
        return run_cycle(day)
    except Exception as exc:
        raise HTTPException(503, "Recalculation failed; see aggregation logs") from exc
