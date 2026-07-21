"""Exception hierarchy for the Govee H7015 integration.

A specific exception type lets callers (HA coordinator, MQTT bridge)
handle different failure modes differently — e.g. retry on connection
errors but give up on protocol errors.
"""

from __future__ import annotations


class GoveeError(Exception):
    """Base class for all Govee H7015 errors."""


class GoveeConnectionError(GoveeError):
    """BLE connection failed or was lost."""


class GoveeTimeoutError(GoveeConnectionError):
    """A BLE operation timed out."""


class GoveeProtocolError(GoveeError):
    """The device returned a malformed or unexpected response."""


class GoveeChecksumError(GoveeProtocolError):
    """A packet's checksum did not match its payload."""


class GoveeInvalidArgumentError(GoveeError):
    """Caller passed an out-of-range value (e.g. bulb index 15)."""


__all__ = [
    "GoveeChecksumError",
    "GoveeConnectionError",
    "GoveeError",
    "GoveeInvalidArgumentError",
    "GoveeProtocolError",
    "GoveeTimeoutError",
]
