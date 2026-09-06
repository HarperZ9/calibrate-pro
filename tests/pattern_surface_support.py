"""A pattern surface that reports its geometry and remembers what it was given.

A pattern window is judged by a person, so nothing about this lane can be
checked by looking at a return value from the thing that painted. What can be
checked is the arithmetic in front of the window: which rectangles were handed
over, in what order, at what size, and what the surface said about itself
before any of them were painted.

So this fake holds the two facts a real surface reports and no more. The size
in device pixels and the ratio between those and the logical pixels a window is
laid out in are both readable from inside a process, and both change what a
pattern is allowed to claim. Whether the desktop is applying a colour transform
is not readable from inside a process, so nothing here offers to answer it.

The regions handed over are kept rather than counted. A count would pass while
a pattern tiled a surface with a seam down the middle, and the seam is the
defect this lane has to be able to see.
"""

from __future__ import annotations

from pathlib import Path

from calibrate_pro.application.composition import _engine_and_generator, _runner, load_fake_display
from calibrate_pro.application.detection import DeniedCapabilityProbe, DisplayDetector
from calibrate_pro.application.journal import DiagnosticJournal
from calibrate_pro.application.pattern_surface import (
    PatternSurfacePort,
    PatternSurfaceUnavailable,
)
from calibrate_pro.application.patterns import PlacedRegion
from calibrate_pro.application.service import FunctionalRecoveryService
from calibrate_pro.application.session import SessionState
from calibrate_pro.panels.database import get_database
from tests.session_support import ENUMERATOR_NAME

#: What the fake surface calls itself. Distinct from any display name, so a
#: test reading a printed summary can tell the surface from the panel.
SURFACE = "fake pattern surface"

#: How a fake surface says the operator ended it, unless a test says otherwise.
DISMISSED = "the operator closed it"

#: The size the fake reports when a test is not about geometry. Larger than the
#: catalogue's minimum in both directions, and not a round multiple of the
#: crosshatch pitch, so a layout that only tiles on convenient numbers fails.
DEFAULT_PIXELS = (1920, 1080)


class FakeSurface:
    """One open surface, holding what it reported and what it was handed."""

    def __init__(
        self,
        *,
        device_pixels: tuple[int, int] = DEFAULT_PIXELS,
        pixel_ratio: float = 1.0,
        ended: str = DISMISSED,
        identity: str = SURFACE,
    ) -> None:
        self._device_pixels = device_pixels
        self._pixel_ratio = pixel_ratio
        self._ended = ended
        self._identity = identity
        #: Every set of regions presented, in order. A second entry means the
        #: lane painted twice, which no pattern in this build asks for.
        self.presented: list[tuple[PlacedRegion, ...]] = []
        self.waits = 0
        self.closes = 0

    def identity(self) -> str:
        return self._identity

    def geometry(self) -> tuple[int, int]:
        return self._device_pixels

    def pixel_ratio(self) -> float:
        return self._pixel_ratio

    def present(self, regions: tuple[PlacedRegion, ...]) -> None:
        self.presented.append(tuple(regions))

    def wait(self) -> str:
        self.waits += 1
        return self._ended

    def close(self) -> None:
        self.closes += 1

    @property
    def regions(self) -> tuple[PlacedRegion, ...]:
        """The regions of the single presentation, or a failure naming the count."""
        if len(self.presented) != 1:
            raise AssertionError(f"the surface was presented to {len(self.presented)} times, not once")
        return self.presented[0]


class FakeSurfaceSource:
    """Where the session gets the fake surface, and how it answers without one.

    The display id the session asked for is kept, because a pattern opened on
    the wrong monitor is a judgement made about a display nobody selected and
    nothing downstream of the window could notice that.
    """

    def __init__(
        self,
        surface: FakeSurface | None = None,
        *,
        reason: str = "no fake pattern surface was wired",
    ) -> None:
        self._surface = surface
        self._reason = reason
        self.opened: list[str] = []

    def describe(self) -> str:
        return SURFACE if self._surface is not None else self._reason

    def present(self) -> bool:
        return self._surface is not None

    def open(self, display_id: str) -> PatternSurfacePort:
        self.opened.append(display_id)
        if self._surface is None:
            raise PatternSurfaceUnavailable(self._reason)
        return self._surface


def build_pattern_service(
    root: Path,
    source: FakeSurfaceSource | None = None,
) -> FunctionalRecoveryService:
    """The session a terminal drives, with the pattern surface wired to a fake.

    Passing no source leaves the route unwired, which is the session a machine
    with no window toolkit gets and the one the resolver has to decline. The
    capability probe stays closed either way: a pattern needs no capability off
    the panel, and a probe that answered would let a passing gate be read as
    proof of something this lane never asks about.
    """
    display = load_fake_display()
    state = SessionState()
    journal = DiagnosticJournal(root / "diagnostics")
    database = get_database()
    engine, generator = _engine_and_generator(database)
    detector = DisplayDetector(
        enumerator=lambda: (display,),
        capability_probe=DeniedCapabilityProbe("no capability is probed under test"),
        database=database,
        enumerator_name=ENUMERATOR_NAME,
    )
    return FunctionalRecoveryService(
        state=state,
        runner=_runner(state, journal),
        detector=detector,
        generator=generator,
        engine=engine,
        patterns=source,
    )


__all__ = [
    "DEFAULT_PIXELS",
    "DISMISSED",
    "SURFACE",
    "FakeSurface",
    "FakeSurfaceSource",
    "build_pattern_service",
]
