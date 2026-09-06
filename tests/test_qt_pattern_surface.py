"""What the pattern window actually puts on the screen, pixel by pixel.

Everything upstream of this file is arithmetic over rectangles, and arithmetic
is worth nothing here if the last step paints something else. So Qt is driven
for real, the widget is asked to paint, and the pixels that came out are read
back and compared to the code values the pattern declared. That is the only
place in this lane where the claim "these exact values reached the panel" stops
being a claim about a model and starts being a claim about a painter.

The platform plugin is forced to offscreen, so a run never takes over the
machine's display. What that leaves synthetic is the surface. The widget, the
paint events, the key handling and the event loop are the genuine article.

Nothing here waits on a person. Every test that reaches `wait` dismisses the
window first, because a test that did not would hang until the run was killed.
"""

from __future__ import annotations

import os

import pytest

# The plugin is chosen when the application is constructed, so this has to be
# set before anything builds one. A test that opened a real fullscreen window
# would black out the machine running it.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QApplication  # noqa: E402

from calibrate_pro.adapters.qt_pattern_surface import (  # noqa: E402
    DISMISSED_BY_KEY,
    DISMISSED_BY_WINDOW,
    PatternWidget,
    QtPatternSurface,
    open_pattern_window,
)
from calibrate_pro.application.pattern_surface import PatternSurfaceUnavailable  # noqa: E402
from calibrate_pro.application.patterns import PlacedRegion, Swatch  # noqa: E402

#: Small enough to grab quickly, large enough that a region is several pixels
#: across in both directions and an off-by-one is visible rather than fatal.
WIDTH, HEIGHT = 200, 120

GREY = Swatch.grey(37)
ORANGE = Swatch(230, 120, 40)


@pytest.fixture
def app() -> QApplication:
    """The one QApplication a process is allowed, shared across the file."""
    running = QApplication.instance()
    return running if isinstance(running, QApplication) else QApplication([])


@pytest.fixture
def widget(app: QApplication) -> PatternWidget:
    del app
    window = PatternWidget()
    window.resize(WIDTH, HEIGHT)
    return window


def painted(widget: PatternWidget) -> object:
    """The image the widget paints, read back off a grab."""
    return widget.grab().toImage()


def colour_at(widget: PatternWidget, x: int, y: int) -> tuple[int, int, int]:
    image = painted(widget)
    pixel = image.pixelColor(x, y)  # type: ignore[attr-defined]
    return (pixel.red(), pixel.green(), pixel.blue())


class TestWhatIsPainted:
    """The code values, read back off the surface they were painted onto."""

    def test_a_region_is_filled_with_the_exact_value_it_declared(self, widget: PatternWidget) -> None:
        """The whole lane exists so this is true rather than nearly true.

        A patch shifted by a level or two is a defect nobody can see and every
        judgement made in front of it inherits. Reading the pixel back is the
        only way to say the painter did not resample, blend, or colour manage
        what it was handed.
        """
        widget.set_regions((PlacedRegion(0, 0, WIDTH, HEIGHT, ORANGE),))

        assert colour_at(widget, WIDTH // 2, HEIGHT // 2) == ORANGE.values

    def test_regions_are_painted_in_the_order_they_arrive(self, widget: PatternWidget) -> None:
        """The ground goes down first, so a later region covers it.

        A painter running the list backwards would leave every pattern in the
        catalogue as a flat field of its own ground, which looks deliberate and
        is not.
        """
        widget.set_regions(
            (
                PlacedRegion(0, 0, WIDTH, HEIGHT, GREY),
                PlacedRegion(50, 30, 40, 20, ORANGE),
            )
        )

        assert colour_at(widget, 60, 40) == ORANGE.values
        assert colour_at(widget, 10, 10) == GREY.values

    def test_a_region_edge_lands_on_the_pixel_it_was_given(self, widget: PatternWidget) -> None:
        """One pixel inside is the region and one pixel outside is not.

        This is the assertion the crosshatch rests on. A fill that rounded its
        rectangle outward by half a pixel would draw every line two pixels
        wide, and an operator reading a doubled line concludes their display is
        resampling when the doubling happened here.
        """
        widget.set_regions(
            (
                PlacedRegion(0, 0, WIDTH, HEIGHT, GREY),
                PlacedRegion(50, 0, 1, HEIGHT, ORANGE),
            )
        )

        assert colour_at(widget, 50, 60) == ORANGE.values
        assert colour_at(widget, 49, 60) == GREY.values
        assert colour_at(widget, 51, 60) == GREY.values

    def test_nothing_of_this_program_is_drawn_inside_the_pattern(self, widget: PatternWidget) -> None:
        """No text, no border, no cursor. A field of black is a field of black.

        A corner pixel is checked rather than a centre one because that is
        where a frame, a title, or a focus ring would land.
        """
        widget.set_regions((PlacedRegion(0, 0, WIDTH, HEIGHT, Swatch.grey(0)),))

        for x, y in [(0, 0), (WIDTH - 1, 0), (0, HEIGHT - 1), (WIDTH - 1, HEIGHT - 1)]:
            assert colour_at(widget, x, y) == (0, 0, 0)


class TestHowAnOperatorEndsIt:
    """The two ways out, and the one key that takes them."""

    def test_escape_ends_the_presentation(self, widget: PatternWidget) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeyEvent

        widget.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))

        assert widget.ended == DISMISSED_BY_KEY

    def test_another_key_does_not(self, widget: PatternWidget) -> None:
        """A pattern that vanished on a brushed keyboard would be reopened often.

        The operator is reaching across a desk for the display's own buttons
        while this is on screen, which is exactly the moment a keyboard gets
        leaned on.
        """
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeyEvent

        widget.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier))

        assert widget.ended is None

    def test_closing_the_window_ends_it_too_and_says_which_way(self, widget: PatternWidget) -> None:
        widget.close()

        assert widget.ended == DISMISSED_BY_WINDOW

    def test_the_first_reason_is_the_one_reported(self, widget: PatternWidget) -> None:
        """A window closed after Escape still ended because of the key."""
        widget.dismiss(DISMISSED_BY_KEY)
        widget.close()

        assert widget.ended == DISMISSED_BY_KEY


