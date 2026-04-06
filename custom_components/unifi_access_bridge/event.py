"""Event platform for UniFi Access Bridge."""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .__init__ import UnifiAccessBridgeConfigEntry
from .const import ACCESS_EVENT_DENIED, ACCESS_EVENT_GRANTED, DOORBELL_EVENT_RING
from .entity import UnifiAccessBridgeEntity
from .models import DoorEventPayload


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UnifiAccessBridgeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up event entities."""
    del hass
    coordinator = entry.runtime_data
    added: set[str] = set()

    @callback
    def _add_entities() -> None:
        new_ids = sorted(set(coordinator.data) - added)
        if not new_ids:
            return

        entities = [
            entity
            for door_id in new_ids
            for entity in (
                DoorAccessEventEntity(coordinator, door_id),
                DoorBellEventEntity(coordinator, door_id),
            )
        ]
        async_add_entities(entities)
        added.update(new_ids)

    _add_entities()
    entry.async_on_unload(coordinator.async_add_listener(_add_entities))


class _BaseDoorEventEntity(UnifiAccessBridgeEntity, EventEntity):
    """Base class for stateful door event entities."""

    _category: str

    def __init__(self, coordinator, door_id: str, suffix: str) -> None:
        """Initialize the event entity."""
        super().__init__(coordinator, door_id, suffix)
        self._last_payload: DoorEventPayload | None = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to coordinator door events."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_subscribe_door_events(self._handle_event)
        )

    @callback
    def _handle_event(self, payload: DoorEventPayload) -> None:
        """Receive coordinator events and publish them through HA."""
        if payload.door_id != self._door_id or payload.category != self._category:
            return

        self._last_payload = payload
        self._trigger_event(payload.event_type, payload.attributes)
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return common and event-specific attributes."""
        attributes = super().extra_state_attributes
        if self._last_payload is not None:
            attributes.update(self._last_payload.attributes)
        return attributes


class DoorAccessEventEntity(_BaseDoorEventEntity):
    """Access event entity."""

    _attr_event_types = [ACCESS_EVENT_GRANTED, ACCESS_EVENT_DENIED]  # noqa: RUF012
    _attr_name = "Access"
    _category = "access"

    def __init__(self, coordinator, door_id: str) -> None:
        """Initialize the access event entity."""
        super().__init__(coordinator, door_id, "access")


class DoorBellEventEntity(_BaseDoorEventEntity):
    """Doorbell event entity."""

    _attr_event_types = [DOORBELL_EVENT_RING]  # noqa: RUF012
    _attr_name = "Doorbell"
    _category = "doorbell"

    def __init__(self, coordinator, door_id: str) -> None:
        """Initialize the doorbell event entity."""
        super().__init__(coordinator, door_id, "doorbell")
