"""Helper utilities for the UniFi Access adapter layer."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .const import ACCESS_EVENT_DENIED, ACCESS_EVENT_GRANTED
from .models import DoorState


def host_with_port(host: str, port: int) -> str:
    """Return a host string that includes HTTPS and an explicit port."""
    normalized_host = host.strip()
    if "://" in normalized_host:
        normalized_host = normalized_host.split("://", maxsplit=1)[1]
    return f"https://{normalized_host}:{port}"


def normalize_name(name: str) -> str:
    """Normalize a door name for loose matching."""
    return " ".join(name.casefold().split())


def door_is_open(value: Any) -> bool:
    """Return whether a raw door position represents an open state."""
    return str(value or "").casefold() == "open"


def door_is_unlocked(value: Any) -> bool:
    """Return whether a raw relay status represents an unlocked state."""
    return str(value or "").casefold() in {"unlock", "unlocked"}


def access_event_type(result: str) -> str:
    """Map controller access results into stable event types."""
    normalized = result.casefold()
    if normalized in {"access", "allow", "allowed", "granted", "success"}:
        return ACCESS_EVENT_GRANTED
    return ACCESS_EVENT_DENIED


def coerce_int(value: Any) -> int | None:
    """Coerce an arbitrary value to an integer when possible."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def coerce_thumbnail_path(value: Any) -> str | None:
    """Normalize a thumbnail path from Access payloads."""
    if not value:
        return None
    return str(value)


def thumbnail_url(base_host: str, thumbnail_path: str) -> str:
    """Return a fully-qualified thumbnail URL."""
    if thumbnail_path.startswith(("http://", "https://")):
        return thumbnail_path
    if thumbnail_path.startswith("/"):
        return f"{base_host}{thumbnail_path}"
    return f"{base_host}/{thumbnail_path}"


def first_display_name(values: Any) -> str | None:
    """Return the first display name from a metadata list."""
    if not isinstance(values, list) or not values:
        return None
    if not isinstance(values[0], dict):
        return None
    value = values[0].get("display_name")
    return str(value) if value is not None else None


def copy_states(states: dict[str, DoorState]) -> dict[str, DoorState]:
    """Return a shallow copy of normalized door states."""
    return {
        door_id: replace(state, last_event_attributes=dict(state.last_event_attributes))
        for door_id, state in states.items()
    }
