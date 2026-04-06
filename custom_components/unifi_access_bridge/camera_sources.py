"""Camera source adapters for UniFi Access Bridge."""

from __future__ import annotations

from abc import ABC, abstractmethod
import logging

from homeassistant.components.camera import async_get_image, async_get_stream_source
from homeassistant.core import HomeAssistant

from .models import CameraMapping, CameraSourceType, DoorState

_LOGGER = logging.getLogger(__name__)


class BaseDoorCameraSource(ABC):
    """Abstract camera source."""

    @property
    @abstractmethod
    def available(self) -> bool:
        """Return whether the source is currently usable."""

    @abstractmethod
    async def async_stream_source(self) -> str | None:
        """Return stream source or None."""

    @abstractmethod
    async def async_image(
        self,
        width: int | None = None,
        height: int | None = None,
    ) -> bytes | None:
        """Return image bytes."""


class HACameraProxySource(BaseDoorCameraSource):
    """Proxy an existing Home Assistant camera entity."""

    def __init__(self, hass: HomeAssistant, entity_id: str) -> None:
        """Initialize the proxy source."""
        self.hass = hass
        self.entity_id = entity_id

    @property
    def available(self) -> bool:
        """Return whether the mapped camera entity exists."""
        return self.hass.states.get(self.entity_id) is not None

    async def async_stream_source(self) -> str | None:
        """Proxy the upstream stream source."""
        if not self.available:
            return None

        try:
            return await async_get_stream_source(self.hass, self.entity_id)
        except Exception:
            _LOGGER.debug(
                "Unable to resolve stream source for mapped camera %s",
                self.entity_id,
                exc_info=True,
            )
            return None

    async def async_image(
        self,
        width: int | None = None,
        height: int | None = None,
    ) -> bytes | None:
        """Proxy the upstream still image."""
        if not self.available:
            return None

        try:
            image = await async_get_image(
                self.hass,
                self.entity_id,
                width=width,
                height=height,
            )
        except Exception:
            _LOGGER.debug(
                "Unable to fetch still image for mapped camera %s",
                self.entity_id,
                exc_info=True,
            )
            return None

        return image.content


class RTSPSource(BaseDoorCameraSource):
    """Direct RTSP/RTSPS source."""

    def __init__(self, url: str) -> None:
        """Initialize the RTSP source."""
        self.url = url

    @property
    def available(self) -> bool:
        """Return whether the source has a configured URL."""
        return bool(self.url)

    async def async_stream_source(self) -> str | None:
        """Return the configured RTSP URL."""
        return self.url

    async def async_image(
        self,
        width: int | None = None,
        height: int | None = None,
    ) -> bytes | None:
        """Return no still image and let HA stream handling fail cleanly."""
        del width, height
        return None


class SnapshotOnlySource(BaseDoorCameraSource):
    """Access thumbnail fallback source."""

    def __init__(self, state: DoorState) -> None:
        """Initialize the snapshot source."""
        self._state = state

    @property
    def available(self) -> bool:
        """Return whether any snapshot data is available."""
        return self._state.thumbnail_bytes is not None or self._state.thumbnail_path is not None

    async def async_stream_source(self) -> str | None:
        """Snapshot mode has no stream source."""
        return None

    async def async_image(
        self,
        width: int | None = None,
        height: int | None = None,
    ) -> bytes | None:
        """Return the latest Access thumbnail bytes."""
        del width, height
        return self._state.thumbnail_bytes


def build_camera_source(
    hass: HomeAssistant,
    mapping: CameraMapping,
    state: DoorState,
) -> BaseDoorCameraSource:
    """Build a camera source adapter from mapping."""
    if mapping.source_type == CameraSourceType.HA_CAMERA and mapping.value:
        return HACameraProxySource(hass, mapping.value)
    if mapping.source_type == CameraSourceType.RTSP and mapping.value:
        return RTSPSource(mapping.value)
    return SnapshotOnlySource(state)
