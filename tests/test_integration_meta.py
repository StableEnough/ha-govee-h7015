"""Sanity tests that don't require Home Assistant to be installed.

These verify the protocol module imports cleanly and the basic packet
shape is right. For full HA integration tests, use the pytest-homeassistant
hass test framework.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "standalone"))

import json

from protocol import (  # type: ignore[import-not-found]
    checksum,
    pkt_power,
    pkt_brightness,
    pkt_solid_color,
)


def test_manifest_json_is_valid() -> None:
    """manifest.json must parse and have required HA fields."""
    manifest_path = ROOT / "custom_components" / "govee_h7015_ble" / "manifest.json"
    data = json.loads(manifest_path.read_text())
    required = {"domain", "name", "codeowners", "config_flow", "iot_class", "version"}
    assert required.issubset(data.keys()), f"missing fields: {required - set(data.keys())}"
    assert data["domain"] == "govee_h7015_ble"
    assert data["config_flow"] is True


def test_strings_json_is_valid() -> None:
    """strings.json must be valid JSON with config step entries."""
    p = ROOT / "custom_components" / "govee_h7015_ble" / "strings.json"
    data = json.loads(p.read_text())
    assert "config" in data
    assert "step" in data["config"]


def test_hacs_json_exists_and_is_valid() -> None:
    """hacs.json must exist at the repo root and parse."""
    p = ROOT / "hacs.json"
    assert p.exists(), "hacs.json missing - required for HACS distribution"
    data = json.loads(p.read_text())
    assert "name" in data
