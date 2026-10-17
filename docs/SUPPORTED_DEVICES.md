# Govee H7015 BLE — Supported Devices

## Target Device

| Model | Name | Protocol | Notes |
|-------|------|----------|-------|
| H7015 | Govee Outdoor String Lights (48ft, 15 bulbs) | BLE only | Reported field-tested power, raw-percent brightness, and V2 RGB (firmware ≥1.06.00); segment masks and classic scenes have partial field coverage. |

The integration's corrected packets match a user-provided H7015 hardware-test
report. Automated tests use simulated BLE and do not independently confirm
hardware behavior. White-temperature, music, gradient, and DIY commands remain
unverified.

## Other Models Are Not Verified

Matching GATT UUIDs do not establish compatible brightness units, scene codes,
or segment encodings. The corrected defaults are H7015-specific; do not assume
they work on H6127, H617A, H7020, or other Govee devices. Older community captures
from those models are reference material, not confirmation of H7015 behavior.

## Not Compatible

These Govee devices use different protocols and will NOT work with this integration:

| Model | Reason |
|-------|--------|
| H6004-H6099 (most) | Use WiFi/LAN API, not BLE |
| H7012, H7020, H7021+ | Support LAN API — use the official `govee_light_local` integration instead |
| H5179 | Different BLE protocol |

## Adding New Devices

If you have a Govee BLE device that's not listed:

1. Identify the exact model and firmware version.
2. Capture the official app's BLE command packets for that model.
3. Compare brightness units, scene byte order, and segment encoding.
4. Report redacted captures and observed hardware behavior with the proposed change.
