"""Upstream client integration for py-unifi-access."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from inspect import signature
import json
import logging
import ssl
from typing import Any, Protocol

from .access_errors import UnifiAccessDependencyError

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class AccessLibraryHandles:
    """Runtime handles imported from the upstream library."""

    client_class: type[Any]
    auth_error: type[Exception]
    api_error: type[Exception]
    device_notifications_url: str
    doors_url: str


class AccessClient(Protocol):
    """Protocol for the wrapped upstream client."""

    host: str

    def authenticate(self, api_token: str) -> str:
        """Authenticate against the Access controller."""

    def fetch_raw_doors(self) -> list[dict[str, Any]]:
        """Fetch the raw doors payload."""

    def fetch_thumbnail_image(self, image_url: str) -> bytes:
        """Fetch thumbnail bytes for a door."""

    def unlock_door(self, door_id: str) -> None:
        """Unlock a door through the upstream client."""

    def close(self) -> None:
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

    return AccessLibraryHandles(
        client_class=UnifiAccessApiClient,
        auth_error=ApiAuthError,
        api_error=ApiError,
        device_notifications_url=DEVICE_NOTIFICATIONS_URL,
        doors_url=DOORS_URL,
    )


def build_library_client(
    *,
    library: AccessLibraryHandles,
    host: str,
    verify_ssl: bool,
    on_message: Callable[[dict[str, Any]], None],
    on_connection_state: Callable[[bool], None],
) -> AccessClient:
    """Create a patched upstream client that exposes raw websocket events."""

    class ThreadAwareUnifiAccessClient(library.client_class):  # type: ignore[misc, valid-type]
        """Small subclass that keeps websocket callbacks observable."""

        def __init__(self) -> None:
            super().__init__(**_client_init_kwargs(library.client_class, host, verify_ssl))
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

    return ThreadAwareUnifiAccessClient()


def _ssl_options(verify_ssl: bool) -> dict[str, Any]:
    """Build websocket SSL options."""
    if verify_ssl:
        return {"cert_reqs": ssl.CERT_REQUIRED}
    return {"cert_reqs": ssl.CERT_NONE}


def _client_init_kwargs(
    client_class: type[Any],
    host: str,
    verify_ssl: bool,
) -> dict[str, Any]:
    """Build constructor kwargs compatible with multiple upstream client versions."""
    kwargs: dict[str, Any] = {
        "host": host,
        "verify_ssl": verify_ssl,
    }
    if "use_polling" in signature(client_class.__init__).parameters:
        kwargs["use_polling"] = False
    return kwargs
