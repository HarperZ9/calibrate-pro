"""What the patch window puts on screen, and which screen it puts it on.

The window is half of a measurement. The instrument reports light and says
nothing about where the light came from, so every claim that a run measured a
particular display at a particular patch size rests on this file rather than on
the sensor.

Qt is driven for real here rather than mocked. The platform plugin is forced to
offscreen so a test run never takes over the machine's display, which leaves the
widget, the paint events and the event loop as the genuine article and only the
surface they land on synthetic.
"""

from __future__ import annotations

import os

import pytest

# The plugin is chosen when the application is constructed, so this has to be
# set before anything builds one. A test that opened a real fullscreen window
# would black out the machine running it.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from calibrate_pro.adapters.qt_patch_presenter import (  # noqa: E402
    MINIMUM_WINDOW_FRACTION,
    SIGNAL_LEVELS,
    PatchWidget,
    PatchWindowUnavailable,
    QtPatchPresenter,
    describe_geometry,
    open_patch_window,
    patch_rect,
    quantize,
    select_screen,
)
from calibrate_pro.application.measurement import MeasurementRefused, measure_characterization  # noqa: E402
from tests.test_measurement_contract import SyntheticDisplay, base_panel  # noqa: E402


class FakeGeometry:
    def __init__(self, x: int, y: int) -> None:
        self._x = x
        self._y = y

    def x(self) -> int:
        return self._x

    def y(self) -> int:
        return self._y


class FakeScreen:
    """A screen as `select_screen` sees one: a name and a corner."""

    def __init__(self, name: str, x: int, y: int) -> None:
        self._name = name
        self._geometry = FakeGeometry(x, y)

    def name(self) -> str:
        return self._name

    def geometry(self) -> FakeGeometry:
        return self._geometry


LEFT = FakeScreen(r"\\.\DISPLAY1", 0, 0)
RIGHT = FakeScreen(r"\\.\DISPLAY2", 2560, 0)


# Which screen a run opens on ------------------------------------------------


def test_the_screen_the_platform_named_is_the_screen_that_is_chosen() -> None:
    assert select_screen([LEFT, RIGHT], device_name=r"\\.\DISPLAY2") is RIGHT


def test_a_screen_whose_name_qt_spells_differently_is_still_found_by_position() -> None:
    """Qt and the Windows enumeration do not always agree on a device name."""
    chosen = select_screen([LEFT, RIGHT], device_name=r"\\.\DISPLAY9", position=(2560, 0))
    assert chosen is RIGHT


def test_a_display_that_matches_nothing_refuses_instead_of_taking_the_first_screen() -> None:
    """The false success this guards is a full profile of the wrong monitor."""
    with pytest.raises(PatchWindowUnavailable) as refusal:
        select_screen([LEFT, RIGHT], device_name=r"\\.\DISPLAY7", position=(9999, 9999))
    message = str(refusal.value)
    assert r"\\.\DISPLAY7" in message
    assert r"\\.\DISPLAY1" in message, "the refusal does not say which screens were available"


def test_opening_a_window_on_no_named_display_refuses() -> None:
    with pytest.raises(PatchWindowUnavailable) as refusal:
        select_screen([LEFT, RIGHT])
    assert "needs the display it is opening on to be named" in str(refusal.value)


def test_a_session_with_no_screens_refuses() -> None:
    with pytest.raises(PatchWindowUnavailable) as refusal:
        select_screen([], device_name=r"\\.\DISPLAY1")
    assert "no screens" in str(refusal.value)


# What the window paints ------------------------------------------------------


def test_a_requested_level_becomes_the_nearest_signal_the_surface_carries() -> None:
    assert quantize((0.0, 0.0, 0.0)) == (0, 0, 0)
    assert quantize((1.0, 1.0, 1.0)) == (SIGNAL_LEVELS, SIGNAL_LEVELS, SIGNAL_LEVELS)
    assert quantize((0.5, 0.25, 0.75)) == (128, 64, 191)


def test_a_ramp_step_lands_within_one_signal_level_of_what_was_asked_for() -> None:
    """The ramp asks for sixteenths, which no eight-bit surface holds exactly."""
    for step in range(17):
        requested = step / 16
        painted = quantize((requested, requested, requested))[0]
        assert abs(painted - requested * SIGNAL_LEVELS) <= 0.5


def test_a_level_outside_the_signal_range_refuses() -> None:
    with pytest.raises(MeasurementRefused) as refusal:
        quantize((1.5, 0.0, 0.0))
    assert "outside the signal range" in str(refusal.value)
    with pytest.raises(MeasurementRefused):
        quantize((0.0, -0.001, 0.0))
    with pytest.raises(MeasurementRefused):
        quantize((0.0, 0.0, float("nan")))


def test_a_full_field_patch_covers_the_whole_screen() -> None:
    assert patch_rect(3840, 2160, 1.0) == QRect(0, 0, 3840, 2160)


def test_a_window_patch_covers_its_share_of_the_area_and_sits_in_the_middle() -> None:
    rect = patch_rect(1000, 1000, 0.10)
    area = rect.width() * rect.height()
    assert abs(area / (1000 * 1000) - 0.10) < 0.001
    assert rect.center().x() in (499, 500)
    assert rect.center().y() in (499, 500)


