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
        ("pkt_solid_color", (255, 0, 0), "33051501ff0000ff7f000000000000000000005d"),
        ("pkt_segment", (0, 255, 0, 0), "33051501ff0000010000000000000000000000dc"),
        ("pkt_segment", (8, 255, 0, 0), "33051501ff0000000100000000000000000000dc"),
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
