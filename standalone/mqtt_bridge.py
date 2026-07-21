#!/usr/bin/env python3
"""
Govee H7015 -> MQTT bridge (async, aiomqtt, pydantic-validated).

Long-running daemon that exposes one or more Govee H7015 lights to Home
Assistant over MQTT, using Home Assistant's MQTT discovery protocol.

This version uses aiomqtt (pure async, no thread handoffs) and pydantic
models for runtime payload validation.

Topic layout (per device, where <mac> is the uppercased MAC without colons):

  govee/h7015/<mac>/state          JSON:  DeviceState (see models.py)
  govee/h7015/<mac>/set            JSON:  HACommandPayload (see models.py)
  govee/h7015/<mac>/availability   "online" | "offline"

Home Assistant auto-discovers the light via:
  homeassistant/light/govee_h7015_<mac>/config
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Any, Final

try:
    from aiomqtt import Client as AioMqttClient, MqttError
except ImportError:
    raise SystemExit("Please install aiomqtt:  pip install aiomqtt")

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from govee_h7015 import GoveeH7015Client, GoveeError
from models import (
    BrightnessCommand,
    ColorCommand,
    DeviceConfig,
    DeviceState,
    HADiscovery,
    MusicCommand,
    PowerCommand,
    SceneCommand,
    SegmentCommand,
    WarmCommand,
    parse_command,
)
from protocol import H7015State, MusicMode, Scene
from pydantic import AliasChoices, Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict
from govee_types import MacAddress

LOGGER = logging.getLogger("h7015_bridge")


# ---------------------------------------------------------------------------
# Config — Pydantic Settings (typed, validated, env-loaded)
# ---------------------------------------------------------------------------
class BridgeSettings(BaseSettings):
    """Bridge configuration loaded from env vars / .env file."""

    model_config = SettingsConfigDict(
        env_prefix="GOVEE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    mqtt_host: str = "127.0.0.1"
    mqtt_port: int = Field(default=1883, ge=1, le=65535)
    mqtt_user: str | None = None
    mqtt_password: str | None = None
    topic_prefix: str = "govee/h7015"
    poll_interval: int = Field(default=60, ge=0)
    reconnect_backoff: int = Field(default=5, ge=1)
    state_cache: Path | None = None
    log_level: str = "INFO"
    devices_raw: str = Field(
        default="",
        validation_alias=AliasChoices("GOVEE_DEVICES", "devices_raw"),
    )

    @property
    def devices(self) -> list[DeviceConfig]:
        result: list[DeviceConfig] = []
        for chunk in self.devices_raw.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            if "=" in chunk:
                mac, name = chunk.split("=", 1)
            else:
                mac, name = chunk, chunk
            try:
                result.append(DeviceConfig(mac=mac.strip(), name=name.strip()))
            except ValidationError as exc:
                LOGGER.error("Invalid device config %r: %s", chunk, exc)
        return result


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------
class StateCache:
    """JSON file cache so HA restores immediately after a daemon restart."""

    def __init__(self, path: Path | None) -> None:
        self.path = path

    def load(self) -> dict[str, dict[str, Any]]:
        if not self.path or not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text())
        except Exception as exc:
            LOGGER.warning("state cache unreadable: %s", exc)
            return {}

    def save(self, mac_id: str, state: dict[str, Any]) -> None:
        if not self.path:
            return
        all_state = self.load()
        if all_state.get(mac_id) == state:
            return
        all_state[mac_id] = state
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(all_state, indent=2))
        except Exception as exc:
            LOGGER.warning("state cache save failed: %s", exc)


# ---------------------------------------------------------------------------
# Per-device bridge
# ---------------------------------------------------------------------------
class DeviceBridge:
    """Bridges a single H7015 to MQTT."""

    def __init__(
        self,
        device: DeviceConfig,
        settings: BridgeSettings,
        mqtt_client: AioMqttClient,
        state_cache: StateCache,
    ) -> None:
        self.device = device
        self.settings = settings
        self.mqtt = mqtt_client
        self.state_cache = state_cache

        self.mac_id = device.device_id
        self.base_topic = f"{settings.topic_prefix}/{self.mac_id}"
        self.state_topic = f"{self.base_topic}/state"
        self.set_topic = f"{self.base_topic}/set"
        self.avail_topic = f"{self.base_topic}/availability"
        self.discovery_topic = f"homeassistant/light/govee_h7015_{self.mac_id}/config"
        self.attributes_topic = f"{self.base_topic}/attributes"
        self._client: GoveeH7015Client | None = None
        self._task: asyncio.Task[None] | None = None
        self._last_state: dict[str, Any] = {"state": "OFF"}

    # --- MQTT publishing (all async via aiomqtt) -------------------------
    async def publish_discovery(self) -> None:
        effects = [s.name.lower() for s in Scene] + [
            f"music_{m.name.lower()}" for m in MusicMode
        ]
        payload = HADiscovery(
            name=self.device.name,
            unique_id=f"govee_h7015_{self.mac_id}",
            state_topic=self.state_topic,
            command_topic=self.set_topic,
            availability_topic=self.avail_topic,
            effect_list=effects,
            json_attributes_topic=self.attributes_topic,
            device={
                "identifiers": [f"govee_h7015_{self.mac_id}"],
                "name": self.device.name,
                "manufacturer": "Govee",
                "model": "H7015 Outdoor String Lights",
                "sw_version": "reverse-engineered",
            },
        )
        await self.mqtt.publish(
            self.discovery_topic,
            payload.model_dump_json(by_alias=True),
            retain=True,
            qos=1,
        )
        LOGGER.info("[%s] published discovery", self.mac_id)

    async def publish_state(self, state: H7015State) -> None:
        payload: dict[str, Any] = {"state": "ON" if state.power else "OFF"}
        if state.brightness is not None:
            payload["brightness"] = state.brightness
        # Determine color_mode from the mode string
        if state.mode:
            if state.mode.startswith("color_temp:"):
                payload["color_mode"] = "color_temp"
                try:
                    kelvin = int(state.mode.split(":", 1)[1])
                    if kelvin > 0:
                        payload["color_temp"] = round(1000000 / kelvin)
                except (ValueError, IndexError, ZeroDivisionError):
                    pass
            elif state.mode.startswith("scene:"):
                payload["color_mode"] = "rgb"
                payload["effect"] = state.mode.split(":", 1)[1]
            elif state.mode.startswith("music:"):
                payload["color_mode"] = "rgb"
                payload["effect"] = f"music_{state.mode.split(':', 1)[1]}"
            else:
                payload["color_mode"] = "rgb"
                payload["effect"] = state.mode
        elif state.brightness is not None:
            payload["color_mode"] = "rgb"
        if state.rgb is not None and payload.get("color_mode") == "rgb":
            payload["color"] = {
                "r": state.rgb[0],
                "g": state.rgb[1],
                "b": state.rgb[2],
            }

        if payload == self._last_state:
            return
        self._last_state = payload

        # Validate before publishing — catch bad state from a malformed poll
        try:
            validated = DeviceState(**payload)
        except ValidationError as exc:
            LOGGER.warning("[%s] skipping publish of invalid state: %s", self.mac_id, exc)
            return

        await self.mqtt.publish(
            self.state_topic, validated.model_dump_json(), retain=True, qos=1
        )
        await self.mqtt.publish(
            self.attributes_topic,
            json.dumps({"raw": state.raw.hex() if state.raw else None}),
            retain=True,
            qos=1,
        )
        self.state_cache.save(self.mac_id, payload)

    async def publish_cached_state(self) -> None:
        cached = self.state_cache.load().get(self.mac_id)
        if cached:
            await self.mqtt.publish(
                self.state_topic, json.dumps(cached), retain=True, qos=1
            )
            LOGGER.info("[%s] restored cached state", self.mac_id)

    async def publish_availability(self, online: bool) -> None:
        await self.mqtt.publish(
            self.avail_topic,
            "online" if online else "offline",
            retain=True,
            qos=1,
        )

    # --- Command handling (pydantic-validated) ---------------------------
    async def handle_command(self, payload: bytes) -> None:
        try:
            cmd = parse_command(payload)
        except (ValidationError, ValueError, json.JSONDecodeError) as exc:
            LOGGER.warning("[%s] bad command payload: %s", self.mac_id, exc)
            return

        if cmd is None:
            return

        LOGGER.info("[%s] RX %s", self.mac_id, cmd)

        if not self._client:
            LOGGER.warning("[%s] not connected, dropping cmd", self.mac_id)
            return

        try:
            await self._dispatch(cmd)
            try:
                st = await self._client.poll_state()
                await self.publish_state(st)
            except Exception as exc:
                LOGGER.debug("[%s] post-cmd poll failed: %s", self.mac_id, exc)
        except GoveeError as exc:
            LOGGER.error("[%s] cmd failed: %s", self.mac_id, exc)
        except Exception:
            LOGGER.exception("[%s] cmd failed", self.mac_id)

    async def _dispatch(
        self,
        cmd: PowerCommand | BrightnessCommand | ColorCommand | SceneCommand | MusicCommand | SegmentCommand | WarmCommand,
    ) -> None:
        """Type-safe dispatch using match + class patterns."""
        if self._client is None:
            LOGGER.error("[%s] cannot dispatch — no BLE client", self.mac_id)
            return

        match cmd:
            case PowerCommand(value=v):
                await self._client.set_power(v)
            case BrightnessCommand(value=v):
                await self._client.set_brightness(v)
            case ColorCommand(r=r, g=g, b=b, brightness=br):
                await self._client.set_color(r, g, b)
                if br is not None:
                    await self._client.set_brightness(br)
            case SceneCommand(name=n):
                await self._client.set_scene(Scene[n.upper()])
            case MusicCommand(name=n):
                await self._client.set_music_mode(MusicMode[n.upper()])
            case SegmentCommand(bulb=bulb, r=r, g=g, b=b):
                await self._client.set_segment(bulb, r, g, b)
            case WarmCommand(value=v):
                await self._client.set_warm_white()

    # --- Connection lifecycle --------------------------------------------
    async def run(self) -> None:
        """Main loop: connect BLE, poll, reconnect on drop."""
        backoff = self.settings.reconnect_backoff
        while True:
            try:
                LOGGER.info("[%s] connecting BLE...", self.mac_id)
                self._client = GoveeH7015Client(
                    MacAddress(self.device.mac),
                    keepalive=True,
                    reconnect=False,
                )
                await self._client.connect()
                await self.publish_availability(True)
                try:
                    st = await self._client.poll_state()
                    await self.publish_state(st)
                except Exception as exc:
                    LOGGER.warning("[%s] initial poll failed: %s", self.mac_id, exc)

                while self._client and self._client.is_connected:
                    if self.settings.poll_interval > 0:
                        await asyncio.sleep(self.settings.poll_interval)
                        try:
                            st = await self._client.poll_state()
                            await self.publish_state(st)
                        except Exception as exc:
                            LOGGER.debug("[%s] poll failed: %s", self.mac_id, exc)
                    else:
                        await asyncio.sleep(60)
            except asyncio.CancelledError:
                LOGGER.info("[%s] cancelled", self.mac_id)
                break
            except Exception as exc:
                LOGGER.error("[%s] BLE error: %s", self.mac_id, exc)
            finally:
                await self.publish_availability(False)
                if self._client:
                    try:
                        await self._client.disconnect()
                    except Exception:
                        pass
                self._client = None
            LOGGER.info("[%s] reconnecting in %ds", self.mac_id, backoff)
            await asyncio.sleep(backoff)

    def start(self) -> asyncio.Task[None]:
        self._task = asyncio.create_task(self.run())
        return self._task

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._client:
            try:
                await self._client.disconnect()
            except Exception:
                pass
        await self.publish_availability(False)


# ---------------------------------------------------------------------------
# MQTT subscriber task (async, handles reconnect)
# ---------------------------------------------------------------------------
async def mqtt_subscriber(
    client: AioMqttClient,
    bridges: list[DeviceBridge],
    settings: BridgeSettings,
    stop_event: asyncio.Event,
) -> None:
    """Subscribe to all device command topics and dispatch messages.

    Handles MQTT broker reconnects with exponential backoff.
    Device bridges are started ONCE (outside the reconnect loop) to avoid
    creating duplicate BLE tasks on every MQTT reconnect.
    """
    bridge_by_topic = {b.set_topic: b for b in bridges}

    # Start device bridges once — they handle their own BLE reconnection
    # independently of MQTT connection state.
    for b in bridges:
        b.start()

    while not stop_event.is_set():
        try:
            async with client:
                for b in bridges:
                    await client.subscribe(b.set_topic, qos=1)
                    await b.publish_discovery()
                    await b.publish_cached_state()
                    await b.publish_availability(False)

                LOGGER.info("MQTT subscribed, listening for commands...")

                async for message in client.messages:
                    bridge = bridge_by_topic.get(str(message.topic))
                    if bridge:
                        await bridge.handle_command(message.payload)

        except MqttError as exc:
            LOGGER.error("MQTT error: %s — reconnecting in %ds", exc, settings.reconnect_backoff)
            await asyncio.sleep(settings.reconnect_backoff)
        except asyncio.CancelledError:
            break


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mqtt-host", default=None)
    p.add_argument("--mqtt-port", type=int, default=None)
    p.add_argument("--mqtt-user", default=None)
    p.add_argument("--mqtt-password", default=None)
    p.add_argument("--topic-prefix", default=None)
    p.add_argument(
        "--devices",
        default=None,
        help='MAC=Name[,MAC2=Name2,...]  e.g. "AABBCCDDEEFF=Patio"',
    )
    p.add_argument("--poll-interval", type=int, default=None)
    p.add_argument("--reconnect-backoff", type=int, default=None)
    p.add_argument("--state-cache", default=None, help="Path to state cache JSON")
    p.add_argument("--env-file", default=".env", help="Path to .env file")
    p.add_argument("--log-level", default=None, help="DEBUG / INFO / WARNING / ERROR")
    return p.parse_args(argv)


def build_settings(args: argparse.Namespace) -> BridgeSettings:
    """Construct BridgeSettings from CLI args + env vars."""
    overrides: dict[str, Any] = {}
    if args.mqtt_host is not None:
        overrides["mqtt_host"] = args.mqtt_host
    if args.mqtt_port is not None:
        overrides["mqtt_port"] = args.mqtt_port
    if args.mqtt_user is not None:
        overrides["mqtt_user"] = args.mqtt_user
    if args.mqtt_password is not None:
        overrides["mqtt_password"] = args.mqtt_password
    if args.topic_prefix is not None:
        overrides["topic_prefix"] = args.topic_prefix
    if args.devices is not None:
        overrides["devices_raw"] = args.devices
    if args.poll_interval is not None:
        overrides["poll_interval"] = args.poll_interval
    if args.reconnect_backoff is not None:
        overrides["reconnect_backoff"] = args.reconnect_backoff
    if args.state_cache is not None:
        overrides["state_cache"] = Path(args.state_cache)
    if args.log_level is not None:
        overrides["log_level"] = args.log_level
    return BridgeSettings(**overrides)


async def main_async(args: argparse.Namespace) -> int:
    if args.env_file and Path(args.env_file).exists():
        try:
            from dotenv import load_dotenv

            load_dotenv(args.env_file)
        except ImportError:
            pass

    settings = build_settings(args)

    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    devices = settings.devices
    if not devices:
        print(
            "ERROR: no devices configured. Use --devices or set "
            "GOVEE_DEVICES=MAC=Name[,MAC2=Name2]",
            file=sys.stderr,
        )
        return 2

    state_cache = StateCache(settings.state_cache)
    stop_event = asyncio.Event()

    # Signal handler
    loop = asyncio.get_running_loop()

    def _signal_handler(*_args: Any) -> None:
        LOGGER.info("shutdown signal received")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            signal.signal(sig, _signal_handler)

    # Create the MQTT client (aiomqtt — pure async, no thread handoff)
    client = AioMqttClient(
        hostname=settings.mqtt_host,
        port=settings.mqtt_port,
        username=settings.mqtt_user,
        password=settings.mqtt_password,
        identifier=f"govee-h7015-{os.getpid()}",
    )

    bridges = [
        DeviceBridge(device=d, settings=settings, mqtt_client=client, state_cache=state_cache)
        for d in devices
    ]

    LOGGER.info("Starting bridge with %d device(s).", len(bridges))

    # Run the MQTT subscriber + all device bridges concurrently.
    # Using TaskGroup so any failure cancels all others cleanly.
    subscriber_task = asyncio.create_task(
        mqtt_subscriber(client, bridges, settings, stop_event)
    )

    await stop_event.wait()

    LOGGER.info("shutting down...")
    subscriber_task.cancel()
    # Cancel all device bridges
    for b in bridges:
        await b.stop()

    try:
        async with asyncio.timeout(10):
            await subscriber_task
    except (asyncio.TimeoutError, asyncio.CancelledError):
        pass

    return 0


def main() -> int:
    args = parse_args()
    try:
        return asyncio.run(main_async(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
