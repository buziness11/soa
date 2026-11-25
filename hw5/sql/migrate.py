"""Apply the initial, re-runnable DDL in dependency order on every Compose start."""
import logging
import os
from pathlib import Path

import psycopg

from aggregation.storage import clickhouse

HERE = Path(__file__).resolve().parent


def main():
    logging.basicConfig(level=logging.INFO)
    for path in [*sorted((HERE / "ingestion").glob("*.sql")), HERE / "aggregate/clickhouse.sql"]:
        clickhouse(path.read_text())
        logging.info("applied ClickHouse %s", path.name)
    with psycopg.connect(os.environ["POSTGRES_DSN"]) as connection:
        connection.execute((HERE / "aggregate/postgres.sql").read_text())
    logging.info("applied PostgreSQL daily_metrics")


if __name__ == "__main__":
    main()
