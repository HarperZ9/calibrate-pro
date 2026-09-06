"""A patch window: the display's own light, put in front of the instrument.

A measurement run needs a solid colour on the screen being measured, and it
needs it on that screen rather than on whichever one Qt would have picked. A
window opened on the wrong monitor still produces a complete profile, of a
display nobody asked about, so the screen is resolved by name and position and
the run is refused when neither matches.

Two properties of the window change the numbers a colorimeter reports, so both
are decided here and both are stated in `describe`.

The first is patch size. An OLED holds a small window at full output and dims a
full white field to stay inside its power budget, so the same panel reads two
different peaks depending on how much of it was lit. A luminance is only
reproducible next to the geometry it was read at.

The second is signal depth. A widget painted through QPainter carries eight
bits per channel, so a requested level is rounded to the nearest of 256 steps
before it reaches the panel. The ramp asks for levels a sixteenth apart, which
land within a third of a step of their rounded values, and the rounding is
reported rather than hidden.

What this window does not do is clear the display's own correction. Whatever
gamma ramp and colour profile Windows currently has loaded sits between the
value painted here and the light the panel emits, so a run against a calibrated
display characterizes the display together with its calibration. Establishing
that the correction is off belongs to whoever starts the run, not to a window.

The event loop is pumped rather than run. A measurement is a straight line of
show, settle, read, and the caller drives it, so this holds no exec() of its own
and instead gives Qt the turns it needs to paint what was asked for and to
notice the operator pressing Escape.
"""

from __future__ import annotations

import math
import time
from collections.abc import Sequence
from typing import Any, Protocol, cast

from PySide6.QtCore import QEventLoop, QRect, Qt
from PySide6.QtGui import QColor, QKeyEvent, QPainter, QScreen
from PySide6.QtWidgets import QApplication, QWidget

from calibrate_pro.application.measurement import MeasurementRefused

#: Levels a channel can take once the window has painted it. A widget surface is
#: eight bits deep, so the value asked for is the value rounded to this.
SIGNAL_LEVELS = 255

#: Longest a single patch is given to reach the screen. A paint that has not
#: happened by now is a window that is not on screen, and reading the instrument
#: anyway would measure whatever was there before.
PAINT_TIMEOUT_SECONDS = 2.0

#: How long one pump of the event loop may block. Short enough that an Escape
#: press is noticed inside a settle, long enough that the pump is not a spin.
PUMP_MILLISECONDS = 20

#: Smallest patch this will open. Below it the window is narrower than a
#: colorimeter's aperture, and the reading would take in the surround.
MINIMUM_WINDOW_FRACTION = 0.01


class ScreenLike(Protocol):
    """The part of a QScreen that picking one depends on."""

    def name(self) -> str: ...

    def geometry(self) -> Any: ...


class PatchWindowUnavailable(RuntimeError):
    """No screen matched the display a run was asked to measure."""


def quantize(rgb: tuple[float, float, float]) -> tuple[int, int, int]:
    """Round a requested level to the signal the window can actually paint."""
    values = []
    for name, value in zip(("red", "green", "blue"), rgb, strict=True):
        number = float(value)
        if not math.isfinite(number) or not 0.0 <= number <= 1.0:
            raise MeasurementRefused(f"{name} was asked for at {number}, outside the signal range a display takes")
        values.append(int(round(number * SIGNAL_LEVELS)))
    return values[0], values[1], values[2]


def select_screen(
    screens: Sequence[ScreenLike],
    *,
    device_name: str | None = None,
    position: tuple[int, int] | None = None,
) -> ScreenLike:
    """Find the one screen a display was detected on, or refuse.

    Name is tried first because it is what the platform calls the device.
    Position is the fallback for a Qt build that names screens differently from
    the enumeration the display was detected through. Two screens cannot share a
    top-left corner, so a position identifies one display as exactly as a name
    does. Nothing here falls back to the primary screen: a run that quietly
    moved to another monitor would report a profile of the wrong display.
    """
    if device_name is None and position is None:
        raise PatchWindowUnavailable("a patch window needs the display it is opening on to be named")
    if not screens:
        raise PatchWindowUnavailable("this session found no screens to open a patch window on")
    if device_name is not None:
        for screen in screens:
            if screen.name() == device_name:
                return screen
    if position is not None:
        for screen in screens:
            geometry = screen.geometry()
            if (geometry.x(), geometry.y()) == position:
                return screen
    found = ", ".join(screen.name() for screen in screens)
    wanted = device_name if device_name is not None else str(position)
    raise PatchWindowUnavailable(f"no screen matched {wanted}; this session sees {found}")


