"""Constants for the Govee H7015 BLE integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "govee_h7015_ble"

# Configuration keys
CONF_MAC = "mac"
CONF_NAME = "name"
CONF_POLL_INTERVAL = "poll_interval"

DEFAULT_NAME = "Govee H7015"
DEFAULT_POLL_INTERVAL = 60  # seconds

# Service names
SERVICE_SET_BULB = "set_bulb"
SERVICE_SNAPSHOT_SCENE = "snapshot_scene"
ATTR_BULB = "bulb"
ATTR_RGB = "rgb"
ATTR_SCENE_NAME = "scene_name"

# BLE endpoints (shared across the Govee RGBIC BLE family)
SERVICE_UUID: Final = "00010203-0405-0607-0809-0a0b0c0d1910"
WRITE_CHAR_UUID: Final = "00010203-0405-0607-0809-0a0b0c0d2b11"
READ_CHAR_UUID: Final = "00010203-0405-0607-0809-0a0b0c0d2b10"

# Effects exposed to HA (all scene + music mode names lowercase)
# Scenes: 47 total (12 confirmed + 35 from H6127 protocol docs)
# Music modes: 4 total
EFFECTS: Final[list[str]] = [
    # Original 12 confirmed scenes
    "sunrise",
    "sunset",
    "movie",
    "dating",
    "romantic",
    "twinkle",
    "candlelight",
    "breathe",
    "snowflake",
    "energetic",
    "crossing",
    "rainbow",
    # Additional scenes from H6127 protocol (may work on H7015)
    "snowing",
    "cloud",
    "gorgeous",
    "blinking",
    "starry",
    "flow",
    "dream",
    "jumping",
    "volcano",
    "ripple",
    "shadow",
    "wind",
    "ocean",
    "aurora",
    "forest",
    "waterfall",
    "firefly",
    "sparkle",
    "meteor",
    "galaxy",
    "sunny",
    "night",
    "dawn",
    "dusk",
    "spring",
    "summer",
    "autumn",
    "winter",
    "christmas",
    "halloween",
    "thanksgiving",
    "valentine",
    "new_year",
    "birthday",
    "party",
    "relax",
    "energize",
    "focus",
    "reading",
    "night_light",
    "celebrate",
    "festive",
    "gradient",
    "pulse",
    "wave",
    "chase",
    "stack",
    # Music modes
    "music_energic",
    "music_spectrum",
    "music_rolling",
    "music_rhythm",
]
