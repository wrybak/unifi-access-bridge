"""State storage helpers for UniFi Access doors."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .access_helpers import (
    coerce_int,
    coerce_thumbnail_path,
    copy_states,
    door_is_open,
    door_is_unlocked,
    normalize_name,
)
from .models import DoorEventPayload, DoorState


class AccessStateStore:
    """Manage normalized door state for the adapter."""

    def __init__(self) -> None:
        """Initialize the state store."""
        self._door_states: dict[str, DoorState] = {}
        self._door_names: dict[str, str] = {}
        self._doorbell_requests: dict[str, str] = {}

    def replace_from_raw_doors(
        self,
        raw_doors: list[dict[str, Any]],
    ) -> dict[str, DoorState]:
        """Replace all states from the raw doors payload."""
        new_states: dict[str, DoorState] = {}
        for raw_door in raw_doors:
            if raw_door.get("is_bind_hub") is False:
                continue

            door_id = str(raw_door.get("id") or "")
            if not door_id:
                continue

            previous = self._door_states.get(door_id)
            thumbnail_path = coerce_thumbnail_path(raw_door.get("door_thumbnail"))
            thumbnail_updated_at = coerce_int(raw_door.get("door_thumbnail_last_update"))

            new_states[door_id] = DoorState(
                door_id=door_id,
                name=str(raw_door.get("name") or door_id),
                full_name=str(raw_door.get("full_name") or raw_door.get("name") or door_id),
                is_open=door_is_open(raw_door.get("door_position_status")),
                is_unlocked=door_is_unlocked(raw_door.get("door_lock_relay_status")),
                thumbnail_path=thumbnail_path or (previous.thumbnail_path if previous else None),
                thumbnail_updated_at=thumbnail_updated_at
                if thumbnail_updated_at is not None
                else (previous.thumbnail_updated_at if previous else None),
                thumbnail_bytes=previous.thumbnail_bytes if previous else None,
                last_event_type=previous.last_event_type if previous else None,
                last_event_attributes=dict(previous.last_event_attributes) if previous else {},
                last_actor=previous.last_actor if previous else None,
            )

        self._door_states = new_states
        self._door_names = {
            normalize_name(state.name): door_id
            for door_id, state in self._door_states.items()
        }
        return copy_states(self._door_states)

    def get(self, door_id: str) -> DoorState | None:
        """Return the current state for a door."""
        return self._door_states.get(door_id)

    def update(self, door_id: str, **changes: Any) -> DoorState | None:
        """Replace and store a single door state."""
        state = self._door_states.get(door_id)
        if state is None or not changes:
            return state

        updated = replace(state, **changes)
        self._door_states[door_id] = updated
        self._door_names[normalize_name(updated.name)] = door_id
        return updated

    def apply_event(self, payload: DoorEventPayload) -> DoorState | None:
        """Persist the latest event metadata onto the current door state."""
        state = self._door_states.get(payload.door_id)
        if state is None:
            return None

        updated = state.with_event(payload)
        self._door_states[payload.door_id] = updated
        return updated

    def set_thumbnail_bytes(self, door_id: str, image_bytes: bytes) -> DoorState | None:
        """Cache thumbnail bytes on a door."""
        return self.update(door_id, thumbnail_bytes=image_bytes)

    def resolve_door_id(self, door_name: str) -> str | None:
        """Resolve a door id from a normalized name."""
        return self._door_names.get(normalize_name(door_name))

    def remember_doorbell_request(self, request_id: str, door_id: str) -> None:
        """Track a doorbell request id for later cleanup."""
        self._doorbell_requests[request_id] = door_id

    def forget_doorbell_request(self, request_id: str) -> None:
        """Drop a tracked doorbell request id."""
        self._doorbell_requests.pop(request_id, None)
