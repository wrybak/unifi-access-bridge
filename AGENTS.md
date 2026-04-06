# AGENTS.md

This file describes the working assumptions for contributors and coding agents.

## Project Goal

Build and maintain a HACS-compatible Home Assistant custom integration named
`unifi_access_bridge` for:

- door unlock via UniFi Access
- door open/closed state
- per-door camera view

## Core Assumptions

1. UniFi Access is the source of truth for:
   - doors
   - door state
   - access events
   - doorbell events
   - thumbnails
   - unlock actions
2. Video must stay decoupled from Access live-stream assumptions.
3. The integration is local-only.
4. No cloud login, Site Manager dependency, or remote control path is allowed.

## Camera Rules

Supported door camera modes:

1. `ha_camera`
   - proxy an existing Home Assistant `camera.*` entity
2. `rtsp`
   - use a manual `rtsp://` or `rtsps://` URL
3. `snapshot`
   - use UniFi Access thumbnail bytes only

Do not assume UniFi Access exposes a stable live-video endpoint.

## API and Port Rules

1. Prefer the adapter layer over direct library usage in entities.
2. Keep `py-unifi-access` isolated behind `access_api.py`.
3. If OpenAPI port is not explicitly configured, auto-probe:
   - `12445`
   - `12455`
4. Persist the resolved port in the config entry.

## Home Assistant Architecture

Keep the integration split into:

- adapter layer
- domain models
- Home Assistant entities/platforms

Preferred runtime behavior:

1. WebSocket push first
2. polling only when push is unavailable
3. shared state via `DataUpdateCoordinator`

## Entity Contract

Required entities:

- `button.<door>_unlock`
- `binary_sensor.<door>_door`
- `camera.<door>_paired_view`

Recommended entities:

- `event.<door>_access`
- `event.<door>_doorbell`

## Mapping Contract

Per-door camera mapping must stay in config entry options and use:

```json
{
  "door_id": "string",
  "source_type": "ha_camera|rtsp|snapshot",
  "value": "camera.entity_id or rtsp url or null"
}
```

## Coding Rules

1. Use typed Python.
2. Avoid blocking I/O in Home Assistant async paths.
3. Keep Access logic separate from camera-source logic.
4. Prefer small modules and small functions.
5. Target a maximum of 250 lines of code per source file when practical.
6. If a file grows beyond that, split by responsibility instead of stacking features.
7. Add docstrings for public modules, classes, and non-trivial methods.

## Change Rules

When changing behavior:

1. update tests
2. preserve HACS compatibility
3. keep README installation steps accurate
4. keep Lovelace example aligned with actual entities

## Testing Expectations

Maintain coverage for at least:

1. config flow success
2. port fallback from `12445` to `12455`
3. unlock button/service behavior
4. open/closed updates
5. HA camera proxy mode
6. snapshot fallback mode
7. options flow persistence
8. websocket reconnect handling

## Documentation Expectations

README should always document:

- HACS installation
- manual installation
- required configuration values
- camera modes
- dashboard example

## Safe Defaults

If requirements are ambiguous, prefer:

1. local-only behavior
2. stable snapshot fallback
3. adapter isolation from upstream library changes
4. explicit configuration over brittle auto-discovery
