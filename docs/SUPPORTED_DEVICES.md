# Govee H7015 BLE — Supported Devices

## Confirmed Working

| Model | Name | Protocol | Notes |
|-------|------|----------|-------|
| H7015 | Govee Outdoor String Lights (48ft, 15 bulbs) | BLE only | Primary target. 47 scene modes, RGBIC, warm/cold white. |

## Likely Working (Same Protocol Family)

These devices share the Govee RGBIC BLE protocol (`00010203-0405-0607-0809-0a0b0c0d1910`).
They may work with this integration, but the config flow only auto-discovers `H7015_*` devices.
To try another model, add it manually by MAC address.

| Model | Name | Differences |
|-------|------|-------------|
| H7020 | Govee Outdoor String Lights 2 | WiFi + BLE (BLE fallback when WiFi fails) |
| H6054 | Govee LED Strip | Different segment count |
| H6113 | Govee LED Strip | Different segment count |
| H6127 | Govee LED Strip | Protocol was reverse-engineered from this model |
| H617A | Govee LED Strip | Community-confirmed working |

## Not Compatible

These Govee devices use different protocols and will NOT work with this integration:

| Model | Reason |
|-------|--------|
| H6004-H6099 (most) | Use WiFi/LAN API, not BLE |
| H7012, H7020, H7021+ | Support LAN API — use the official `govee_light_local` integration instead |
| H5179 | Different BLE protocol |

## Adding New Devices

If you have a Govee BLE device that's not listed:

1. Run `python standalone/scan.py --all` to find its advertised name
2. If the name starts with `H` followed by 4 digits, it likely uses the same protocol
3. Add it manually via the integration's config flow (enter MAC address)
4. Report results in a GitHub issue with the `[PROTOCOL]` template
