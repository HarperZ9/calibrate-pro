"""Where a monitor's own controls enter the application.

DDC/CI is the one route in this product that changes the display rather than
the signal sent to it. A brightness write moves the backlight. An RGB gain
write moves the panel's own drive. Both sit upstream of every table this build
can load, so a session that changes one has changed the thing its sealed plan
was built against.

Displays implement this protocol badly, and in more than one way. A display can
report a maximum for a control it does not drive, take a write and ignore it,
or clamp it to a value of its own choosing. None of those failures raise, and
the write call returns success for all three. So nothing here treats a
successful call as a change: every value written is read back afterwards, and
the transaction reports the number the display answered with beside the number
it was asked for.

That read-back is the display's own account of its state. It is not a
measurement of light, and no result in this module says a screen got brighter.
It says a control now reads at a value.

Nothing here imports :mod:`calibrate_pro.hardware`. The port is a protocol, the
Windows source that satisfies it lives in the adapter layer, and a session with
no write route builds this module and loads no display driver.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

#: What a session reports when nothing wired a port. It names the composition
#: rather than the display, so a reader never mistakes it for a probe result.
NO_PORT_REASON = "this session was built without a monitor control port"

#: What a source reports when a display was addressed and did not answer.
NO_MONITOR_REASON = "the selected display did not answer on DDC/CI"

BRIGHTNESS = 0x10
CONTRAST = 0x12
RED_GAIN = 0x16
GREEN_GAIN = 0x18
BLUE_GAIN = 0x1A
RED_BLACK_LEVEL = 0x6C
GREEN_BLACK_LEVEL = 0x6E
BLUE_BLACK_LEVEL = 0x70

#: Writing any value to this code asks the display to restore its own factory
#: settings. It cannot be read, so a restore is reported by what the readable
#: controls said before and after rather than by a return value.
RESTORE_FACTORY_DEFAULTS = 0x04

#: The controls this build drives, and what an operator calls each one. A code
#: outside this table is reachable only through the raw read and raw write,
#: which name it by number because this build knows nothing else about it.
CONTROL_LABELS: dict[int, str] = {
    BRIGHTNESS: "Brightness",
    CONTRAST: "Contrast",
    RED_GAIN: "Red gain",
    GREEN_GAIN: "Green gain",
    BLUE_GAIN: "Blue gain",
    RED_BLACK_LEVEL: "Red black level",
    GREEN_BLACK_LEVEL: "Green black level",
    BLUE_BLACK_LEVEL: "Blue black level",
}

#: The action that stages each control. The manifest declares one action per
#: control rather than a single staging action carrying a code, so a surface
#: binds a slider to an id and the resolver answers for that control alone.
CONTROL_ACTIONS: dict[int, str] = {
    BRIGHTNESS: "ddc.stage.brightness",
    CONTRAST: "ddc.stage.contrast",
    RED_GAIN: "ddc.stage.red_gain",
    GREEN_GAIN: "ddc.stage.green_gain",
    BLUE_GAIN: "ddc.stage.blue_gain",
    RED_BLACK_LEVEL: "ddc.stage.red_black_level",
    GREEN_BLACK_LEVEL: "ddc.stage.green_black_level",
    BLUE_BLACK_LEVEL: "ddc.stage.blue_black_level",
}

#: The same map read the other way, for a session handed an action id by a
#: surface. Built from one table so the two directions cannot disagree.
STAGE_ACTION_CODES: dict[str, int] = {action_id: code for code, action_id in CONTROL_ACTIONS.items()}

#: Read in this order, so a reading lists brightness before the channel trims
#: the way the panel's own menu does.
STAGEABLE_CODES: tuple[int, ...] = tuple(CONTROL_LABELS)

#: How long a display is given to act on a write before the value is read back.
#: Panels apply a DDC write over several frames, and reading immediately
#: returns the old value on hardware that is working correctly.
SETTLE_SECONDS = 0.20


class MonitorControlUnavailable(RuntimeError):
    """No display answered, and the message names what was tried."""


class MonitorControlError(RuntimeError):
    """A display was addressed and its answer could not be trusted."""


def label_for(code: int) -> str:
    """Name one control, falling back to its number for a code this build does not know."""
    return CONTROL_LABELS.get(code, f"VCP 0x{code:02X}")


def validate_code(code: int, field: str) -> None:
    """Refuse a VCP code this build cannot address, before it reaches a driver."""
    if isinstance(code, bool) or not isinstance(code, int):
        raise MonitorControlError(f"{field} must be an exact integer")
    if code < 0 or code > 0xFF:
        raise MonitorControlError(f"{field} must fall within 0 and 255")


@dataclass(frozen=True)
class MonitorControl:
    """One control the display reported, at the value it reported it."""

    code: int
    label: str
    current: int
    maximum: int

    def __post_init__(self) -> None:
        validate_code(self.code, "code")
        if type(self.label) is not str or not self.label.strip():
            raise MonitorControlError("label must be a nonblank exact string")
        for name in ("current", "maximum"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise MonitorControlError(f"{name} must be an exact integer")
        if self.maximum < 1:
            raise MonitorControlError("a control reporting a maximum below 1 drives nothing")
        if self.current < 0 or self.current > self.maximum:
            raise MonitorControlError("current must fall within 0 and the reported maximum")

    @property
    def line(self) -> str:
        return f"{self.label}: {self.current} of {self.maximum}"


@dataclass(frozen=True)
class RefusedControl:
    """One control that was asked for and did not answer, and why."""

    code: int
    label: str
    reason: str

    def __post_init__(self) -> None:
        validate_code(self.code, "code")
        for name in ("label", "reason"):
            if type(getattr(self, name)) is not str or not getattr(self, name).strip():
                raise MonitorControlError(f"{name} must be a nonblank exact string")


@dataclass(frozen=True)
class MonitorReading:
    """What one display answered when its controls were read."""

    display_id: str
    instrument: str
    controls: tuple[MonitorControl, ...]
    refused: tuple[RefusedControl, ...]

    def __post_init__(self) -> None:
        for name in ("display_id", "instrument"):
            if type(getattr(self, name)) is not str or not getattr(self, name).strip():
                raise MonitorControlError(f"{name} must be a nonblank exact string")
        for name in ("controls", "refused"):
            if type(getattr(self, name)) is not tuple:
                raise MonitorControlError(f"{name} must be an exact tuple")
        codes = [control.code for control in self.controls]
        if len(codes) != len(set(codes)):
            raise MonitorControlError("a reading carries one entry per control")

    def control(self, code: int) -> MonitorControl | None:
        """Return what the display said about one control, or None if it said nothing."""
        for control in self.controls:
            if control.code == code:
                return control
        return None

    @property
    def codes(self) -> frozenset[int]:
        """The codes this display answered, which are the ones a value may be staged for."""
        return frozenset(control.code for control in self.controls)

    @property
    def summary(self) -> str:
        if not self.controls:
            return f"{self.instrument} answered on DDC/CI and reported none of the {len(self.refused)} controls read."
        answered = ", ".join(control.line for control in self.controls)
        line = f"{self.instrument} reported {answered}."
        if self.refused:
            line += f" {len(self.refused)} of the controls read did not answer."
        return line


class MonitorControlPort(Protocol):
    """One display's control channel, for as long as a caller holds it."""

    def identity(self) -> str: ...

    def read(self, code: int) -> tuple[int, int]: ...

    def write(self, code: int, value: int) -> None: ...

    def close(self) -> None: ...


