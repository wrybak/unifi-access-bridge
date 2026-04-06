"""Tests for the options flow."""

from __future__ import annotations

from types import SimpleNamespace

from homeassistant.data_entry_flow import FlowResultType

from custom_components.unifi_access_bridge.const import CONF_CAMERA_MAPPINGS, DOMAIN

from .conftest import make_door_state


async def test_options_flow_persists_per_door_mappings(hass, mock_config_entry) -> None:
    """Store camera mappings in config entry options."""
    mock_config_entry.runtime_data = SimpleNamespace(
        data={
            "door-001": make_door_state(door_id="door-001", name="Back Door"),
            "door-002": make_door_state(door_id="door-002", name="Front Door"),
        }
    )
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "door"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={"source_type": "snapshot"},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "door"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "source_type": "rtsp",
            "value": "rtsp://camera.local/front",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY

    mappings = mock_config_entry.options[CONF_CAMERA_MAPPINGS]
    assert mappings["door-001"] == {
        "door_id": "door-001",
        "source_type": "snapshot",
        "value": None,
    }
    assert mappings["door-002"] == {
        "door_id": "door-002",
        "source_type": "rtsp",
        "value": "rtsp://camera.local/front",
    }


async def test_options_flow_requires_value_for_rtsp_mapping(
    hass, mock_config_entry
) -> None:
    """Keep the current door on screen when a value-backed mapping is incomplete."""
    mock_config_entry.runtime_data = SimpleNamespace(
        data={"door-001": make_door_state(door_id="door-001", name="Back Door")}
    )
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "door"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={"source_type": "rtsp", "value": ""},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "door"
    assert result["errors"] == {"base": "missing_value"}
