"""Publish one ProtobufSingle value and wait for Kafka before reporting success."""
import logging
import time
from concurrent.futures import Future

from confluent_kafka import KafkaException, Producer

from producer.bootstrap import BROKERS, TOPIC, VERSION
from producer.events import Event

logger = logging.getLogger(__name__)


class Publisher:
    def __init__(self, schema_id: int):
        self.schema_id = schema_id
        self.kafka = Producer({
            "bootstrap.servers": BROKERS,
            "enable.idempotence": True,
            "acks": "all",
            "retries": 8,
            "retry.backoff.ms": 100,        # librdkafka doubles the delay up to the cap.
            "retry.backoff.max.ms": 2000,
            "delivery.timeout.ms": 12000,
        })

    def publish(self, event: Event) -> None:
        delivery = Future()

        def delivered(error, message):
            if error is not None:
                delivery.set_exception(KafkaException(error))
            else:
                delivery.set_result((message.partition(), message.offset()))

        # Native ProtobufSingle payload for ClickHouse; schema metadata is in Kafka headers.
        self.kafka.produce(
            TOPIC, key=event.user_id.encode(), value=event.protobuf_bytes(),
            headers={"schema-id": str(self.schema_id), "schema-version": str(VERSION)},
            on_delivery=delivered,
        )
        deadline = time.monotonic() + 15
        while not delivery.done():
            if time.monotonic() >= deadline:
                raise TimeoutError("Kafka delivery confirmation timed out")
            self.kafka.poll(0.1)
        partition, offset = delivery.result()
        logger.info(
            "published event_id=%s event_type=%s timestamp=%s partition=%s offset=%s",
            event.event_id, event.event_type.value, event.timestamp_utc, partition, offset,
        )

    def close(self) -> None:
        self.kafka.flush(15)
