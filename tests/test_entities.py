"""Tests for entities and coordinator updates."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.unifi_access_bridge.camera import DoorCameraEntity
from custom_components.unifi_access_bridge.const import (
    CONF_CAMERA_MAPPINGS,
    DOMAIN,
    SERVICE_UNLOCK_DOOR,
)
from custom_components.unifi_access_bridge.coordinator import UnifiAccessBridgeCoordinator
from custom_components.unifi_access_bridge.models import AccessUpdate, CameraMapping, CameraSourceType

from .conftest import MOCK_CONFIG, MOCK_DOOR_ID, make_door_state


async def test_unlock_button_and_service(hass, setup_integration) -> None:
    """Unlock through the entity button and the integration service."""
    _entry, fake_adapter = setup_integration

    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": "button.front_door_unlock"},
        blocking=True,
    )
    await hass.services.async_call(
        DOMAIN,
        SERVICE_UNLOCK_DOOR,
        {"door_id": MOCK_DOOR_ID},
        blocking=True,
    )

    assert fake_adapter.unlock_calls == [MOCK_DOOR_ID, MOCK_DOOR_ID]


async def test_binary_sensor_updates_from_push(hass, setup_integration) -> None:
    """Update the door sensor when the adapter emits a push message."""
    _entry, fake_adapter = setup_integration

    assert hass.states.get("binary_sensor.front_door_door").state == "off"

    fake_adapter.emit(
        AccessUpdate(door_state=replace(make_door_state(), is_open=True))
    )
    await hass.async_block_till_done()

    assert hass.states.get("binary_sensor.front_door_door").state == "on"


async def test_camera_proxy_source_uses_ha_camera_entity(hass) -> None:
    """Proxy stream and still image data from an existing HA camera."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="UniFi Access Bridge",
        data=MOCK_CONFIG,
        options={
            CONF_CAMERA_MAPPINGS: {
                MOCK_DOOR_ID: CameraMapping(
                    door_id=MOCK_DOOR_ID,
                    source_type=CameraSourceType.HA_CAMERA,
                    value="camera.entryway",
                ).as_dict()
            }
        },
    )
    coordinator = UnifiAccessBridgeCoordinator(
        hass,
        entry,
        SimpleNamespace(
            websocket_connected=True,
            async_subscribe_updates=lambda listener: lambda: None,
            async_get_doors=AsyncMock(),
            async_unlock_door=AsyncMock(),
            async_refresh_thumbnail=AsyncMock(return_value=None),
            async_close=AsyncMock(),
        ),
    )
    coordinator.data = {MOCK_DOOR_ID: make_door_state()}
    coordinator.last_update_success = True

    hass.states.async_set("camera.entryway", "idle")
    entity = DoorCameraEntity(hass, coordinator, entry, MOCK_DOOR_ID)

    with (
        patch(
            "custom_components.unifi_access_bridge.camera_sources.async_get_stream_source",
            AsyncMock(return_value="rtsp://proxied/stream"),
        ),
        patch(
            "custom_components.unifi_access_bridge.camera_sources.async_get_image",
            AsyncMock(return_value=SimpleNamespace(content=b"ha-camera-image")),
        ),
    ):
        assert entity.available is True
        assert await entity.stream_source() == "rtsp://proxied/stream"
        assert await entity.async_camera_image() == b"ha-camera-image"

    hass.states.async_remove("camera.entryway")
    assert entity.available is False


async def test_snapshot_only_fallback_uses_access_thumbnail(hass) -> None:
    """Fetch an Access thumbnail when snapshot mode has no cached bytes yet."""
    thumbnail_bytes = b"fresh-thumbnail"
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="UniFi Access Bridge",
        data=MOCK_CONFIG,
        options={
            CONF_CAMERA_MAPPINGS: {
                MOCK_DOOR_ID: CameraMapping(
                    door_id=MOCK_DOOR_ID,
                    source_type=CameraSourceType.SNAPSHOT,
                ).as_dict()
            }
        },
    )

    fake_adapter = SimpleNamespace(
        websocket_connected=True,
        async_subscribe_updates=lambda listener: lambda: None,
        async_get_doors=AsyncMock(),
        async_unlock_door=AsyncMock(),
        async_refresh_thumbnail=AsyncMock(return_value=thumbnail_bytes),
        async_close=AsyncMock(),
    )
    coordinator = UnifiAccessBridgeCoordinator(hass, entry, fake_adapter)
    coordinator.data = {
        MOCK_DOOR_ID: make_door_state(thumbnail_bytes=None, thumbnail_path="/thumb.jpg")
    }
    coordinator.last_update_success = True

    entity = DoorCameraEntity(hass, coordinator, entry, MOCK_DOOR_ID)

    assert await entity.async_camera_image() == thumbnail_bytes
    fake_adapter.async_refresh_thumbnail.assert_awaited_once_with(MOCK_DOOR_ID)


async def test_websocket_reconnect_state_is_reflected_on_entities(
    hass, setup_integration
) -> None:
    """Expose websocket connection state via entity attributes."""
    _entry, fake_adapter = setup_integration

    fake_adapter.emit(AccessUpdate(websocket_connected=False))
    await hass.async_block_till_done()
    assert (
        hass.states.get("binary_sensor.front_door_door").attributes["websocket_connected"]
        is False
    )

    fake_adapter.emit(AccessUpdate(websocket_connected=True))
    await hass.async_block_till_done()
    assert (
        hass.states.get("binary_sensor.front_door_door").attributes["websocket_connected"]
        is True
    )


async def test_websocket_disconnect_enables_poll_fallback(hass) -> None:
    """Start polling only while websocket push is disconnected."""
    entry = MockConfigEntry(domain=DOMAIN, title="UniFi Access Bridge", data=MOCK_CONFIG)
    fake_adapter = SimpleNamespace(
        websocket_connected=True,
        async_subscribe_updates=lambda listener: lambda: None,
        async_get_doors=AsyncMock(return_value={MOCK_DOOR_ID: make_door_state()}),
        async_unlock_door=AsyncMock(),
        async_refresh_thumbnail=AsyncMock(return_value=None),
        async_close=AsyncMock(),
    )
    coordinator = UnifiAccessBridgeCoordinator(hass, entry, fake_adapter)
    unsubscribe = Mock()

    with patch(
        "custom_components.unifi_access_bridge.coordinator.async_track_time_interval",
        return_value=unsubscribe,
    ) as track_time_interval:
        await coordinator._async_setup()

        coordinator._handle_adapter_update(AccessUpdate(websocket_connected=False))

        track_time_interval.assert_called_once()
        poll_callback = track_time_interval.call_args.args[1]

        with patch.object(coordinator, "async_request_refresh", AsyncMock()) as refresh:
            await poll_callback(None)
            refresh.assert_awaited_once()

        coordinator._handle_adapter_update(AccessUpdate(websocket_connected=True))

    unsubscribe.assert_called_once()
