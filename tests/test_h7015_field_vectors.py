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


@pytest.mark.parametrize("module", [standalone, integration], ids=["standalone", "ha"])
@pytest.mark.parametrize(
    ("bulb", "rgb", "expected"),
    [
        (1, (0, 0, 255), "330515010000ff000000000002000000000000df"),
        (7, (255, 255, 255), "33051501ffffff0000000000800000000000005d"),
        (14, (255, 77, 77), "33051501ff4d4d0000000000004000000000009d"),
    ],
)
def test_h7015_app_capture_individual_bulbs(module, bulb, rgb, expected):
    """Preserve complete captured writes, including the mask's byte boundary."""
    assert module.pkt_segment(bulb, *rgb) == bytes.fromhex(expected)


@pytest.mark.parametrize("module", [standalone, integration], ids=["standalone", "ha"])
@pytest.mark.parametrize(
    ("bulb", "percent", "expected"),
    [
        (1, 51, "3305150233020000000000000000000000000010"),
        (1, 75, "330515024b020000000000000000000000000068"),
        (14, 100, "3305150264004000000000000000000000000005"),
    ],
)
def test_h7015_app_capture_bulb_brightness(module, bulb, percent, expected):
    """Relative brightness has its own percent byte and selection-mask offsets."""
    assert module.pkt_segment_brightness(bulb, percent) == bytes.fromhex(expected)


@pytest.mark.parametrize("module", [standalone, integration], ids=["standalone", "ha"])
def test_bulb_brightness_bounds(module):
    """Reject invalid bulb indices and retain the existing percent clamping."""
    for bulb in (-1, 15):
        with pytest.raises(module.GoveeInvalidArgumentError):
            module.pkt_segment_brightness(bulb, 50)
    assert module.pkt_segment_brightness(1, 0) == module.pkt_segment_brightness(1, 1)
    assert module.pkt_segment_brightness(1, 101) == module.pkt_segment_brightness(1, 100)
