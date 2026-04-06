"""Config flow for UniFi Access Bridge."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_VERIFY_SSL
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.selector import EntitySelector, EntitySelectorConfig

from .access_api import (
    UnifiAccessAuthenticationError,
    UnifiAccessBridgeError,
    UnifiAccessSSLError,
    async_create_access_adapter,
)
from .const import (
    CONF_API_TOKEN,
    CONF_CAMERA_MAPPINGS,
    CONF_OPENAPI_PORT,
    CONF_SOURCE_TYPE,
    CONF_SOURCE_VALUE,
    DOMAIN,
)
from .models import CameraMapping, CameraSourceType

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_API_TOKEN): str,
        vol.Optional(CONF_VERIFY_SSL, default=False): bool,
        vol.Optional(CONF_OPENAPI_PORT): vol.Coerce(int),
    }
)


async def _async_validate_input(hass, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    try:
        adapter, resolved_port = await async_create_access_adapter(
            hass,
            host=data[CONF_HOST],
            api_token=data[CONF_API_TOKEN],
            verify_ssl=data.get(CONF_VERIFY_SSL, False),
            requested_port=data.get(CONF_OPENAPI_PORT),
        )
    except UnifiAccessAuthenticationError as err:
        raise InvalidAuthError from err
    except UnifiAccessSSLError as err:
        raise InvalidSSLError from err
    except UnifiAccessBridgeError as err:
        raise CannotConnectError from err

    await adapter.async_close()

    return {
        "title": data[CONF_HOST],
        CONF_OPENAPI_PORT: resolved_port,
    }


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for UniFi Access Bridge."""

    VERSION = 1

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await _async_validate_input(self.hass, user_input)
            except CannotConnectError:
                errors["base"] = "cannot_connect"
            except InvalidAuthError:
                errors["base"] = "invalid_auth"
            except InvalidSSLError:
                errors["base"] = "ssl_error"
            except Exception:
                _LOGGER.exception("Unexpected exception during config flow")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(
                    f"{user_input[CONF_HOST]}:{info[CONF_OPENAPI_PORT]}"
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=info["title"],
                    data={**user_input, CONF_OPENAPI_PORT: info[CONF_OPENAPI_PORT]},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(
        self,
        entry_data: Mapping[str, Any],
    ) -> ConfigFlowResult:
        """Handle re-authentication for invalid API tokens."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Confirm re-authentication with a new API token."""
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()

        if user_input is not None:
            data = {**reauth_entry.data, CONF_API_TOKEN: user_input[CONF_API_TOKEN]}
            try:
                info = await _async_validate_input(self.hass, data)
            except CannotConnectError:
                errors["base"] = "cannot_connect"
            except InvalidAuthError:
                errors["base"] = "invalid_auth"
            except InvalidSSLError:
                errors["base"] = "ssl_error"
            except Exception:
                _LOGGER.exception("Unexpected exception during reauth flow")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data={**data, CONF_OPENAPI_PORT: info[CONF_OPENAPI_PORT]},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_TOKEN): str}),
            errors=errors,
        )

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle reconfiguration of the controller connection settings."""
        errors: dict[str, str] = {}
        reconfigure_entry = self._get_reconfigure_entry()

        if user_input is not None:
            data = {**reconfigure_entry.data, **user_input}
            try:
                info = await _async_validate_input(self.hass, data)
            except CannotConnectError:
                errors["base"] = "cannot_connect"
            except InvalidAuthError:
                errors["base"] = "invalid_auth"
            except InvalidSSLError:
                errors["base"] = "ssl_error"
            except Exception:
                _LOGGER.exception("Unexpected exception during reconfigure flow")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    reconfigure_entry,
                    data={**data, CONF_OPENAPI_PORT: info[CONF_OPENAPI_PORT]},
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_HOST,
                        default=reconfigure_entry.data[CONF_HOST],
                    ): str,
                    vol.Required(
                        CONF_API_TOKEN,
                        default=reconfigure_entry.data[CONF_API_TOKEN],
                    ): str,
                    vol.Optional(
                        CONF_VERIFY_SSL,
                        default=reconfigure_entry.data.get(CONF_VERIFY_SSL, False),
                    ): bool,
                    vol.Optional(
                        CONF_OPENAPI_PORT,
                        default=reconfigure_entry.data.get(CONF_OPENAPI_PORT),
                    ): vol.Any(None, vol.Coerce(int)),
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return options flow."""
        return UnifiAccessBridgeOptionsFlow(config_entry)


