"""Tests for the config flow."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.data_entry_flow import FlowResultType

from custom_components.unifi_access_bridge.const import CONF_OPENAPI_PORT, DOMAIN

from .conftest import FakeAdapter, MOCK_CONFIG, make_door_state


async def test_config_flow_success(hass) -> None:
    """Create a config entry after a successful validation."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "user"},
    )

    with patch(
        "custom_components.unifi_access_bridge.config_flow.async_create_access_adapter",
        return_value=(FakeAdapter(make_door_state()), 12455),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={k: v for k, v in MOCK_CONFIG.items() if k != CONF_OPENAPI_PORT},
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_OPENAPI_PORT] == 12455
