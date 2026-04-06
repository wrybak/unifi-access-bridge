"""Button platform for UniFi Access Bridge."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import UnifiAccessBridgeEntity
from .__init__ import UnifiAccessBridgeConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UnifiAccessBridgeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up unlock buttons."""
    coordinator = entry.runtime_data
    added: set[str] = set()

    @callback
    def _add_entities() -> None:
        new_ids = sorted(set(coordinator.data) - added)
        if not new_ids:
            return
        async_add_entities(UnlockDoorButton(coordinator, door_id) for door_id in new_ids)
        added.update(new_ids)

    _add_entities()
    entry.async_on_unload(coordinator.async_add_listener(_add_entities))


class UnlockDoorButton(UnifiAccessBridgeEntity, ButtonEntity):
    """Unlock button for a door."""

    _attr_name = "Unlock"

    def __init__(self, coordinator, door_id: str) -> None:
        """Initialize the unlock button."""
        super().__init__(coordinator, door_id, "unlock")

    async def async_press(self) -> None:
        """Unlock the associated door."""
        await self.coordinator.async_unlock_door(self._door_id)
