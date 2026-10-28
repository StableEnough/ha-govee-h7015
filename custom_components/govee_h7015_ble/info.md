# Govee H7015 BLE

Local Bluetooth control of **Govee H7015 Outdoor String Lights** directly
from Home Assistant — no cloud, no Govee account, no MQTT broker required.

This HACS repository installs a Home Assistant custom integration that
uses HA's built-in Bluetooth framework to talk to the H7015 over BLE,
using command packets matched to a user-provided H7015 field-test report.

## Features

- **Auto-discovery** via HA Bluetooth (the H7015 shows up automatically
  in the device list when in range).
- **Power, brightness, and RGB color** control from the standard HA
  light entity UI.
- **Scene effects**: sunrise, sunset, movie, dating, romantic, twinkle,
  candlelight, snowflake, energetic, breathe, crossing, rainbow.
- **Music modes** (experimental): energic, spectrum, rolling, rhythm.
- **Per-bulb RGBIC control** — 15 individual light entities with independent
  colour and relative-brightness controls in the HA UI.
- **State-aware icons** — string-lights for the main entity and individual bulbs
  for the per-bulb entities, each with an off-state variant. Icons set manually
  in HA entity settings still take precedence.
- **Custom Lovelace card** — visual bulb editor with color pickers, selected-bulb
  brightness, and presets (Rainbow, Warm White, etc.).
- **HA Scenes support** — snapshot colors and known whole-string/lit-bulb brightness
  as a scene and recall with one tap.
- **Configurable heartbeat polling interval** via Options UI (Settings → Configure).
- **Diagnostics download** for easy bug reporting.
- **No cloud dependency** — works fully offline.

## Requirements

- Home Assistant 2024.8 or later
- A working HA Bluetooth setup (built-in radio, ESPHome Bluetooth proxy,
  or a USB Bluetooth dongle)
- The H7015 in Bluetooth range of your HA Bluetooth adapter
- Firmware **1.06.00 or newer** for the reported working V2 RGB/per-bulb commands.
  No automatic older-firmware fallback is attempted.

## Verification limits

The corrected brightness, V2 RGB, and classic-scene packets match user-reported
hardware tests. Selected-bulb RGB also has H7015 app HCI captures and user-confirmed
physical operation: selecting Bulb 2 produced mask `02`, and Bulbs 2 + 4 produced
mask `0A` at byte 12. Automated integration tests use simulated BLE, not real lights.
Brightness uses a raw 1–100 percent byte, not the H6127 20–254 scale.
Selected-bulb relative brightness is captured as `33 05 15 02 <percent> maskLo maskHi`,
with mask bytes at offsets 5–6 rather than RGB's 12–13. Bulb 2 captures at 51%
and 75% preserve its colour and the neighbours' displayed brightness.
The 12 classic scene names are the app's built-in catalogue; individual scene
coverage is partial. Dynamic scenes, DIY, music, gradient, and color-temperature
encodings remain unverified for H7015.

BLE notifications are subscribed on the same `…2b11` characteristic used for
writes. Polling sends a heartbeat rather than reading `…2b10`. State is last-commanded
unless a supported notification updates it; unknown `0xAB` replies and write
acknowledgements are not decoded as power, brightness, or color. Changes made in the
Govee app may not appear automatically.
Successful commands immediately publish last-commanded state to all affected
entities; whole-string colour changes also refresh the 15 bulb entities.

Turning a bulb off sends black but retains its last non-black colour; turning it
back on restores that colour, or white if unknown. Per-bulb brightness is relative
to the separate whole-string setting and stays unknown until commanded.
Main settings, bulb colors, non-black restore colors, and relative brightness
survive integration reloads and HA restarts in HA's local storage. They remain
assumed state, not hardware readback. Loading them does not replay control commands;
removing the integration entry deletes them.
A successful manual bulb colour or relative-brightness command clears the main
entity's scene/music effect; a failed write leaves the previous state intact.

## Installation

### Via HACS (requires a GitHub mirror)

HACS cannot install directly from Forgejo. If a public GitHub mirror is
maintained, add its URL under HACS → Integrations → Custom repositories,
select the Integration category, and install "Govee H7015 BLE".
Restart Home Assistant, then add Govee H7015 under Devices & Services.
The device auto-discovers in Bluetooth range; otherwise enter its MAC manually.

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
- Selected-bulb relative-brightness slider (1–100%) and percentage; unknown until commanded
- One-click **Save as Scene** button that snapshots colors and known brightness

### Using the `set_bulb` service

You can also set individual bulbs via service calls (useful in automations):

```yaml
service: govee_h7015_ble.set_bulb
data:
  device_id: [<your H7015 device id>]
  bulb: 0       # 0..14, counting from the controller end
  rgb: [255, 0, 0]
```

> **Note:** The service requires a target device. If you have multiple
> H7015s, you must specify which one to control.

## Creating custom scenes

### One-click from the card

1. Set bulb colors and brightness, plus whole-string brightness if needed
2. Click **💾 Save as Scene**
3. Enter a name (e.g. "Christmas", "Date Night", "Patriotic")
4. Click **Save Scene**

### Via the `snapshot_scene` service

You can also create scenes from automations or scripts:

```yaml
service: govee_h7015_ble.snapshot_scene
data:
  device_id: [<your H7015 device id>]
  scene_name: Christmas
```

This saves bulb colors/on-off states and known whole-string and lit-bulb brightness
using `scene.create`. Unknown brightness is omitted, not guessed. Off bulbs stay off;
native HA light scenes do not recall their latent brightness. The main string is
turned on to display the saved pattern. Activate the scene from the dashboard,
automations, or voice commands. The name is normalized to a scene ID (for example,
`Date Night` becomes `scene.date_night`). Scenes created this way last until HA
restarts; use the native Scenes UI below for a persistent scene.

### Manual scene creation

You can also use HA's native Scenes UI:

1. **Settings** → **Scenes** → **+ Add Scene**
2. Name it
3. Add the 15 bulb entities (`light.patio_lights_bulb_1` through
   `light.patio_lights_bulb_15`)
4. Set each bulb's color to match your desired pattern
5. Save

> **Note:** The app's selected-bulb capture path is **Color → Subsection → select
> bulbs → scroll below relative brightness → Basic Colors**. The separate
> **Color Tool** applies swatches to the whole string. HA bulb entities are
> numbered 1–15; the `set_bulb` service uses indices 0–14.

## Diagnostics

If you're having issues, download diagnostic data via:
Settings → Devices & Services → Govee H7015 BLE → (your device) → Download diagnostics.
This exports the current state, connection status, and configuration
(without sensitive data) for bug reports.

## Limitations

- **State synchronization**: Heartbeats run every 2s and the configurable poll
  also sends a heartbeat. Notifications are received on the write characteristic,
  but unknown replies do not provide decoded state. HA retains last-commanded
  values; changes in the Govee app or physical button may remain unseen.
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
