"""Shared fixtures for UniFi Access Bridge tests."""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from unittest.mock import patch

from homeassistant.helpers import entity_platform as _entity_platform
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.unifi_access_bridge.const import (
    CONF_API_TOKEN,
    CONF_OPENAPI_PORT,
    DOMAIN,
)
from custom_components.unifi_access_bridge.models import AccessUpdate, DoorState

if not hasattr(_entity_platform, "AddConfigEntryEntitiesCallback"):
    _entity_platform.AddConfigEntryEntitiesCallback = _entity_platform.AddEntitiesCallback

MOCK_HOST = "192.168.10.2"
MOCK_DOOR_ID = "door-001"
MOCK_CONFIG = {
    "host": MOCK_HOST,
    CONF_API_TOKEN: "token-123",
    "verify_ssl": False,
    CONF_OPENAPI_PORT: 12455,
}


def make_door_state(
    *,
    door_id: str = MOCK_DOOR_ID,
    name: str = "Front Door",
    is_open: bool = False,
    is_unlocked: bool = False,
    thumbnail_path: str | None = "/static/front-door.jpg",
    thumbnail_bytes: bytes | None = b"initial-snapshot",
) -> DoorState:
    """Create a normalized door state for tests."""
    return DoorState(
        door_id=door_id,
        name=name,
        full_name=f"Main Building / {name}",
        is_open=is_open,
        is_unlocked=is_unlocked,
        thumbnail_path=thumbnail_path,
        thumbnail_updated_at=1,
        thumbnail_bytes=thumbnail_bytes,
    )


class FakeAdapter:
    """Simple adapter stub for integration tests."""

    def __init__(self, *doors: DoorState, websocket_connected: bool = True) -> None:
        """Initialize the fake adapter."""
        self.websocket_connected = websocket_connected
        self._doors = {door.door_id: replace(door) for door in doors}
        self._listeners: list[Any] = []
        self.unlock_calls: list[str] = []
        self.closed = False
        self.thumbnail_responses: dict[str, bytes] = {
            door.door_id: door.thumbnail_bytes or b"snapshot"
            for door in doors
        }

    async def async_authenticate(self) -> None:
        """Pretend to authenticate."""

    async def async_get_doors(self) -> dict[str, DoorState]:
        """Return a copy of known door states."""
        return {
            door_id: replace(door, last_event_attributes=dict(door.last_event_attributes))
            for door_id, door in self._doors.items()
        }

    async def async_unlock_door(self, door_id: str) -> None:
        """Record unlock calls."""
        self.unlock_calls.append(door_id)

    async def async_refresh_thumbnail(self, door_id: str) -> bytes | None:
        """Return a configured thumbnail and update local door state."""
        image = self.thumbnail_responses.get(door_id)
        if image is None:
            return None

        if door_id in self._doors:
            self._doors[door_id] = replace(self._doors[door_id], thumbnail_bytes=image)
        return image

    async def async_close(self) -> None:
        """Mark the fake adapter as closed."""
        self.closed = True

    def async_subscribe_updates(self, listener):
        """Register a listener for coordinator pushes."""
        self._listeners.append(listener)

        def _unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return _unsubscribe

    def emit(self, update: AccessUpdate) -> None:
        """Emit a push update to subscribed listeners."""
        if update.websocket_connected is not None:
            self.websocket_connected = update.websocket_connected
        if update.door_state is not None:
            self._doors[update.door_state.door_id] = update.door_state
        for listener in list(self._listeners):
            listener(update)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations for all tests."""


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Create a mock config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="UniFi Access Bridge",
        data=MOCK_CONFIG,
        unique_id=f"{MOCK_HOST}:12455",
    )


@pytest.fixture
def fake_adapter() -> FakeAdapter:
    """Create a fake adapter with one front door."""
    return FakeAdapter(make_door_state())


@pytest.fixture
async def setup_integration(hass, mock_config_entry: MockConfigEntry, fake_adapter: FakeAdapter):
    """Set up the integration with a patched adapter factory."""
    mock_config_entry.add_to_hass(hass)

    with patch(
        "custom_components.unifi_access_bridge.async_create_access_adapter",
        return_value=(fake_adapter, 12455),
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        yield mock_config_entry, fake_adapter
        await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()
