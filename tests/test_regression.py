"""Regression tests for bugs found by the superpowers code reviewer.

These tests verify that specific bugs stay fixed:
- C1: MAC identifier mismatch (services couldn't find coordinators)
- C2: Effect state wiped on every poll
- D1: GoveeH7015Client.is_connected missing (crashed the MQTT bridge's poll loop)
- D2: Reconfigure flow didn't detect MAC collisions with other entries
- D3: Diagnostics dump included the MAC address unredacted
- D4: BLE_CONNECT_TIMEOUT didn't cover the actual connect call, so a
  non-responding device hung setup forever instead of retrying
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "standalone"))

from custom_components.govee_h7015_ble.const import DOMAIN
from custom_components.govee_h7015_ble.coordinator import H7015Coordinator
from custom_components.govee_h7015_ble.protocol import H7015State, Scene

try:
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    USE_MOCK_ENTRY = True
except ImportError:
    USE_MOCK_ENTRY = False


def _make_entry(entry_id: str = "regress") -> object:
    if USE_MOCK_ENTRY:
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Patio Lights",
            data={"mac": "AA:BB:CC:DD:EE:FF", "name": "Patio Lights"},
            entry_id=entry_id,
            unique_id="AA:BB:CC:DD:EE:FF",
        )
        return entry
    from homeassistant.config_entries import ConfigEntry

    return ConfigEntry(
        version=1,
        domain=DOMAIN,
        title="Patio Lights",
        data={"mac": "AA:BB:CC:DD:EE:FF", "name": "Patio Lights"},
        source="user",
        entry_id=entry_id,
        unique_id="AA:BB:CC:DD:EE:FF",
        minor_version=1,
        discovery_keys={},
    )


# ===========================================================================
# C1 Regression: MAC identifier mismatch
# The device identifier must use MAC without colons so that
# _find_coordinator_for_device can match it.
# ===========================================================================


async def test_device_identifier_has_no_colons(hass) -> None:  # type: ignore[no-untyped-def]
    """Device identifier must be MAC without colons, not with colons.

    Bug: light.py used self._mac.upper() (with colons) for the device
    identifier, but __init__.py's _find_coordinator_for_device strips
    colons before comparing. These never matched.
    """
    entry = _make_entry("c1_regress")
    entry.add_to_hass(hass)

    async def mock_update(self):  # type: ignore[no-untyped-def]
        return H7015State(power=True)

    with (
        patch.object(H7015Coordinator, "_async_update_data", mock_update),
        patch.object(H7015Coordinator, "_ensure_connected", new=AsyncMock()),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # Check the device registry — the identifier should NOT have colons
        from homeassistant.helpers import device_registry as dr

        dev_reg = dr.async_get(hass)
        devices = dr.async_entries_for_config_entry(dev_reg, entry.entry_id)
        assert len(devices) == 1
        device = devices[0]

        # Find our domain's identifier
        our_id = None
        for ident in device.identifiers:
            if ident[0] == DOMAIN:
                our_id = ident[1]
                break

        assert our_id is not None, "No device identifier for our domain"
        assert ":" not in our_id, f"Identifier has colons: {our_id}"
        assert our_id == "AABBCCDDEEFF", f"Expected AABBCCDDEEFF, got {our_id}"


@pytest.mark.parametrize("write_failure", [False, True])
async def test_set_bulb_finds_coordinator_with_real_device_id(hass, write_failure: bool) -> None:  # type: ignore[no-untyped-def]
    """set_bulb service must find the coordinator using the real device ID.

    This test does NOT pre-create the device registry entry — it lets
    light.py create it naturally, then calls the service. This is the
    scenario that was broken before the fix.
    """
    entry = _make_entry("c1_regress2")
    entry.add_to_hass(hass)

    async def mock_update(self):  # type: ignore[no-untyped-def]
        return H7015State(power=True)

    with (
        patch.object(H7015Coordinator, "_async_update_data", mock_update),
        patch.object(H7015Coordinator, "_ensure_connected", new=AsyncMock()),
        patch.object(
            H7015Coordinator,
            "set_bulb",
            new=AsyncMock(
                side_effect=TimeoutError("simulated write failure") if write_failure else None
            ),
        ) as mock_set_bulb,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # Find the device that light.py created (not pre-created by the test)
        from homeassistant.helpers import device_registry as dr

        dev_reg = dr.async_get(hass)
        devices = dr.async_entries_for_config_entry(dev_reg, entry.entry_id)
        assert len(devices) == 1
        device = devices[0]

        from homeassistant.exceptions import HomeAssistantError

        data = {"bulb": 0, "rgb": [255, 0, 0], "device_id": [device.id]}
        if write_failure:
            with pytest.raises(HomeAssistantError, match="simulated write failure"):
                await hass.services.async_call(DOMAIN, "set_bulb", data, blocking=True)
        else:
            await hass.services.async_call(DOMAIN, "set_bulb", data, blocking=True)
        mock_set_bulb.assert_awaited_once()


# ===========================================================================
# C2 Regression: Effect state preserved after poll
# ===========================================================================


async def test_effect_preserved_after_poll(hass) -> None:  # type: ignore[no-untyped-def]
    """After a poll, the effect (mode) should NOT be wiped to None.

    Bug: _async_update_data did self._device_state = decode_state(raw),
    which replaced the entire state. decode_state never sets mode, so
    mode was reset to None after every 60s poll.
    """
    entry = _make_entry("c2_regress")
    entry.add_to_hass(hass)

    poll_count = 0

    async def mock_update(self):  # type: ignore[no-untyped-def]
        nonlocal poll_count
        poll_count += 1
        # Return a state packet that has power + brightness but no mode info
        return H7015State(power=True, brightness=50)

    with (
        patch.object(H7015Coordinator, "_async_update_data", mock_update),
        patch.object(H7015Coordinator, "_ensure_connected", new=AsyncMock()),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        coordinator: H7015Coordinator = hass.data[DOMAIN][entry.entry_id]

        # Set a scene — this sets mode to "scene:rainbow"
        with patch.object(H7015Coordinator, "_send", new=AsyncMock()):
            await coordinator.set_scene(Scene.RAINBOW)

        assert coordinator.device_state.mode == "scene:rainbow"

        # Trigger another poll — this should NOT wipe mode
        coordinator.async_update_listeners()
        await hass.async_block_till_done()

        # Mode should still be "scene:rainbow" after the update
        assert coordinator.device_state.mode == "scene:rainbow", (
            "Mode was wiped by poll — C2 regression"
        )


async def test_color_temp_preserved_after_poll(hass) -> None:  # type: ignore[no-untyped-def]
    """Color temperature mode should survive a poll."""
    entry = _make_entry("c2_regress2")
    entry.add_to_hass(hass)

    async def mock_update(self):  # type: ignore[no-untyped-def]
        return H7015State(power=True, brightness=50)

    with (
        patch.object(H7015Coordinator, "_async_update_data", mock_update),
        patch.object(H7015Coordinator, "_ensure_connected", new=AsyncMock()),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        coordinator: H7015Coordinator = hass.data[DOMAIN][entry.entry_id]

        with patch.object(H7015Coordinator, "_send", new=AsyncMock()):
            await coordinator.set_color_temperature(2700)

        assert coordinator.device_state.mode == "color_temp:2700"

        # Trigger update
        coordinator.async_update_listeners()
        await hass.async_block_till_done()

        assert coordinator.device_state.mode == "color_temp:2700", (
            "Color temp mode was wiped by poll — C2 regression"
        )


# ===========================================================================
# D1 Regression: GoveeH7015Client.is_connected missing
#
# standalone/mqtt_bridge.py's DeviceBridge.run() poll loop does
# `while self._client and self._client.is_connected:`, but GoveeH7015Client
# never defined that property (only the internal bleak client did). This
# raised AttributeError the first time through the loop, crashing the
# bridge's polling for every device it managed.
# ===========================================================================


def test_govee_h7015_client_has_is_connected_property() -> None:
    from govee_h7015 import GoveeH7015Client  # type: ignore[import-not-found]

    client = GoveeH7015Client("AA:BB:CC:DD:EE:FF")
    # No underlying BLE connection yet — must not raise AttributeError.
    assert client.is_connected is False


def test_govee_h7015_client_is_connected_reflects_ble_client() -> None:
    from govee_h7015 import GoveeH7015Client  # type: ignore[import-not-found]

    client = GoveeH7015Client("AA:BB:CC:DD:EE:FF")
    fake_ble_client = type("FakeBleakClient", (), {"is_connected": True})()
    client._client = fake_ble_client  # type: ignore[assignment]
    assert client.is_connected is True


# ===========================================================================
# D2 Regression: Reconfigure flow didn't detect MAC collisions
#
# async_step_reconfigure called self._abort_if_unique_id_configured() without
# first calling async_set_unique_id(mac) for the *new* MAC being entered. It
# was checking the flow's original (old) unique_id, so reconfiguring one
# entry to use a MAC already claimed by a different entry silently succeeded
# instead of aborting — leaving two entries with the same MAC/unique_id.
# ===========================================================================


async def test_reconfigure_rejects_mac_already_used_by_another_entry(hass) -> None:  # type: ignore[no-untyped-def]
    """Reconfiguring entry A to entry B's MAC must abort, not succeed."""
    if not USE_MOCK_ENTRY:
        pytest.skip("requires pytest_homeassistant_custom_component")

    entry_a = MockConfigEntry(
        domain=DOMAIN,
        title="Patio Lights",
        data={"mac": "AA:BB:CC:DD:EE:FF", "name": "Patio Lights"},
        entry_id="d2_entry_a",
        unique_id="AA:BB:CC:DD:EE:FF",
    )
    entry_b = MockConfigEntry(
        domain=DOMAIN,
        title="Garden Lights",
        data={"mac": "11:22:33:44:55:66", "name": "Garden Lights"},
        entry_id="d2_entry_b",
        unique_id="11:22:33:44:55:66",
    )
    entry_a.add_to_hass(hass)
    entry_b.add_to_hass(hass)

    from homeassistant.config_entries import SOURCE_RECONFIGURE

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": entry_a.entry_id},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"mac": entry_b.data["mac"], "name": "Patio Lights"},
    )

    assert result["type"] == "abort"
    assert result["reason"] == "already_configured"
    # entry_a's MAC must be unchanged — the collision must not have applied.
    assert entry_a.data["mac"] == "AA:BB:CC:DD:EE:FF"


