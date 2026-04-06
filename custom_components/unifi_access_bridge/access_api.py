"""Async-safe UniFi Access adapter facade."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback

from .access_client import AccessClient, build_library_client, import_access_library
from .access_errors import (
    UnifiAccessAuthenticationError,
    UnifiAccessBridgeError,
    UnifiAccessCannotConnectError,
    UnifiAccessSSLError,
)
from .access_events import AccessEventParser
from .access_helpers import host_with_port, thumbnail_url
from .access_state import AccessStateStore
from .const import DEFAULT_OPENAPI_PORTS
from .models import AccessUpdate, DoorState


class UnifiAccessAdapter:
    """Async-safe wrapper around the upstream UniFi Access client."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        host: str,
        api_token: str,
        verify_ssl: bool,
        port: int,
    ) -> None:
        """Initialize the adapter."""
        self._hass = hass
        self._api_token = api_token
        self._resolved_port = port
        self._listeners: list[Callable[[AccessUpdate], None]] = []
        self._websocket_connected = False
        self._state_store = AccessStateStore()
        self._library = import_access_library()
        self._client: AccessClient = build_library_client(
            library=self._library,
            host=host_with_port(host, port),
            verify_ssl=verify_ssl,
            on_message=self._schedule_message,
            on_connection_state=self._schedule_connection_state,
        )
        self._event_parser = AccessEventParser(self._state_store)

    @property
    def resolved_port(self) -> int:
        """Return the port selected for this adapter."""
        return self._resolved_port

    @property
    def websocket_connected(self) -> bool:
        """Return whether the websocket is currently connected."""
        return self._websocket_connected

    async def async_authenticate(self) -> None:
        """Authenticate and start websocket updates."""
        status = await self._hass.async_add_executor_job(
            self._client.authenticate,
            self._api_token,
        )
        if status == "ok":
            return
        if status == "api_auth_error":
            raise UnifiAccessAuthenticationError("Invalid UniFi Access token")
        if status == "ssl_error":
            raise UnifiAccessSSLError("SSL verification failed")
        raise UnifiAccessCannotConnectError(f"Unable to connect to {self._client.host}")

    async def async_get_doors(self) -> dict[str, DoorState]:
        """Fetch and normalize all bound doors."""
        try:
            raw_doors = await self._hass.async_add_executor_job(
                self._client.fetch_raw_doors
            )
        except self._library.auth_error as err:
            raise UnifiAccessAuthenticationError from err
        except self._library.api_error as err:
            raise UnifiAccessCannotConnectError("Unable to fetch doors from UniFi Access") from err
        return self._state_store.replace_from_raw_doors(raw_doors)

    async def async_unlock_door(self, door_id: str) -> None:
        """Unlock a door via the Access API."""
        try:
            await self._hass.async_add_executor_job(self._client.unlock_door, door_id)
        except self._library.auth_error as err:
            raise UnifiAccessAuthenticationError from err
        except self._library.api_error as err:
            raise UnifiAccessCannotConnectError(
                f"Unable to unlock door {door_id}"
            ) from err

    async def async_refresh_thumbnail(self, door_id: str) -> bytes | None:
        """Fetch the latest thumbnail for a door."""
        state = self._state_store.get(door_id)
        if state is None or not state.thumbnail_path:
            return None

        try:
            image_bytes = await self._hass.async_add_executor_job(
                self._client.fetch_thumbnail_image,
                thumbnail_url(self._client.host, state.thumbnail_path),
            )
        except self._library.auth_error as err:
            raise UnifiAccessAuthenticationError from err
        except self._library.api_error as err:
            raise UnifiAccessCannotConnectError(
                f"Unable to fetch thumbnail for door {door_id}"
            ) from err
        self._state_store.set_thumbnail_bytes(door_id, image_bytes)
        return image_bytes

    async def async_close(self) -> None:
        """Close the underlying websocket client."""
        await self._hass.async_add_executor_job(self._client.close)

    @callback
    def async_subscribe_updates(
        self,
        listener: Callable[[AccessUpdate], None],
    ) -> CALLBACK_TYPE:
        """Subscribe to adapter updates."""
        self._listeners.append(listener)

        def _unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return _unsubscribe

    def _schedule_message(self, payload: dict[str, Any]) -> None:
        """Forward websocket messages from the thread into the event loop."""
        self._hass.loop.call_soon_threadsafe(self._handle_message, payload)

    def _schedule_connection_state(self, connected: bool) -> None:
        """Forward websocket connection state changes into the event loop."""
        self._hass.loop.call_soon_threadsafe(self._handle_connection_state, connected)

    @callback
    def _handle_connection_state(self, connected: bool) -> None:
        """Record websocket state and notify listeners."""
        self._websocket_connected = connected
        self._emit_update(AccessUpdate(websocket_connected=connected))

    @callback
    def _handle_message(self, payload: dict[str, Any]) -> None:
        """Normalize raw websocket payloads into adapter updates."""
        for update in self._event_parser.parse_message(payload):
            self._emit_update(update)

    @callback
    def _emit_update(self, update: AccessUpdate) -> None:
        """Emit an adapter update to all listeners."""
        for listener in list(self._listeners):
            listener(update)


async def async_create_access_adapter(
    hass: HomeAssistant,
    *,
    host: str,
    api_token: str,
    verify_ssl: bool,
    requested_port: int | None,
) -> tuple[UnifiAccessAdapter, int]:
    """Create and authenticate an adapter, probing common ports when needed."""
    candidates = (requested_port,) if requested_port is not None else DEFAULT_OPENAPI_PORTS

    last_error: UnifiAccessBridgeError | None = None
    for port in candidates:
        adapter = UnifiAccessAdapter(
            hass,
            host=host,
            api_token=api_token,
            verify_ssl=verify_ssl,
            port=port,
        )
        try:
            await adapter.async_authenticate()
        except UnifiAccessAuthenticationError:
            await adapter.async_close()
            raise
        except UnifiAccessSSLError:
            await adapter.async_close()
            raise
        except UnifiAccessBridgeError as err:
            last_error = err
            await adapter.async_close()
            if requested_port is not None:
                raise
            continue
        else:
            return adapter, port

    if last_error is not None:
        raise last_error
    raise UnifiAccessCannotConnectError("No UniFi Access OpenAPI port candidates configured")
