"""UniFi Access adapter with async-safe Home Assistant wrappers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
import json
import logging
import ssl
from typing import Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback

from .const import (
    ACCESS_EVENT_DENIED,
    ACCESS_EVENT_GRANTED,
    DEFAULT_OPENAPI_PORTS,
    DOORBELL_EVENT_RING,
    EVENT_CATEGORY_ACCESS,
    EVENT_CATEGORY_DOORBELL,
)
from .models import AccessUpdate, DoorEventPayload, DoorState

_LOGGER = logging.getLogger(__name__)


class UnifiAccessBridgeError(Exception):
    """Base adapter error."""


class UnifiAccessAuthenticationError(UnifiAccessBridgeError):
    """Raised when the Access controller rejects credentials."""


class UnifiAccessCannotConnectError(UnifiAccessBridgeError):
    """Raised when the Access controller cannot be reached."""


class UnifiAccessSSLError(UnifiAccessBridgeError):
    """Raised when SSL verification fails."""


class UnifiAccessDependencyError(UnifiAccessBridgeError):
    """Raised when the upstream client dependency is unavailable."""


def _import_access_library() -> tuple[type[Any], type[Exception], type[Exception], str, str]:
    """Import the upstream UniFi Access library lazily."""
    try:
        from unifi_access_api import ApiAuthError, ApiError, UnifiAccessApiClient
        from unifi_access_api.const import DEVICE_NOTIFICATIONS_URL, DOORS_URL
    except ImportError as err:
        raise UnifiAccessDependencyError(
            "py-unifi-access is not installed"
        ) from err

    return (
        UnifiAccessApiClient,
        ApiAuthError,
        ApiError,
        DEVICE_NOTIFICATIONS_URL,
        DOORS_URL,
    )


def _build_library_client(
    *,
    host: str,
    verify_ssl: bool,
    on_message: Callable[[dict[str, Any]], None],
    on_connection_state: Callable[[bool], None],
) -> Any:
    """Create a patched upstream client that exposes raw websocket events."""
    (
        unifi_access_api_client,
        _api_auth_error,
        _api_error,
        device_notifications_url,
        _doors_url,
    ) = _import_access_library()

    class ThreadAwareUnifiAccessClient(unifi_access_api_client):  # type: ignore[misc, valid-type]
        """Small subclass that keeps websocket callbacks observable."""

        def __init__(self) -> None:
            super().__init__(host=host, verify_ssl=verify_ssl, use_polling=False)
            self._bridge_on_message = on_message
            self._bridge_on_connection_state = on_connection_state
            self._bridge_should_stop = False
            self._bridge_websocket_app: Any | None = None

        def on_message(self, ws: Any, message: str) -> None:
            """Process websocket messages from Access."""
            if "Hello" in message:
                return

            try:
                payload = json.loads(message)
            except json.JSONDecodeError:
                _LOGGER.debug("Ignoring malformed websocket message: %s", message)
                return

            self._bridge_on_message(payload)

        def on_error(self, ws: Any, error: Any) -> None:
            """Track websocket failures for reconnection handling."""
            self._bridge_on_connection_state(False)
            _LOGGER.debug("UniFi Access websocket error: %s", error)

        def on_open(self, ws: Any) -> None:
            """Mark the websocket as connected."""
            self._bridge_on_connection_state(True)
            _LOGGER.debug("UniFi Access websocket connected")

        def on_close(self, ws: Any, close_status_code: Any, close_msg: Any) -> None:
            """Reconnect the websocket until the adapter is explicitly closed."""
            self._bridge_on_connection_state(False)
            _LOGGER.debug(
                "UniFi Access websocket closed code=%s message=%s",
                close_status_code,
                close_msg,
            )
            if not self._bridge_should_stop:
                self._run_forever(ws)

        def _run_forever(self, ws: Any) -> None:
            """Run the websocket loop with reconnect enabled."""
            sslopt: dict[str, Any] = {"cert_reqs": ssl.CERT_REQUIRED}
            if verify_ssl is False:
                sslopt = {"cert_reqs": ssl.CERT_NONE}
            ws.run_forever(sslopt=sslopt, reconnect=5)

        def listen_for_updates(self) -> None:
            """Create and run the websocket client."""
            import websocket

            uri = f"{self.websocket_host}{device_notifications_url}"
            ws = websocket.WebSocketApp(
                uri,
                header=self._websocket_headers,
                on_message=self.on_message,
                on_error=self.on_error,
                on_open=self.on_open,
                on_close=self.on_close,
            )
            self._bridge_websocket_app = ws
            self._run_forever(ws)

        def close(self) -> None:
            """Stop reconnecting and close the websocket if one exists."""
            self._bridge_should_stop = True
            if self._bridge_websocket_app is not None:
                self._bridge_websocket_app.keep_running = False
                self._bridge_websocket_app.close()

    return ThreadAwareUnifiAccessClient()


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
        self._verify_ssl = verify_ssl
        self._resolved_port = port
        self._listeners: list[Callable[[AccessUpdate], None]] = []
        self._door_states: dict[str, DoorState] = {}
        self._door_names: dict[str, str] = {}
        self._doorbell_requests: dict[str, str] = {}
        self._websocket_connected = False

        self._client = _build_library_client(
            host=_host_with_port(host, port),
            verify_ssl=verify_ssl,
            on_message=self._schedule_message,
            on_connection_state=self._schedule_connection_state,
        )
        (
            _unifi_access_api_client,
            self._api_auth_error,
            self._api_error,
            _device_notifications_url,
            self._doors_url,
        ) = _import_access_library()

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
            raw_doors = await self._hass.async_add_executor_job(self._fetch_raw_doors)
        except self._api_auth_error as err:
            raise UnifiAccessAuthenticationError from err
        except self._api_error as err:
            raise UnifiAccessCannotConnectError("Unable to fetch doors from UniFi Access") from err
        new_states: dict[str, DoorState] = {}

        for raw_door in raw_doors:
            if raw_door.get("is_bind_hub") is False:
                continue

            door_id = str(raw_door["id"])
            previous = self._door_states.get(door_id)
            thumbnail_path = _coerce_thumbnail_path(raw_door.get("door_thumbnail"))
            thumbnail_updated_at = _coerce_int(raw_door.get("door_thumbnail_last_update"))

            new_states[door_id] = DoorState(
                door_id=door_id,
                name=str(raw_door.get("name") or door_id),
                full_name=str(raw_door.get("full_name") or raw_door.get("name") or door_id),
                is_open=_door_is_open(raw_door.get("door_position_status")),
                is_unlocked=_door_is_unlocked(raw_door.get("door_lock_relay_status")),
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
            _normalize_name(state.name): door_id
            for door_id, state in self._door_states.items()
        }
        return _copy_states(self._door_states)

    async def async_unlock_door(self, door_id: str) -> None:
        """Unlock a door via the Access API."""
        try:
            await self._hass.async_add_executor_job(self._client.unlock_door, door_id)
        except self._api_auth_error as err:
            raise UnifiAccessAuthenticationError from err
        except self._api_error as err:
            raise UnifiAccessCannotConnectError(
                f"Unable to unlock door {door_id}"
            ) from err

    async def async_refresh_thumbnail(self, door_id: str) -> bytes | None:
        """Fetch the latest thumbnail for a door."""
        state = self._door_states.get(door_id)
        if state is None or not state.thumbnail_path:
            return None

        try:
            image_bytes = await self._hass.async_add_executor_job(
                self._client._get_thumbnail_image,  # noqa: SLF001
                _thumbnail_url(self._client.host, state.thumbnail_path),
            )
        except self._api_auth_error as err:
            raise UnifiAccessAuthenticationError from err
        except self._api_error as err:
            raise UnifiAccessCannotConnectError(
                f"Unable to fetch thumbnail for door {door_id}"
            ) from err
        updated = replace(state, thumbnail_bytes=image_bytes)
        self._door_states[door_id] = updated
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

    def _fetch_raw_doors(self) -> list[dict[str, Any]]:
        """Return the raw doors payload from the upstream client."""
        return self._client._make_http_request(f"{self._client.host}{self._doors_url}")  # noqa: SLF001

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
        event_name = payload.get("event")
        updates: list[AccessUpdate] = []

        if event_name in {
            "access.data.device.location_update_v2",
            "access.data.v2.location.update",
            "access.data.location.update",
        }:
            update = self._handle_location_update(payload)
            if update is not None:
                updates.append(update)
        elif event_name == "access.data.v2.device.update":
            updates.extend(self._handle_v2_device_update(payload))
        elif event_name == "access.data.device.remote_unlock":
            update = self._handle_remote_unlock(payload)
            if update is not None:
                updates.append(update)
        elif event_name in {"access.remote_view", "access.hw.door_bell"}:
            update = self._handle_doorbell(payload)
            if update is not None:
                updates.append(update)
        elif event_name == "access.remote_view.change":
            self._handle_doorbell_stop(payload)
        elif event_name in {"access.logs.insights.add", "access.logs.add"}:
            update = self._handle_access_event(payload)
            if update is not None:
                updates.append(update)

        for update in updates:
            self._emit_update(update)

    @callback
    def _emit_update(self, update: AccessUpdate) -> None:
        """Emit an adapter update to all listeners."""
        for listener in list(self._listeners):
            listener(update)

    def _handle_location_update(self, payload: dict[str, Any]) -> AccessUpdate | None:
        """Normalize location updates into a door-state update."""
        data = payload.get("data") or {}
        door_id = str(data.get("id") or data.get("unique_id") or "")
        if not door_id:
            return None

        changes: dict[str, Any] = {}
        state_payload = data.get("state")
        if isinstance(state_payload, dict):
            if "dps" in state_payload:
                changes["is_open"] = _door_is_open(state_payload.get("dps"))
            if "lock" in state_payload:
                changes["is_unlocked"] = _door_is_unlocked(state_payload.get("lock"))

        thumbnail = data.get("thumbnail")
        if isinstance(thumbnail, dict):
            thumbnail_path = _coerce_thumbnail_path(thumbnail.get("url"))
            if thumbnail_path is not None:
                changes["thumbnail_path"] = thumbnail_path
                changes["thumbnail_bytes"] = None
            thumbnail_updated_at = _coerce_int(thumbnail.get("door_thumbnail_last_update"))
            if thumbnail_updated_at is not None:
                changes["thumbnail_updated_at"] = thumbnail_updated_at

        extras = data.get("extras")
        if isinstance(extras, dict):
            thumbnail_path = _coerce_thumbnail_path(extras.get("door_thumbnail"))
            if thumbnail_path is not None:
                changes["thumbnail_path"] = thumbnail_path
                changes["thumbnail_bytes"] = None
            thumbnail_updated_at = _coerce_int(extras.get("door_thumbnail_last_update"))
            if thumbnail_updated_at is not None:
                changes["thumbnail_updated_at"] = thumbnail_updated_at

        updated = self._replace_state(door_id, **changes)
        if updated is None:
            return None
        return AccessUpdate(door_state=updated)

    def _handle_v2_device_update(self, payload: dict[str, Any]) -> list[AccessUpdate]:
        """Normalize device update messages that carry multiple location states."""
        updates: list[AccessUpdate] = []
        data = payload.get("data") or {}

        for location_state in data.get("location_states") or []:
            door_id = str(location_state.get("location_id") or "")
            if not door_id:
                continue

            changes: dict[str, Any] = {}
            if "dps" in location_state:
                changes["is_open"] = _door_is_open(location_state.get("dps"))
            if "lock" in location_state:
                changes["is_unlocked"] = _door_is_unlocked(location_state.get("lock"))

            updated = self._replace_state(door_id, **changes)
            if updated is not None:
                updates.append(AccessUpdate(door_state=updated))

        return updates

    def _handle_remote_unlock(self, payload: dict[str, Any]) -> AccessUpdate | None:
        """Normalize remote unlock messages."""
        data = payload.get("data") or {}
        door_id = str(data.get("unique_id") or data.get("id") or "")
        if not door_id:
            return None

        updated = self._replace_state(door_id, is_unlocked=True)
        if updated is None:
            return None
        return AccessUpdate(door_state=updated)

    def _handle_doorbell(self, payload: dict[str, Any]) -> AccessUpdate | None:
        """Normalize doorbell events."""
        data = payload.get("data") or {}
        door_id = data.get("door_id")
        if not door_id:
            door_id = self._door_names.get(_normalize_name(str(data.get("door_name") or "")))
        if not door_id:
            return None

        request_id = data.get("request_id")
        if request_id:
            self._doorbell_requests[str(request_id)] = str(door_id)

        door = self._door_states.get(str(door_id))
        attributes = {
            "door_id": str(door_id),
            "door_name": door.name if door is not None else str(data.get("door_name") or door_id),
            "type": DOORBELL_EVENT_RING,
            "raw_event": str(payload.get("event")),
        }
        door_event = DoorEventPayload(
            door_id=str(door_id),
            category=EVENT_CATEGORY_DOORBELL,
            event_type=DOORBELL_EVENT_RING,
            attributes=attributes,
        )
        updated = self._apply_event(door_event)
        return AccessUpdate(door_state=updated, door_event=door_event)

    def _handle_doorbell_stop(self, payload: dict[str, Any]) -> None:
        """Track remote-view stop messages for future presses."""
        data = payload.get("data") or {}
        request_id = data.get("remote_call_request_id")
        if request_id:
            self._doorbell_requests.pop(str(request_id), None)

    def _handle_access_event(self, payload: dict[str, Any]) -> AccessUpdate | None:
        """Normalize access log and insight events."""
        event_name = str(payload.get("event"))
        if event_name == "access.logs.insights.add":
            door_event = self._handle_insights_add(payload)
        else:
            door_event = self._handle_logs_add(payload)

        if door_event is None:
            return None

        updated = self._apply_event(door_event)
        return AccessUpdate(door_state=updated, door_event=door_event)

    def _handle_insights_add(self, payload: dict[str, Any]) -> DoorEventPayload | None:
        """Normalize insights.add into an access event."""
        data = payload.get("data") or {}
        metadata = data.get("metadata") or {}
        door_entries = metadata.get("door") or []
        if not door_entries:
            return None

        door_id = str(door_entries[0].get("id") or "")
        if not door_id or door_id not in self._door_states:
            return None

        result = str(data.get("result") or "")
        actor = (metadata.get("actor") or {}).get("display_name")
        authentication = (metadata.get("authentication") or {}).get("display_name")
        direction = _first_display_name(metadata.get("opened_direction"))
        method = _first_display_name(metadata.get("opened_method"))
        door = self._door_states[door_id]

        return DoorEventPayload(
            door_id=door_id,
            category=EVENT_CATEGORY_ACCESS,
            event_type=_access_event_type(result),
            attributes={
                "door_id": door_id,
                "door_name": door.name,
                "actor": actor,
                "authentication": authentication,
                "direction": direction,
                "method": method,
                "result": result,
                "raw_event": str(data.get("event_type") or payload.get("event")),
            },
        )

    def _handle_logs_add(self, payload: dict[str, Any]) -> DoorEventPayload | None:
        """Normalize logs.add into an access event fallback."""
        data = payload.get("data") or {}
        source = data.get("source") or {}
        targets = source.get("target") or []
        door_id = ""
        for target in targets:
            if target.get("type") == "door":
                door_id = str(target.get("id") or "")
                break

        if not door_id or door_id not in self._door_states:
            return None

        actor = (source.get("actor") or {}).get("display_name")
        authentication = (source.get("authentication") or {}).get("credential_provider")
        event = source.get("event") or {}
        result = str(event.get("result") or "")
        door = self._door_states[door_id]

        return DoorEventPayload(
            door_id=door_id,
            category=EVENT_CATEGORY_ACCESS,
            event_type=_access_event_type(result),
            attributes={
                "door_id": door_id,
                "door_name": door.name,
                "actor": actor,
                "authentication": authentication,
                "result": result,
                "raw_event": str(payload.get("event")),
            },
        )

    def _replace_state(self, door_id: str, **changes: Any) -> DoorState | None:
        """Replace and store a single door state."""
        state = self._door_states.get(door_id)
        if state is None or not changes:
            return state

        updated = replace(state, **changes)
        self._door_states[door_id] = updated
        self._door_names[_normalize_name(updated.name)] = door_id
        return updated

    def _apply_event(self, payload: DoorEventPayload) -> DoorState | None:
        """Persist the latest event metadata onto the current door state."""
        state = self._door_states.get(payload.door_id)
        if state is None:
            return None

        updated = state.with_event(payload)
        self._door_states[payload.door_id] = updated
        return updated


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


def _host_with_port(host: str, port: int) -> str:
    """Return a host string that includes https and an explicit port."""
    normalized_host = host.strip()
    if "://" in normalized_host:
        normalized_host = normalized_host.split("://", maxsplit=1)[1]
    return f"https://{normalized_host}:{port}"


def _normalize_name(name: str) -> str:
    """Normalize a door name for loose matching."""
    return " ".join(name.casefold().split())


def _door_is_open(value: Any) -> bool:
    """Return whether a raw door position represents an open state."""
    return str(value or "").casefold() == "open"


def _door_is_unlocked(value: Any) -> bool:
    """Return whether a raw relay status represents an unlocked state."""
    return str(value or "").casefold() in {"unlock", "unlocked"}


def _access_event_type(result: str) -> str:
    """Map controller access results into stable event types."""
    normalized = result.casefold()
    if normalized in {"access", "allow", "allowed", "granted", "success"}:
        return ACCESS_EVENT_GRANTED
    return ACCESS_EVENT_DENIED


def _coerce_int(value: Any) -> int | None:
    """Coerce an arbitrary value to an integer when possible."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_thumbnail_path(value: Any) -> str | None:
    """Normalize a thumbnail path from Access payloads."""
    if not value:
        return None
    return str(value)


def _thumbnail_url(base_host: str, thumbnail_path: str) -> str:
    """Return a fully-qualified thumbnail URL."""
    if thumbnail_path.startswith(("http://", "https://")):
        return thumbnail_path
    if thumbnail_path.startswith("/"):
        return f"{base_host}{thumbnail_path}"
    return f"{base_host}/{thumbnail_path}"


def _first_display_name(values: Any) -> str | None:
    """Return the first display name from a metadata list."""
    if not isinstance(values, list) or not values:
        return None
    if not isinstance(values[0], dict):
        return None
    value = values[0].get("display_name")
    return str(value) if value is not None else None


def _copy_states(states: dict[str, DoorState]) -> dict[str, DoorState]:
    """Return a shallow copy of normalized door states."""
    return {
        door_id: replace(state, last_event_attributes=dict(state.last_event_attributes))
        for door_id, state in states.items()
    }
