"""
Govee H7015 BLE client — async, type-safe, modern Python 3.12+.

This module wraps the protocol (see protocol.py) with a bleak-based BLE
client that handles keepalive, reconnection, and state polling.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
import time
from typing import TYPE_CHECKING, Final

try:
    from bleak import BleakClient
    from bleak.exc import BleakError
except ImportError:  # pragma: no cover — bleak only needed for live use
    BleakClient = None  # type: ignore[assignment,unused-ignore]
    BleakError = Exception  # type: ignore[assignment,misc]

from exceptions import (  # type: ignore[import-not-found]
    GoveeConnectionError,
    GoveeError,
    GoveeTimeoutError,
)
from govee_types import BulbIndex, MacAddress  # type: ignore[import-not-found]
from protocol import (  # type: ignore[import-not-found]
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
    pkt_multi_segment,
    pkt_music,
    pkt_power,
    pkt_scene,
    pkt_segment,
    pkt_solid_color,
    pkt_warm_white,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

LOGGER = logging.getLogger("govee_h7015")

BLE_OP_TIMEOUT: Final = 10.0
BLE_CONNECT_TIMEOUT: Final = 20.0
RECONNECT_MAX_ATTEMPTS: Final = 10
WRITE_GAP: Final = 0.08  # spec write_pacing minimum gap


class GoveeH7015Client:
    """Async BLE client for the H7015.

    Keeps a keepalive task running while connected. Reconnects on drop.

    Usage:
        async with GoveeH7015Client(MacAddress("AA:BB:CC:DD:EE:FF")) as c:
            await c.power_on()
            await asyncio.sleep(1)
            await c.set_color(255, 0, 0)
    """

    def __init__(
        self,
        address: MacAddress | str,
        *,
        keepalive: bool = True,
        reconnect: bool = True,
        state_callback: Callable[[H7015State], Awaitable[None]] | None = None,
    ) -> None:
        if BleakClient is None:
            raise RuntimeError("bleak is not installed. Run: pip install bleak")
        self.address = MacAddress(str(address))
        self.keepalive_enabled = keepalive
        self.reconnect_enabled = reconnect
        self.state_callback = state_callback
        self._client: BleakClient | None = None  # type: ignore[assignment]
        self._keepalive_task: asyncio.Task[None] | None = None
        self._reconnect_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._state: H7015State = H7015State()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._intentional_disconnect = False
        self._last_write = float("-inf")
        self._notify_tasks: set[asyncio.Future[None]] = set()

    @property
    def state(self) -> H7015State:
        return self._state

    @property
    def is_connected(self) -> bool:
        """Whether the underlying BLE client is currently connected."""
        return self._client is not None and self._client.is_connected

    @property
    def keepalive_running(self) -> bool:
        """Whether the keepalive task is currently running."""
        return self._keepalive_task is not None and not self._keepalive_task.done()

    async def __aenter__(self) -> GoveeH7015Client:
        await self.connect()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.disconnect()

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------
    async def connect(self, timeout: float = BLE_CONNECT_TIMEOUT) -> None:
        """Connect to the device and start the keepalive task."""
        LOGGER.info("Connecting to %s", self.address)
        self._loop = asyncio.get_running_loop()
        self._intentional_disconnect = False
        self._client = BleakClient(
            self.address, timeout=timeout, disconnected_callback=self._on_disconnect
        )
        try:
            async with asyncio.timeout(timeout):
                await self._client.connect()
            await asyncio.sleep(0.2)  # service-discovery quirk
            # Subscribe before any write (spec).
            async with asyncio.timeout(BLE_OP_TIMEOUT):
                await self._client.start_notify(WRITE_CHAR_UUID, self._on_notify)
        except BaseException as exc:
            self._intentional_disconnect = True
            client, self._client = self._client, None
            if client is not None:
                with contextlib.suppress(Exception):
                    async with asyncio.timeout(BLE_OP_TIMEOUT):
                        await client.disconnect()
            if isinstance(exc, TimeoutError):
                raise GoveeTimeoutError(f"connect/subscribe timed out after {timeout}s") from exc
            if isinstance(exc, BleakError):
                raise GoveeConnectionError(f"BLE connect failed: {exc}") from exc
            raise

        if self.keepalive_enabled:
            self._keepalive_task = asyncio.create_task(self._keepalive_loop())
        LOGGER.info("Connected to %s", self.address)

    async def disconnect(self) -> None:
        """Cancel keepalive and disconnect."""
        self._intentional_disconnect = True
        if self._reconnect_task:
            self._reconnect_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reconnect_task
            self._reconnect_task = None
        if self._keepalive_task:
            self._keepalive_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._keepalive_task
            self._keepalive_task = None
        if self._client and self._client.is_connected:
            with contextlib.suppress(Exception):  # pragma: no cover
                async with asyncio.timeout(BLE_OP_TIMEOUT):
                    await self._client.disconnect()
        self._client = None
        tasks = self._notify_tasks - {asyncio.current_task()}
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        LOGGER.info("Disconnected")

    def _on_disconnect(self, _client: BleakClient) -> None:
        """Called by bleak from a non-loop thread when the device drops."""
        if self._intentional_disconnect:
            LOGGER.debug("Intentional disconnect — not reconnecting")
            return
        LOGGER.warning("Device disconnected: %s", self.address)
        if not self.reconnect_enabled:
            return
        # Schedule task ownership on the loop, even when bleak calls from a thread.
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._start_reconnect)
        else:
            LOGGER.error("No running event loop; cannot auto-reconnect")

    def _start_reconnect(self) -> None:
        if not self._intentional_disconnect and (
            self._reconnect_task is None or self._reconnect_task.done()
        ):
            self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        """Exponential-backoff reconnect, up to RECONNECT_MAX_ATTEMPTS tries."""
        for attempt in range(1, RECONNECT_MAX_ATTEMPTS + 1):
            LOGGER.info("Reconnect attempt %d/%d", attempt, RECONNECT_MAX_ATTEMPTS)
            try:
                await self._teardown_for_reconnect()
                await self.connect()
                return
            except Exception as exc:  # pragma: no cover
                LOGGER.warning("Reconnect failed: %s", exc)
                await asyncio.sleep(2 ** min(attempt, 5))
        LOGGER.error("Giving up reconnect after %d attempts", RECONNECT_MAX_ATTEMPTS)

    async def _teardown_for_reconnect(self) -> None:
        """Clean up stale client + keepalive before a reconnect attempt."""
        self._client = None
        if self._keepalive_task and not self._keepalive_task.done():
            self._keepalive_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._keepalive_task
            self._keepalive_task = None

    async def _keepalive_loop(self) -> None:
        """Send a keepalive packet every KEEPALIVE_INTERVAL seconds.

        If the keepalive write fails (connection dead), tear down the client
        so the next operation triggers a reconnect.
        """
        try:
            while True:
                await asyncio.sleep(KEEPALIVE_INTERVAL)
                if self._client and self._client.is_connected:
                    try:
                        async with asyncio.timeout(BLE_OP_TIMEOUT):
                            await self._write(pkt_keepalive())
                    except TimeoutError:
                        LOGGER.warning("keepalive timed out — connection may be dead")
                        await self._teardown_for_reconnect()
                        return
                    except GoveeConnectionError as exc:
                        LOGGER.warning("keepalive failed: %s — tearing down", exc)
                        await self._teardown_for_reconnect()
                        return
                    except Exception as exc:  # pragma: no cover
                        LOGGER.debug("keepalive error: %s", exc)
                        await self._teardown_for_reconnect()
                        return
        except asyncio.CancelledError:
            raise

    # ------------------------------------------------------------------
    # Low-level write
    # ------------------------------------------------------------------
    async def _write(self, data: bytes, *, response: bool = True) -> None:
        if not self._client or not self._client.is_connected:
            raise GoveeConnectionError("not connected")
        async with self._lock:
            LOGGER.debug("TX %s", data.hex())
            try:
                async with asyncio.timeout(BLE_OP_TIMEOUT):
                    wait = WRITE_GAP - (time.monotonic() - self._last_write)
                    if wait > 0:
                        await asyncio.sleep(wait)
                    try:
                        await self._client.write_gatt_char(WRITE_CHAR_UUID, data, response=response)
                    finally:
                        self._last_write = time.monotonic()
            except TimeoutError as exc:
                raise GoveeTimeoutError(f"write timed out after {BLE_OP_TIMEOUT}s") from exc
            except BleakError as exc:
                raise GoveeConnectionError(f"BLE write failed: {exc}") from exc
            except Exception as exc:
                # Catch dbus_fast errors and other non-BleakError exceptions
                raise GoveeConnectionError(f"unexpected BLE write error: {exc}") from exc

    # ------------------------------------------------------------------
    # High-level commands
    # ------------------------------------------------------------------
    async def power_on(self) -> None:
        await self._write(pkt_power(True))
        self._state = dataclasses.replace(self._state, power=True)

    async def power_off(self) -> None:
        await self._write(pkt_power(False))
        self._state = dataclasses.replace(self._state, power=False)

    async def set_power(self, on: bool) -> None:
        await self.power_on() if on else await self.power_off()

    async def set_brightness(self, percent: int) -> None:
        packet = pkt_brightness(percent)
        await self._write(packet)
        self._state = dataclasses.replace(self._state, brightness=packet[2])

    async def set_color(self, r: int, g: int, b: int) -> None:
        packet = pkt_solid_color(r, g, b)
        await self._write(packet)
        rgb = (packet[4], packet[5], packet[6])
        self._state = dataclasses.replace(self._state, rgb=rgb, mode="manual")

    async def set_warm_white(self) -> None:
        await self._write(pkt_warm_white())

    async def set_scene(self, scene: Scene) -> None:
        await self._write(pkt_scene(scene))
        self._state = dataclasses.replace(self._state, mode=f"scene:{scene.name.lower()}")

    async def set_music_mode(self, mode: MusicMode, r: int = 0, g: int = 0, b: int = 0) -> None:
        await self._write(pkt_music(mode, r, g, b))
        self._state = dataclasses.replace(self._state, mode=f"music:{mode.name.lower()}")

    async def set_gradient(self, on: bool) -> None:
        await self._write(pkt_gradient(on))

    async def set_color_temperature(self, kelvin: int) -> None:
        """Set color temperature (warm/cold white) in Kelvin."""
        await self._write(pkt_color_temperature(kelvin))
        self._state = dataclasses.replace(self._state, mode=f"color_temp:{kelvin}")

    async def set_segment(self, bulb: BulbIndex, r: int, g: int, b: int) -> None:
        await self._write(pkt_segment(bulb, r, g, b))

    async def set_segments(self, pairs: list[tuple[BulbIndex, int, int, int]]) -> None:
        for pkt in pkt_multi_segment(pairs):
            await self._write(pkt)
            await asyncio.sleep(0.05)  # pacing

    # ------------------------------------------------------------------
    # State polling
    # ------------------------------------------------------------------
    async def poll_state(self) -> H7015State:
        """Send a heartbeat and return retained state.

        The device has no readable state characteristic; any reply arrives via
        notification and is merged by ``_on_notify``.
        """
        await self._write(pkt_keepalive())
        return self._state

    def _on_notify(self, _char: object, data: bytearray) -> None:
        """Merge known fields from a notification; ACKs/unknown frames keep state."""
        if self._intentional_disconnect:
            return
        raw = bytes(data)
        LOGGER.debug("RX %s", raw.hex())
        decoded = decode_state(raw)
        previous = self._state
        self._state = dataclasses.replace(
            previous,
            power=decoded.power if decoded.power is not None else previous.power,
            brightness=(
                decoded.brightness if decoded.brightness is not None else previous.brightness
            ),
            rgb=decoded.rgb if decoded.rgb is not None else previous.rgb,
            raw=raw,
        )
        if self.state_callback and self._loop:
            task = asyncio.ensure_future(self.state_callback(self._state), loop=self._loop)
            self._notify_tasks.add(task)
            task.add_done_callback(self._notification_done)

    def _notification_done(self, task: asyncio.Future[None]) -> None:
        """Release callback tasks and report callback failures."""
        self._notify_tasks.discard(task)
        if not task.cancelled() and (error := task.exception()) is not None:
            LOGGER.error("State callback failed: %s", error)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":  # pragma: no cover
    import argparse
    import sys

    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="Govee H7015 BLE CLI")
    parser.add_argument("address", help="MAC address of the H7015")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("on")
    sub.add_parser("off")
    p_br = sub.add_parser("brightness")
    p_br.add_argument("value", type=int)
    p_col = sub.add_parser("color")
    p_col.add_argument("r", type=int)
    p_col.add_argument("g", type=int)
    p_col.add_argument("b", type=int)
    p_scene = sub.add_parser("scene")
    p_scene.add_argument("name", choices=[s.name.lower() for s in Scene])
    p_seg = sub.add_parser("segment")
    p_seg.add_argument("bulb", type=int)
    p_seg.add_argument("r", type=int)
    p_seg.add_argument("g", type=int)
    p_seg.add_argument("b", type=int)
    sub.add_parser("state")

    args = parser.parse_args()

    async def run() -> None:
        async with GoveeH7015Client(MacAddress(args.address)) as c:
            match args.cmd:
                case "on":
                    await c.power_on()
                case "off":
                    await c.power_off()
                case "brightness":
                    await c.set_brightness(args.value)
                case "color":
                    await c.set_color(args.r, args.g, args.b)
                case "scene":
                    await c.set_scene(Scene[args.name.upper()])
                case "segment":
                    await c.set_segment(args.bulb, args.r, args.g, args.b)
                case "state":
                    st = await c.poll_state()
                    print(st)
            await asyncio.sleep(0.5)

    try:
        asyncio.run(run())
    except GoveeError as exc:
        print(f"Govee error: {exc}", file=sys.stderr)
        sys.exit(1)
