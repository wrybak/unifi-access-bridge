"""Validation helpers for UniFi Access Bridge config flows."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.const import CONF_HOST, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .access_api import (
    UnifiAccessAuthenticationError,
    UnifiAccessBridgeError,
    UnifiAccessSSLError,
    async_create_access_adapter,
)
from .const import CONF_API_TOKEN, CONF_OPENAPI_PORT


async def async_validate_connection(
    hass: HomeAssistant,
    data: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate that the provided input allows us to connect."""
    try:
        adapter, resolved_port = await async_create_access_adapter(
            hass,
            host=str(data[CONF_HOST]),
            api_token=str(data[CONF_API_TOKEN]),
            verify_ssl=bool(data.get(CONF_VERIFY_SSL, False)),
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
        "title": str(data[CONF_HOST]),
        CONF_OPENAPI_PORT: resolved_port,
    }


def build_connection_schema(
    defaults: Mapping[str, Any] | None = None,
) -> vol.Schema:
    """Build the connection form schema for user and reconfigure flows."""
    defaults = defaults or {}

    fields: dict[Any, Any] = {
        _required_field(CONF_HOST, defaults): str,
        _required_field(CONF_API_TOKEN, defaults): str,
        vol.Optional(
            CONF_VERIFY_SSL,
            default=defaults.get(CONF_VERIFY_SSL, False),
        ): bool,
        _optional_field(CONF_OPENAPI_PORT, defaults): vol.Any(None, vol.Coerce(int)),
    }
    return vol.Schema(fields)


class CannotConnectError(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidSSLError(HomeAssistantError):
    """Error to indicate SSL verification failed."""


class InvalidAuthError(HomeAssistantError):
    """Error to indicate invalid authentication."""


def _required_field(key: str, defaults: Mapping[str, Any]) -> vol.Marker:
    """Build a required field with an optional default."""
    if key in defaults:
        return vol.Required(key, default=defaults[key])
    return vol.Required(key)


def _optional_field(key: str, defaults: Mapping[str, Any]) -> vol.Marker:
    """Build an optional field with an optional default."""
    if key in defaults:
        return vol.Optional(key, default=defaults[key])
    return vol.Optional(key)