class MonitorControlSource(Protocol):
    """Where a session gets a port, and how it answers before it has one."""

    def describe(self) -> str: ...

    def present(self) -> bool: ...

    def open(self, display_id: str) -> MonitorControlPort: ...


class NoMonitorControlSource:
    """The default source, which reports no display and opens nothing.

    A session that wired no source has proved nothing about the machine.
    Reporting a control channel it never opened would put a display's state
    behind a reading no display produced.
    """

    def __init__(self, reason: str = NO_PORT_REASON) -> None:
        if type(reason) is not str or not reason.strip():
            raise TypeError("reason must be a nonblank exact string")
        self._reason = reason

    def describe(self) -> str:
        return self._reason

    def present(self) -> bool:
        return False

    def open(self, display_id: str) -> MonitorControlPort:
        del display_id
        raise MonitorControlUnavailable(self._reason)


__all__ = [
    "BLUE_BLACK_LEVEL",
    "BLUE_GAIN",
    "BRIGHTNESS",
    "CONTRAST",
    "CONTROL_ACTIONS",
    "CONTROL_LABELS",
    "GREEN_BLACK_LEVEL",
    "GREEN_GAIN",
    "NO_MONITOR_REASON",
    "NO_PORT_REASON",
    "RED_BLACK_LEVEL",
    "RED_GAIN",
    "RESTORE_FACTORY_DEFAULTS",
    "SETTLE_SECONDS",
    "STAGEABLE_CODES",
    "STAGE_ACTION_CODES",
    "MonitorControl",
    "MonitorControlError",
    "MonitorControlPort",
    "MonitorControlSource",
    "MonitorControlUnavailable",
    "MonitorReading",
    "NoMonitorControlSource",
    "RefusedControl",
    "label_for",
    "validate_code",
]
