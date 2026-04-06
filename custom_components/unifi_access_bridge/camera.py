"""Camera platform for UniFi Access Bridge."""

from __future__ import annotations

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .__init__ import UnifiAccessBridgeConfigEntry
from .camera_sources import build_camera_source
from .const import CONF_CAMERA_MAPPINGS
from .entity import UnifiAccessBridgeEntity
from .models import CameraMapping, CameraSourceType


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UnifiAccessBridgeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up per-door camera entities."""
    coordinator = entry.runtime_data
    added: set[str] = set()

    @callback
    def _add_entities() -> None:
        new_ids = sorted(set(coordinator.data) - added)
        if not new_ids:
            return
        async_add_entities(
            DoorCameraEntity(hass, coordinator, entry, door_id) for door_id in new_ids
        )
        added.update(new_ids)

    _add_entities()
    entry.async_on_unload(coordinator.async_add_listener(_add_entities))


class DoorCameraEntity(UnifiAccessBridgeEntity, Camera):
    """Camera entity for the door's paired view."""

    _attr_name = "Paired View"

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator,
        entry: UnifiAccessBridgeConfigEntry,
        door_id: str,
    ) -> None:
        """Initialize the door camera entity."""
        super().__init__(coordinator, door_id, "paired_view")
        Camera.__init__(self)
        self.hass = hass
        self._entry = entry

    @property
    def available(self) -> bool:
        """Return whether the door camera is available."""
        if not super().available:
            return False

        mapping = self._mapping
        source = build_camera_source(self.hass, mapping, self._door_state)
        if mapping.source_type == CameraSourceType.HA_CAMERA:
            return source.available
        if mapping.source_type == CameraSourceType.RTSP:
            return bool(mapping.value)
        return source.available

    @property
    def supported_features(self) -> CameraEntityFeature:
        """Return supported camera features."""
        mapping = self._mapping
        if mapping.source_type in (CameraSourceType.HA_CAMERA, CameraSourceType.RTSP):
            return CameraEntityFeature.STREAM
        return CameraEntityFeature(0)

    @property
    def _mapping(self) -> CameraMapping:
        """Return camera mapping for this door."""
        raw = self._entry.options.get(CONF_CAMERA_MAPPINGS, {}).get(self._door_id)
        return CameraMapping.from_dict(self._door_id, raw)

    async def stream_source(self) -> str | None:
        """Return stream source for the current mapping."""
        source = build_camera_source(self.hass, self._mapping, self._door_state)
        return await source.async_stream_source()

    async def async_camera_image(
        self,
        width: int | None = None,
        height: int | None = None,
    ) -> bytes | None:
        """Return image bytes for the current mapping."""
        mapping = self._mapping
        source = build_camera_source(self.hass, mapping, self._door_state)
        image = await source.async_image(width=width, height=height)

        if image is not None:
            return image

        if mapping.source_type == CameraSourceType.HA_CAMERA and not source.available:
            return None

        if self._door_state.thumbnail_path and self._door_state.thumbnail_bytes is None:
            await self.coordinator.async_refresh_thumbnail(self._door_id)
            return self.coordinator.data[self._door_id].thumbnail_bytes

        return self._door_state.thumbnail_bytes
