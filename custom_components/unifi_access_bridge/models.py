"""Domain models for UniFi Access Bridge."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any


class CameraSourceType(StrEnum):
    """Supported camera source types."""

    HA_CAMERA = "ha_camera"
    RTSP = "rtsp"
    SNAPSHOT = "snapshot"


@dataclass(slots=True)
class CameraMapping:
    """User-defined mapping of a door to a camera source."""

    door_id: str
    source_type: CameraSourceType = CameraSourceType.SNAPSHOT
    value: str | None = None

    @classmethod
    def from_dict(cls, door_id: str, raw: dict[str, Any] | None) -> CameraMapping:
        """Build a mapping from config entry data."""
        if not raw:
            return cls(door_id=door_id)

        source_type = raw.get("source_type", CameraSourceType.SNAPSHOT)
        return cls(
            door_id=raw.get("door_id", door_id),
            source_type=CameraSourceType(source_type),
            value=raw.get("value"),
        )

    def as_dict(self) -> dict[str, str | None]:
        """Serialize the mapping for config entry options."""
        return {
            "door_id": self.door_id,
            "source_type": self.source_type.value,
            "value": self.value,
        }


@dataclass(slots=True)
class DoorState:
    """Normalized state for a UniFi Access door."""

    door_id: str
    name: str
    full_name: str
    is_open: bool = False
    is_unlocked: bool = False
    thumbnail_path: str | None = None
    thumbnail_updated_at: int | None = None
    thumbnail_bytes: bytes | None = None
    last_event_type: str | None = None
    last_event_attributes: dict[str, Any] = field(default_factory=dict)
    last_actor: str | None = None

    def with_event(self, payload: DoorEventPayload) -> DoorState:
        """Return a copy with the latest event metadata applied."""
        return replace(
            self,
            last_event_type=payload.event_type,
            last_event_attributes=dict(payload.attributes),
            last_actor=payload.attributes.get("actor"),
        )


@dataclass(slots=True)
class DoorEventPayload:
    """Normalized event payload for a door."""

    door_id: str
    category: str
    event_type: str
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AccessUpdate:
    """Single adapter update emitted to the coordinator."""

    door_state: DoorState | None = None
    door_event: DoorEventPayload | None = None
    websocket_connected: bool | None = None
