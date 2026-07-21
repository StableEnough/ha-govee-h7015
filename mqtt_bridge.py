#!/usr/bin/env python3
"""
Govee H7015 -> MQTT bridge.

Long-running daemon that exposes one or more Govee H7015 lights to Home
Assistant over MQTT, using Home Assistant's MQTT discovery protocol so the
lights appear automatically in the HA UI.

Topic layout (per device, where <mac> is the uppercased MAC without colons):

  govee/h7015/<mac>/state          JSON:  {"state":"ON","brightness":50,
                                           "color":{"r":255,"g":0,"b":0},
                                           "mode":"manual"}
  govee/h7015/<mac>/set            JSON:  {"cmd":"power","value":true}
                                           {"cmd":"brightness","value":50}
                                           {"cmd":"color","r":255,"g":0,"b":0}
                                           {"cmd":"scene","name":"rainbow"}
                                           {"cmd":"segment","bulb":0,"r":255,"g":0,"b":0}
  govee/h7015/<mac>/availability   "online" | "offline"

Home Assistant will auto-discover the light via the discovery topic:
  homeassistant/light/govee_h7015_<mac>/config

Configuration via environment variables (or .env file):

  GOVEE_MQTT_HOST           (default: 127.0.0.1)
  GOVEE_MQTT_PORT           (default: 1883)
  GOVEE_MQTT_USER           (optional)
  GOVEE_MQTT_PASSWORD       (optional)
  GOVEE_MQTT_TOPIC_PREFIX   (default: govee/h7015)
  GOVEE_DEVICES             MAC=Name,MAC2=Name2
                              e.g. "AABBCCDDEEFF=Patio,112233445566=Garden"
  GOVEE_POLL_INTERVAL       (default: 60 seconds; 0 = disable)
  GOVEE_RECONNECT_BACKOFF   (default: 5 seconds)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
from dataclasses import dataclass, field
from typing import Optional

try:
    import paho.mqtt.client as mqtt
except ImportError:
    raise SystemExit("Please install paho-mqtt:  pip install paho-mqtt")

from govee_h7015 import (
    GoveeH7015Client,
    H7015State,
    Scene,
    MusicMode,
    LOGGER as PROTO_LOGGER,
)


LOGGER = logging.getLogger("h7015_bridge")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
@dataclass
class BridgeConfig:
    mqtt_host: str = os.getenv("GOVEE_MQTT_HOST", "127.0.0.1")
    mqtt_port: int = int(os.getenv("GOVEE_MQTT_PORT", "1883"))
    mqtt_user: Optional[str] = os.getenv("GOVEE_MQTT_USER")
    mqtt_password: Optional[str] = os.getenv("GOVEE_MQTT_PASSWORD")
    topic_prefix: str = os.getenv("GOVEE_MQTT_TOPIC_PREFIX", "govee/h7015")
    devices: list[tuple[str, str]] = field(default_factory=list)
    poll_interval: int = int(os.getenv("GOVEE_POLL_INTERVAL", "60"))
    reconnect_backoff: int = int(os.getenv("GOVEE_RECONNECT_BACKOFF", "5"))

    @classmethod
    def from_env(cls) -> "BridgeConfig":
        raw = os.getenv("GOVEE_DEVICES", "")
        devices: list[tuple[str, str]] = []
        for chunk in raw.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            if "=" in chunk:
                mac, name = chunk.split("=", 1)
            else:
                mac, name = chunk, chunk
            devices.append((mac.strip(), name.strip()))
        if not devices:
            LOGGER.warning(
                "GOVEE_DEVICES is empty. Set it to MAC=Name[,MAC2=Name2,...]"
            )
        return cls(devices=devices)


# ---------------------------------------------------------------------------
# Per-device bridge
# ---------------------------------------------------------------------------
class DeviceBridge:
    def __init__(
        self,
        mac: str,
        name: str,
        cfg: BridgeConfig,
        mqtt_client: mqtt.Client,
    ) -> None:
        self.mac = mac
        self.mac_id = mac.replace(":", "").upper()
        self.name = name
        self.cfg = cfg
        self.mqtt = mqtt_client

        self.base_topic = f"{cfg.topic_prefix}/{self.mac_id}"
        self.state_topic = f"{self.base_topic}/state"
        self.set_topic = f"{self.base_topic}/set"
        self.avail_topic = f"{self.base_topic}/availability"
        self.discovery_topic = f"homeassistant/light/govee_h7015_{self.mac_id}/config"

        self._client: Optional[GoveeH7015Client] = None
        self._task: Optional[asyncio.Task] = None
        self._state_lock = asyncio.Lock()
        self._last_state: dict = {"state": "OFF"}

    # --- MQTT plumbing ----------------------------------------------------
    def publish_discovery(self) -> None:
        payload = {
            "name": self.name,
            "unique_id": f"govee_h7015_{self.mac_id}",
            "state_topic": self.state_topic,
            "command_topic": self.set_topic,
            "availability_topic": self.avail_topic,
            "schema": "json",
            "brightness": True,
            "brightness_scale": 100,
            "color_mode": True,
            "supported_color_modes": ["rgb"],
            "effect": True,
            "effect_list": [s.name.lower() for s in Scene]
            + [f"music_{m.name.lower()}" for m in MusicMode],
            "json_attributes_topic": f"{self.base_topic}/attributes",
            "device": {
                "identifiers": [f"govee_h7015_{self.mac_id}"],
                "name": self.name,
                "manufacturer": "Govee",
                "model": "H7015 Outdoor String Lights",
                "sw_version": "reverse-engineered",
            },
        }
        self.mqtt.publish(
            self.discovery_topic, json.dumps(payload), retain=True, qos=1
        )
        LOGGER.info("[%s] published discovery", self.mac_id)

    def publish_state(self, state: H7015State) -> None:
        payload: dict = {"state": "ON" if state.power else "OFF"}
        if state.brightness is not None:
            payload["brightness"] = state.brightness
            payload["color_mode"] = "rgb"
        if state.rgb is not None:
            payload["color"] = {
                "r": state.rgb[0],
                "g": state.rgb[1],
                "b": state.rgb[2],
            }
        if state.mode:
            payload["effect"] = state.mode
        # Always include availability + last-update stamp
        self._last_state = payload
        self.mqtt.publish(
            self.state_topic, json.dumps(payload), retain=True, qos=1
        )
        self.mqtt.publish(
            f"{self.base_topic}/attributes",
            json.dumps({"raw": state.raw.hex() if state.raw else None}),
            retain=True,
            qos=1,
        )

    def publish_availability(self, online: bool) -> None:
        self.mqtt.publish(
            self.avail_topic, "online" if online else "offline", retain=True, qos=1
        )

    # --- Command handling -------------------------------------------------
    async def _handle_command(self, payload: bytes) -> None:
        try:
            data = json.loads(payload.decode("utf-8"))
        except Exception as exc:
            LOGGER.warning("[%s] bad JSON: %s", self.mac_id, exc)
            return
        LOGGER.info("[%s] RX cmd: %s", self.mac_id, data)

        if not self._client:
            LOGGER.warning("[%s] not connected, dropping cmd", self.mac_id)
            return

        try:
            cmd = data.get("cmd") or self._infer_cmd(data)
            if cmd == "power":
                await self._client.set_power(bool(data["value"]))
            elif cmd == "brightness":
                await self._client.set_brightness(int(data["value"]))
            elif cmd == "color":
                # Home Assistant sends {r,g,b}; HA also sends state+brightness
                # together when using the color picker, so apply both.
                await self._client.set_color(
                    int(data["r"]), int(data["g"]), int(data["b"])
                )
                if "brightness" in data:
                    await self._client.set_brightness(int(data["brightness"]))
            elif cmd == "scene":
                await self._client.set_scene(Scene[str(data["name"]).upper()])
            elif cmd == "music":
                mode = MusicMode[str(data["name"]).upper()]
                await self._client.set_music_mode(mode)
            elif cmd == "segment":
                await self._client.set_segment(
                    int(data["bulb"]),
                    int(data["r"]),
                    int(data["g"]),
                    int(data["b"]),
                )
            elif cmd == "warm":
                await self._client.set_warm_white(255)
            else:
                LOGGER.warning("[%s] unknown cmd: %s", self.mac_id, cmd)
            # Best-effort state publish
            await self._client.poll_state()
        except Exception as exc:
            LOGGER.exception("[%s] cmd failed: %s", self.mac_id, exc)

    @staticmethod
    def _infer_cmd(data: dict) -> str:
        """HA MQTT JSON light sends {state, brightness, color, effect}."""
        if "effect" in data:
            name = data["effect"]
            if name.startswith("music_"):
                return "music"
            return "scene"
        if "color" in data:
            return "color"
        if "brightness" in data and "state" in data:
            return "brightness"
        if "state" in data:
            return "power"
        if "brightness" in data:
            return "brightness"
        raise ValueError(f"cannot infer cmd from {data}")

    def on_mqtt_message(self, _client, _userdata, msg) -> None:
        if msg.topic != self.set_topic:
            return
        # Hand off to the device's event loop
        if self._task and not self._task.done():
            asyncio.run_coroutine_threadsafe(
                self._handle_command(msg.payload), self._loop
            )

    # --- Connection lifecycle --------------------------------------------
    async def _run(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        backoff = self.cfg.reconnect_backoff
        while True:
            try:
                LOGGER.info("[%s] connecting BLE...", self.mac_id)
                self._client = GoveeH7015Client(
                    self.mac,
                    keepalive=True,
                    reconnect=False,
                    state_callback=self.publish_state,
                )
                await self._client.connect()
                self.publish_availability(True)
                # Initial state sync
                try:
                    st = await self._client.poll_state()
                    self.publish_state(st)
                except Exception as exc:
                    LOGGER.warning("[%s] initial poll failed: %s", self.mac_id, exc)

                # Optional periodic polling (catches state changes made via
                # the Govee app or physical button).
                while self._client and self._client.is_connected:
                    if self.cfg.poll_interval > 0:
                        await asyncio.sleep(self.cfg.poll_interval)
                        try:
                            st = await self._client.poll_state()
                            self.publish_state(st)
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
                self.publish_availability(False)
                if self._client:
                    try:
                        await self._client.disconnect()
                    except Exception:
                        pass
                self._client = None
            LOGGER.info("[%s] reconnecting in %ds", self.mac_id, backoff)
            await asyncio.sleep(backoff)

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self._task = loop.create_task(self._run(loop))

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
        self.publish_availability(False)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
async def main_async() -> int:
    logging.basicConfig(
        level=os.getenv("GOVEE_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if logging.getLogger().level <= logging.DEBUG:
        PROTO_LOGGER.setLevel(logging.DEBUG)

    cfg = BridgeConfig.from_env()
    if not cfg.devices:
        print(
            "ERROR: no devices configured. Set GOVEE_DEVICES=MAC=Name[,MAC2=Name2]",
            file=sys.stderr,
        )
        return 2

    # MQTT client
    mqtt_client = mqtt.Client(client_id=f"govee-h7015-{os.getpid()}")
    if cfg.mqtt_user:
        mqtt_client.username_pw_set(cfg.mqtt_user, cfg.mqtt_password)
    mqtt_client.loop_start()
    try:
        mqtt_client.connect(cfg.mqtt_host, cfg.mqtt_port, keepalive=60)
    except Exception as exc:
        LOGGER.error("MQTT connect failed: %s", exc)
        return 3

    # Per-device bridges
    bridges = [
        DeviceBridge(mac, name, cfg, mqtt_client) for mac, name in cfg.devices
    ]

    loop = asyncio.get_event_loop()

    # Subscribe to each device's set topic
    def on_message(_client, _userdata, msg):
        # Find the matching bridge and dispatch
        for b in bridges:
            if msg.topic == b.set_topic:
                b.on_mqtt_message(_client, _userdata, msg)
                return

    mqtt_client.on_message = on_message
    for b in bridges:
        mqtt_client.subscribe(b.set_topic, qos=1)
        b.publish_discovery()
        b.publish_availability(False)
        b.start(loop)

    LOGGER.info("Bridge running with %d device(s). Ctrl-C to stop.", len(bridges))

    # Wait for shutdown signal
    stop_event = asyncio.Event()

    def _signal_handler(*_):
        LOGGER.info("shutdown signal received")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Windows fallback
            signal.signal(sig, _signal_handler)

    await stop_event.wait()

    LOGGER.info("shutting down...")
    await asyncio.gather(*[b.stop() for b in bridges], return_exceptions=True)
    mqtt_client.loop_stop()
    mqtt_client.disconnect()
    return 0


def main() -> int:
    try:
        return asyncio.run(main_async())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
