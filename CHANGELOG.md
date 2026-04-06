# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog and the project uses Semantic Versioning.

## [0.1.1] - 2026-04-06

### Fixed
- Added compatibility with legacy `unifi_access_api` client constructors that do not accept the `use_polling` argument.
- Improved Home Assistant runtime compatibility across coordinator, config flow, camera platform, and options flow behavior.
- Restored reliable websocket-to-polling fallback behavior and covered it with tests.

### Changed
- Refactored the integration to keep UniFi Access library details behind a dedicated client and adapter boundary.
- Updated docs and translations to reflect current runtime behavior and options flow validation.

## [0.1.0] - 2026-04-05

### Added
- Initial HACS-compatible release of `unifi_access_bridge`.
- Unlock button, door binary sensor, paired camera entity, and access and doorbell event entities.
- Port probing from `12445` to `12455`, snapshot fallback camera mode, and configurable per-door camera mappings.
- Initial config flow, options flow, docs, examples, and automated tests.