def patch_rect(width: int, height: int, fraction: float) -> QRect:
    """The centred rectangle covering `fraction` of a screen's area.

    The fraction is of area rather than of a side, because area is what a
    display's power limiter responds to and what every published window size is
    quoted as.
    """
    if not math.isfinite(fraction) or not MINIMUM_WINDOW_FRACTION <= fraction <= 1.0:
        raise PatchWindowUnavailable(
            f"a patch window covering {fraction} of the screen is outside the "
            f"{MINIMUM_WINDOW_FRACTION} to 1.0 range a sensor can read"
        )
    side = math.sqrt(fraction)
    patch_width = max(1, int(round(width * side)))
    patch_height = max(1, int(round(height * side)))
    return QRect((width - patch_width) // 2, (height - patch_height) // 2, patch_width, patch_height)


def describe_geometry(fraction: float) -> str:
    """Say what was on screen, in the terms a measurement is quoted in."""
    if fraction >= 1.0:
        return "full-field patches"
    return f"{fraction * 100:.0f}% window patches on black"


class PatchWidget(QWidget):
    """The window itself: black, with one solid patch painted on it.

    The surround is painted on every pass rather than left to the platform's
    background, so a window fraction below one reads against a known black
    instead of against whatever the compositor had there.
    """

    def __init__(self, fraction: float) -> None:
        super().__init__()
        self._fraction = fraction
        self._colour = QColor(0, 0, 0)
        self.paints = 0
        self.cancelled = False
        self.setWindowTitle("Calibrate Pro measurement")
        self.setCursor(Qt.CursorShape.BlankCursor)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

    def set_signal(self, rgb: tuple[int, int, int]) -> None:
        """Take the eight-bit signal the next paint will fill the patch with."""
        self._colour = QColor(*rgb)
        self.update()

    def signal(self) -> tuple[int, int, int]:
        """What the last accepted signal was, for a caller checking the window."""
        return self._colour.red(), self._colour.green(), self._colour.blue()

    def paintEvent(self, event: Any) -> None:  # noqa: N802  (Qt names this method)
        del event
        painter = QPainter(self)
        try:
            painter.fillRect(self.rect(), QColor(0, 0, 0))
            painter.fillRect(patch_rect(self.width(), self.height(), self._fraction), self._colour)
        finally:
            painter.end()
        self.paints += 1

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802  (Qt names this method)
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled = True
        super().keyPressEvent(event)


class QtPatchPresenter:
    """A patch port backed by one fullscreen window on one named screen."""

    def __init__(self, *, window: PatchWidget, app: QApplication, fraction: float) -> None:
        self._window: PatchWidget | None = window
        self._app = app
        self._fraction = fraction

    def show(self, rgb: tuple[float, float, float]) -> None:
        """Put a colour on screen and return once it has actually painted."""
        window = self._live_window()
        before = window.paints
        window.set_signal(quantize(rgb))
        deadline = time.monotonic() + PAINT_TIMEOUT_SECONDS
        while window.paints == before:
            if time.monotonic() > deadline:
                raise MeasurementRefused(
                    f"the patch window did not paint within {PAINT_TIMEOUT_SECONDS} seconds, so the "
                    "instrument would have read whatever was on screen before it"
                )
            self._pump()
        self._raise_if_cancelled()

    def settle(self, seconds: float) -> None:
        """Wait for the panel to reach the patch, keeping the window responsive."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self._pump()
        self._raise_if_cancelled()

    def describe(self) -> str:
        """Name the patch geometry every reading in this run was taken at."""
        return describe_geometry(self._fraction)

    def close(self) -> None:
        """Take the window off the screen. A second call does nothing."""
        window, self._window = self._window, None
        if window is None:
            return
        window.close()
        self._pump()

    def _live_window(self) -> PatchWidget:
        window = self._window
        if window is None:
            raise MeasurementRefused("the patch window was already closed")
        return window

    def _raise_if_cancelled(self) -> None:
        window = self._window
        if window is not None and window.cancelled:
            raise MeasurementRefused("the operator stopped the run at the patch window")

    def _pump(self) -> None:
        self._app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, PUMP_MILLISECONDS)


def open_patch_window(
    *,
    device_name: str | None = None,
    position: tuple[int, int] | None = None,
    fraction: float = 1.0,
) -> QtPatchPresenter:
    """Open a fullscreen patch window on one display and return its port.

    This has to run on the thread that owns Qt, which is the process's main
    thread. An application already running its own Qt shell is reused rather
    than replaced, because Qt itself refuses a second QApplication in one
    process.
    """
    # Qt types its own instance() as the base application class, which has no
    # screens and no widgets. A widget shell is the only kind this module
    # opens, so the running one is read as the kind it is.
    running = QApplication.instance()
    app = cast(QApplication, running) if running is not None else QApplication([])
    screen = select_screen(app.screens(), device_name=device_name, position=position)
    geometry = screen.geometry()
    window = PatchWidget(fraction)
    window.setGeometry(geometry)
    window.show()
    handle = window.windowHandle()
    if handle is not None:
        # Placement is asked for twice on purpose. A window has no platform
        # handle until it has been shown, and the screen it sits on is only
        # settable through that handle, so the geometry is applied again once
        # the window knows which display it belongs to.
        handle.setScreen(cast(QScreen, screen))
        window.setGeometry(geometry)
    window.showFullScreen()
    window.raise_()
    window.activateWindow()
    presenter = QtPatchPresenter(window=window, app=app, fraction=fraction)
    try:
        presenter.show((0.0, 0.0, 0.0))
    except BaseException:
        # The window belongs to this function until it returns. A first paint
        # that never arrives, or an operator pressing Escape while the window
        # is opening, would otherwise leave a fullscreen black window on the
        # display with nothing left holding a reference to close it.
        presenter.close()
        raise
    return presenter


__all__ = [
    "MINIMUM_WINDOW_FRACTION",
    "PAINT_TIMEOUT_SECONDS",
    "PUMP_MILLISECONDS",
    "SIGNAL_LEVELS",
    "PatchWidget",
    "PatchWindowUnavailable",
    "QtPatchPresenter",
    "ScreenLike",
    "describe_geometry",
    "open_patch_window",
    "patch_rect",
    "quantize",
    "select_screen",
]