# ===========================================================================
# D3 Regression: Diagnostics dump included the MAC address unredacted
#
# info.md promises diagnostics export "without sensitive data", but the MAC
# was included in the clear in both entry.data and the device block. HA's
# own diagnostics guidelines call for redacting device identifiers like MACs
# since diagnostics get pasted into public bug reports.
# ===========================================================================


async def test_diagnostics_redacts_mac(hass) -> None:  # type: ignore[no-untyped-def]
    """The MAC address must be redacted from the diagnostics dump."""
    from custom_components.govee_h7015_ble.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    entry = _make_entry("d3_regress")
    entry.add_to_hass(hass)

    async def mock_update(self):  # type: ignore[no-untyped-def]
        return H7015State(power=True)

    with (
        patch.object(H7015Coordinator, "_async_update_data", mock_update),
        patch.object(H7015Coordinator, "_ensure_connected", new=AsyncMock()),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        diag = await async_get_config_entry_diagnostics(hass, entry)

    assert "AA:BB:CC:DD:EE:FF" not in str(diag)
    assert diag["entry"]["data"]["mac"] == "**REDACTED**"
    assert diag["device"]["mac"] == "**REDACTED**"


# ===========================================================================
# D4 Regression: BLE_CONNECT_TIMEOUT didn't cover the actual connect call
#
# _ensure_connected() built the client via _build_client() (which calls
# bleak-retry-connector's establish_connection() — the call that actually
# talks to BlueZ over D-Bus and can hang indefinitely for an unresponsive
# device) *before* entering the asyncio.timeout() block. The timeout only
# wrapped the redundant client.connect() call afterward, which is a no-op
# once already connected. A device that never responds hung setup forever
# instead of failing over to setup_retry.
# ===========================================================================


async def test_ensure_connected_times_out_when_build_client_hangs(hass) -> None:  # type: ignore[no-untyped-def]
    """A _build_client() that never returns must not hang _ensure_connected()."""
    import asyncio

    from custom_components.govee_h7015_ble import coordinator as coordinator_module

    async def hanging_build_client(self, ble_device):  # type: ignore[no-untyped-def]
        await asyncio.sleep(10)
        raise AssertionError("should have timed out before this point")

    async def fake_lookup(hass, mac, connectable):  # type: ignore[no-untyped-def]
        return object()  # any non-None sentinel is enough to pass the discovery check

    coordinator = H7015Coordinator(
        hass,
        mac="AA:BB:CC:DD:EE:FF",
        name="Patio Lights",
        poll_interval=60,
        entry_id="d4_regress",
        ble_device_lookup=fake_lookup,
    )

    with (
        patch.object(coordinator_module, "BLE_CONNECT_TIMEOUT", 0.05),
        patch.object(H7015Coordinator, "_build_client", hanging_build_client),
    ):
        from homeassistant.helpers.update_coordinator import UpdateFailed

        from custom_components.govee_h7015_ble.exceptions import GoveeConnectionError

        with pytest.raises((UpdateFailed, GoveeConnectionError)):
            await asyncio.wait_for(coordinator._ensure_connected(), timeout=2)


def _transport_coordinator(hass, client, entry_id: str = "transport"):  # type: ignore[no-untyped-def]
    coordinator = H7015Coordinator(
        hass,
        mac="AA:BB:CC:DD:EE:FF",
        name="Review",
        poll_interval=60,
        entry_id=entry_id,
        ble_device_lookup=AsyncMock(return_value=object()),
    )
    coordinator._build_client = AsyncMock(return_value=client)  # type: ignore[method-assign]
    return coordinator


async def test_subscribes_before_first_write_and_poll_never_reads(hass) -> None:  # type: ignore[no-untyped-def]
    from tests.mock_h7015 import MockH7015Client

    client = MockH7015Client()
    await client.connect()
    coordinator = _transport_coordinator(hass, client)
    try:
        await coordinator.set_power(True)
        state = await coordinator._async_update_data()
    finally:
        await coordinator.shutdown()
    assert client.events[:2] == ["start_notify", "write"]
    assert client.events.count("start_notify") == 1
    assert client.mock_write_count == 2  # command + heartbeat, no characteristic read
    assert state.power is True  # retained commanded state


async def test_subscribe_failure_disconnects_and_raises(hass) -> None:  # type: ignore[no-untyped-def]
    from homeassistant.helpers.update_coordinator import UpdateFailed

    from tests.mock_h7015 import MockH7015Client

    client = MockH7015Client()
    await client.connect()
    client.start_notify = AsyncMock(side_effect=RuntimeError("cccd denied"))  # type: ignore[method-assign]
    coordinator = _transport_coordinator(hass, client, "subfail")
    with pytest.raises(UpdateFailed, match="subscribe"):
        await coordinator._ensure_connected()
    assert not client.is_connected
    assert coordinator._client is None
    assert client.mock_write_count == 0
    assert not coordinator.keepalive_running


@pytest.mark.parametrize(
    "frame",
    [
        bytes([0x33, 0x04, 0x01]) + b"\x00" * 17,  # command ACK
        bytes([0x33, 0x05, 0x00]) + b"\x00" * 17,  # command ACK
        bytes([0xAB]) + bytes(range(1, 20)),  # unverified AB layout
    ],
)
async def test_ack_and_unknown_notifications_preserve_state(hass, frame: bytes) -> None:  # type: ignore[no-untyped-def]
    from govee_h7015 import GoveeH7015Client
    from protocol import H7015State as StandaloneState

    coordinator = H7015Coordinator(
        hass, mac="AA:BB:CC:DD:EE:FF", name="Review", poll_interval=60, entry_id="ack"
    )
    coordinator._device_state = H7015State(
        power=True, brightness=50, rgb=(10, 20, 30), mode="scene:rainbow"
    )
    coordinator._on_notify(None, bytearray(frame))
    standalone = GoveeH7015Client("AA:BB:CC:DD:EE:FF", keepalive=False)
    standalone._state = StandaloneState(
        power=True, brightness=50, rgb=(10, 20, 30), mode="scene:rainbow"
    )
    standalone._on_notify(None, bytearray(frame))
    for state in (coordinator.device_state, standalone.state):
        assert (state.power, state.brightness, state.rgb) == (True, 50, (10, 20, 30))
        assert state.mode == "scene:rainbow"
        assert state.raw == frame


async def test_standalone_poll_is_heartbeat_not_read() -> None:
    from govee_h7015 import GoveeH7015Client
    from protocol import pkt_keepalive

    transport = AsyncMock()
    transport.is_connected = True
    standalone = GoveeH7015Client("AA:BB:CC:DD:EE:FF", keepalive=False)
    standalone._client = transport
    await standalone.poll_state()
    transport.write_gatt_char.assert_awaited_once()
    assert transport.write_gatt_char.await_args.args[1] == pkt_keepalive()
    transport.read_gatt_char.assert_not_called()


async def test_disconnect_cancels_inflight_reconnect() -> None:
    import asyncio

    from govee_h7015 import GoveeH7015Client

    reconnect_started = asyncio.Event()
    release_reconnect = asyncio.Event()
    transports = []

    class Transport:
        is_connected = False

        async def connect(self) -> None:
            if len(transports) == 2:
                reconnect_started.set()
                await release_reconnect.wait()
            self.is_connected = True

        async def start_notify(self, char_uuid, callback) -> None:
            pass

        async def disconnect(self) -> None:
            self.is_connected = False

    def factory(*args, **kwargs):
        transport = Transport()
        transports.append(transport)
        return transport

    client = GoveeH7015Client("AA:BB:CC:DD:EE:FF", keepalive=False)
    with patch("govee_h7015.BleakClient", factory):
        await client.connect()
        transports[0].is_connected = False
        client._on_disconnect(transports[0])
        await asyncio.wait_for(reconnect_started.wait(), timeout=2)
        await client.disconnect()
        release_reconnect.set()
        client._on_disconnect(transports[0])
        await asyncio.sleep(0)
        assert not client.is_connected
        assert all(not transport.is_connected for transport in transports)
        assert client._reconnect_task is None
        await client.connect()
        assert client.is_connected
        await client.disconnect()


async def test_full_string_color_replaces_cached_bulbs(hass) -> None:  # type: ignore[no-untyped-def]
    """An all-segment command must replace older individual bulb colors."""
    from tests.mock_h7015 import MockH7015Client

    client = MockH7015Client()
    await client.connect()
    coordinator = _transport_coordinator(hass, client, "full_color")
    try:
        await coordinator.set_bulb(8, 0, 0, 255)
        await coordinator.set_color(255, 0, 0)
        assert coordinator.get_all_bulb_colors() == dict.fromkeys(range(15), (255, 0, 0))
        assert coordinator.device_state.rgb == client.mock_rgb == (255, 0, 0)
    finally:
        await coordinator.shutdown()


async def test_disconnect_cancels_pending_notification_callback() -> None:
    """Shutdown must not leave a callback running after its BLE client closes."""
    import asyncio

    from govee_h7015 import GoveeH7015Client

    started = asyncio.Event()
    stopped = asyncio.Event()

    async def state_callback(state) -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    client = GoveeH7015Client("AA:BB:CC:DD:EE:FF", keepalive=False, state_callback=state_callback)
    client._loop = asyncio.get_running_loop()
    client._on_notify(None, bytearray.fromhex("ab010000000000000000000000000000000000aa"))
    await asyncio.wait_for(started.wait(), timeout=1)
    await client.disconnect()
    assert stopped.is_set()
    assert not client._notify_tasks
