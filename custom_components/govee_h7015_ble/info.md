# Govee H7015 BLE

Local Bluetooth control of **Govee H7015 Outdoor String Lights** directly
from Home Assistant — no cloud, no Govee account, no MQTT broker required.

This HACS repository installs a Home Assistant custom integration that
uses HA's built-in Bluetooth framework to talk to the H7015 over BLE,
using the protocol reverse-engineered from the Govee Home app.

## Features

- **Auto-discovery** via HA Bluetooth (the H7015 shows up automatically
  in the device list when in range).
- **Power, brightness, and RGB color** control from the standard HA
  light entity UI.
- **Scene effects**: sunrise, sunset, movie, dating, romantic, twinkle,
  candlelight, snowflake, energetic, breathe, crossing, rainbow.
- **Music modes**: energic, spectrum, rolling, rhythm.
- **Per-bulb RGBIC control** — 15 individual light entities (one per bulb)
  for controlling each bulb independently from the HA UI.
- **Custom Lovelace card** — visual bulb editor with color pickers and
  presets (Rainbow, Warm White, etc.).
- **HA Scenes support** — snapshot per-bulb colors as a scene and recall
  with one tap.
- **Configurable poll interval** via Options UI (Settings → Configure).
- **Diagnostics download** for easy bug reporting.
- **No cloud dependency** — works fully offline.

## Requirements

- Home Assistant 2024.8 or later
- A working HA Bluetooth setup (built-in radio, ESPHome Bluetooth proxy,
  or a USB Bluetooth dongle)
- The H7015 in Bluetooth range of your HA Bluetooth adapter

## Installation

### Via HACS (recommended)

1. Add this repository to HACS:
   - HACS → Integrations → ⋮ → Custom repositories
   - URL: `https://github.com/StableEnough/ha-govee-h7015`
   - Category: **Integration**
2. Click **Install** on "Govee H7015 BLE".
3. Restart Home Assistant.
4. Settings → Devices & Services → Add Integration → search "Govee H7015".
5. The H7015 should auto-discover if it's in Bluetooth range; otherwise
   enter the MAC address manually.

### Manual

Copy the entire `custom_components/govee_h7015_ble/` directory into your
HA configuration's `custom_components/` directory, then restart HA.

## Configuration

The integration is configured via the UI (no YAML required). After
installing, go to Settings → Devices & Services → Add Integration.

If your H7015 doesn't auto-discover:

1. Make sure HA's Bluetooth integration is set up and the H7015 is in range.
2. Use `python standalone/scan.py --name H7015` (from the standalone toolkit) to find
   the MAC address.
3. Add the integration manually and enter the MAC.

### Options

Go to Settings → Devices & Services → Govee H7015 BLE → Configure to
change the poll interval (5–3600 seconds, default 60).

## Per-bulb RGBIC control

The H7015 has 15 individually-addressable bulbs. This integration creates
**15 separate light entities** (one per bulb) so you can control each one
independently from the HA UI, dashboards, automations, and scenes.

The bulb entities are named `Bulb 1` through `Bulb 15` and are marked as
`EntityCategory.CONFIG` so they don't clutter the main device view.

### Using the custom Lovelace card

Install the **Govee H7015 Bulb Editor** card (in the `frontend/` directory)
via HACS (Dashboard category) for a visual bulb-by-bulb color editor with:
- 12 preset patterns (Rainbow, Warm White, Fireplace, Ocean, Christmas, Sunset,
  Flag, Candy Cane, All Red/Green/Blue, All Off)
- Click-to-edit color picker for each bulb
- One-click **Save as Scene** button that snapshots current colors as a HA scene

### Using the `set_bulb` service

You can also set individual bulbs via service calls (useful in automations):

```yaml
service: govee_h7015_ble.set_bulb
target:
  device_id: <your H7015 device id>
data:
  bulb: 0       # 0..14, counting from the controller end
  rgb: [255, 0, 0]
```

> **Note:** The service requires a target device. If you have multiple
> H7015s, you must specify which one to control.

## Creating custom scenes

### One-click from the card

1. Set the bulbs to the colors you want (via presets or individual color pickers)
2. Click **💾 Save as Scene**
3. Enter a name (e.g. "Christmas", "Date Night", "Patriotic")
4. Click **Save Scene**

### Via the `snapshot_scene` service

You can also create scenes from automations or scripts:

```yaml
service: govee_h7015_ble.snapshot_scene
target:
  device_id: <your H7015 device id>
data:
  scene_name: Christmas
```

This snapshots all 15 bulb colors and creates a HA scene using the built-in
`scene.create` service. The scene can then be activated from the dashboard,
automations, or voice commands.

### Manual scene creation

You can also use HA's native Scenes UI:

1. **Settings** → **Scenes** → **+ Add Scene**
2. Name it
3. Add the 15 bulb entities (`light.patio_lights_bulb_1` through
   `light.patio_lights_bulb_15`)
4. Set each bulb's color to match your desired pattern
5. Save

> **Note:** The per-bulb segment encoding is based on the H6127-style
> bitmask and may need adjustment for the H7015. See the README in the
> main repository for instructions on capturing the H7015-specific
> segment packet via HCI snoop.

## Diagnostics

If you're having issues, download diagnostic data via:
Settings → Devices & Services → Govee H7015 BLE → (your device) → Download diagnostics.
This exports the current state, connection status, and configuration
(without sensitive data) for bug reports.

## Limitations

- **State polling**: The H7015 doesn't push state changes. The integration
  polls every 60s by default (configurable in Options). If you change the
  lights via the Govee app or physical button, HA will catch up on the
  next poll.
- **Single connection**: The H7015 only allows one BLE connection at a
  time. Close the Govee Home app on your phone before controlling from
  HA, or you'll see connection errors.
- **Range**: Bluetooth range is ~10m line-of-sight, less through walls.
  Use an ESPHome Bluetooth proxy to extend range.

## Troubleshooting

See the main repository README for troubleshooting tips and protocol
documentation.

## License

GPLv3. Reverse engineering for interoperability is permitted under
17 USC §1201(f).
