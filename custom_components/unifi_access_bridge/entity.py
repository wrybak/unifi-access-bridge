"""Base entity classes for UniFi Access Bridge."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import UnifiAccessBridgeCoordinator
from .models import DoorState


class UnifiAccessBridgeEntity(CoordinatorEntity[UnifiAccessBridgeCoordinator]):
    """Base entity for a normalized door."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: UnifiAccessBridgeCoordinator,
        door_id: str,
        suffix: str,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._door_id = door_id
        self._attr_unique_id = f"{door_id}_{suffix}"

    @property
    def available(self) -> bool:
        """Return whether the entity is available."""
        return super().available and self._door_id in self.coordinator.data

    @property
    def _door_state(self) -> DoorState:
        """Return the normalized state for this door."""
        return self.coordinator.data[self._door_id]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose common state attributes on all entities."""
        attributes: dict[str, Any] = {
            "door_id": self._door_id,
            "full_name": self._door_state.full_name,
            "websocket_connected": self.coordinator.websocket_connected,
        }
        if self.coordinator.last_websocket_disconnect_at is not None:
            attributes["last_websocket_disconnect_at"] = (
                self.coordinator.last_websocket_disconnect_at.isoformat()
            )
        return attributes

    @property
    def device_info(self) -> dict[str, Any]:
        """Return Home Assistant device info."""
        return {
            "identifiers": {(DOMAIN, self._door_id)},
            "name": self._door_state.name,
            "manufacturer": "Ubiquiti",
            "model": "UniFi Access Door",
        }
