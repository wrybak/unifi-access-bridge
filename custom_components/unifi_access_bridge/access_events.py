"""Normalize UniFi Access websocket payloads."""

from __future__ import annotations

from typing import Any

from .access_helpers import (
    access_event_type,
    coerce_int,
    coerce_thumbnail_path,
    door_is_open,
    door_is_unlocked,
    first_display_name,
)
from .access_state import AccessStateStore
from .const import (
    DOORBELL_EVENT_RING,
    EVENT_CATEGORY_ACCESS,
    EVENT_CATEGORY_DOORBELL,
)
from .models import AccessUpdate, DoorEventPayload

LOCATION_UPDATE_EVENTS = {
    "access.data.device.location_update_v2",
    "access.data.v2.location.update",
    "access.data.location.update",
}
DOORBELL_EVENTS = {"access.remote_view", "access.hw.door_bell"}
ACCESS_LOG_EVENTS = {"access.logs.insights.add", "access.logs.add"}


class AccessEventParser:
    """Normalize raw websocket messages into integration updates."""

    def __init__(self, state_store: AccessStateStore) -> None:
        """Initialize the parser."""
        self._state_store = state_store

    def parse_message(self, payload: dict[str, Any]) -> list[AccessUpdate]:
        """Normalize a raw websocket message."""
        event_name = str(payload.get("event") or "")
        if event_name in LOCATION_UPDATE_EVENTS:
            return self._as_updates(self._parse_location_update(payload))
        if event_name == "access.data.v2.device.update":
            return self._parse_device_update(payload)
        if event_name == "access.data.device.remote_unlock":
            return self._as_updates(self._parse_remote_unlock(payload))
        if event_name in DOORBELL_EVENTS:
            return self._as_updates(self._parse_doorbell(payload))
        if event_name == "access.remote_view.change":
            self._parse_doorbell_stop(payload)
            return []
        if event_name in ACCESS_LOG_EVENTS:
            return self._as_updates(self._parse_access_event(payload))
        return []

    def _parse_location_update(
        self,
        payload: dict[str, Any],
    ) -> AccessUpdate | None:
        """Normalize location updates into a door-state update."""
        data = payload.get("data") or {}
        door_id = str(data.get("id") or data.get("unique_id") or "")
        if not door_id:
            return None
        changes: dict[str, Any] = {}
        state_payload = data.get("state")
        if isinstance(state_payload, dict):
            if "dps" in state_payload:
                changes["is_open"] = door_is_open(state_payload.get("dps"))
            if "lock" in state_payload:
                changes["is_unlocked"] = door_is_unlocked(state_payload.get("lock"))

        for thumbnail_payload in (data.get("thumbnail"), data.get("extras")):
            if not isinstance(thumbnail_payload, dict):
                continue
            thumbnail_path = coerce_thumbnail_path(
                thumbnail_payload.get("url") or thumbnail_payload.get("door_thumbnail")
            )
            if thumbnail_path is not None:
                changes["thumbnail_path"] = thumbnail_path
                changes["thumbnail_bytes"] = None
            thumbnail_updated_at = coerce_int(
                thumbnail_payload.get("door_thumbnail_last_update")
            )
            if thumbnail_updated_at is not None:
                changes["thumbnail_updated_at"] = thumbnail_updated_at

        updated = self._state_store.update(door_id, **changes)
        if updated is None:
            return None
        return AccessUpdate(door_state=updated)

    def _parse_device_update(self, payload: dict[str, Any]) -> list[AccessUpdate]:
        """Normalize device update messages with multiple location states."""
        updates: list[AccessUpdate] = []
        data = payload.get("data") or {}

        for location_state in data.get("location_states") or []:
            door_id = str(location_state.get("location_id") or "")
            if not door_id:
                continue

            changes: dict[str, Any] = {}
            if "dps" in location_state:
                changes["is_open"] = door_is_open(location_state.get("dps"))
            if "lock" in location_state:
                changes["is_unlocked"] = door_is_unlocked(location_state.get("lock"))

            updated = self._state_store.update(door_id, **changes)
            if updated is not None:
                updates.append(AccessUpdate(door_state=updated))

        return updates

    def _parse_remote_unlock(
        self,
        payload: dict[str, Any],
    ) -> AccessUpdate | None:
        """Normalize remote unlock messages."""
        data = payload.get("data") or {}
        door_id = str(data.get("unique_id") or data.get("id") or "")
        if not door_id:
            return None
        updated = self._state_store.update(door_id, is_unlocked=True)
        if updated is None:
            return None
        return AccessUpdate(door_state=updated)

    def _parse_doorbell(self, payload: dict[str, Any]) -> AccessUpdate | None:
        """Normalize doorbell events."""
        data = payload.get("data") or {}
        door_id = str(data.get("door_id") or "")
        if not door_id:
            door_id = self._state_store.resolve_door_id(str(data.get("door_name") or "")) or ""
        if not door_id:
            return None

        request_id = str(data.get("request_id") or "")
        if request_id:
            self._state_store.remember_doorbell_request(request_id, door_id)

        door = self._state_store.get(door_id)
        attributes = {
            "door_id": door_id,
            "door_name": door.name if door is not None else str(data.get("door_name") or door_id),
            "type": DOORBELL_EVENT_RING,
            "raw_event": str(payload.get("event")),
        }
        door_event = DoorEventPayload(
            door_id=door_id,
            category=EVENT_CATEGORY_DOORBELL,
            event_type=DOORBELL_EVENT_RING,
            attributes=attributes,
        )
        updated = self._state_store.apply_event(door_event)
        return AccessUpdate(door_state=updated, door_event=door_event)

    def _parse_doorbell_stop(self, payload: dict[str, Any]) -> None:
        """Track remote-view stop messages for future presses."""
        data = payload.get("data") or {}
        request_id = str(data.get("remote_call_request_id") or "")
        if request_id:
            self._state_store.forget_doorbell_request(request_id)

    def _parse_access_event(self, payload: dict[str, Any]) -> AccessUpdate | None:
        """Normalize access log and insight events."""
        if payload.get("event") == "access.logs.insights.add":
            door_event = self._parse_insights_event(payload)
        else:
            door_event = self._parse_logs_event(payload)
        if door_event is None:
            return None
        updated = self._state_store.apply_event(door_event)
        return AccessUpdate(door_state=updated, door_event=door_event)

    def _parse_insights_event(
        self,
        payload: dict[str, Any],
    ) -> DoorEventPayload | None:
        """Normalize insights.add into an access event."""
        data = payload.get("data") or {}
        metadata = data.get("metadata") or {}
        door_entries = metadata.get("door") or []
        if not door_entries:
            return None

        door_id = str(door_entries[0].get("id") or "")
        door = self._state_store.get(door_id)
        if not door_id or door is None:
            return None

        result = str(data.get("result") or "")
        return DoorEventPayload(
            door_id=door_id,
            category=EVENT_CATEGORY_ACCESS,
            event_type=access_event_type(result),
            attributes={
                "door_id": door_id,
                "door_name": door.name,
                "actor": (metadata.get("actor") or {}).get("display_name"),
                "authentication": (metadata.get("authentication") or {}).get("display_name"),
                "direction": first_display_name(metadata.get("opened_direction")),
                "method": first_display_name(metadata.get("opened_method")),
                "result": result,
                "raw_event": str(data.get("event_type") or payload.get("event")),
            },
        )

    def _parse_logs_event(self, payload: dict[str, Any]) -> DoorEventPayload | None:
        """Normalize logs.add into an access event fallback."""
        data = payload.get("data") or {}
        source = data.get("source") or {}
        door_id = ""

        for target in source.get("target") or []:
            if target.get("type") == "door":
                door_id = str(target.get("id") or "")
                break

        door = self._state_store.get(door_id)
        if not door_id or door is None:
            return None

        event = source.get("event") or {}
        result = str(event.get("result") or "")
        return DoorEventPayload(
            door_id=door_id,
            category=EVENT_CATEGORY_ACCESS,
            event_type=access_event_type(result),
            attributes={
                "door_id": door_id,
                "door_name": door.name,
                "actor": (source.get("actor") or {}).get("display_name"),
                "authentication": (source.get("authentication") or {}).get(
                    "credential_provider"
                ),
                "result": result,
                "raw_event": str(payload.get("event")),
            },
        )

    @staticmethod
    def _as_updates(update: AccessUpdate | None) -> list[AccessUpdate]:
        """Return a zero-or-one list for a parsed update."""
        return [] if update is None else [update]
