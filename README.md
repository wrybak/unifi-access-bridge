# UniFi Access Bridge

`unifi_access_bridge` is a HACS-compatible Home Assistant custom integration that keeps UniFi Access responsible for doors while letting you choose the best video source per door.

It provides:

- `button.<door>_unlock`
- `binary_sensor.<door>_door`
- `camera.<door>_paired_view`
- `event.<door>_access`
- `event.<door>_doorbell`

## Design

The integration is intentionally split in two:

- UniFi Access is the source of truth for doors, unlock actions, door state, access events, doorbell events, and thumbnails.
- Video is configured separately per door:
  - proxy an existing Home Assistant `camera.*` entity,
  - use a manual `rtsp://` or `rtsps://` URL,
  - or fall back to Access thumbnails only.

This keeps the MVP local-only and avoids depending on any cloud login or unstable live-video assumptions in the Access API.

## Installation

### HACS

This integration is ready to be installed as a custom repository in HACS.

1. Open HACS in Home Assistant.
2. Go to `Integrations`.
3. Open the three-dot menu in the top right corner and choose `Custom repositories`.
4. Add `https://github.com/wrybak/unifi-access-bridge` as a repository.
5. Choose category `Integration`.
6. Click `Add`.
7. Search for `UniFi Access Bridge` in HACS and install it.
8. Restart Home Assistant.
9. Go to `Settings -> Devices & Services -> Add Integration`.
10. Search for `UniFi Access Bridge`.
11. Enter:
    - the local controller host or IP,
    - your UniFi Access API token,
    - optional OpenAPI port if you want to bypass auto-probing.

### HACS Notes

- If you leave the OpenAPI port empty, the integration tries `12445` first and then `12455`.
- Camera mapping is configured after setup in the integration options.
- Until the repository is added to the default HACS catalog, install it through `Custom repositories`.

### Manual

1. Copy `custom_components/unifi_access_bridge` into your Home Assistant `config/custom_components` directory.
2. Restart Home Assistant.
3. Add the integration from `Settings -> Devices & Services`.

## Configuration

The config flow asks for:

- `host`
- `api_token`
- `verify_ssl`
- `openapi_port` (optional)

If `openapi_port` is omitted, the integration probes:

1. `12445`
2. `12455`

The resolved port is stored back into the config entry.

## Camera Mapping

Use the integration options flow to configure one source per discovered door.

Supported modes:

1. `Snapshot only`
2. `Existing Home Assistant camera entity`
3. `RTSP/RTSPS URL`

Mappings are stored in config entry options in this shape:

```json
{
  "camera_mappings": {
    "door-001": {
      "door_id": "door-001",
      "source_type": "ha_camera",
      "value": "camera.front_porch"
    }
  }
}
```

## Entities

### Unlock button

Pressing `button.<door>_unlock` calls UniFi Access directly.

The integration also exposes a service:

```yaml
service: unifi_access_bridge.unlock_door
data:
  door_id: door-001
```

### Door sensor

`binary_sensor.<door>_door` is `on` when the door is open and `off` when closed.

### Paired camera

`camera.<door>_paired_view` behaves by mode:

- `ha_camera`: proxies still image and stream source from the selected Home Assistant camera entity
- `rtsp`: returns the configured RTSP/RTSPS URL as the stream source
- `snapshot`: uses UniFi Access thumbnail bytes only

If the mapped Home Assistant camera entity disappears, the paired camera becomes unavailable cleanly.

## Dashboard Example

An example dashboard lives at `docs/LOVELACE_EXAMPLE.yaml`.

Example:

```yaml
type: vertical-stack
cards:
  - type: picture-glance
    title: Front Door
    camera_image: camera.front_door_paired_view
    camera_view: live
    entities:
      - entity: binary_sensor.front_door_door
      - entity: button.front_door_unlock
  - type: entities
    entities:
      - entity: event.front_door_access
      - entity: event.front_door_doorbell
```

## Notes

- The integration is local-LAN only.
- No UniFi Site Manager or cloud auth is used.
- Access thumbnails remain the fallback image path when no live source is configured.
- If you later export a local Access OpenAPI spec to `docs/openapi_access.json`, the adapter is structured so the backend can be swapped without changing the Home Assistant entities.
