# Govee H7015 → Home Assistant

A complete toolkit for controlling **Govee H7015 Outdoor String Lights**
from Home Assistant over Bluetooth Low Energy (BLE), with no cloud
dependency.

The H7015 is **Bluetooth-only** — no WiFi chip, no Govee LAN API. That
rules out the standard `Govee LAN` HACS integration. This project gives
you two ways to bridge the lights into HA:

- **Path A — HACS custom integration (recommended for HA users).** Native
  HA integration that uses HA's built-in Bluetooth framework. Auto-discovery,
  config flow, no extra services to run. Installable via HACS.
- **Path B — Standalone MQTT bridge (for non-HA setups or remote HA).**
  A Python daemon you run on a separate Linux box or ESP32. Useful when
  HA is too far from the lights for Bluetooth range, or when you want to
  drive the lights from openHAB / Node-RED / etc.

Both paths share the same protocol implementation.

---

## Repository layout

```
.
├── custom_components/govee_h7015_ble/   ← Path A: HA native integration (HACS)
├── standalone/                          ← Path B: MQTT bridge + CLI scripts
│   ├── govee_h7015.py
│   ├── scan.py
│   ├── probe.py
│   ├── mqtt_bridge.py
│   └── analyze_hci.py
├── esphome/                             ← Path B variant: ESP32 BLE bridge
├── homeassistant/                       ← Example MQTT YAML (Path B)
├── tests/                               ← Pytest suite (runs in CI)
├── systemd/                             ← systemd unit for Path B
├── docker/                              ← Dockerfile + compose for Path B
├── .github/workflows/                   ← HACS + hassfest + tests CI
├── pyproject.toml                       ← uv-compatible project config
├── hacs.json                            ← HACS repository metadata
└── README.md
```

---

## Path A: HACS custom integration (recommended)

### Install via HACS

1. Add this repository to HACS:
   - HACS → Integrations → ⋮ → Custom repositories
   - URL: `https://github.com/StableEnough/ha-govee-h7015`
   - Category: **Integration**
2. Click **Install** on "Govee H7015 BLE".
3. Restart Home Assistant.
4. Settings → Devices & Services → Add Integration → search "Govee H7015".
5. The H7015 auto-discovers if it's in Bluetooth range; otherwise enter
   the MAC manually.

### Requirements

- Home Assistant 2024.8+
- A working HA Bluetooth setup (built-in radio, ESPHome Bluetooth proxy,
  or a USB Bluetooth dongle)
- H7015 in Bluetooth range

### Features

- Auto-discovery via HA Bluetooth
- Power, brightness, RGB color from the standard HA light UI
- **Color temperature** (warm/cold white, 2000K–6500K) with dedicated white LEDs
- **47 scene modes** + 4 music modes as HA effects
- **15 per-bulb light entities** for individual RGBIC control from the HA UI
- **Custom Lovelace card** with 12 preset patterns + visual bulb editor
- **One-click scene creation** via `snapshot_scene` service or card button
- **Option flow** for configurable poll interval (5–3600s)
- **Diagnostics platform** for easy bug reporting
- Uses HA-recommended `bleak-retry-connector` for reliable BLE connections

See [`custom_components/govee_h7015_ble/info.md`](custom_components/govee_h7015_ble/info.md)
for full integration docs.

---

## Path B: Standalone MQTT bridge

Use this when HA doesn't have Bluetooth (e.g. HA OS in a VM), or when
the lights are outdoors and out of range of your HA host's radio.

### Install with uv

```bash
# Install uv (one-time)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone + sync deps
git clone https://github.com/StableEnough/ha-govee-h7015
cd ha-govee-h7015
uv sync
```

### Find your H7015's MAC

```bash
uv run python standalone/scan.py --name H7015
```

### Probe the lights (confirms protocol matches)

```bash
uv run python standalone/probe.py AA:BB:CC:DD:EE:FF
```

### Run the bridge

```bash
cp .env.example .env
# Edit .env — set GOVEE_DEVICES and MQTT credentials
uv run python standalone/mqtt_bridge.py
```

Or with CLI args:

```bash
uv run python standalone/mqtt_bridge.py \
    --mqtt-host 127.0.0.1 \
    --mqtt-user homeassistant \
    --mqtt-password '...' \
    --devices 'AABBCCDDEEFF=Patio Lights' \
    --poll-interval 30
```

### Make it persistent

systemd:

