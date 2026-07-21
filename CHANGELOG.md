# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2026-07-11

### Added
- Color temperature support (warm/cold white, 2000K–6500K) with dedicated white LEDs
- 47 scene modes (up from 12) — nature, seasons, holidays, activities, patterns
- 15 per-bulb light entities for individual RGBIC control from the HA UI
- Custom Lovelace card with 12 preset patterns (Rainbow, Fireplace, Ocean, Christmas, etc.)
- One-click scene creation via `snapshot_scene` service and card button
- Option flow for configurable poll interval (5–3600s, slider UI)
- Diagnostics platform for downloadable bug reports
- `bleak-retry-connector` for reliable BLE connections (HA-recommended)
- `async_address_reachability_diagnostics` for human-readable connection errors
- `after_deps: ["bluetooth"]` in manifest for proper HA load ordering
- Pydantic models for all HA MQTT payloads with discriminated union validation
- Hypothesis property-based fuzzing tests (1200+ iterations per CI run)
- Real HA integration tests using `pytest-homeassistant-custom-component`
- `.gitignore`, `.dockerignore`, `pre-commit` hooks, `justfile`
- ESP32 BLE→MQTT bridge config with connection guards on all scripts

### Fixed
- `GOVEE_DEVICES` env var silently ignored (Pydantic alias mismatch)
- Coordinator `state` property shadowed HA's `DataUpdateCoordinator.state`
- MQTT reconnect started duplicate BLE tasks (device bridges now started once)
- `turn_on(brightness=)` didn't power on the light
- `disconnect()` triggered immediate reconnect (no `_intentional_disconnect` flag)
- `_ensure_connected` race condition (added `_connect_lock` with double-check)
- `set_bulb` service applied to ALL devices when no target specified
- Coordinator leaked on first-refresh failure (now stored before refresh)
- Division by zero in color temperature conversion
- Bulb `is_on` returned True for black (0,0,0) color
- `snapshot_scene` generated wrong entity IDs (now uses entity registry)
- Manifest bluetooth matcher too broad (removed shared service_uuid)
- Stale entity state after commands (command methods now update `self.data`)
- `async_request_refresh` coroutine never awaited warning
- `analyze_hci.py` direction logic (now based on MAC match, not src≠dst)
- ESPHome `ble_write` scripts crash if BLE disconnected (added connection guards)
- MQTT bridge `publish_state` reported wrong color_mode in CT mode

### Changed
- Migrated from `paho-mqtt` to `aiomqtt` (pure async, no thread handoffs)
- Migrated from `requirements.txt` to `pyproject.toml` + `uv`
- Bumped Python requirement from 3.11 to 3.12
- `iot_class` from `local_polling` to `local_push`
- All `Optional[T]` → `T | None` (PEP 604)
- All `Union[A, B]` → `A | B`
- Replaced fragile `_keep_state` helper with `dataclasses.replace()`
- Replaced manual MAC validation with Pydantic `DeviceConfig`
- README updated with full feature list and HA best practices documentation

## [1.0.0] - 2026-07-10

### Added
- Initial release
- BLE protocol library implementing Govee RGBIC BLE protocol
- Home Assistant custom integration with config flow and auto-discovery
- Standalone MQTT bridge daemon with aiomqtt
- ESP32 BLE bridge config for ESPHome
- HCI snoop log analyzer for protocol capture
- 12 scene modes, 4 music modes
- Per-bulb segment control via `set_bulb` service
- Power, brightness, RGB color control
- Keepalive with auto-reconnect
- State persistence across daemon restarts
- Docker and systemd deployment support
