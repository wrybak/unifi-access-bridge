"""Config flow for UniFi Access Bridge."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import CONF_API_TOKEN, CONF_OPENAPI_PORT, DOMAIN
from .flow_validation import (
    CannotConnectError,
    InvalidAuthError,
    InvalidSSLError,
    async_validate_connection,
    build_connection_schema,
)
from .options_flow import UnifiAccessBridgeOptionsFlow

_LOGGER = logging.getLogger(__name__)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for UniFi Access Bridge."""

    VERSION = 1

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Handle the initial setup step."""
        if user_input is None:
            return self._show_connection_form("user")

        info, errors = await self._async_validate(user_input, "config flow")
        if errors:
            return self._show_connection_form("user", errors=errors)

        await self.async_set_unique_id(
            f"{user_input['host']}:{info[CONF_OPENAPI_PORT]}"
        )
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=info["title"],
            data={**user_input, CONF_OPENAPI_PORT: info[CONF_OPENAPI_PORT]},
        )

    async def async_step_reauth(
        self,
        entry_data: Mapping[str, Any],
    ) -> FlowResult:
        """Handle re-authentication for invalid API tokens."""
        del entry_data
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Confirm re-authentication with a new API token."""
        if user_input is None:
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=vol.Schema({vol.Required(CONF_API_TOKEN): str}),
                errors={},
            )

        reauth_entry = self._get_reauth_entry()
        data = {**reauth_entry.data, CONF_API_TOKEN: user_input[CONF_API_TOKEN]}
        info, errors = await self._async_validate(data, "reauth flow")
        if errors:
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=vol.Schema({vol.Required(CONF_API_TOKEN): str}),
                errors=errors,
            )

        return self.async_update_reload_and_abort(
            reauth_entry,
            data={**data, CONF_OPENAPI_PORT: info[CONF_OPENAPI_PORT]},
        )

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Handle reconfiguration of controller connection settings."""
        entry = self._get_reconfigure_entry()
        if user_input is None:
            return self._show_connection_form("reconfigure", defaults=entry.data)

        data = {**entry.data, **user_input}
        info, errors = await self._async_validate(data, "reconfigure flow")
        if errors:
            return self._show_connection_form(
                "reconfigure",
                defaults=data,
                errors=errors,
            )

        return self.async_update_reload_and_abort(
            entry,
            data={**data, CONF_OPENAPI_PORT: info[CONF_OPENAPI_PORT]},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return options flow."""
        return UnifiAccessBridgeOptionsFlow(config_entry)

    async def _async_validate(
        self,
        data: Mapping[str, Any],
        context_name: str,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """Validate connection data and translate exceptions into flow errors."""
        try:
            info = await async_validate_connection(self.hass, data)
        except CannotConnectError:
            return {}, {"base": "cannot_connect"}
        except InvalidAuthError:
            return {}, {"base": "invalid_auth"}
        except InvalidSSLError:
            return {}, {"base": "ssl_error"}
        except Exception:
            _LOGGER.exception("Unexpected exception during %s", context_name)
            return {}, {"base": "unknown"}
        return info, {}

    def _show_connection_form(
        self,
        step_id: str,
        *,
        defaults: Mapping[str, Any] | None = None,
        errors: dict[str, str] | None = None,
    ) -> FlowResult:
        """Render a connection settings form."""
        return self.async_show_form(
            step_id=step_id,
            data_schema=build_connection_schema(defaults),
            errors=errors or {},
        )