class TestThePortAroundTheWindow:
    """What the application layer sees, which is a port and not a widget."""

    def surface(self, app: QApplication, widget: PatternWidget) -> QtPatternSurface:
        return QtPatternSurface(window=widget, app=app, screen_name="a synthetic screen")

    def test_the_size_is_reported_in_the_panel_s_own_pixels(self, app: QApplication, widget: PatternWidget) -> None:
        """Qt lays out in logical pixels and a pattern is declared in device ones."""
        port = self.surface(app, widget)
        ratio = widget.devicePixelRatioF()

        assert port.geometry() == (round(WIDTH * ratio), round(HEIGHT * ratio))
        assert port.pixel_ratio() == ratio

    def test_presenting_returns_only_after_the_window_has_painted(
        self, app: QApplication, widget: PatternWidget
    ) -> None:
        """A call that returned before the first frame reported on nothing.

        Telling an operator to judge a pattern that has not reached the screen
        yet is worse than refusing, so present blocks on the paint counter
        rather than on the request to repaint.
        """
        widget.show()
        port = self.surface(app, widget)

        port.present((PlacedRegion(0, 0, WIDTH, HEIGHT, ORANGE),))

        assert widget.paints >= 1

    def test_waiting_returns_the_reason_the_window_ended_for(self, app: QApplication, widget: PatternWidget) -> None:
        port = self.surface(app, widget)
        widget.dismiss(DISMISSED_BY_KEY)

        assert port.wait() == DISMISSED_BY_KEY

    def test_the_identity_names_the_screen_the_window_is_on(self, app: QApplication, widget: PatternWidget) -> None:
        """A pattern judged on the wrong monitor is a judgement about nothing."""
        assert "a synthetic screen" in self.surface(app, widget).identity()

    def test_closing_twice_is_not_an_error(self, app: QApplication, widget: PatternWidget) -> None:
        """The action closes in a finally, and a caller may close as well."""
        port = self.surface(app, widget)

        port.close()
        port.close()

    def test_a_closed_port_refuses_rather_than_reporting_a_stale_size(
        self, app: QApplication, widget: PatternWidget
    ) -> None:
        """The window is gone, so every number it would report describes nothing."""
        port = self.surface(app, widget)
        port.close()

        with pytest.raises(PatternSurfaceUnavailable, match="already closed"):
            port.geometry()


class TestOpeningOne:
    """Choosing which display the window goes on, before it goes anywhere."""

    def test_a_display_this_desktop_does_not_have_is_refused_in_this_lane_s_words(self) -> None:
        """The patch window's refusal, retold as a pattern surface refusal.

        The screen selector is shared with the measurement lane, so its own
        exception type would reach the pattern action unrecognised and arrive
        as a crash instead of a refusal an operator can act on.
        """
        with pytest.raises(PatternSurfaceUnavailable):
            open_pattern_window(device_name="NO-SUCH-DISPLAY-DEVICE")
