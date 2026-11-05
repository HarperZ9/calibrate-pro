"""The seams the closed loop drives: panel controls, a patch presenter, a clock.

The loop never imports a DDC/CI driver. It asks a `PanelControls` for the
controls a panel advertises and writes through a bounded writer that holds the
user's approval. A simulated panel implements these protocols for tests; a
real adapter must route through the confirmation coordinator and the canonical
Windows display adapter, which this slice does not wire.
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol

RGB = tuple[float, float, float]

#: MCCS VCP codes the loop knows by name.
VCP_NAMES: dict[int, str] = {
    0x10: "brightness",
    0x12: "contrast",
    0x14: "color_preset",
    0x16: "red_gain",
    0x18: "green_gain",
    0x1A: "blue_gain",
    0x6C: "red_offset",
    0x6E: "green_offset",
    0x70: "blue_offset",
    0xDC: "display_mode",
}

#: Controls the first slice of the loop may write. Contrast stays at its
#: neutral setting, because most LCDs fake it in the signal path (ArgyllCMS
#: dispcal documentation), and preset or mode changes are a separate step.
LOOP_WRITABLE = ("brightness", "red_gain", "green_gain", "blue_gain")
GAIN_NAMES = ("red_gain", "green_gain", "blue_gain")


@dataclass(frozen=True)
class ControlSpec:
    """One continuous control a panel advertises."""

    name: str
    vcp: int
    minimum: int
    maximum: int

    def __post_init__(self) -> None:
        if self.minimum >= self.maximum:
            raise ValueError(f"control {self.name} has an empty range")


class PanelControls(Protocol):
    def controls(self) -> tuple[ControlSpec, ...]: ...

    def read_control(self, name: str) -> int: ...

    def write_control(self, name: str, value: int) -> None: ...


class PatchPresenter(Protocol):
    def show(self, rgb: RGB) -> None: ...


class Clock(Protocol):
    def now(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...


class SystemClock:
    """Wall-clock time, for a real panel."""

    def now(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


class SimulatedClock:
    """A clock that only moves when asked, for simulated panels."""

    def __init__(self, start: float = 0.0) -> None:
        self._now = float(start)

    def now(self) -> float:
        return self._now

    def sleep(self, seconds: float) -> None:
        if seconds < 0.0:
            raise ValueError("cannot sleep a negative time")
        self._now += seconds


def loop_controls_from_vcp(codes: Iterable[int], maxima: Mapping[int, int]) -> tuple[ControlSpec, ...]:
    """Name the loop-writable controls a panel advertises.

    A control the panel answers on read but does not list in its capabilities
    string is left out: the loop writes only what the panel advertises.
    """
    advertised = set(codes)
    found = []
    for code, name in VCP_NAMES.items():
        if name in LOOP_WRITABLE and code in advertised and maxima.get(code, 0) > 0:
            found.append(ControlSpec(name, code, 0, int(maxima[code])))
    return tuple(found)


__all__ = [
    "GAIN_NAMES",
    "LOOP_WRITABLE",
    "VCP_NAMES",
    "Clock",
    "ControlSpec",
    "PanelControls",
    "PatchPresenter",
    "SimulatedClock",
    "SystemClock",
    "loop_controls_from_vcp",
]
