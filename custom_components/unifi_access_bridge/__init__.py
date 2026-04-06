"""UniFi Access Bridge integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady, ServiceValidationError
import voluptuous as vol

from .access_api import (
    UnifiAccessAuthenticationError,
    UnifiAccessBridgeError,
    async_create_access_adapter,
)
from .const import (
    ATTR_DOOR_ID,
    CONF_API_TOKEN,
    CONF_OPENAPI_PORT,
    DOMAIN,
    PLATFORMS,
    SERVICE_UNLOCK_DOOR,
)
from .coordinator import UnifiAccessBridgeCoordinator

UnifiAccessBridgeConfigEntry = ConfigEntry[UnifiAccessBridgeCoordinator]

SERVICE_UNLOCK_SCHEMA = vol.Schema({vol.Required(ATTR_DOOR_ID): str})


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the integration domain."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UnifiAccessBridgeConfigEntry,
) -> bool:
    """Set up the integration from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    try:
        adapter, resolved_port = await async_create_access_adapter(
            hass,
            host=entry.data[CONF_HOST],
            api_token=entry.data[CONF_API_TOKEN],
            verify_ssl=entry.data.get(CONF_VERIFY_SSL, False),
            requested_port=entry.data.get(CONF_OPENAPI_PORT),
        )
    except UnifiAccessAuthenticationError as err:
        raise ConfigEntryAuthFailed from err
    except UnifiAccessBridgeError as err:
        raise ConfigEntryNotReady(str(err)) from err

    if entry.data.get(CONF_OPENAPI_PORT) != resolved_port:
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_OPENAPI_PORT: resolved_port},
        )

    coordinator = UnifiAccessBridgeCoordinator(hass, entry, adapter)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await _async_ensure_service(hass)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: UnifiAccessBridgeConfigEntry,
) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    coordinator = hass.data[DOMAIN].pop(entry.entry_id)
    await coordinator.async_shutdown()

    if not hass.data[DOMAIN]:
        hass.services.async_remove(DOMAIN, SERVICE_UNLOCK_DOOR)

    return True


async def async_reload_entry(
    hass: HomeAssistant,
    entry: UnifiAccessBridgeConfigEntry,
) -> None:
    """Reload an entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_ensure_service(hass: HomeAssistant) -> None:
    """Register the unlock service once per Home Assistant instance."""
    if hass.services.has_service(DOMAIN, SERVICE_UNLOCK_DOOR):
        return

    async def _async_handle_unlock(call: ServiceCall) -> None:
        door_id = call.data[ATTR_DOOR_ID]
        for coordinator in hass.data[DOMAIN].values():
            if door_id in coordinator.data:
                await coordinator.async_unlock_door(door_id)
                return

        raise ServiceValidationError(f"Unknown door_id: {door_id}")

    hass.services.async_register(
        DOMAIN,
        SERVICE_UNLOCK_DOOR,
        _async_handle_unlock,
        schema=SERVICE_UNLOCK_SCHEMA,
    )
