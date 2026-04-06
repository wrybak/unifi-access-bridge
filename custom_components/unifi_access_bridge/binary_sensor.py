"""Binary sensor platform for UniFi Access Bridge."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import UnifiAccessBridgeEntity
from .__init__ import UnifiAccessBridgeConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UnifiAccessBridgeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up door position binary sensors."""
    coordinator = entry.runtime_data
    added: set[str] = set()

    @callback
    def _add_entities() -> None:
        new_ids = sorted(set(coordinator.data) - added)
        if not new_ids:
            return
        async_add_entities(DoorPositionBinarySensor(coordinator, door_id) for door_id in new_ids)
        added.update(new_ids)

    _add_entities()
    entry.async_on_unload(coordinator.async_add_listener(_add_entities))


class DoorPositionBinarySensor(UnifiAccessBridgeEntity, BinarySensorEntity):
    """Door open/closed sensor."""

    _attr_device_class = BinarySensorDeviceClass.DOOR
    _attr_name = "Door"

    @property
    def is_on(self) -> bool:
        """Return True if the door is open."""
        return self._door_state.is_open
