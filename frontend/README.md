# Govee H7015 Bulb Editor

A custom Lovelace card for visually controlling individual bulb colors and relative
brightness on the Govee H7015 Outdoor String Lights.

![Bulb Editor](https://via.placeholder.com/400x200?text=Govee+H7015+Bulb+Editor)

## Features

- **Visual bulb grid** — 15 color swatches, one per bulb
- **Click to edit** — select a bulb, then use its color picker or 1–100% brightness slider
- **12 preset patterns**:
  - 🌈 Rainbow — full spectrum across all 15 bulbs
  - 💡 Warm White — all bulbs warm white (255, 196, 120)
  - 🔥 Fireplace — warm flickering reds, oranges, and yellows
  - 🌊 Ocean — blue-to-cyan gradient like ocean waves
  - 🎄 Christmas — alternating red, green, and gold
  - 🌅 Sunset — gradient from deep red to orange to yellow to purple
  - 🇺🇸 Flag — red, white, blue pattern
  - 🍭 Candy Cane — alternating red and white
  - 🔴 All Red / 🟢 All Green / 🔵 All Blue
  - ⚫ All Off
- **Save as Scene** — snapshot colors and known whole-string/lit-bulb brightness
- **Instant feedback** — colors update immediately as you send commands
- **Power toggle** — turn the whole string on/off from the card

The brightness percentage is relative to the separate whole-string brightness.
It shows **Unknown** until commanded and is disabled until an available bulb is
selected. Dragging previews the value; releasing sends one command to that bulb.

## Installation

### Via HACS (requires a GitHub mirror)

HACS cannot install directly from Forgejo. If a public GitHub mirror is
maintained, add its URL under HACS → Frontend → Custom repositories, select
Dashboard (Lovelace), and install "Govee H7015 Bulb Editor".
Add the card via Edit Dashboard → Add Card → Manual.

### Manual

1. Copy `govee-h7015-bulb-card.js` to `/config/www/`
2. Add to Lovelace resources:
   - Settings → Dashboards → Resources → Add
   - URL: `/local/govee-h7015-bulb-card.js`
   - Type: **JavaScript Module**
3. Add the card to any dashboard via **Edit Dashboard → Add Card → Manual**

## Configuration

```yaml
type: custom:govee-h7015-bulb-card
entity: light.patio_lights          # main H7015 light entity
device_id: aabbccddeeff1234567890   # device ID from Settings → Devices
```

| Field | Required | Description |
|-------|----------|-------------|
| `entity` | Yes | The main H7015 light entity ID (e.g. `light.patio_lights`) |
| `device_id` | Yes | The HA device ID — find it in Settings → Devices → click your H7015 → copy the ID from the URL |

## Creating Scenes

### One-click scene creation

1. Set bulb colors and brightness; adjust whole-string brightness in HA if needed
2. Click **💾 Save as Scene**
3. Enter a name (e.g. "Christmas", "Date Night", "Patriotic")
4. Click **Save Scene**

The card calls the integration's `snapshot_scene` service, which uses HA's built-in
`scene.create`. You can immediately activate the scene from the dashboard,
automations, or voice commands. These dynamic scenes last until HA restarts;
use HA's native Scenes UI to save a permanent scene.

### Via the `snapshot_scene` service

You can also create scenes from automations or scripts:

```yaml
service: govee_h7015_ble.snapshot_scene
data:
  device_id: [<your H7015 device id>]
  scene_name: Christmas
```

This saves all 15 bulb colors/on-off states and known whole-string and lit-bulb
brightness. Unknown levels are omitted rather than replaced with a guessed value.
As with native HA light scenes, off bulbs stay off; their latent brightness is not
recalled. The main string is turned on to display the saved pattern.

## Tips

- **BLE write speed**: Setting all 15 bulbs takes ~1.5 seconds (100ms pacing
  between writes to avoid overwhelming the BLE connection).
- **Assumed state**: Colors and brightness remember commands across integration
  reloads and HA restarts. Govee app changes can leave them stale; restored values
  are not hardware readback and do not automatically send commands to the lights.
- **Group the bulb entities**: In HA's entity settings, you can hide the 15
  individual bulb entities from the main view if you only want to control
  them via this card.
