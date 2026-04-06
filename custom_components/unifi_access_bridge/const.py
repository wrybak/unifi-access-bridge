"""Constants for UniFi Access Bridge."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "unifi_access_bridge"

CONF_API_TOKEN = "api_token"
CONF_OPENAPI_PORT = "openapi_port"
CONF_CAMERA_MAPPINGS = "camera_mappings"
CONF_SOURCE_TYPE = "source_type"
CONF_SOURCE_VALUE = "value"

ATTR_DOOR_ID = "door_id"

SERVICE_UNLOCK_DOOR = "unlock_door"

DEFAULT_OPENAPI_PORTS: tuple[int, int] = (12445, 12455)
POLL_FALLBACK_INTERVAL = timedelta(seconds=30)

EVENT_CATEGORY_ACCESS = "access"
EVENT_CATEGORY_DOORBELL = "doorbell"

ACCESS_EVENT_GRANTED = "access_granted"
ACCESS_EVENT_DENIED = "access_denied"
DOORBELL_EVENT_RING = "ring"

OPTION_SOURCE_SNAPSHOT = "snapshot"
OPTION_SOURCE_HA_CAMERA = "ha_camera"
OPTION_SOURCE_RTSP = "rtsp"

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.BINARY_SENSOR,
    Platform.CAMERA,
    Platform.EVENT,
]
