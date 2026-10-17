"""DataUpdateCoordinator for the H7015.

Type-safe, uses a Protocol-based BLE client for testability, asyncio.timeout
on every BLE operation to prevent hangs, and a typed exception hierarchy.

Uses bleak-retry-connector (HA-recommended) for reliable BLE connections
that handle transient BlueZ errors automatically.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final, override

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .exceptions import (
    GoveeConnectionError,
    GoveeError,
)
from .protocol import (
    BULB_COUNT,
    KEEPALIVE_INTERVAL,
    WRITE_CHAR_UUID,
    H7015State,
    MusicMode,
    Scene,
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
)

if TYPE_CHECKING:
    from .govee_types import RGB, BleClient, BulbIndex, MacAddress

_LOGGER = logging.getLogger(__name__)

# BLE operation timeout — prevents indefinite hangs if the radio wedges.
BLE_OP_TIMEOUT: Final = 10.0
# Minimum gap between GATT writes (spec write_pacing).
WRITE_GAP: Final = 0.08
# Connect timeout — HA recommends >= 10s for BlueZ service resolution.
BLE_CONNECT_TIMEOUT: Final = 20.0


# Type alias for the HA Bluetooth device-lookup function.
type BleDeviceLookup = Callable[[HomeAssistant, str, bool], Awaitable[Any | None]]


class H7015Coordinator(DataUpdateCoordinator[H7015State]):
    """Coordinator that holds a BLE connection and pushes commands."""

    def __init__(
        self,
        hass: HomeAssistant,
        mac: MacAddress,
        name: str,
        poll_interval: int,
        entry_id: str,
        ble_device_lookup: BleDeviceLookup | None = None,
        config_entry: Any = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"H7015 {name}",
            update_interval=timedelta(seconds=max(5, poll_interval)),
        )
        self.mac = mac
        self.name = name
        self.entry_id = entry_id
        self._config_entry = config_entry
        self._ble_device_lookup = ble_device_lookup or _default_ble_device_lookup
        self._client: BleClient | None = None
        self._keepalive_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._last_write = float("-inf")
        self._connect_lock = asyncio.Lock()  # prevents concurrent _ensure_connected
        self._device_state: H7015State = H7015State()
        # Per-bulb colors are last-commanded state, not hardware readback.
        # Changes made through the Govee app may leave this cache stale.
        self._bulb_colors: dict[int, RGB] = {}
        # Track consecutive connection failures for repair issue creation.
        self._consecutive_failures = 0
        self._repair_issue_created = False

    @property
    def device_state(self) -> H7015State:
        """Last-known device state (power, brightness, color, etc).

        Prefers ``self.data`` (set by HA's DataUpdateCoordinator from the
        return of ``_async_update_data``) over ``self._device_state`` (set
        by individual command methods like ``set_power``). This ensures
        the entity always reflects the latest polled state, even if
        commands were sent between polls.

        Named ``device_state`` (not ``state``) to avoid shadowing
        ``DataUpdateCoordinator.state``, which HA uses internally to track
        the coordinator's lifecycle.
        """
        if self.data is not None:
            return self.data
        return self._device_state

    @property
    def is_connected(self) -> bool:
        """Whether the BLE client is currently connected."""
        return self._client is not None and self._client.is_connected

    @property
    def keepalive_running(self) -> bool:
        """Whether the keepalive task is currently running."""
        return self._keepalive_task is not None and not self._keepalive_task.done()

    def get_bulb_color(self, bulb: int) -> RGB | None:
        """Get the last-commanded color for a specific bulb."""
        return self._bulb_colors.get(bulb)

    def get_all_bulb_colors(self) -> dict[int, RGB]:
        """Get all bulb colors (snapshot for scene creation)."""
        return dict(self._bulb_colors)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def _ensure_connected(self) -> BleClient:
        """Connect if needed and return the active client.

        Uses _connect_lock to prevent two concurrent callers from both
        trying to connect at the same time.
        """
        # Fast path: already connected
        if self._client and self._client.is_connected:
            return self._client

        # Slow path: acquire connect lock so only one caller connects
        async with self._connect_lock:
            # Re-check after acquiring lock — another caller may have connected
            if self._client and self._client.is_connected:
                return self._client

            await self._teardown_client()
            _LOGGER.info("Connecting to %s", self.mac)

            ble_device = await self._ble_device_lookup(self.hass, self.mac, True)
            if ble_device is None:
                # Use HA's reachability diagnostics for a human-readable reason
                reason = await self._get_reachability_reason()
                raise UpdateFailed(f"H7015 {self.mac} not discovered via HA Bluetooth: {reason}")

            try:
                async with asyncio.timeout(BLE_CONNECT_TIMEOUT):
                    # establish_connection() inside _build_client() connects
                    # over BlueZ and may hang, so keep it inside the timeout.
                    client = await self._build_client(ble_device)
                await asyncio.sleep(0.2)  # service-discovery quirk
            except TimeoutError as exc:
                raise UpdateFailed(f"connect timeout for {self.mac}") from exc
            except GoveeConnectionError as exc:
                raise UpdateFailed(f"BLE connection failed: {exc}") from exc
            except Exception as exc:
                # bleak-retry-connector handles most transient errors, but
                # anything that escapes it should still produce a clear message.
                raise UpdateFailed(f"BLE connection failed: {exc}") from exc

            # Subscribe before any write (spec); clean up on failure.
            try:
                async with asyncio.timeout(BLE_OP_TIMEOUT):
                    await client.start_notify(WRITE_CHAR_UUID, self._on_notify)
            except BaseException as exc:
                with contextlib.suppress(Exception):
                    async with asyncio.timeout(BLE_OP_TIMEOUT):
                        await client.disconnect()
                if isinstance(exc, TimeoutError):
                    raise UpdateFailed(f"notification subscribe timed out for {self.mac}") from exc
                if isinstance(exc, Exception):
                    raise UpdateFailed(f"notification subscribe failed: {exc}") from exc
                raise

            self._client = client
            self._keepalive_task = asyncio.create_task(self._keepalive_loop())
            return client

    async def _get_reachability_reason(self) -> str:
        """Get a human-readable explanation of why the device is unreachable."""
        # TODO: Use HA's async_address_reachability_diagnostics API when it
        # becomes available in a future HA version. For now, return a generic
        # message — the full reachability API requires BluetoothReachabilityIntent
        # which is not yet in HA 2025.x.
        return "device not in range of any Bluetooth adapter"

    async def _build_client(self, ble_device: Any) -> BleClient:
        """Construct a BLE client using bleak-retry-connector.

        bleak-retry-connector handles transient BlueZ connection failures
        automatically — much more reliably than our manual retry logic.
        See: https://developers.home-assistant.io/docs/bluetooth
        """
        try:
            from bleak import BleakClient
            from bleak_retry_connector import establish_connection
        except ImportError as exc:
            raise UpdateFailed(
                "bleak-retry-connector not installed. Run: pip install bleak-retry-connector"
            ) from exc

        # establish_connection returns a BleakClient that's already connected,
        # with retry logic baked in. We wrap it in a thin adapter so it
        # satisfies our BleClient Protocol.
        client = await establish_connection(
            BleakClient,
            ble_device,
            self.mac,  # name for logging
            max_attempts=3,
        )
        return client  # type: ignore[return-value]

    async def _teardown_client(self) -> None:
        """Cancel keepalive and disconnect any stale client."""
        if self._keepalive_task and not self._keepalive_task.done():
            self._keepalive_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._keepalive_task
            self._keepalive_task = None
        if self._client:
            with contextlib.suppress(Exception):  # pragma: no cover — best-effort cleanup
                if self._client.is_connected:
                    async with asyncio.timeout(BLE_OP_TIMEOUT):
                        await self._client.disconnect()
            self._client = None

    async def _keepalive_loop(self) -> None:
        """Send a keepalive packet every 2 seconds while connected.

        If the keepalive write fails (connection dead), just return.
        The next _send or _async_update_data call will detect the dead
        connection and call _teardown_client + reconnect.
        """
        try:
            while True:
                await asyncio.sleep(KEEPALIVE_INTERVAL)
                if self._client and self._client.is_connected:
                    try:
                        async with self._lock:
                            async with asyncio.timeout(BLE_OP_TIMEOUT):
                                await self._write_paced(
                                    self._client, pkt_keepalive(), response=True
                                )
                    except TimeoutError:
                        _LOGGER.warning("keepalive timed out — connection may be dead")
                        return
                    except Exception as exc:
                        _LOGGER.warning("keepalive failed: %s — connection may be dead", exc)
                        return
        except asyncio.CancelledError:
            raise

    async def shutdown(self) -> None:
        """Cleanly tear down the connection."""
        await self._teardown_client()

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------
    async def _write_paced(self, client: BleClient, packet: bytes, *, response: bool) -> None:
        """Single paced write; caller MUST hold self._lock."""
        loop = asyncio.get_running_loop()
        wait = WRITE_GAP - (loop.time() - self._last_write)
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            await client.write_gatt_char(WRITE_CHAR_UUID, packet, response=response)
        finally:
            self._last_write = loop.time()

    async def _send(self, packet: bytes) -> None:
        """Write a packet to the device with timeout, locking and pacing."""
        client = await self._ensure_connected()
        async with self._lock:
            _LOGGER.debug("TX %s", packet.hex())
            try:
                async with asyncio.timeout(BLE_OP_TIMEOUT):
                    await self._write_paced(client, packet, response=True)
            except TimeoutError as exc:
                raise UpdateFailed(f"write timed out: {exc}") from exc
            except Exception as exc:
                # Catch BleakError and other BLE exceptions
                raise UpdateFailed(f"BLE write failed: {exc}") from exc

    async def set_power(self, on: bool) -> None:
        await self._send(pkt_power(on))
        self._update_state(power=on)

    async def set_brightness(self, percent: int) -> None:
        packet = pkt_brightness(percent)
        await self._send(packet)
        self._update_state(brightness=packet[2])

    async def set_color(self, r: int, g: int, b: int) -> None:
        packet = pkt_solid_color(r, g, b)
        await self._send(packet)
        rgb = (packet[4], packet[5], packet[6])
        self._bulb_colors = dict.fromkeys(range(BULB_COUNT), rgb)
        self._update_state(rgb=rgb, mode="manual")

    async def set_scene(self, scene: Scene) -> None:
        await self._send(pkt_scene(scene))
        self._update_state(mode=f"scene:{scene.name.lower()}")

    async def set_music_mode(self, mode: MusicMode, r: int = 0, g: int = 0, b: int = 0) -> None:
        await self._send(pkt_music(mode, r, g, b))
        self._update_state(mode=f"music:{mode.name.lower()}")

    async def set_bulb(self, bulb: BulbIndex, r: int, g: int, b: int) -> None:
        packet = pkt_segment(bulb, r, g, b)
        await self._send(packet)
        self._bulb_colors[bulb] = (packet[4], packet[5], packet[6])

    async def set_color_temperature(self, kelvin: int) -> None:
        """Set color temperature (warm/cold white) in Kelvin.

        This legacy encoding is not verified for the H7015.
        """
        await self._send(pkt_color_temperature(kelvin))
        self._update_state(mode=f"color_temp:{kelvin}")

    async def set_gradient(self, on: bool) -> None:
        """Toggle gradient mode (smooth color transitions between bulbs)."""
        await self._send(pkt_gradient(on))

    def _update_state(self, **changes: Any) -> None:
        """Update both ``self.data`` and ``self._device_state``.

        ``self.data`` is what HA entities read via ``coordinator.data``.
        ``self._device_state`` is the fallback before the first poll.
        Both must be updated so the entity immediately reflects commands.
        """
        self._device_state = dataclasses.replace(self._device_state, **changes)
        if self.data is not None:
            self.data = dataclasses.replace(self.data, **changes)

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------
    @override
    async def _async_update_data(self) -> H7015State:
        # Spec: no readable state characteristic. Poll = heartbeat; replies (if any)
        # arrive via notification and are merged by _on_notify. Return retained state.
        try:
            await self._ensure_connected()
            await self._send(pkt_keepalive())
            # Success — reset failure counter and delete repair issue
            self._consecutive_failures = 0
            if self._repair_issue_created:
                from .repairs import delete_unreachable_issue

                delete_unreachable_issue(self.hass, self._config_entry)
                self._repair_issue_created = False
        except TimeoutError as exc:
            await self._teardown_client()
            self._track_failure()
            raise UpdateFailed(f"BLE heartbeat timed out: {exc}") from exc
        except GoveeError as exc:
            await self._teardown_client()
            self._track_failure()
            raise UpdateFailed(f"BLE error: {exc}") from exc
        except UpdateFailed:
            self._track_failure()
            raise
        except Exception as exc:
            await self._teardown_client()
            self._track_failure()
            raise UpdateFailed(f"unexpected: {exc}") from exc
        return self.device_state

    def _on_notify(self, _char: Any, data: bytearray) -> None:
        """Merge known fields from a notification; ACKs/unknown frames keep state."""
        raw = bytes(data)
        _LOGGER.debug("RX %s", raw.hex())
        previous = self.device_state
        changes: dict[str, Any] = {"raw": raw}
        if raw[:1] == b"\xaa":  # 0x33 cmd-status ACKs are not state
            decoded = decode_state(raw)
            for field in ("power", "brightness", "rgb"):
                value = getattr(decoded, field)
                if value is not None:
                    changes[field] = value
        self._device_state = dataclasses.replace(previous, **changes)
        self.async_set_updated_data(self._device_state)

    def _track_failure(self) -> None:
        """Track consecutive failures and create a repair issue after 3."""
        self._consecutive_failures += 1
        if self._consecutive_failures >= 3 and not self._repair_issue_created:
            from .repairs import create_unreachable_issue

            create_unreachable_issue(self.hass, self._config_entry)
            self._repair_issue_created = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _default_ble_device_lookup(
    hass: HomeAssistant, mac: str, connectable: bool
) -> Any | None:
    """Default HA Bluetooth device lookup."""
    try:
        from homeassistant.components.bluetooth import async_ble_device_from_address
    except ImportError:
        return None
    return async_ble_device_from_address(hass, mac, connectable=connectable)


# Re-export for type-checkers
__all__ = ["BLE_OP_TIMEOUT", "BleDeviceLookup", "H7015Coordinator"]
