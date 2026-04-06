"""Coordinator for UniFi Access Bridge."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, UTC
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .access_api import (
    UnifiAccessAdapter,
    UnifiAccessAuthenticationError,
    UnifiAccessBridgeError,
)
from .models import AccessUpdate, DoorEventPayload, DoorState

_LOGGER = logging.getLogger(__name__)


class UnifiAccessBridgeCoordinator(DataUpdateCoordinator[dict[str, DoorState]]):
    """Shared Access state coordinator."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        adapter: UnifiAccessAdapter,
    ) -> None:
        """Initialize coordinator."""
        super().__init__(hass, logger=_LOGGER, name="unifi_access_bridge")
        self.adapter = adapter
        self.config_entry = entry
        self.websocket_connected = adapter.websocket_connected
        self.last_websocket_disconnect_at: datetime | None = None
        self._event_listeners: list[Callable[[DoorEventPayload], None]] = []
        self._unsubscribe_adapter: CALLBACK_TYPE | None = None

    async def _async_setup(self) -> None:
        """Subscribe to adapter pushes before the first refresh."""
        self._unsubscribe_adapter = self.adapter.async_subscribe_updates(
            self._handle_adapter_update
        )

    async def _async_update_data(self) -> dict[str, DoorState]:
        """Fetch the latest door state from Access."""
        try:
            doors = await self.adapter.async_get_doors()
        except UnifiAccessAuthenticationError as err:
            raise ConfigEntryAuthFailed from err
        except UnifiAccessBridgeError as err:
            raise UpdateFailed(str(err)) from err

        self.websocket_connected = self.adapter.websocket_connected
        return doors

    async def async_shutdown(self) -> None:
        """Tear down adapter subscriptions and websocket resources."""
        if self._unsubscribe_adapter is not None:
            self._unsubscribe_adapter()
            self._unsubscribe_adapter = None
        await self.adapter.async_close()

    async def async_unlock_door(self, door_id: str) -> None:
        """Unlock a door via Access API."""
        try:
            await self.adapter.async_unlock_door(door_id)
        except UnifiAccessAuthenticationError as err:
            raise ConfigEntryAuthFailed from err

    async def async_refresh_thumbnail(self, door_id: str) -> bytes | None:
        """Refresh thumbnail bytes for a door if available."""
        try:
            image_bytes = await self.adapter.async_refresh_thumbnail(door_id)
        except UnifiAccessAuthenticationError as err:
            raise ConfigEntryAuthFailed from err

        if image_bytes is None:
            return None

        door = self.data.get(door_id)
        if door is None:
            return image_bytes

        self.async_set_updated_data(
            {
                **self.data,
                door_id: replace(door, thumbnail_bytes=image_bytes),
            }
        )
        return image_bytes

    @callback
    def async_subscribe_door_events(
        self,
        listener: Callable[[DoorEventPayload], None],
    ) -> CALLBACK_TYPE:
        """Subscribe to normalized door events."""
        self._event_listeners.append(listener)

        def _unsubscribe() -> None:
            if listener in self._event_listeners:
                self._event_listeners.remove(listener)

        return _unsubscribe

    @callback
    def async_dispatch_event(self, payload: DoorEventPayload) -> None:
        """Dispatch a normalized door event to listeners."""
        for listener in list(self._event_listeners):
            listener(payload)

    @callback
    def _handle_adapter_update(self, update: AccessUpdate) -> None:
        """Merge adapter updates into coordinator state."""
        changed = False
        data = dict(self.data) if self.data else {}

        if update.websocket_connected is not None:
            self.websocket_connected = update.websocket_connected
            if update.websocket_connected:
                self.last_websocket_disconnect_at = None
            else:
                self.last_websocket_disconnect_at = datetime.now(tz=UTC)
            changed = True

        if update.door_state is not None:
            data[update.door_state.door_id] = update.door_state
            changed = True

        if update.door_event is not None:
            self.async_dispatch_event(update.door_event)
            changed = True

        if changed:
            self.async_set_updated_data(data)
