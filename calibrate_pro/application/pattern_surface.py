"""What a surface has to establish before a pattern shown on it means anything.

A pattern is a set of exact code values. Putting one on screen claims those
values reached the panel, and on a modern desktop that claim is not free. The
compositor may be scaling the window, in which case a bar declared at code 12
arrives as a blend of 12 and whatever it sat next to. The operating system may
be applying a colour transform to the desktop, in which case every value in the
pattern is being rewritten between this process and the cable.

So a surface reports what it established rather than asserting it is clean. Two
facts are established from inside the process. The window's size in device
pixels is known, and the ratio between device pixels and the logical pixels the
window was laid out in is known: a ratio of one means the surface is not being
resampled on its way to the panel. One fact is not establishable from here at
all. Whether Windows is applying a display colour transform is a property of the
compositor, and a process that guessed would be substituting a guess for a
measurement in exactly the place this product refuses to.

That is why ``colour_management`` is held as ``None`` and reported as a fact
this build did not establish. Reporting it as false would be the same defect as
reporting a control value from a write call's return: an answer nobody got.

One pattern in the catalogue is refused outright when the ratio is not one. The
crosshatch exists to show a line one pixel wide, and a scaled surface cannot
carry one. Offering it anyway would hand the operator a blurred grid and let
them conclude their display resamples, when the resampling happened in this
program.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from calibrate_pro.application.patterns import Pattern, PlacedRegion

#: What a session with no surface wired says when asked for one.
NO_SURFACE_REASON = "no pattern surface was wired into this session"

#: What the pixel ratio has to read for a pattern to reach the panel unresampled.
UNSCALED_RATIO = 1.0


class PatternSurfaceUnavailable(RuntimeError):
    """No surface could be opened, and the message names what was tried."""


class PatternSurfaceError(RuntimeError):
    """A surface opened and cannot carry the pattern it was asked for."""


@dataclass(frozen=True)
class SurfaceQualification:
    """What a surface established about itself, and what it could not.

    Held separately from the presentation so a caller can ask what a surface
    would be able to claim before anything is put on screen.
    """

    display_id: str
    surface: str
    device_pixels: tuple[int, int]
    pixel_ratio: float
    #: Whether the desktop is applying a colour transform, which no process can
    #: establish about itself. Always ``None``, and reported as unestablished.
    colour_management: bool | None = None

    def __post_init__(self) -> None:
        for name in ("display_id", "surface"):
            value = getattr(self, name)
            if type(value) is not str or not value.strip():
                raise PatternSurfaceError(f"{name} must be a nonblank exact string")
        width, height = self.device_pixels
        for value, name in ((width, "width"), (height, "height")):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise PatternSurfaceError(f"the surface reported a {name} of {value!r}, which no window has")
        if isinstance(self.pixel_ratio, bool) or not isinstance(self.pixel_ratio, int | float):
            raise PatternSurfaceError("pixel_ratio must be a number")
        if self.pixel_ratio <= 0:
            raise PatternSurfaceError("a surface reporting a pixel ratio at or below zero has no geometry")

    @property
    def one_to_one(self) -> bool:
        """Whether one pixel in the pattern is one pixel on the panel."""
        return self.pixel_ratio == UNSCALED_RATIO

    @property
    def unestablished(self) -> tuple[str, ...]:
        """The facts this surface could not settle, in the words a report uses.

        These travel with every presentation rather than being printed once,
        because an operator reading a pattern is about to change a panel control
        on the strength of it.
        """
        limits = [
            "Whether the desktop is applying a colour transform was not established. "
            "A process cannot read that about itself, so the values below are what "
            "this program sent rather than what reached the panel."
        ]
        if not self.one_to_one:
            limits.append(
                f"The surface is scaled at {self.pixel_ratio:g}, so each value is resampled "
                f"before it reaches the panel and structure narrower than {self.pixel_ratio:g} "
                f"pixels cannot be shown."
            )
        return tuple(limits)

    @property
    def summary(self) -> str:
        width, height = self.device_pixels
        scaling = "unscaled" if self.one_to_one else f"scaled at {self.pixel_ratio:g}"
        return f"{self.surface} on {self.display_id}, {width} by {height} device pixels, {scaling}."


@dataclass(frozen=True)
class PatternPresentation:
    """One pattern that was put on screen, and what could be said about it."""

    pattern_id: str
    name: str
    decision: str
    look_for: str
    qualification: SurfaceQualification
    regions: int
    ended: str

    @property
    def limits(self) -> tuple[str, ...]:
        return self.qualification.unestablished

    @property
    def summary(self) -> str:
        return f"{self.name} shown on {self.qualification.display_id}, and {self.ended}."


class PatternSurfacePort(Protocol):
    """One window a pattern is painted into, for as long as a caller holds it."""

    def identity(self) -> str: ...

    def geometry(self) -> tuple[int, int]: ...

    def pixel_ratio(self) -> float: ...

    def present(self, regions: tuple[PlacedRegion, ...]) -> None: ...

    def wait(self) -> str: ...

    def close(self) -> None: ...


class PatternSurfaceSource(Protocol):
    """Where a session gets a surface, and how it answers before it has one."""

    def describe(self) -> str: ...

    def present(self) -> bool: ...

    def open(self, display_id: str) -> PatternSurfacePort: ...


class NoPatternSurfaceSource:
    """The default source, which reports no surface and opens nothing.

    A session with no surface wired has proved nothing about the machine, and a
    pattern reported as shown on a window that was never opened would be a
    claim about a screen nobody looked at.
    """

    def __init__(self, reason: str = NO_SURFACE_REASON) -> None:
        if type(reason) is not str or not reason.strip():
            raise TypeError("reason must be a nonblank exact string")
        self._reason = reason

    def describe(self) -> str:
        return self._reason

    def present(self) -> bool:
        return False

    def open(self, display_id: str) -> PatternSurfacePort:
        del display_id
        raise PatternSurfaceUnavailable(self._reason)


def qualify(port: PatternSurfacePort, display_id: str) -> SurfaceQualification:
    """Ask an open surface what it can establish about itself."""
    return SurfaceQualification(
        display_id=display_id,
        surface=port.identity(),
        device_pixels=port.geometry(),
        pixel_ratio=port.pixel_ratio(),
    )


def show_pattern(
    port: PatternSurfacePort,
    display_id: str,
    pattern: Pattern,
) -> PatternPresentation:
    """Lay a pattern out for one open surface, paint it, and hold it there.

    The surface is qualified before the pattern is laid out, so a window too
    small or too scaled to carry the pattern is refused with nothing painted
    rather than after the operator has already looked at it.
    """
    qualification = qualify(port, display_id)
    if pattern.exact_pixels and not qualification.one_to_one:
        raise PatternSurfaceError(
            f"{pattern.name} asks for structure one pixel wide, and this surface is "
            f"scaled at {qualification.pixel_ratio:g}. Set the display to 100% scaling "
            f"in Windows display settings, or choose a pattern with no pixel-level structure."
        )
    width, height = qualification.device_pixels
    regions = pattern.place(width, height)
    port.present(regions)
    ended = port.wait()
    return PatternPresentation(
        pattern_id=pattern.pattern_id,
        name=pattern.name,
        decision=pattern.decision,
        look_for=pattern.look_for,
        qualification=qualification,
        regions=len(regions),
        ended=ended,
    )


__all__ = [
    "NO_SURFACE_REASON",
    "UNSCALED_RATIO",
    "NoPatternSurfaceSource",
    "PatternPresentation",
    "PatternSurfaceError",
    "PatternSurfacePort",
    "PatternSurfaceSource",
    "PatternSurfaceUnavailable",
    "SurfaceQualification",
    "qualify",
    "show_pattern",
]
