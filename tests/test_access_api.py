"""Tests for the Access adapter factory."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from custom_components.unifi_access_bridge.access_client import (
    AccessLibraryHandles,
    build_library_client,
)
from custom_components.unifi_access_bridge.access_api import (
    UnifiAccessCannotConnectError,
    async_create_access_adapter,
)


async def test_port_auto_probe_falls_back_to_12455(hass) -> None:
    """Probe 12445 first and fall back to 12455 when needed."""
    created_ports: list[int] = []

    class ProbeAdapter:
        """Test adapter that fails on the first port."""

        def __init__(self, hass, *, host, api_token, verify_ssl, port) -> None:
            del hass, host, api_token, verify_ssl
            self.port = port
            self.websocket_connected = False
            created_ports.append(port)

        async def async_authenticate(self) -> None:
            if self.port == 12445:
                raise UnifiAccessCannotConnectError("first port failed")

        async def async_close(self) -> None:
            return None

    with patch(
        "custom_components.unifi_access_bridge.access_api.UnifiAccessAdapter",
        ProbeAdapter,
    ):
        adapter, resolved_port = await async_create_access_adapter(
            hass,
            host="192.168.1.10",
            api_token="token",
            verify_ssl=False,
            requested_port=None,
        )

    assert created_ports == [12445, 12455]
    assert resolved_port == 12455
    assert adapter.port == 12455


def test_build_library_client_supports_upstream_without_use_polling() -> None:
    """Create the wrapped client even when upstream __init__ lacks use_polling."""
    init_kwargs: dict[str, object] = {}

    class LegacyClient:
        """Older upstream shape without a use_polling kwarg."""

        def __init__(self, *, host: str, verify_ssl: bool) -> None:
            init_kwargs.update({"host": host, "verify_ssl": verify_ssl})
            self.host = host
            self.websocket_host = host.replace("https://", "wss://")
            self._websocket_headers: dict[str, str] = {}

    client = build_library_client(
        library=AccessLibraryHandles(
            client_class=LegacyClient,
            auth_errors=(Exception,),
            api_errors=(Exception,),
            connection_errors=(),
            ssl_errors=(),
            device_notifications_url="/notifications",
            doors_url="/doors",
        ),
        host="https://192.168.2.13:12455",
        api_token="token",
        verify_ssl=False,
        session=None,
        on_message=lambda payload: None,
        on_connection_state=lambda connected: None,
    )

    assert init_kwargs == {
        "host": "https://192.168.2.13:12455",
        "verify_ssl": False,
    }
    assert client.host == "https://192.168.2.13:12455"


async def test_build_library_client_supports_modern_async_client() -> None:
    """Create the wrapped client for modern async py-unifi-access versions."""
    init_kwargs: dict[str, object] = {}

    class ModernDoor:
        """Door model stub."""

        def model_dump(self) -> dict[str, object]:
            return {"id": "door-001", "name": "Front Door", "is_bind_hub": True}

    class ModernClient:
        """New upstream shape with injected auth and session."""

        def __init__(
            self,
            host: str,
            api_token: str,
            session: object,
            *,
            verify_ssl: bool = False,
        ) -> None:
            init_kwargs.update(
                {
                    "host": host,
                    "api_token": api_token,
                    "session": session,
                    "verify_ssl": verify_ssl,
                }
            )
            self._host = host
            self.started = False

        async def authenticate(self) -> None:
            return None

        async def get_doors(self) -> list[ModernDoor]:
            return [ModernDoor()]

        async def unlock_door(self, door_id: str) -> None:
            assert door_id == "door-001"

        async def get_thumbnail(self, path: str) -> bytes:
            assert path == "/thumb.jpg"
            return b"image-bytes"

        async def close(self) -> None:
            return None

        def start_websocket(self, **kwargs) -> object:
            self.started = True
            kwargs["on_connect"]()
            kwargs["on_raw_message"]({"event": "test"})
            return SimpleNamespace()

    websocket_states: list[bool] = []
    raw_messages: list[dict[str, object]] = []
    session = object()

    client = build_library_client(
        library=AccessLibraryHandles(
            client_class=ModernClient,
            auth_errors=(Exception,),
            api_errors=(Exception,),
            connection_errors=(),
            ssl_errors=(),
            device_notifications_url="/notifications",
            doors_url="/doors",
            static_url="/api/v1/developer/system/static",
        ),
        host="https://192.168.2.13:12455",
        api_token="token",
        verify_ssl=False,
        session=session,
        on_message=raw_messages.append,
        on_connection_state=websocket_states.append,
    )

    assert await client.authenticate("ignored") == "ok"
    assert await client.fetch_raw_doors() == [
        {"id": "door-001", "name": "Front Door", "is_bind_hub": True}
    ]
    assert await client.fetch_thumbnail_image(
        "https://192.168.2.13:12455/api/v1/developer/system/static/thumb.jpg"
    ) == b"image-bytes"

    assert init_kwargs == {
        "host": "https://192.168.2.13:12455",
        "api_token": "token",
        "session": session,
        "verify_ssl": False,
    }
    assert websocket_states == [True]
    assert raw_messages == [{"event": "test"}]
