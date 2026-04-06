"""Options flow for per-door camera mappings."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_VERIFY_SSL
from homeassistant.data_entry_flow import FlowResult

from .access_api import async_create_access_adapter
from .const import (
    CONF_API_TOKEN,
    CONF_CAMERA_MAPPINGS,
    CONF_OPENAPI_PORT,
    CONF_SOURCE_TYPE,
    CONF_SOURCE_VALUE,
)
from .models import CameraMapping, CameraSourceType

SOURCE_TYPE_LABELS = {
    CameraSourceType.SNAPSHOT.value: "Snapshot only",
    CameraSourceType.HA_CAMERA.value: "Existing Home Assistant camera entity",
    CameraSourceType.RTSP.value: "RTSP/RTSPS URL",
}


class UnifiAccessBridgeOptionsFlow(config_entries.OptionsFlow):
    """Configure per-door camera mappings."""

    def __init__(self, config_entry) -> None:
        """Initialize the options flow."""
        self.config_entry = config_entry
        self._doors: list[tuple[str, str]] = []
        self._door_index = 0
        self._mappings: dict[str, dict[str, str | None]] = dict(
            config_entry.options.get(CONF_CAMERA_MAPPINGS, {})
        )

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Load discovered doors and start the per-door wizard."""
        del user_input
        self._doors = await self._async_get_doors()
        self._door_index = 0

        if not self._doors:
            return self.async_create_entry(
                title="",
                data={CONF_CAMERA_MAPPINGS: self._mappings},
            )
        return await self.async_step_door()

    async def async_step_door(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Configure one door mapping and continue to the next door."""
        if self._door_index >= len(self._doors):
            return self.async_create_entry(
                title="",
                data={CONF_CAMERA_MAPPINGS: self._mappings},
            )

        door_id, door_name = self._doors[self._door_index]
        current_mapping = CameraMapping.from_dict(door_id, self._mappings.get(door_id))
        errors: dict[str, str] = {}

        if user_input is not None:
            pending_mapping = CameraMapping(
                door_id=door_id,
                source_type=CameraSourceType(user_input[CONF_SOURCE_TYPE]),
                value=self._normalize_value(user_input.get(CONF_SOURCE_VALUE)),
            )
            if self._mapping_requires_value(pending_mapping):
                errors["base"] = "missing_value"
                return self._show_door_form(
                    door_name,
                    pending_mapping,
                    errors=errors,
                )

            self._mappings[door_id] = pending_mapping.as_dict()
            self._door_index += 1
            return await self.async_step_door()

        return self._show_door_form(door_name, current_mapping, errors=errors)

    def _show_door_form(
        self,
        door_name: str,
        mapping: CameraMapping,
        *,
        errors: dict[str, str] | None = None,
    ) -> FlowResult:
        """Render the current door mapping form."""
        return self.async_show_form(
            step_id="door",
            data_schema=vol.Schema(self._build_door_fields(mapping)),
            description_placeholders={
                "door_name": door_name,
                "door_number": str(self._door_index + 1),
                "door_total": str(len(self._doors)),
            },
            errors=errors or {},
        )

    async def _async_get_doors(self) -> list[tuple[str, str]]:
        """Return discovered doors for the options flow."""
        runtime_data = getattr(self.config_entry, "runtime_data", None)
        if runtime_data is not None and runtime_data.data:
            return sorted((door_id, door.name) for door_id, door in runtime_data.data.items())

        adapter, _resolved_port = await async_create_access_adapter(
            self.hass,
            host=self.config_entry.data[CONF_HOST],
            api_token=self.config_entry.data[CONF_API_TOKEN],
            verify_ssl=self.config_entry.data.get(CONF_VERIFY_SSL, False),
            requested_port=self.config_entry.data.get(CONF_OPENAPI_PORT),
        )
        try:
            doors = await adapter.async_get_doors()
        finally:
            await adapter.async_close()

        return sorted((door_id, door.name) for door_id, door in doors.items())

    @staticmethod
    def _mapping_requires_value(mapping: CameraMapping) -> bool:
        """Return whether a mapping is incomplete."""
        return (
            mapping.source_type in {CameraSourceType.HA_CAMERA, CameraSourceType.RTSP}
            and not mapping.value
        )

    @staticmethod
    def _normalize_value(value: Any) -> str | None:
        """Normalize the mapping value from form input."""
        if value in (None, ""):
            return None
        return str(value)

    @staticmethod
    def _build_door_fields(mapping: CameraMapping) -> dict[Any, Any]:
        """Build the schema fields for a single door form."""
        fields: dict[Any, Any] = {
            vol.Required(
                CONF_SOURCE_TYPE,
                default=mapping.source_type.value,
            ): vol.In(SOURCE_TYPE_LABELS),
            vol.Optional(
                CONF_SOURCE_VALUE,
                default=mapping.value or "",
            ): str,
        }
        return fields
