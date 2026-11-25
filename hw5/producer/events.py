"""HTTP input and the single conversion to the registered wire format."""
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from producer import movie_event_pb2 as proto

# Derive allowed API enum names from the compiled contract.
EventType = Enum("EventType", {name: name for name in proto.EventType.keys()}, type=str)
DeviceType = Enum("DeviceType", {name: name for name in proto.DeviceType.keys()}, type=str)
Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)]


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    user_id: Identifier
    movie_id: Identifier
    event_type: EventType
    timestamp: AwareDatetime
    device_type: DeviceType
    session_id: Identifier
    progress_seconds: Annotated[int, Field(strict=True, ge=0, le=2**32 - 1)] | None = None

    @field_validator("timestamp", mode="before")
    @classmethod
    def parse_timestamp(cls, value):
        if isinstance(value, datetime):
            return value
        if not isinstance(value, str):
            raise ValueError("timestamp must be an ISO 8601 string with a timezone")
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    @field_validator("timestamp")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        try:
            utc = value.astimezone(timezone.utc)
        except OverflowError as error:
            raise ValueError("timestamp is outside the supported range") from error
        if not 1900 <= utc.year <= 2299:
            raise ValueError("timestamp is outside the DateTime64(3) range")
        return utc.replace(microsecond=utc.microsecond // 1000 * 1000)

    @model_validator(mode="after")
    def check_progress(self):
        viewing = self.event_type.value.startswith("VIEW_")
        if viewing != (self.progress_seconds is not None):
            raise ValueError("progress_seconds must be present exactly for viewing events")
        return self

    @property
    def timestamp_utc(self) -> str:
        return self.timestamp.isoformat(timespec="milliseconds").replace("+00:00", "Z")

    def protobuf_bytes(self) -> bytes:
        message = proto.MovieEvent(
            event_id=str(self.event_id), user_id=self.user_id, movie_id=self.movie_id,
            event_type=proto.EventType.Value(self.event_type.value), timestamp=self.timestamp_utc,
            device_type=proto.DeviceType.Value(self.device_type.value), session_id=self.session_id,
        )
        if self.progress_seconds is not None:
            message.progress_seconds = self.progress_seconds
        # Proto2 SerializeToString also checks all required fields.
        return message.SerializeToString()
