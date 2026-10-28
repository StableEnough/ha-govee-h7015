"""Persistence tests for last-commanded H7015 settings."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from custom_components.govee_h7015_ble.coordinator import H7015Coordinator
from custom_components.govee_h7015_ble.protocol import Scene


def _coordinator(hass, entry_id: str) -> H7015Coordinator:  # type: ignore[no-untyped-def]
    return H7015Coordinator(
        hass,
        mac="AA:BB:CC:DD:EE:FF",
        name="Patio Lights",
        poll_interval=60,
        entry_id=entry_id,
    )


async def test_store_reloads_commanded_main_and_bulb_state(hass) -> None:  # type: ignore[no-untyped-def]
    first = _coordinator(hass, "persist-one")
    first._send = AsyncMock()  # type: ignore[method-assign]
    await first.set_power(False)
    await first.set_brightness(37)
    await first.set_color(7, 8, 9)
    await first.set_bulb(4, 12, 34, 56)
    await first.set_bulb(4, 0, 0, 0)
    await first.set_bulb_brightness(4, 23)
    await first.set_scene(Scene.RAINBOW)
    await first.shutdown()

    persisted = await first._store.async_load()
    assert persisted is not None
    assert "raw" not in persisted["state"]
    restored = _coordinator(hass, "persist-one")
    restored._send = AsyncMock()  # type: ignore[method-assign]
    await restored.async_load_state()
    restored._send.assert_not_awaited()
    assert restored.device_state.power is False
    assert restored.device_state.brightness == 37
    assert restored.device_state.rgb == (7, 8, 9)
    assert restored.device_state.mode == "scene:rainbow"
    assert restored.get_bulb_color(4) == (0, 0, 0)
    assert restored.get_bulb_restore_color(4) == (12, 34, 56)
    assert restored.get_bulb_brightness(4) == 23
    assert restored._client is None

    separate = _coordinator(hass, "persist-two")
    await separate.async_load_state()
    assert separate.device_state.power is None
    assert separate.get_bulb_color(4) is None


async def test_failed_write_does_not_persist_command(hass) -> None:  # type: ignore[no-untyped-def]
    first = _coordinator(hass, "persist-failure")
    send = AsyncMock()
    first._send = send  # type: ignore[method-assign]
    await first.set_power(True)
    send.side_effect = RuntimeError("write failed")
    with pytest.raises(RuntimeError, match="write failed"):
        await first.set_power(False)
    await first.shutdown()

    restored = _coordinator(hass, "persist-failure")
    await restored.async_load_state()
    assert restored.device_state.power is True
