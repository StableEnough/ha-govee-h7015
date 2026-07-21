"""Tests for the Govee H7015 protocol module.

These tests run without Home Assistant installed — they only exercise
the protocol module, which is pure Python with no HA deps.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Standalone path: protocol.py uses absolute imports (from exceptions, from govee_types)
# so adding standalone/ to sys.path lets us `import protocol` directly.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "standalone"))

import pytest

from protocol import (  # type: ignore[import-not-found]
    ColorMode,
    Command,
    MusicMode,
    Scene,
    build_packet,
    checksum,
    decode_state,
    pkt_brightness,
    pkt_color_temperature,
    pkt_gradient,
    pkt_keepalive,
    pkt_music,
    pkt_power,
    pkt_scene,
    pkt_segment,
    pkt_solid_color,
    PACKET_LEN,
)
from protocol import H7015State  # type: ignore[import-not-found]


# ---------------------------------------------------------------------------
# Checksum
# ---------------------------------------------------------------------------
class TestChecksum:
    def test_checksum_xor_of_all_bytes(self) -> None:
        assert checksum(b"\x33\x01\x01") == 0x33 ^ 0x01 ^ 0x01

    def test_checksum_single_byte(self) -> None:
        assert checksum(b"\xff") == 0xFF

    def test_checksum_empty(self) -> None:
        assert checksum(b"") == 0

    def test_checksum_is_8bit(self) -> None:
        # 0xFF XOR 0x01 wraps via mask to 0xFE
        assert checksum(b"\xff\x01") == 0xFE

    @pytest.mark.parametrize(
        "payload",
        [
            b"\x33\x01\x01" + b"\x00" * 15,
            b"\xaa\x01" + b"\x00" * 16,
            b"\x33\x05\x02\xff\x00\x00" + b"\x00" * 13,
        ],
    )
    def test_checksum_in_range(self, payload: bytes) -> None:
        assert 0 <= checksum(payload) <= 0xFF


# ---------------------------------------------------------------------------
# Packet length + structure
# ---------------------------------------------------------------------------
class TestPacketStructure:
    def test_all_packets_are_20_bytes(self) -> None:
        packets = [
            pkt_keepalive(),
            pkt_power(True),
            pkt_power(False),
            pkt_brightness(50),
            pkt_brightness(0),
            pkt_brightness(100),
            pkt_solid_color(255, 0, 0),
            pkt_scene(Scene.SUNRISE),
            pkt_music(MusicMode.RHYTHM),
            pkt_gradient(True),
            pkt_segment(0, 255, 0, 0),
        ]
        for p in packets:
            assert len(p) == PACKET_LEN, f"bad length: {p.hex()}"

    def test_checksum_byte_is_xor_of_first_19(self) -> None:
        for p in [
            pkt_power(True),
            pkt_brightness(75),
            pkt_solid_color(128, 64, 32),
            pkt_scene(Scene.RAINBOW),
            pkt_segment(7, 100, 200, 50),
        ]:
            body = p[:-1]
            expected = checksum(body)
            assert p[-1] == expected, f"bad checksum: {p.hex()}"

    def test_packets_are_zero_padded(self) -> None:
        # Power-on packet should be: 33 01 01 00*16 + checksum
        p = pkt_power(True)
        assert p[3:19] == b"\x00" * 16

    def test_build_packet_truncates_oversized_payload(self) -> None:
        # Build a packet with too much data — it should be truncated, not error.
        p = build_packet(b"\x33\x01", b"\xff" * 100)
        assert len(p) == PACKET_LEN


# ---------------------------------------------------------------------------
# Specific commands
# ---------------------------------------------------------------------------
class TestPower:
    def test_power_on(self) -> None:
        p = pkt_power(True)
        assert p[0] == 0x33
        assert p[1] == Command.POWER
        assert p[2] == 0x01
        # 0x33 ^ 0x01 ^ 0x01 = 0x33
        assert p[-1] == 0x33

    def test_power_off(self) -> None:
        p = pkt_power(False)
        assert p[2] == 0x00
        # 0x33 ^ 0x01 ^ 0x00 = 0x32
        assert p[-1] == 0x32


class TestBrightness:
    def test_brightness_0_maps_to_0x00(self) -> None:
        p = pkt_brightness(0)
        assert p[2] == 0x00

    def test_brightness_100_maps_to_0xFE(self) -> None:
        p = pkt_brightness(100)
        assert p[2] == 0xFE

    def test_brightness_1_maps_to_0x14(self) -> None:
        p = pkt_brightness(1)
        assert p[2] == 0x14

    def test_brightness_clamps_high(self) -> None:
        p = pkt_brightness(150)
        assert p[2] == 0xFE

    def test_brightness_clamps_negative(self) -> None:
        p = pkt_brightness(-10)
        assert p[2] == 0x00

    def test_brightness_monotonic(self) -> None:
        # Brightness should monotonically increase with input value
        values = [pkt_brightness(v)[2] for v in range(1, 101)]
        assert values == sorted(set(values)), "brightness is not monotonic"


class TestColor:
    def test_solid_color_red(self) -> None:
        p = pkt_solid_color(255, 0, 0)
        assert p[1] == Command.COLOR
        assert p[2] == ColorMode.MANUAL
        assert p[3:6] == bytes([255, 0, 0])

    def test_solid_color_clamps(self) -> None:
        p = pkt_solid_color(300, -5, 128)
        assert p[3:6] == bytes([255, 0, 128])

    def test_solid_color_checksum(self) -> None:
        # Verified by hand: 0x33 ^ 0x05 ^ 0x02 ^ 0xff ^ 0x00 ^ 0x00
        p = pkt_solid_color(255, 0, 0)
        body = p[:-1]
        assert p[-1] == checksum(body)


class TestScenes:
    @pytest.mark.parametrize("scene", list(Scene))
    def test_all_scenes_have_valid_packets(self, scene: Scene) -> None:
        p = pkt_scene(scene)
        assert len(p) == PACKET_LEN
        assert p[0] == 0x33
        assert p[1] == Command.COLOR
        assert p[2] == ColorMode.SCENE
        assert p[3] == scene.value
        assert p[-1] == checksum(p[:-1])


class TestMusic:
    @pytest.mark.parametrize("mode", list(MusicMode))
    def test_all_music_modes_have_valid_packets(self, mode: MusicMode) -> None:
        p = pkt_music(mode, 255, 0, 0)
        assert len(p) == PACKET_LEN
        assert p[1] == Command.COLOR
        assert p[2] == ColorMode.MUSIC
        assert p[3] == mode.value

    def test_music_with_color(self) -> None:
        p = pkt_music(MusicMode.SPECTRUM, 0, 255, 0)
        assert p[3:7] == bytes([MusicMode.SPECTRUM, 0, 255, 0])


class TestSegments:
    def test_segment_first_bulb(self) -> None:
        p = pkt_segment(0, 255, 0, 0)
        assert p[1] == Command.COLOR
        assert p[2] == ColorMode.SEGMENTS
        assert p[3:6] == bytes([255, 0, 0])
        # First bulb should set bit 0 of the left byte
        assert p[6] == 0x01
        assert p[7] == 0x00

    def test_segment_bulb_8_uses_right_byte(self) -> None:
        p = pkt_segment(8, 0, 0, 255)
        assert p[6] == 0x00
        assert p[7] == 0x01

    def test_segment_bulb_14(self) -> None:
        p = pkt_segment(14, 255, 255, 255)
        # Bit 6 of the right byte
        assert p[7] == 0x40

    def test_segment_out_of_range_raises(self) -> None:
        from exceptions import GoveeInvalidArgumentError  # type: ignore[import-not-found]
        with pytest.raises(GoveeInvalidArgumentError):
            pkt_segment(15, 0, 0, 0)
        with pytest.raises(GoveeInvalidArgumentError):
            pkt_segment(-1, 0, 0, 0)


class TestColorTemperature:
    """Tests for the color temperature (warm/cold white) feature."""

    def test_warmest_temp(self) -> None:
        """2000K should produce max warm (0xFF) and zero cold (0x00)."""
        pkt = pkt_color_temperature(2000)
        assert len(pkt) == PACKET_LEN
        assert pkt[0] == 0x33
        assert pkt[1] == Command.COLOR
        assert pkt[2] == ColorMode.MANUAL
        # Byte 6 is the white LED flag (0x01)
        assert pkt[6] == 0x01
        # Byte 7 = warm, byte 8 = cold
        assert pkt[7] == 0xFF  # max warm
        assert pkt[8] == 0x00  # no cold

    def test_coldest_temp(self) -> None:
        """6500K should produce zero warm (0x00) and max cold (0xFF)."""
        pkt = pkt_color_temperature(6500)
        assert pkt[6] == 0x01  # white LED flag
        assert pkt[7] == 0x00  # no warm
        assert pkt[8] == 0xFF  # max cold

    def test_mid_temp(self) -> None:
        """4250K (midpoint) should produce roughly equal warm and cold."""
        pkt = pkt_color_temperature(4250)
        assert pkt[6] == 0x01  # white LED flag
        # At midpoint, warm and cold should be roughly equal (~127 each)
        assert abs(pkt[7] - pkt[8]) <= 2  # within 2 of each other

    def test_clamps_high(self) -> None:
        """Temperatures above 6500K should clamp to 6500K."""
        pkt = pkt_color_temperature(10000)
        assert pkt[7] == 0x00
        assert pkt[8] == 0xFF

    def test_clamps_low(self) -> None:
        """Temperatures below 2000K should clamp to 2000K."""
        pkt = pkt_color_temperature(1000)
        assert pkt[7] == 0xFF
        assert pkt[8] == 0x00

    def test_checksum_valid(self) -> None:
        """Color temperature packets must have valid checksums."""
        for kelvin in [2000, 3000, 4250, 5500, 6500]:
            pkt = pkt_color_temperature(kelvin)
            assert pkt[-1] == checksum(pkt[:-1]), f"bad checksum for {kelvin}K"


class TestKeepalive:
    def test_keepalive_format(self) -> None:
        p = pkt_keepalive()
        assert p[0] == 0xAA
        assert p[1] == 0x01
        assert p[2:19] == b"\x00" * 17
        # AA ^ 01 = AB
        assert p[-1] == 0xAB


class TestDIYMode:
    """Tests for the DIY mode multi-packet sequence."""

    def test_diy_basic_fade(self) -> None:
        """DIY fade with 2 colors should produce start + 1 data + end + activate."""
        from protocol import pkt_diy, DIYStyle, DIYStyleMode  # type: ignore[import-not-found]
        packets = pkt_diy(
            name=0x3B,
            style=DIYStyle.FADE,
            style_mode=DIYStyleMode.WHOLE,
            speed=50,
            colors=[(255, 0, 0), (0, 0, 255)],
        )
        # Start + 1 data + end + activate = 4 packets
        assert len(packets) == 4

        # Start packet starts with A1 02 00
        assert packets[0][0] == 0xA1
        assert packets[0][1] == 0x02
        assert packets[0][2] == 0x00

        # Data packet starts with A1 02 01
        assert packets[1][0] == 0xA1
        assert packets[1][1] == 0x02
        assert packets[1][2] == 0x01

        # End packet starts with A1 02 FF
        assert packets[2][0] == 0xA1
        assert packets[2][1] == 0x02
        assert packets[2][2] == 0xFF

        # Activate packet starts with 33 05 0A
        assert packets[3][0] == 0x33
        assert packets[3][1] == 0x05
        assert packets[3][2] == 0x0A

    def test_diy_all_packets_20_bytes(self) -> None:
        """Every DIY packet must be exactly 20 bytes."""
        from protocol import pkt_diy, DIYStyle, DIYStyleMode  # type: ignore[import-not-found]
        packets = pkt_diy(
            name=0x3B,
            style=DIYStyle.JUMPING,
            style_mode=DIYStyleMode.CIRCULATION,
            speed=100,
            colors=[(255, 0, 0), (0, 255, 0), (0, 0, 255)],
        )
        for p in packets:
            assert len(p) == 20

    def test_diy_speed_validated(self) -> None:
        """Speed out of range should raise."""
        from protocol import pkt_diy, DIYStyle, DIYStyleMode  # type: ignore[import-not-found]
        from exceptions import GoveeInvalidArgumentError  # type: ignore[import-not-found]
        with pytest.raises(GoveeInvalidArgumentError):
            pkt_diy(0x3B, DIYStyle.FADE, DIYStyleMode.WHOLE, 150, [(255, 0, 0)])
        with pytest.raises(GoveeInvalidArgumentError):
            pkt_diy(0x3B, DIYStyle.FADE, DIYStyleMode.WHOLE, -5, [(255, 0, 0)])

    def test_diy_no_colors_raises(self) -> None:
        """Empty color list should raise."""
        from protocol import pkt_diy, DIYStyle, DIYStyleMode  # type: ignore[import-not-found]
        from exceptions import GoveeInvalidArgumentError  # type: ignore[import-not-found]
        with pytest.raises(GoveeInvalidArgumentError):
            pkt_diy(0x3B, DIYStyle.FADE, DIYStyleMode.WHOLE, 50, [])

    def test_diy_too_many_colors_raises(self) -> None:
        """More than 8 colors should raise."""
        from protocol import pkt_diy, DIYStyle, DIYStyleMode  # type: ignore[import-not-found]
        from exceptions import GoveeInvalidArgumentError  # type: ignore[import-not-found]
        with pytest.raises(GoveeInvalidArgumentError):
            pkt_diy(
                0x3B, DIYStyle.FADE, DIYStyleMode.WHOLE, 50,
                [(i, i, i) for i in range(9)],
            )

    def test_diy_combo_adds_extra_packet(self) -> None:
        """Combo style should produce an extra data packet."""
        from protocol import pkt_diy, DIYStyle, DIYStyleMode  # type: ignore[import-not-found]
        packets = pkt_diy(
            name=0x3B,
            style=DIYStyle.COMBO,
            style_mode=DIYStyleMode.WHOLE,
            speed=50,
            colors=[(255, 0, 0)],
        )
        # Start + 1 data + combo data + end + activate = 5 packets
        assert len(packets) == 5


# ---------------------------------------------------------------------------
# State decoding
# ---------------------------------------------------------------------------
class TestDecodeState:
    def test_decode_power_on(self) -> None:
        # Construct a fake state response that looks like a power packet
        raw = bytes([0x33, 0x01, 0x01]) + b"\x00" * 16 + bytes([0x33])
        st = decode_state(raw)
        assert st.power is True

    def test_decode_power_off(self) -> None:
        raw = bytes([0x33, 0x01, 0x00]) + b"\x00" * 16 + bytes([0x32])
        st = decode_state(raw)
        assert st.power is False

    def test_decode_brightness(self) -> None:
        # 0xFE is the max raw byte; decode_state should convert to 100%
        raw = bytes([0x33, 0x04, 0xFE]) + b"\x00" * 16 + bytes([0xC9])
        st = decode_state(raw)
        assert st.brightness == 100

    def test_decode_brightness_zero(self) -> None:
        raw = bytes([0x33, 0x04, 0x00]) + b"\x00" * 16 + bytes([0x37])
        st = decode_state(raw)
        assert st.brightness == 0

    def test_decode_brightness_mid(self) -> None:
        # 0x14 = 1%, 0xFE = 100%, midpoint ~= 0x89
        raw = bytes([0x33, 0x04, 0x89]) + b"\x00" * 16 + bytes([0])
        st = decode_state(raw)
        assert 45 <= st.brightness <= 55

    def test_decode_color(self) -> None:
        raw = bytes([0x33, 0x05, 0x02, 0xFF, 0x00, 0x00]) + b"\x00" * 13
        raw += bytes([checksum(raw)])
        st = decode_state(raw)
        assert st.rgb == (0xFF, 0x00, 0x00)

    def test_decode_garbage_returns_empty_state(self) -> None:
        st = decode_state(b"\x00\x01\x02")
        assert st.power is None
        assert st.brightness is None

    def test_decode_empty_returns_empty_state(self) -> None:
        st = decode_state(b"")
        assert st.power is None