```bash
sudo cp systemd/govee-h7015-bridge.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now govee-h7015-bridge
sudo journalctl -u govee-h7015-bridge -f
```

Docker:

```bash
cd docker
docker compose up -d --build
docker compose logs -f
```

---

## Path B variant: ESP32 BLE bridge

When the lights are far from any Linux box, an ESP32 next to the lights
bridges BLE → WiFi/MQTT. Flash the YAML in `esphome/` with ESPHome.

See [`esphome/esphome_h7015_bridge.yaml`](esphome/esphome_h7015_bridge.yaml).

---

## Capturing H7015-specific packets (the one manual step)

The base protocol (power, brightness, color, scenes, music modes) is
already implemented from sibling Govee device captures. The one thing
that **may** differ on the H7015 is the per-bulb segment encoding.

To capture it:

1. Enable Bluetooth HCI snoop on Android (Developer options → Bluetooth
   HCI snoop log).
2. Use the Govee app to set individual bulb colors. Start a screen
   recording so you can correlate taps with packets later.
3. Pull the log: `adb bugreport govee.zip && unzip govee.zip -d bugreport`
4. Extract packets:
   ```bash
   uv sync --extra analyze
   uv run python standalone/analyze_hci.py \
       bugreport/FS/data/misc/bluetooth/logs/btsnoop_hci.log --govee-only
   ```
5. If the segment encoding differs from what's in `pkt_segment()`, patch
   that function in either:
   - `custom_components/govee_h7015_ble/protocol.py` (HACS path)
   - `standalone/govee_h7015.py` (MQTT bridge path)

---

## Topic reference (Path B)

| Topic | Direction | Payload |
|-------|-----------|---------|
| `govee/h7015/<MAC>/set` | HA → bridge | `{"cmd":"power","value":true}` |
| `govee/h7015/<MAC>/set` | HA → bridge | `{"cmd":"brightness","value":50}` |
| `govee/h7015/<MAC>/set` | HA → bridge | `{"cmd":"color","r":255,"g":0,"b":0}` |
| `govee/h7015/<MAC>/set` | HA → bridge | `{"cmd":"scene","name":"rainbow"}` |
| `govee/h7015/<MAC>/set` | HA → bridge | `{"cmd":"segment","bulb":0,"r":255,"g":0,"b":0}` |
| `govee/h7015/<MAC>/state` | bridge → HA | `{"state":"ON","brightness":50,...}` |
| `govee/h7015/<MAC>/availability` | bridge → HA | `online` / `offline` |

---

## Development

```bash
# Install dev deps (includes HA test framework + Hypothesis)
uv sync --extra dev --extra analyze

# Run tests (126 tests: protocol + pydantic models + HA integration + Hypothesis fuzzing)
uv run pytest tests/ -v

# Run with Hypothesis statistics
uv run pytest tests/test_protocol_property.py tests/test_models_property.py --hypothesis-show-statistics

# Lint + format
uv run ruff check .
uv run ruff format --check .

# Auto-fix lint issues
uv run ruff check --fix .
uv run ruff format .

# Type-check with mypy --strict
uv run mypy --strict standalone

# Install pre-commit hooks
uv run pre-commit install
uv run pre-commit run --all-files
```

Or use the included `justfile`:

```bash
just setup    # one-time: install uv + sync deps
just test     # run tests
just ci       # lint + typecheck + test
just hooks    # install pre-commit
```

CI runs HACS validation, hassfest, and the pytest suite (including real HA
integration tests and Hypothesis fuzzing) on every push (see
`.github/workflows/`).

### Type safety & validation

The codebase targets **Python 3.12+** and is fully type-annotated. Key
features:

- **Pydantic models** for every HA MQTT payload — `PowerCommand`,
  `BrightnessCommand`, `ColorCommand`, `SceneCommand`, `MusicCommand`,
  `SegmentCommand`, `WarmCommand` as a discriminated union. Bad JSON is
  rejected with a clear `ValidationError` at the boundary, not a `KeyError`
  deep in the bridge.
- **Pydantic Settings** for config — env vars and CLI args are validated at
  startup. A typo like `GOVEE_MQTT_PORT=abc` crashes immediately.
