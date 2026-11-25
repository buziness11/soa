"""Set up the Kafka topic and the versioned Protobuf contract before serving events."""
import json
import logging
import os
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from confluent_kafka import KafkaError, KafkaException
from confluent_kafka.admin import AdminClient, NewTopic

TOPIC = "movie-events"
PARTITIONS = 3
SUBJECT = f"{TOPIC}-value"
VERSION = 1
SCHEMA_FILE = Path(__file__).resolve().parents[1] / "schemas" / "movie_event.proto"
REGISTRY = os.getenv("SCHEMA_REGISTRY_URL", "http://schema-registry:8081").rstrip("/")
BROKERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
logger = logging.getLogger(__name__)


def registry_request(method: str, path: str, data: dict | None = None) -> dict:
    request = Request(
        f"{REGISTRY}{path}", method=method,
        data=json.dumps(data).encode() if data is not None else None,
        headers={"Content-Type": "application/vnd.schemaregistry.v1+json"},
    )
    with urlopen(request, timeout=5) as response:
        return json.load(response)


def schema_payload() -> dict:
    return {"schemaType": "PROTOBUF", "schema": SCHEMA_FILE.read_text(encoding="utf-8")}


def lookup_schema_id() -> int:
    # Lookup by content, not simply 'latest'. Registry normalizes Protobuf syntax.
    found = registry_request("POST", f"/subjects/{SUBJECT}?normalize=true", schema_payload())
    if found["version"] != VERSION:
        raise RuntimeError(f"Expected {SUBJECT} version {VERSION}, found {found['version']}")
    return found["id"]


def ensure_schema() -> None:
    registry_request("PUT", f"/config/{SUBJECT}", {"compatibility": "BACKWARD_TRANSITIVE"})
    try:
        registry_request("GET", f"/subjects/{SUBJECT}/versions/{VERSION}")
    except HTTPError as error:
        if error.code != 404:
            raise
        registry_request("POST", f"/subjects/{SUBJECT}/versions?normalize=true", schema_payload())
    schema_id = lookup_schema_id()
    logger.info("schema ready subject=%s version=%s id=%s", SUBJECT, VERSION, schema_id)


def ensure_topic() -> None:
    admin = AdminClient({"bootstrap.servers": BROKERS})
    future = admin.create_topics(
        [NewTopic(TOPIC, num_partitions=PARTITIONS, replication_factor=1)], request_timeout=8
    )[TOPIC]
    try:
        future.result()
    except KafkaException as error:
        if error.args[0].code() != KafkaError.TOPIC_ALREADY_EXISTS:
            raise
    topic = admin.list_topics(timeout=5).topics.get(TOPIC)
    if topic is None or topic.error:
        raise ConnectionError(f"Topic metadata unavailable for {TOPIC}")
    if len(topic.partitions) < PARTITIONS:
        raise RuntimeError(f"{TOPIC} requires at least {PARTITIONS} partitions")
    logger.info("topic ready name=%s partitions=%s", TOPIC, len(topic.partitions))


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    for attempt in range(10):
        try:
            ensure_topic()
            ensure_schema()
            return
        except HTTPError as error:
            if error.code < 500:
                reason = error.read().decode(errors="replace")
                raise RuntimeError(f"Schema Registry HTTP {error.code}: {reason}") from error
            failure = str(error)
        except (URLError, OSError, KafkaException) as error:
            failure = str(error)
        logger.warning("bootstrap retry attempt=%s reason=%s", attempt + 1, failure)
        if attempt == 9:
            raise RuntimeError(f"Bootstrap failed: {failure}")
        time.sleep(min(2 ** attempt, 8))


if __name__ == "__main__":
    main()
