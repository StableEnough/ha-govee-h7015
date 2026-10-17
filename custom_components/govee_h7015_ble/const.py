"""Constants for the Govee H7015 BLE integration."""

from __future__ import annotations

from typing import Final

from .protocol import MusicMode, Scene

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

# Classic scene names come from the protocol catalogue; music remains experimental.
EFFECTS: Final[list[str]] = [scene.name.lower() for scene in Scene] + [
    f"music_{mode.name.lower()}" for mode in MusicMode
]
