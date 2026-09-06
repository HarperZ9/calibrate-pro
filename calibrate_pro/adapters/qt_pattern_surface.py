"""A pattern window: exact code values, held on one display until dismissed.

This is the patch window's sibling and it is built from the same parts. The
screen is resolved by name and position rather than left to Qt, because a
pattern shown on the wrong monitor is a judgement made about a display nobody
asked about. The window is frameless, always on top, and carries no cursor, so
nothing of this program's own is inside the area being judged.

Where the two differ is what they are for. A patch window shows one colour to an
instrument and the caller drives it. A pattern window shows a set of rectangles
to a person and waits, because the operator is turning a knob on the display
while it is on screen and a call that returned before then would be reporting on
a window nobody had looked at.

Everything about the painting is chosen for exactness. Antialiasing is off,
nothing is interpolated, no text is drawn, and every rectangle is filled with a
flat eight-bit colour. On a scaled display the painter is scaled by exactly the
inverse of the device pixel ratio, so a rectangle declared in device pixels
lands on those device pixels rather than near them. Windows scaling factors are
quarters, which invert without rounding.

What this window cannot establish is whether the desktop is applying a colour
transform between these values and the cable. That fact is reported as
unestablished by the qualification the caller builds from this port, and it is
not guessed at here.
"""

from __future__ import annotations

import time
from typing import Any, cast

from PySide6.QtCore import QEventLoop, QRect, Qt
from PySide6.QtGui import QCloseEvent, QColor, QKeyEvent, QPainter, QScreen
from PySide6.QtWidgets import QApplication, QWidget

from calibrate_pro.adapters.qt_patch_presenter import (
    PUMP_MILLISECONDS,
    PatchWindowUnavailable,
    select_screen,
)
from calibrate_pro.application.pattern_surface import (
    PatternSurfacePort,
    PatternSurfaceUnavailable,
)
from calibrate_pro.application.patterns import PlacedRegion

#: How the window says it ended, once for each way an operator can end it.
DISMISSED_BY_KEY = "the operator closed it"
DISMISSED_BY_WINDOW = "the window was closed"

#: Longest the first frame is given to reach the screen. A window that has not
#: painted is not showing the pattern, and telling an operator to judge one that
#: is not there would be worse than refusing.
PAINT_TIMEOUT_SECONDS = 2.0


class PatternWidget(QWidget):
    """The window itself: flat rectangles, painted in the order they arrive.

    The first region a pattern places covers the whole surface, so a repaint
    always writes every pixel it was given before it writes anything on top.
    Nothing here checks that, because a window is the wrong place to be
    checking a pattern: the model guarantees it, and this paints what it is
    handed.
    """

    def __init__(self) -> None:
        super().__init__()
        self._regions: tuple[PlacedRegion, ...] = ()
        self.paints = 0
        self.ended: str | None = None
        self.setWindowTitle("Calibrate Pro test pattern")
        self.setCursor(Qt.CursorShape.BlankCursor)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

    def set_regions(self, regions: tuple[PlacedRegion, ...]) -> None:
        """Take the rectangles the next paint will fill, in device pixels."""
        self._regions = tuple(regions)
        self.update()

    def dismiss(self, reason: str) -> None:
        """End the presentation, keeping the first reason it ended for."""
        if self.ended is None:
            self.ended = reason

    def paintEvent(self, event: Any) -> None:  # noqa: N802  (Qt names this method)
        del event
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
            ratio = self.devicePixelRatioF()
            if ratio != 1.0:
                # The regions are in device pixels and QPainter works in
                # logical ones. Scaling by the exact inverse maps one to the
                # other with no rounding, which is the only way a bar declared
                # at a pixel boundary lands on that boundary.
                painter.scale(1.0 / ratio, 1.0 / ratio)
            for region in self._regions:
                painter.fillRect(
                    QRect(region.x, region.y, region.width, region.height),
                    QColor(region.swatch.red, region.swatch.green, region.swatch.blue),
                )
        finally:
            painter.end()
        self.paints += 1

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802  (Qt names this method)
        # Escape alone, rather than any key. An operator judging a near-black
        # step is reaching across a desk for the display's own buttons, and a
        # pattern that vanished on a brushed keyboard would have to be opened
        # again from the beginning.
        if event.key() == Qt.Key.Key_Escape:
            self.dismiss(DISMISSED_BY_KEY)
        super().keyPressEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802  (Qt names this method)
        self.dismiss(DISMISSED_BY_WINDOW)
        super().closeEvent(event)


