"""Packet regressions from the user-supplied H7015 field-test specification.

These vectors establish software parity with the reported working packets;
they do not claim that this test suite exercises physical lights.
"""

from __future__ import annotations

import protocol as standalone
import pytest

from custom_components.govee_h7015_ble import protocol as integration


@pytest.mark.parametrize("module", [standalone, integration], ids=["standalone", "ha"])
@pytest.mark.parametrize(
    ("command", "arguments", "expected"),
    [
        ("pkt_brightness", (1,), "3304010000000000000000000000000000000036"),
        ("pkt_brightness", (50,), "3304320000000000000000000000000000000005"),
        ("pkt_brightness", (100,), "3304640000000000000000000000000000000053"),
        ("pkt_keepalive", (), "aa010000000000000000000000000000000000ab"),
    ],
)
def test_reported_h7015_packets(module, command, arguments, expected):
    """Public command helpers must produce the independently supplied bytes."""
    assert getattr(module, command)(*arguments) == bytes.fromhex(expected)


@pytest.mark.parametrize("module", [standalone, integration], ids=["standalone", "ha"])
def test_reported_classic_scene_rainbow(module):
    """The tested classic-scene path uses code 22, high byte first."""
    assert module.pkt_scene(module.Scene.RAINBOW) == bytes.fromhex(
        "3305040016000000000000000000000000000024"
    )


@pytest.mark.parametrize("module", [standalone, integration], ids=["standalone", "ha"])
@pytest.mark.parametrize(
    ("rgb", "expected"),
    [
        ((255, 0, 0), "33051501ff00000000000000ff7f00000000005d"),
        ((0, 255, 0), "3305150100ff000000000000ff7f00000000005d"),
    ],
)
def test_h7015_app_capture_colors(module, rgb, expected):
    """Match complete RGB writes captured from Govee Home on H7015, 2026-10-27."""
    assert module.pkt_solid_color(*rgb) == bytes.fromhex(expected)
