"""Pydantic models for HA MQTT payloads and device state.

These give us runtime validation of incoming JSON (bad payloads are rejected
with a clear error instead of causing a KeyError deep in the bridge) and
type-safe access to fields (mypy knows the shape of every payload).
"""

from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Color
# ---------------------------------------------------------------------------
class HAColor(BaseModel):
    """HA's nested color object."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    r: int = Field(ge=0, le=255)
    g: int = Field(ge=0, le=255)
    b: int = Field(ge=0, le=255)


# ---------------------------------------------------------------------------
# Discriminated union of our explicit commands (has "cmd" field)
# ---------------------------------------------------------------------------
class PowerCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cmd: Literal["power"] = "power"
    value: bool = True


class BrightnessCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cmd: Literal["brightness"] = "brightness"
    value: int = Field(ge=0, le=100)


class ColorCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cmd: Literal["color"] = "color"
    r: int = Field(ge=0, le=255)
    g: int = Field(ge=0, le=255)
    b: int = Field(ge=0, le=255)
    brightness: int | None = Field(default=None, ge=0, le=100)


class SceneCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cmd: Literal["scene"] = "scene"
    name: str


class MusicCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cmd: Literal["music"] = "music"
    name: str


class WarmCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cmd: Literal["warm"] = "warm"
    value: int = Field(default=255, ge=0, le=255)


class SegmentCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cmd: Literal["segment"] = "segment"
    bulb: int = Field(ge=0, le=14)
    r: int = Field(ge=0, le=255)
    g: int = Field(ge=0, le=255)
    b: int = Field(ge=0, le=255)


# ---------------------------------------------------------------------------
# HA's native MQTT JSON light payload (no "cmd" field — HA sends state/
# brightness/color/effect directly)
# ---------------------------------------------------------------------------
class HANativePayload(BaseModel):
    """HA's native MQTT JSON light command payload.

    HA sends a subset of these fields per command. We normalize to one of
    the explicit command types above via to_command().
    """

    model_config = ConfigDict(extra="ignore")

    state: Literal["ON", "OFF"] | None = None
    brightness: int | None = Field(default=None, ge=0, le=255)
    color: HAColor | None = None
    effect: str | None = None

    def to_command(
        self,
    ) -> PowerCommand | BrightnessCommand | ColorCommand | SceneCommand | MusicCommand | None:
        """Normalize HA's native payload to one of our explicit commands.

        Returns None if the payload is empty (no actionable fields).
        """
        # Effect takes precedence
        if self.effect is not None:
            name = self.effect
            if name.startswith("music_"):
                return MusicCommand(name=name[len("music_") :])
            return SceneCommand(name=name)

        # Color command (optionally with brightness)
        if self.color is not None:
            return ColorCommand(
                r=self.color.r,
                g=self.color.g,
                b=self.color.b,
                brightness=(
                    int(self.brightness * 100 / 255) if self.brightness is not None else None
                ),
            )

        # Brightness-only command
        if self.brightness is not None:
            return BrightnessCommand(value=int(self.brightness * 100 / 255))

        # Power-only command
        if self.state is not None:
            return PowerCommand(value=self.state == "ON")

        return None


# ---------------------------------------------------------------------------
# Device state (published to the state topic)
# ---------------------------------------------------------------------------
class DeviceState(BaseModel):
    """State published to HA's MQTT state topic."""

    model_config = ConfigDict(extra="forbid")

    state: Literal["ON", "OFF"]
    brightness: int | None = Field(default=None, ge=0, le=100)
    color_mode: Literal["rgb"] | None = None
    color: HAColor | None = None
    effect: str | None = None


# ---------------------------------------------------------------------------
# Device configuration
# ---------------------------------------------------------------------------
class DeviceConfig(BaseModel):
    """A single H7015 device entry (MAC + friendly name)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mac: str
    name: str

    @field_validator("mac")
    @classmethod
    def _validate_mac(cls, v: str) -> str:
        v = v.strip().upper().replace("-", ":")
        if ":" not in v and len(v) == 12:
            v = ":".join(v[i : i + 2] for i in range(0, 12, 2))
        if not re.match(r"^[A-F0-9]{2}([:][A-F0-9]{2}){5}$", v):
            raise ValueError(f"invalid MAC address: {v!r}")
        return v

    @property
    def device_id(self) -> str:
        """Uppercased MAC without colons — used as HA device identifier."""
        return self.mac.replace(":", "").upper()


# ---------------------------------------------------------------------------
# Discovery payload
# ---------------------------------------------------------------------------
class HADiscovery(BaseModel):
    """MQTT discovery payload for HA auto-discovery."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: str
    unique_id: str
    state_topic: str
    command_topic: str
    availability_topic: str
    schema_: Literal["json"] = Field(default="json", alias="schema")
    brightness: bool = True
    brightness_scale: int = 100
    color_mode: bool = True
    supported_color_modes: list[str] = ["rgb"]
    effect: bool = True
    effect_list: list[str]
    json_attributes_topic: str
    availability_mode: str = "latest"


# ---------------------------------------------------------------------------
# Parsing entry point
# ---------------------------------------------------------------------------
# Union of all explicit command types (for type annotations)
type Command = (
    PowerCommand
    | BrightnessCommand
    | ColorCommand
    | SceneCommand
    | MusicCommand
    | WarmCommand
    | SegmentCommand
)


def parse_command(payload: bytes) -> Command | None:
    """Parse a raw MQTT payload into a typed command.

    Returns None for empty payloads. Raises ValidationError on malformed JSON
    or out-of-range values.
    """
    data = json.loads(payload.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object, got {type(data).__name__}")

    if not data:
        return None

    # If it has a "cmd" field, parse as an explicit command.
    if "cmd" in data:
        cmd_type = data["cmd"]
        match cmd_type:
            case "power":
                return PowerCommand(**data)
            case "brightness":
                return BrightnessCommand(**data)
            case "color":
                return ColorCommand(**data)
            case "scene":
                return SceneCommand(**data)
            case "music":
                return MusicCommand(**data)
            case "warm":
                return WarmCommand(**data)
            case "segment":
                return SegmentCommand(**data)
            case _:
                raise ValueError(f"unknown cmd: {cmd_type!r}")

    # Otherwise, parse as HA-native and normalize.
    native = HANativePayload(**data)
    return native.to_command()


__all__ = [
    "BrightnessCommand",
    "ColorCommand",
    "Command",
    "DeviceConfig",
    "DeviceState",
    "HAColor",
    "HADiscovery",
    "HANativePayload",
    "MusicCommand",
    "PowerCommand",
    "SceneCommand",
    "SegmentCommand",
    "WarmCommand",
    "parse_command",
]