def test_a_patch_smaller_than_a_sensor_aperture_refuses() -> None:
    with pytest.raises(PatchWindowUnavailable) as refusal:
        patch_rect(1000, 1000, MINIMUM_WINDOW_FRACTION / 2)
    assert "range a sensor can read" in str(refusal.value)


def test_the_geometry_is_described_in_the_terms_a_measurement_is_quoted_in() -> None:
    assert describe_geometry(1.0) == "full-field patches"
    assert describe_geometry(0.10) == "10% window patches on black"


# The window driven for real --------------------------------------------------


@pytest.fixture(scope="module")
def app() -> QApplication:
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


def _presenter(app: QApplication, fraction: float = 1.0) -> tuple[QtPatchPresenter, PatchWidget]:
    window = PatchWidget(fraction)
    window.setGeometry(QRect(0, 0, 320, 240))
    window.show()
    return QtPatchPresenter(window=window, app=app, fraction=fraction), window


def test_showing_a_patch_returns_only_after_the_window_has_painted_it(app: QApplication) -> None:
    presenter, window = _presenter(app)
    try:
        presenter.show((1.0, 0.0, 0.0))
        assert window.paints >= 1, "show returned before the window had painted anything"
        assert window.signal() == (255, 0, 0)
        painted = window.paints
        presenter.show((0.0, 1.0, 0.0))
        assert window.signal() == (0, 255, 0)
        assert window.paints > painted, "the second patch was never painted"
    finally:
        presenter.close()


def test_a_closed_window_refuses_to_show_anything_further(app: QApplication) -> None:
    presenter, _ = _presenter(app)
    presenter.show((0.0, 0.0, 0.0))
    presenter.close()
    presenter.close()
    with pytest.raises(MeasurementRefused) as refusal:
        presenter.show((1.0, 1.0, 1.0))
    assert "already closed" in str(refusal.value)


def test_an_operator_pressing_escape_stops_the_run(app: QApplication) -> None:
    presenter, window = _presenter(app)
    try:
        presenter.show((0.5, 0.5, 0.5))
        window.cancelled = True
        with pytest.raises(MeasurementRefused) as refusal:
            presenter.show((1.0, 1.0, 1.0))
        assert "operator stopped the run" in str(refusal.value)
    finally:
        presenter.close()


def test_the_presenter_reports_the_geometry_it_was_opened_at(app: QApplication) -> None:
    presenter, _ = _presenter(app, fraction=0.10)
    try:
        assert presenter.describe() == "10% window patches on black"
    finally:
        presenter.close()


def test_opening_a_window_on_a_screen_this_session_does_not_have_refuses(app: QApplication) -> None:
    del app
    with pytest.raises(PatchWindowUnavailable):
        open_patch_window(device_name=r"\\.\DISPLAY-THAT-IS-NOT-HERE", position=(-99999, -99999))


# False-success controls ------------------------------------------------------


class NeverPaints:
    """A window that accepts a signal and never puts it on screen."""

    paints = 0
    cancelled = False

    def set_signal(self, rgb: tuple[int, int, int]) -> None:
        del rgb


class IdleApp:
    """An application whose event loop has nothing to deliver."""

    def processEvents(self, *args: object) -> None:  # noqa: N802  (Qt names this method)
        del args


def test_a_window_that_never_paints_refuses_rather_than_letting_a_reading_stand(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without this the instrument reads whatever was on screen before the run."""
    monkeypatch.setattr("calibrate_pro.adapters.qt_patch_presenter.PAINT_TIMEOUT_SECONDS", 0.05)
    presenter = QtPatchPresenter(window=NeverPaints(), app=IdleApp(), fraction=1.0)  # type: ignore[arg-type]
    with pytest.raises(MeasurementRefused) as refusal:
        presenter.show((1.0, 1.0, 1.0))
    assert "did not paint" in str(refusal.value)


# The whole loop, through the real window -------------------------------------


class WindowReadingInstrument:
    """An instrument that reads the signal the real window is showing.

    The display arithmetic is synthetic and the window is not. Reading the
    window rather than the requested colour is what makes this a test of the
    presenter: a patch that never reached the screen reads as the patch before
    it, and the profile that comes out says so.
    """

    def __init__(self, display: SyntheticDisplay, window: PatchWidget) -> None:
        self._display = display
        self._window = window

    def identity(self) -> str:
        return self._display.identity()

    def read(self) -> object:
        red, green, blue = self._window.signal()
        self._display.show((red / SIGNAL_LEVELS, green / SIGNAL_LEVELS, blue / SIGNAL_LEVELS))
        return self._display.read()


def test_a_run_through_the_real_window_recovers_the_display_behind_it(app: QApplication) -> None:
    presenter, window = _presenter(app)
    display = SyntheticDisplay(white_luminance=250.0, black_luminance=0.05, gamma=(2.20, 2.24, 2.18))
    try:
        result = measure_characterization(
            instrument=WindowReadingInstrument(display, window),  # type: ignore[arg-type]
            patches=presenter,
            base=base_panel(),
            steps=17,
            settle=lambda: presenter.settle(0.0),
        )
    finally:
        presenter.close()
    assert result.patch_count == 68
    assert window.paints >= 68, "some patches were read without ever reaching the screen"
    assert result.patch_geometry == "full-field patches"
    assert abs(result.white_luminance - 250.05) < 1.0
    for measured, expected in zip(result.gamma, (2.20, 2.24, 2.18), strict=True):
        assert abs(measured - expected) < 0.03