class QtPatternSurface:
    """A pattern port backed by one fullscreen window on one named screen."""

    def __init__(self, *, window: PatternWidget, app: QApplication, screen_name: str) -> None:
        self._window: PatternWidget | None = window
        self._app = app
        self._screen_name = screen_name

    def identity(self) -> str:
        return f"a fullscreen window on {self._screen_name}"

    def geometry(self) -> tuple[int, int]:
        """The window's size in the panel's own pixels.

        Qt lays a window out in logical pixels and backs it with a surface the
        device pixel ratio larger. A pattern is declared in the larger of the
        two, because that is the grid the panel actually has.
        """
        window = self._live_window()
        ratio = window.devicePixelRatioF()
        return (round(window.width() * ratio), round(window.height() * ratio))

    def pixel_ratio(self) -> float:
        return self._live_window().devicePixelRatioF()

    def present(self, regions: tuple[PlacedRegion, ...]) -> None:
        """Put the pattern on screen and return once it has actually painted."""
        window = self._live_window()
        before = window.paints
        window.set_regions(regions)
        deadline = time.monotonic() + PAINT_TIMEOUT_SECONDS
        while window.paints == before:
            if time.monotonic() > deadline:
                raise PatternSurfaceUnavailable(
                    f"the pattern window did not paint within {PAINT_TIMEOUT_SECONDS} seconds, "
                    "so there is nothing on screen to judge"
                )
            self._pump()

    def wait(self) -> str:
        """Hold the pattern on screen until the operator ends it.

        The event loop is pumped rather than entered. A nested exec() inside a
        running Qt shell takes over that shell's loop, and this window has to
        be able to open from a GUI as well as from a terminal.
        """
        window = self._live_window()
        while window.ended is None:
            self._pump()
        return window.ended

    def close(self) -> None:
        """Take the window off the screen. A second call does nothing."""
        window, self._window = self._window, None
        if window is None:
            return
        window.close()
        self._pump()

    def _live_window(self) -> PatternWidget:
        window = self._window
        if window is None:
            raise PatternSurfaceUnavailable("the pattern window was already closed")
        return window

    def _pump(self) -> None:
        self._app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, PUMP_MILLISECONDS)


def open_pattern_window(
    *,
    device_name: str | None = None,
    position: tuple[int, int] | None = None,
) -> QtPatternSurface:
    """Open a fullscreen pattern window on one display and return its port.

    This has to run on the thread that owns Qt, which is the process's main
    thread. An application already running its own Qt shell is reused rather
    than replaced, because Qt refuses a second QApplication in one process.
    """
    running = QApplication.instance()
    app = cast(QApplication, running) if running is not None else QApplication([])
    try:
        screen = select_screen(app.screens(), device_name=device_name, position=position)
    except PatchWindowUnavailable as exc:
        raise PatternSurfaceUnavailable(str(exc)) from exc
    geometry = screen.geometry()
    window = PatternWidget()
    window.setGeometry(geometry)
    window.show()
    handle = window.windowHandle()
    if handle is not None:
        # Asked for twice, for the reason the patch window asks twice. A window
        # has no platform handle until it has been shown, and the screen it
        # sits on is only settable through that handle.
        handle.setScreen(cast(QScreen, screen))
        window.setGeometry(geometry)
    window.showFullScreen()
    window.raise_()
    window.activateWindow()
    return QtPatternSurface(window=window, app=app, screen_name=screen.name())


__all__ = [
    "DISMISSED_BY_KEY",
    "DISMISSED_BY_WINDOW",
    "PAINT_TIMEOUT_SECONDS",
    "PatternWidget",
    "QtPatternSurface",
    "open_pattern_window",
]


def _port_is_the_protocol(port: QtPatternSurface) -> PatternSurfacePort:
    """Hold the adapter to the port the application layer declared."""
    return port