- `mypy --strict` configured (see `pyproject.toml`)
- `NewType` for `MacAddress` and `RawPacket` — prevents stringly-typed bugs
- `TypedDict` for HA MQTT payload shapes
- `Protocol` class for the BLE client — testable without a real radio
- Proper exception hierarchy (`GoveeError` → `GoveeConnectionError` / etc.)
- `@override` decorator on all HA entity method overrides
- `@dataclass(frozen=True, slots=True)` for immutable state
- `match` statements for command dispatch
- `asyncio.timeout()` on every BLE operation (no hangs)

### Async architecture

The MQTT bridge uses **aiomqtt** (pure async, no thread handoffs):

- No `run_coroutine_threadsafe` — messages are received on the event loop
  directly
- MQTT reconnect handled with exponential backoff
- BLE operations use `asyncio.timeout()` to prevent hangs
- Clean shutdown via `stop_event` + task cancellation

### Real HA integration tests

The test suite includes **6 real Home Assistant integration tests** that
exercise the actual config flow, entity setup, and service registration
using `pytest-homeassistant-custom-component`:

- `test_config_flow_user_manual_mac` — manual MAC entry creates a config entry
- `test_config_flow_rejects_invalid_mac` — bad MACs show a validation error
- `test_config_flow_normalizes_mac` — `aabbccddeeff` → `AA:BB:CC:DD:EE:FF`
- `test_setup_entry_creates_light` — setup creates a coordinator + service
- `test_unload_entry_cleans_up` — unload removes the coordinator
- `test_set_bulb_service_routes_to_coordinator` — service calls reach the BLE layer

### HA Bluetooth best practices

This integration follows the [HA Bluetooth developer guidelines](https://developers.home-assistant.io/docs/bluetooth):

- **`bluetooth_adapters` dependency** in `manifest.json` — ensures all remote
  adapters are connected before the integration starts
- **`bleak-retry-connector`** for reliable BLE connections — handles transient
  BlueZ errors automatically (recommended by HA docs)
- **`async_address_reachability_diagnostics`** — human-readable error messages
  explaining why a device is unreachable (out of range, no adapter, etc.)
- **`asyncio.timeout()` on every BLE op** — no indefinite hangs
- **Persistent connection with keepalive** — `iot_class: local_push`
- **Option flow** for poll interval — configurable from the UI
- **Diagnostics platform** — users can download diagnostic data for bug reports

### Why not the official Govee LAN integration?

The H7015 is **not** in the [official `govee_light_local` supported device
list](https://www.home-assistant.io/integrations/govee_light_local/) — that
integration only supports WiFi-capable Govee lights (H7020, H7021, etc.).
The H7015 is Bluetooth-only with no WiFi chip, so the LAN API is not
available. This BLE integration is the only local-control option.

---

## How the Govee BLE protocol works

Shared across the Govee RGBIC BLE family (H6054, H6113, H6127, H617A,
H7015, H7020):

- GATT service: `00010203-0405-0607-0809-0a0b0c0d1910`
- Write char: `00010203-0405-0607-0809-0a0b0c0d2b11`
- Read char: `00010203-0405-0607-0809-0a0b0c0d2b10`
- Packets: 20 bytes, zero-padded
- Byte 0: `0x33` (command) / `0xAA` (keepalive) / `0xA1` (DIY write)
- Byte 1: command type
- Bytes 2-18: payload
- Byte 19: XOR checksum of bytes 0-18

Sources: BeauJBurroughs/Govee-H6127-Reverse-Engineering,
blog.coding.kiwi/reverse-engineering-govee-smart-lights,
community.home-assistant.io Govee H617A reverse-engineering thread,
xda-developers.com reverse-engineered Govee smart lights article.

---

## Troubleshooting

### `Device not found` / `Could not connect`

- The H7015 only allows **one** BLE connection at a time. Close the
  Govee Home app on your phone first.
- On Linux, ensure your user is in the `bluetooth` group.
- Restart Bluetooth: `sudo systemctl restart bluetooth`.
- For Path A: use an ESPHome Bluetooth proxy if range is the issue.

### State in HA doesn't update after using the Govee app

- The H7015 doesn't push state. Reduce `poll_interval` to poll more often.

### Connection drops frequently

- Increase `reconnect_backoff` (Path B) or use an ESP32 bridge (Path B variant).
- USB Bluetooth 5.0 dongles with external antennas reach much further
  than the typical Pi's onboard radio.

---

## Legal

Reverse engineering for interoperability is permitted under
17 USC §1201(f) (DMCA). This project is for personal use with hardware
you own.

## License

GPLv3. Contributions welcome, especially H7015-specific segment capture
data.
