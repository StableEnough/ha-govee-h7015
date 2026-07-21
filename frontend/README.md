# Govee H7015 Bulb Editor

A custom Lovelace card for visually controlling individual bulb colors on the
Govee H7015 Outdoor String Lights.

![Bulb Editor](https://via.placeholder.com/400x200?text=Govee+H7015+Bulb+Editor)

## Features

- **Visual bulb grid** — 15 color swatches, one per bulb
- **Click to edit** — click any bulb to select it, then use the color picker
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
- **Save as Scene** — one click to snapshot current colors as a HA scene
- **Instant feedback** — colors update immediately as you send commands
- **Power toggle** — turn the whole string on/off from the card

## Installation

### Via HACS (recommended)

1. Add this repository to HACS:
   - HACS → Frontend → ⋮ → Custom repositories
   - URL: `https://github.com/StableEnough/ha-govee-h7015`
   - Category: **Dashboard (Lovelace)**
2. Click **Install** on "Govee H7015 Bulb Editor"
3. Add the card to any dashboard via **Edit Dashboard → Add Card → Manual**

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

1. Set the bulbs to the colors you want (use presets or individual color pickers)
2. Click **💾 Save as Scene**
3. Enter a name (e.g. "Christmas", "Date Night", "Patriotic")
4. Click **Save Scene**

The card calls HA's built-in `scene.create` service, which creates a scene
you can immediately activate from the dashboard, automations, or voice commands.

### Via the `snapshot_scene` service

You can also create scenes from automations or scripts:

```yaml
service: govee_h7015_ble.snapshot_scene
target:
  device_id: <your H7015 device id>
data:
  scene_name: Christmas
```

This snapshots all 15 bulb colors at the moment of the call and creates a
HA scene with that name.

## Tips

- **BLE write speed**: Setting all 15 bulbs takes ~1.5 seconds (100ms pacing
  between writes to avoid overwhelming the BLE connection).
- **Stale state**: If someone changes the lights via the Govee app, the bulb
  colors shown in the card will be stale until you set them from HA again.
- **Group the bulb entities**: In HA's entity settings, you can hide the 15
  individual bulb entities from the main view if you only want to control
  them via this card.
