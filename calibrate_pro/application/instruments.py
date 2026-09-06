"""Where an instrument reading enters the application.

A colorimeter is the only thing in this product that can answer what a display
actually emitted. Everything else models, predicts, or replays. This module is
the one seam between the two, and it exists so that a MEASURED evidence kind is
attached to a number a device produced.

The port answers what the sensor sees right now. It is not told what was on
screen, because an instrument does not know that: it reports the light in front
of it, and pairing that light with a requested patch is the measurement run's
job. Keeping the pairing outside the port is what stops a caller from asking
the port to vouch for a patch it never saw.

Detection and connection are separate calls on purpose. `available_instruments`
enumerates USB descriptors and opens no device session, so the read-only
capability probe can use it. `open_instrument` opens a session and runs the
device's own dark calibration, which is a physical action with a cost, so a
caller asks for it by name.

Nothing here imports `calibrate_pro.hardware` at module scope. The shipped
read-only session builds with this module loaded and must still be able to
report that no USB driver was ever pulled into its process.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

from calibrate_pro.application.detection import CapabilityUnavailable
from calibrate_pro.panels.detection import DisplayInfo

#: What a session reports when nothing wired a port. It names the composition
#: rather than the machine, so a reader never mistakes it for a probe result.
NO_PORT_REASON = "this session was built without an instrument port"

#: What the USB source reports when enumeration ran and answered nothing. It
#: names what was searched, so the operator knows the search happened.
NO_DEVICE_REASON = "no supported colorimeter answered on USB"

#: Largest tristimulus value a reading may carry, in cd/m2 for Y. A real panel
#: tops out far below this. The bound exists so a driver returning a garbage
#: word is refused at the boundary rather than travelling into a report.
MAXIMUM_TRISTIMULUS = 100_000.0


class InstrumentUnavailable(RuntimeError):
    """No instrument answered, and the message names what was tried."""


class InstrumentError(RuntimeError):
    """An instrument was open and its reading could not be trusted."""


@dataclass(frozen=True)
class InstrumentReading:
    """One tristimulus reading and the device that produced it.

    Every field is validated here rather than at a call site. A reading that
    reaches a report carries a MEASURED evidence kind, so the boundary that
    admits it is the last place a malformed number can be caught.
    """

    #: The device as it identified itself, model and serial where the driver
    #: gave one. This travels into the receipt, so it is a device string and
    #: never a description of the session.
    instrument: str
    xyz: tuple[float, float, float]
    integration_seconds: float

    def __post_init__(self) -> None:
        if type(self.instrument) is not str or not self.instrument.strip():
            raise InstrumentError("instrument must be a nonblank exact string")
        if type(self.xyz) is not tuple or len(self.xyz) != 3:
            raise InstrumentError("xyz must be a three-value tuple")
        for value in self.xyz:
            if isinstance(value, bool) or not isinstance(value, float):
                raise InstrumentError("xyz values must be exact floats")
            if not math.isfinite(value):
                raise InstrumentError("xyz values must be finite")
            if value < 0.0 or value > MAXIMUM_TRISTIMULUS:
                raise InstrumentError(f"xyz values must fall within 0 and {MAXIMUM_TRISTIMULUS}")
        if isinstance(self.integration_seconds, bool) or not isinstance(self.integration_seconds, float):
            raise InstrumentError("integration_seconds must be an exact float")
        if not math.isfinite(self.integration_seconds) or self.integration_seconds < 0.0:
            raise InstrumentError("integration_seconds must be a finite non-negative float")

    @property
    def luminance(self) -> float:
        """Report Y, which is luminance in cd/m2 for an absolute reading."""
        return self.xyz[1]


class InstrumentPort(Protocol):
    """One open instrument, for as long as a caller holds it."""

    def identity(self) -> str: ...

    def read(self) -> InstrumentReading: ...

    def close(self) -> None: ...


class InstrumentSource(Protocol):
    """Where a session gets a port, and how it answers before it has one."""

    def describe(self) -> str: ...

    def present(self) -> bool: ...

    def open(self) -> InstrumentPort: ...


class NoInstrumentSource:
    """The default source, which reports no device and opens nothing.

    A session that has not wired a source has proved nothing about the machine.
    Reporting an instrument it never looked for would put a measured evidence
    claim behind a reading that no device produced.
    """

    def __init__(self, reason: str = NO_PORT_REASON) -> None:
        if type(reason) is not str or not reason.strip():
            raise TypeError("reason must be a nonblank exact string")
        self._reason = reason

    def describe(self) -> str:
        return self._reason

    def present(self) -> bool:
        return False

    def open(self) -> InstrumentPort:
        raise InstrumentUnavailable(self._reason)


class ConnectedInstrument:
    """A port over one connected colorimeter driver.

    The driver is whatever `calibrate_pro.hardware` connected. This wrapper
    holds it, converts one measurement into a validated reading, and closes the
    session once. A driver that answers None is a refusal and not a black
    reading, so it raises rather than returning zeros.
    """

    def __init__(self, driver: object, identity: str) -> None:
        if type(identity) is not str or not identity.strip():
            raise TypeError("identity must be a nonblank exact string")
        self._driver = driver
        self._identity = identity
        self._open = True

    def identity(self) -> str:
        return self._identity

    def read(self) -> InstrumentReading:
        if not self._open:
            raise InstrumentError("this instrument session is already closed")
        measure = getattr(self._driver, "measure_spot", None)
        if not callable(measure):
            raise InstrumentError("the connected driver exposes no spot measurement")
        measurement = measure()
        if measurement is None:
            raise InstrumentError("the instrument returned no measurement")
        return InstrumentReading(
            instrument=self._identity,
            xyz=_tristimulus(measurement),
            integration_seconds=_integration_seconds(measurement),
        )

    def close(self) -> None:
        if not self._open:
            return
        self._open = False
        disconnect = getattr(self._driver, "disconnect", None)
        if callable(disconnect):
            disconnect()


def _tristimulus(measurement: object) -> tuple[float, float, float]:
    """Read X, Y and Z off a driver measurement, refusing anything else."""
    values = []
    for name in ("X", "Y", "Z"):
        value = getattr(measurement, name, None)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise InstrumentError(f"the instrument measurement carries no numeric {name}")
        values.append(float(value))
    return (values[0], values[1], values[2])


def _integration_seconds(measurement: object) -> float:
    """Read the integration time, treating an absent one as unreported."""
    value = getattr(measurement, "integration_time", None)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    seconds = float(value)
    if not math.isfinite(seconds) or seconds < 0.0:
        return 0.0
    return seconds


def _device_identity(device: object) -> str:
    """Name one enumerated device by model and serial where a driver gave one."""
    model = str(getattr(device, "model", "") or getattr(device, "name", "") or "").strip()
    serial = str(getattr(device, "serial", "") or "").strip()
    if not model:
        model = "unidentified colorimeter"
    return f"{model} ({serial})" if serial else model


def available_instruments() -> tuple[str, ...]:
    """Name every colorimeter USB enumeration answered with.

    Enumeration reads descriptors and opens no device session, which is what
    lets the read-only capability probe call this. A backend that is missing or
    that raises answers an empty tuple, because an unanswered question is not a
    device.
    """
    try:
        from calibrate_pro.hardware.native_backend import detect_colorimeters
    except Exception:
        return ()
    try:
        devices = detect_colorimeters()
    except Exception:
        return ()
    if not isinstance(devices, list):
        return ()
    return tuple(_device_identity(device) for device in devices)


def usb_instrument_present(display: DisplayInfo) -> bool:
    """Answer the sensor capability from USB enumeration alone.

    The display is unused. A colorimeter is not attached to one display, and
    the capability contract asks one question per display, so the same answer
    is correct for every display on the machine.
    """
    del display
    found = available_instruments()
    if not found:
        raise CapabilityUnavailable(NO_DEVICE_REASON)
    return True


class UsbInstrumentSource:
    """Open the first colorimeter this machine answers with.

    `calibrate_pro.hardware` is imported inside the method bodies. Importing it
    at module scope would pull a USB driver into the shipped read-only session,
    whose whole claim is that no such module was ever loaded in its process.
    """

    def __init__(self, *, dark_calibrate: bool = True) -> None:
        self._dark_calibrate = bool(dark_calibrate)

    def describe(self) -> str:
        found = available_instruments()
        return found[0] if found else NO_DEVICE_REASON

    def present(self) -> bool:
        return bool(available_instruments())

    def open(self) -> InstrumentPort:
        found = available_instruments()
        if not found:
            raise InstrumentUnavailable(NO_DEVICE_REASON)
        try:
            from calibrate_pro.hardware.native_backend import NativeBackend
        except Exception as exc:
            raise InstrumentUnavailable(f"the native USB backend could not be loaded: {exc}") from exc
        backend = NativeBackend()
        if not backend.connect(0):
            raise InstrumentUnavailable(f"{found[0]} was enumerated and would not open a session")
        if self._dark_calibrate and not backend.calibrate_device():
            backend.disconnect()
            raise InstrumentUnavailable(f"{found[0]} refused its own dark calibration")
        return ConnectedInstrument(backend, found[0])


__all__ = [
    "MAXIMUM_TRISTIMULUS",
    "NO_DEVICE_REASON",
    "NO_PORT_REASON",
    "ConnectedInstrument",
    "InstrumentError",
    "InstrumentPort",
    "InstrumentReading",
    "InstrumentSource",
    "InstrumentUnavailable",
    "NoInstrumentSource",
    "UsbInstrumentSource",
    "available_instruments",
    "usb_instrument_present",
]
