"""Upstream client integration for py-unifi-access."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from inspect import signature
import json
import logging
import ssl
from urllib.parse import urlparse
from typing import Any, Protocol

from .access_errors import UnifiAccessDependencyError

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class AccessLibraryHandles:
    """Runtime handles imported from the upstream library."""

    client_class: type[Any]
    auth_errors: tuple[type[Exception], ...]
    api_errors: tuple[type[Exception], ...]
    connection_errors: tuple[type[Exception], ...]
    ssl_errors: tuple[type[Exception], ...]
    device_notifications_url: str
    doors_url: str
    static_url: str | None = None


class AccessClient(Protocol):
    """Protocol for the wrapped upstream client."""

    host: str

    def authenticate(self, api_token: str) -> Any:
        """Authenticate against the Access controller."""

    def fetch_raw_doors(self) -> Any:
        """Fetch the raw doors payload."""

    def fetch_thumbnail_image(self, image_url: str) -> Any:
        """Fetch thumbnail bytes for a door."""

    def unlock_door(self, door_id: str) -> Any:
        """Unlock a door through the upstream client."""

    def close(self) -> Any:
        """Close the client and its websocket resources."""


def import_access_library() -> AccessLibraryHandles:
    """Import the upstream UniFi Access library lazily."""
    try:
        from unifi_access_api import ApiAuthError, ApiError, UnifiAccessApiClient
        from unifi_access_api.const import DEVICE_NOTIFICATIONS_URL, DOORS_URL
    except ImportError as err:
        raise UnifiAccessDependencyError(
            "py-unifi-access is not installed"
        ) from err

    try:
        from unifi_access_api import ApiConnectionError, ApiSSLError
    except ImportError:
        connection_errors: tuple[type[Exception], ...] = ()
        ssl_errors: tuple[type[Exception], ...] = ()
    else:
        connection_errors = (ApiConnectionError,)
        ssl_errors = (ApiSSLError,)

    try:
        from unifi_access_api.const import STATIC_URL
    except ImportError:
        static_url = None
    else:
        static_url = STATIC_URL

    return AccessLibraryHandles(
        client_class=UnifiAccessApiClient,
        auth_errors=(ApiAuthError,),
        api_errors=(ApiError,),
        connection_errors=connection_errors,
        ssl_errors=ssl_errors,
        device_notifications_url=DEVICE_NOTIFICATIONS_URL,
        doors_url=DOORS_URL,
        static_url=static_url,
    )


def build_library_client(
    *,
    library: AccessLibraryHandles,
    host: str,
    api_token: str,
    verify_ssl: bool,
    session: Any | None,
    on_message: Callable[[dict[str, Any]], None],
    on_connection_state: Callable[[bool], None],
) -> AccessClient:
    """Create a patched upstream client that exposes raw websocket events."""
    if _uses_modern_client(library.client_class):
        if session is None:
            raise UnifiAccessDependencyError(
                "aiohttp session is required for modern py-unifi-access clients"
            )
        return _ModernAccessClient(
            library=library,
            host=host,
            api_token=api_token,
            verify_ssl=verify_ssl,
            session=session,
            on_message=on_message,
            on_connection_state=on_connection_state,
        )

    return _LegacyAccessClient(
        library=library,
        host=host,
        verify_ssl=verify_ssl,
        on_message=on_message,
        on_connection_state=on_connection_state,
    )


def _ssl_options(verify_ssl: bool) -> dict[str, Any]:
    """Build websocket SSL options."""
    if verify_ssl:
        return {"cert_reqs": ssl.CERT_REQUIRED}
    return {"cert_reqs": ssl.CERT_NONE}


class _LegacyAccessClient:
    """Adapter for the legacy synchronous UniFi Access client."""

    def __init__(
        self,
        *,
        library: AccessLibraryHandles,
        host: str,
        verify_ssl: bool,
        on_message: Callable[[dict[str, Any]], None],
        on_connection_state: Callable[[bool], None],
    ) -> None:
        client_class = library.client_class

        class ThreadAwareUnifiAccessClient(client_class):  # type: ignore[misc, valid-type]
            """Small subclass that keeps websocket callbacks observable."""

            def __init__(self) -> None:
                super().__init__(**_legacy_client_init_kwargs(client_class, host, verify_ssl))
                self._bridge_on_message = on_message
                self._bridge_on_connection_state = on_connection_state
                self._bridge_should_stop = False
                self._bridge_websocket_app: Any | None = None

            def on_message(self, ws: Any, message: str) -> None:
                """Process websocket messages from Access."""
                del ws
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
                del ws
                self._bridge_on_connection_state(False)
                _LOGGER.debug("UniFi Access websocket error: %s", error)

            def on_open(self, ws: Any) -> None:
                """Mark the websocket as connected."""
                del ws
                self._bridge_on_connection_state(True)
                _LOGGER.debug("UniFi Access websocket connected")

            def on_close(self, ws: Any, close_status_code: Any, close_msg: Any) -> None:
                """Reconnect the websocket until the adapter is explicitly closed."""
                del ws
                self._bridge_on_connection_state(False)
                _LOGGER.debug(
                    "UniFi Access websocket closed code=%s message=%s",
                    close_status_code,
                    close_msg,
                )
                if not self._bridge_should_stop:
                    self._run_forever(self._bridge_websocket_app)

            def _run_forever(self, websocket_app: Any | None) -> None:
                """Run the websocket loop with reconnect enabled."""
                if websocket_app is None:
                    return
                websocket_app.run_forever(
                    sslopt=_ssl_options(verify_ssl),
                    reconnect=5,
                )

            def listen_for_updates(self) -> None:
                """Create and run the websocket client."""
                import websocket

                uri = f"{self.websocket_host}{library.device_notifications_url}"
                self._bridge_websocket_app = websocket.WebSocketApp(
                    uri,
                    header=self._websocket_headers,
                    on_message=self.on_message,
                    on_error=self.on_error,
                    on_open=self.on_open,
                    on_close=self.on_close,
                )
                self._run_forever(self._bridge_websocket_app)

            def fetch_raw_doors(self) -> list[dict[str, Any]]:
                """Fetch raw doors while keeping private upstream calls isolated here."""
                return self._make_http_request(f"{self.host}{library.doors_url}")  # noqa: SLF001

            def fetch_thumbnail_image(self, image_url: str) -> bytes:
                """Fetch thumbnail bytes while keeping private upstream calls isolated here."""
                return self._get_thumbnail_image(image_url)  # noqa: SLF001

            def close(self) -> None:
                """Stop reconnecting and close the websocket if one exists."""
                self._bridge_should_stop = True
                if self._bridge_websocket_app is not None:
                    self._bridge_websocket_app.keep_running = False
                    self._bridge_websocket_app.close()

        self._client = ThreadAwareUnifiAccessClient()
        self.host = self._client.host

    def authenticate(self, api_token: str) -> str:
        """Authenticate with the legacy sync client."""
        return self._client.authenticate(api_token)

    def fetch_raw_doors(self) -> list[dict[str, Any]]:
        """Fetch raw door payloads."""
        return self._client.fetch_raw_doors()

    def fetch_thumbnail_image(self, image_url: str) -> bytes:
        """Fetch thumbnail bytes."""
        return self._client.fetch_thumbnail_image(image_url)

    def unlock_door(self, door_id: str) -> None:
        """Unlock a door."""
        self._client.unlock_door(door_id)

    def close(self) -> None:
        """Close the legacy client."""
        self._client.close()


class _ModernAccessClient:
    """Adapter for the modern async UniFi Access client."""

    def __init__(
        self,
        *,
        library: AccessLibraryHandles,
        host: str,
        api_token: str,
        verify_ssl: bool,
        session: Any,
        on_message: Callable[[dict[str, Any]], None],
        on_connection_state: Callable[[bool], None],
    ) -> None:
        self._library = library
        self._client = library.client_class(
            host=host,
            api_token=api_token,
            session=session,
            verify_ssl=verify_ssl,
        )
        self.host = getattr(self._client, "host", getattr(self._client, "_host", host))
        self._on_message = on_message
        self._on_connection_state = on_connection_state
        self._static_url = library.static_url
        self._websocket_started = False

    async def authenticate(self, api_token: str) -> str:
        """Authenticate and start the modern websocket client."""
        del api_token
        try:
            await self._client.authenticate()
        except self._library.auth_errors:
            return "api_auth_error"
        except self._library.ssl_errors:
            return "ssl_error"
        except self._library.connection_errors:
            return "cannot_connect"
        except self._library.api_errors:
            return "api_error"

        self._start_websocket()
        return "ok"

    async def fetch_raw_doors(self) -> list[dict[str, Any]]:
        """Fetch raw doors from the modern async client."""
        doors = await self._client.get_doors()
        return [_model_to_dict(door) for door in doors]

    async def fetch_thumbnail_image(self, image_url: str) -> bytes:
        """Fetch thumbnail bytes from the modern async client."""
        return await self._client.get_thumbnail(
            _normalize_thumbnail_path(image_url, self._static_url)
        )

    async def unlock_door(self, door_id: str) -> None:
        """Unlock a door with the modern async client."""
        await self._client.unlock_door(door_id)

    async def close(self) -> None:
        """Close the modern async client."""
        await self._client.close()

    def _start_websocket(self) -> None:
        """Start the websocket once and hook it into the adapter callbacks."""
        if self._websocket_started:
            return

        self._client.start_websocket(
            message_handlers={},
            on_connect=lambda: self._on_connection_state(True),
            on_disconnect=lambda: self._on_connection_state(False),
            on_raw_message=self._on_message,
        )
        self._websocket_started = True


def _uses_modern_client(client_class: type[Any]) -> bool:
    """Return whether the upstream client expects injected auth and session objects."""
    parameters = signature(client_class.__init__).parameters
    return "api_token" in parameters and "session" in parameters


def _legacy_client_init_kwargs(
    client_class: type[Any],
    host: str,
    verify_ssl: bool,
) -> dict[str, Any]:
    """Build constructor kwargs for legacy sync client variants."""
    kwargs: dict[str, Any] = {
        "host": host,
        "verify_ssl": verify_ssl,
    }
    if "use_polling" in signature(client_class.__init__).parameters:
        kwargs["use_polling"] = False
    return kwargs


def _model_to_dict(item: Any) -> dict[str, Any]:
    """Serialize upstream models into plain dicts for adapter normalization."""
    if isinstance(item, dict):
        return item
    if hasattr(item, "model_dump"):
        return item.model_dump()
    if hasattr(item, "dict"):
        return item.dict()
    raise TypeError(f"Unsupported door payload type: {type(item)!r}")


def _normalize_thumbnail_path(image_url: str, static_url: str | None) -> str:
    """Convert full thumbnail URLs into the relative path expected by modern clients."""
    normalized = str(image_url)
    if normalized.startswith(("http://", "https://")):
        normalized = urlparse(normalized).path

    if static_url and normalized.startswith(static_url):
        normalized = normalized[len(static_url) :]

    if not normalized.startswith("/"):
        normalized = f"/{normalized}"

    return normalized
