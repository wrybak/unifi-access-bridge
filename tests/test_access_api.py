"""Tests for the Access adapter factory."""

from __future__ import annotations

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
            auth_error=Exception,
            api_error=Exception,
            device_notifications_url="/notifications",
            doors_url="/doors",
        ),
        host="https://192.168.2.13:12455",
        verify_ssl=False,
        on_message=lambda payload: None,
        on_connection_state=lambda connected: None,
    )

    assert init_kwargs == {
        "host": "https://192.168.2.13:12455",
        "verify_ssl": False,
    }
    assert client.host == "https://192.168.2.13:12455"