class UnifiAccessBridgeOptionsFlow(config_entries.OptionsFlow):
    """Options flow for configuring door-to-camera mappings."""

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
    ) -> ConfigFlowResult:
        """Initialize the options flow."""
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
    ) -> ConfigFlowResult:
        """Configure a single door mapping and continue to the next door."""
        if self._door_index >= len(self._doors):
            return self.async_create_entry(
                title="",
                data={CONF_CAMERA_MAPPINGS: self._mappings},
            )

        door_id, door_name = self._doors[self._door_index]
        current_mapping = CameraMapping.from_dict(door_id, self._mappings.get(door_id))
        selected_source = current_mapping.source_type
        errors: dict[str, str] = {}

        if user_input is not None:
            selected_source = CameraSourceType(user_input[CONF_SOURCE_TYPE])
            value = user_input.get(CONF_SOURCE_VALUE)
            pending_mapping = CameraMapping(
                door_id=door_id,
                source_type=selected_source,
                value=value if value else None,
            )

            if selected_source == CameraSourceType.HA_CAMERA and not value:
                return self._show_door_form(
                    door_name,
                    selected_source,
                    current_mapping=pending_mapping,
                    errors=errors,
                )

            if selected_source == CameraSourceType.RTSP and not value:
                return self._show_door_form(
                    door_name,
                    selected_source,
                    current_mapping=pending_mapping,
                    errors=errors,
                )

            self._mappings[door_id] = pending_mapping.as_dict()
            self._door_index += 1
            return await self.async_step_door()

        return self._show_door_form(
            door_name,
            selected_source,
            current_mapping=current_mapping,
            errors=errors,
        )

    def _show_door_form(
        self,
        door_name: str,
        selected_source: CameraSourceType,
        *,
        current_mapping: CameraMapping,
        errors: dict[str, str],
    ) -> ConfigFlowResult:
        """Render the current door mapping form."""
        schema_fields: dict[Any, Any] = {
            vol.Required(
                CONF_SOURCE_TYPE,
                default=selected_source.value,
            ): vol.In(
                {
                    CameraSourceType.SNAPSHOT.value: "Snapshot only",
                    CameraSourceType.HA_CAMERA.value: "Existing Home Assistant camera entity",
                    CameraSourceType.RTSP.value: "RTSP/RTSPS URL",
                }
            ),
        }

        if selected_source == CameraSourceType.HA_CAMERA:
            value_key = (
                vol.Required(CONF_SOURCE_VALUE, default=current_mapping.value)
                if current_mapping.value
                else vol.Required(CONF_SOURCE_VALUE)
            )
            schema_fields[value_key] = EntitySelector(EntitySelectorConfig(domain="camera"))
        elif selected_source == CameraSourceType.RTSP:
            value_key = (
                vol.Required(CONF_SOURCE_VALUE, default=current_mapping.value)
                if current_mapping.value
                else vol.Required(CONF_SOURCE_VALUE)
            )
            schema_fields[value_key] = str

        return self.async_show_form(
            step_id="door",
            data_schema=vol.Schema(schema_fields),
            description_placeholders={
                "door_name": door_name,
                "door_number": str(self._door_index + 1),
                "door_total": str(len(self._doors)),
            },
            errors=errors,
        )

    async def _async_get_doors(self) -> list[tuple[str, str]]:
        """Return discovered doors for the options flow."""
        runtime_data = getattr(self.config_entry, "runtime_data", None)
        if runtime_data is not None and runtime_data.data:
            return sorted(
                (door_id, door.name)
                for door_id, door in runtime_data.data.items()
            )

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


class CannotConnectError(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidSSLError(HomeAssistantError):
    """Error to indicate SSL verification failed."""


class InvalidAuthError(HomeAssistantError):
    """Error to indicate invalid authentication."""
