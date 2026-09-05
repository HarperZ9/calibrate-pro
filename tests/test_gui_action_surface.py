"""What the active window offers, proved by driving the real one.

The window renders every menu entry, tray entry, and the dashboard's primary
button from the session's own resolver. That claim is only worth anything if
the window is built and used, so these tests construct the real one against the
fake-acceptance composition: it reads a bundled fixture, writes only inside the
directory it is given, and reaches no display and no operator journal.

Three properties are being held down. A control offers what the session would
actually perform, the status line names files that exist, and every card
describes the display the session observed rather than one the page looked up
for itself.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from calibrate_pro.application.outcomes import ActionSuccess
from calibrate_pro.workflow import CalibrationMethod, WorkflowStage
from tests.fake_acceptance_support import MANIFEST_NAME, PRESET_ID, journal_records

CUBE_EXPORT = ".cube (Resolve / dwm_lut)"
CALIBRATE_ALL = "&Calibrate All"

#: What the bundled fixture display resolves to once the session has adopted it.
FIXTURE_LABEL = "Display - FAKE-ACCEPTANCE-PANEL"
FIXTURE_PANEL_KEY = "PG27UCDM"


def _unreachable(*args: object, **kwargs: object) -> None:
    raise AssertionError("the window reached a hardware boundary")


@pytest.fixture
def window(qapp: object, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[object]:
    """Build the active window around a session that touches no hardware."""
    from calibrate_pro.application.composition import build_fake_acceptance_service
    from calibrate_pro.gui import app as gui_app
    from calibrate_pro.gui.app import CalibrateProWindow
    from calibrate_pro.hardware.ddc_ci import DDCCIController
    from calibrate_pro.hardware.i1d3_native import I1D3Driver
    from calibrate_pro.utils.startup_manager import StartupManager

    # Background services are the one part of this window that legitimately
    # reaches the machine, and they are stubbed out. What the window does after
    # that is held to the session: the enumerators below are wired to fail, so a
    # page that reads a display for itself fails every test in this file.
    monkeypatch.setattr(gui_app, "qt_display_snapshots", _unreachable)
    monkeypatch.setattr(I1D3Driver, "find_devices", _unreachable)
    monkeypatch.setattr(DDCCIController, "enumerate_monitors", _unreachable)
    monkeypatch.setattr(StartupManager, "__init__", _unreachable)

    recorded: list[tuple[str, str]] = []
    monkeypatch.setattr(CalibrateProWindow, "_start_services", lambda self: None)
    monkeypatch.setattr(CalibrateProWindow, "_check_first_run", lambda self: None)
    monkeypatch.setattr(
        CalibrateProWindow,
        "show_toast",
        lambda self, message, level="info": recorded.append((message, level)),
    )
    root = tmp_path / "session"
    built = CalibrateProWindow(service=build_fake_acceptance_service(root))
    built.toasts = recorded
    built.session_root = root
    try:
        yield built
    finally:
        built.close()


def entries(window: object) -> dict[str, object]:
    """Every menu and tray entry the window built, by the text it shows."""
    from PySide6.QtGui import QAction

    return {action.text(): action for action in window.findChildren(QAction)}


def drive_to_save_report(service: object) -> None:
    """Walk the session to the stage where there is something to publish."""
    steps = (
        service.detect,
        lambda: service.select_method(CalibrationMethod.SENSORLESS),
        lambda: service.set_target(PRESET_ID),
        service.generate,
        service.preview,
        service.confirm_plan,
        service.apply_confirmed_plan,
        service.verify,
    )
    for step in steps:
        outcome = step()
        assert isinstance(outcome, ActionSuccess), f"the session stopped at {outcome}"
    assert service.stage is WorkflowStage.SAVE_REPORT


def test_the_window_opens_on_a_session_it_has_already_detected(window: object) -> None:
    """Startup detection runs through the session before anything is rendered.

    Without it the menu would describe a session nothing had looked at, and
    every stage-dependent entry would answer from an empty state rather than
    from what the pass observed. The stage is past DETECT because the pass found
    a display and adopted it, which is the observation the menu then renders.
    """
    assert window.service.stage is WorkflowStage.METHOD
    performed = [record["action_id"] for record in journal_records(window.session_root)]
    assert performed == ["display.detect"]


def test_an_action_the_session_hides_is_removed_from_every_surface(window: object) -> None:
    """Calibrate All is hidden by manifest instruction, so it is not shown.

    Rendering it greyed out would still advertise a workflow this build does
    not have. The button stays in the layout because it anchors the header row,
    and it is hidden rather than merely disabled.
    """
    assert not entries(window)[CALIBRATE_ALL].isVisible()
    assert window.dashboard.calibrate_all_btn.isHidden()


def test_an_export_is_offered_only_once_there_is_something_to_export(window: object) -> None:
    entry = entries(window)[CUBE_EXPORT]
    assert not entry.isEnabled()
    assert entry.toolTip()

    drive_to_save_report(window.service)
    window._binder.refresh()

    assert entry.isEnabled()
    # An enabled entry carries no explanation. Qt answers an empty tooltip with
    # the entry's own text, so the absence of a reason reads as the label.
    assert entry.toolTip() == CUBE_EXPORT


def test_using_the_export_entry_writes_the_files_the_status_line_names(
    window: object,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The whole point of the pass: a reported export is an export that ran.

    The old handler showed a save dialog and then reported the chosen name
    without writing to it. Here the reported directory is read back off disk and
    the manifest named in the status line is one of the files in it.
    """
    from calibrate_pro.gui import app as gui_app

    drive_to_save_report(window.service)
    window._binder.refresh()

    destination = tmp_path / "exports"
    monkeypatch.setattr(
        gui_app.QFileDialog,
        "getExistingDirectory",
        staticmethod(lambda *args, **kwargs: str(destination)),
    )
    entries(window)[CUBE_EXPORT].trigger()

    written = destination / "cube"
    names = sorted(path.name for path in written.iterdir())
    assert MANIFEST_NAME in names
    assert any(name.endswith(".cube") for name in names)

    status = window._status.text()
    assert str(written) in status
    assert MANIFEST_NAME in status
    assert window.toasts == []


def test_withdrawing_from_the_export_dialog_reports_nothing_and_writes_nothing(
    window: object,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Closing the dialog is not a refusal, so it is not explained as one."""
    from calibrate_pro.gui import app as gui_app

    drive_to_save_report(window.service)
    window._binder.refresh()
    monkeypatch.setattr(
        gui_app.QFileDialog,
        "getExistingDirectory",
        staticmethod(lambda *args, **kwargs: ""),
    )

    before = window._status.text()
    entries(window)[CUBE_EXPORT].trigger()

    assert window._status.text() == before
    assert window.toasts == []
    assert sorted(path.name for path in tmp_path.iterdir()) == ["session"]


def test_an_export_rendered_before_the_state_moved_is_refused_on_use(
    window: object,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The session decides at the moment of use, not at the moment of drawing.

    A control is rendered from an answer that can go stale: here the entry is
    drawn while an export exists, and the session is then moved back so there is
    nothing to publish. Using the still-enabled entry is refused in the session's
    own words, and nothing is written.
    """
    from calibrate_pro.gui import app as gui_app

    drive_to_save_report(window.service)
    window._binder.refresh()
    entry = entries(window)[CUBE_EXPORT]
    assert entry.isEnabled()

    assert isinstance(window.service.detect(), ActionSuccess)
    assert entry.isEnabled(), "the stale render is the situation under test"

    destination = tmp_path / "exports"
    monkeypatch.setattr(
        gui_app.QFileDialog,
        "getExistingDirectory",
        staticmethod(lambda *args, **kwargs: str(destination)),
    )
    entry.trigger()

    assert not destination.exists()
    assert [level for _message, level in window.toasts] == ["warning"]
    assert window.toasts[0][0]
    # The refusal is also rendered, so the entry stops offering what it cannot do.
    assert not entry.isEnabled()


def labels(window: object, object_name: str) -> list[str]:
    """Every label of one kind the window is currently showing, in order."""
    from PySide6.QtWidgets import QLabel

    return [label.text() for label in window.findChildren(QLabel, object_name)]


def stat_value(window: object, name: str) -> str:
    """Read what one dashboard stat currently says."""
    return getattr(window.dashboard, name)._value_label.text()


def test_a_card_describes_the_display_the_session_observed(window: object) -> None:
    """The card is built from the detection pass, down to the refresh rate.

    The page used to enumerate displays itself on a timer, so a card could
    describe hardware that no action had looked at and no journal entry covered.
    The only reading in this process is the startup pass, and the card carries
    its label, its geometry, and the panel record that pass matched.
    """
    assert labels(window, "displayNameLabel") == [FIXTURE_LABEL]

    detail = labels(window, "displayDetailLabel")[0]
    assert "3840x2160 @ 60 Hz" in detail
    assert f"Panel {FIXTURE_PANEL_KEY}" in detail
    assert "Peak luminance: Not measured" in detail


def test_a_card_claims_no_measurement_a_detection_pass_cannot_make(window: object) -> None:
    """Detection reads geometry and capability. It never reads light.

    Every colorimetric field on the card says so, and the HDR line reports that
    the switch went unread rather than rendering an unanswered query as SDR.
    """
    from calibrate_pro.gui.app import GamutBar

    assert labels(window, "displayStatusLabel") == ["Calibration: Not measured · HDR: not read"]

    bar = window.findChild(GamutBar)
    assert bar is not None
    assert [metric.value for metric in (bar._srgb, bar._p3, bar._bt2020)] == [None, None, None]


def test_the_sensor_row_reports_the_pass_rather_than_opening_the_device(window: object) -> None:
    """The fixture pass found no colorimeter, so the page offers no live readout.

    Opening the device here to recover a product name would put a second,
    unjournaled instrument read behind a label the session never produced.
    """
    from calibrate_pro.gui.app import LiveSensorCard, SensorCard

    assert window.findChild(SensorCard) is not None
    assert window.findChild(LiveSensorCard) is None
    assert stat_value(window, "_stat_sensor") == "Not detected"


def test_the_window_reports_services_the_page_is_not_allowed_to_read(window: object) -> None:
    """Guard and startup state come from the window, never from a repaint.

    Constructing a StartupManager creates the application config directory, so
    a page that read it while drawing would write to the filesystem on every
    redraw. This window's services never started, and both stats say so.
    """
    assert stat_value(window, "_stat_guard") == "Inactive"
    assert stat_value(window, "_stat_startup") == "Not read"


def test_a_refused_detection_leaves_the_last_observation_standing(
    window: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pass that did not happen does not get to change what the page shows.

    Refresh is bound to the detection action and the page is repainted only from
    a success, so a refusal leaves the card describing the last pass that ran
    instead of clearing it to a state nothing observed. The refusal stands in
    for any detector the session turns down; it is a real one the session
    produced, not a hand-built error object.
    """
    from calibrate_pro.application.outcomes import ActionError

    refusal = window.service.export_format("cube")
    assert isinstance(refusal, ActionError), "expected the session to refuse an export it has nothing for"
    monkeypatch.setattr(window.service, "detect", lambda: refusal)

    window.dashboard.refresh_btn.click()

    assert labels(window, "displayNameLabel") == [FIXTURE_LABEL]
    assert [level for _message, level in window.toasts] == ["warning"]


def test_the_ddc_selector_lists_the_displays_the_session_observed(window: object) -> None:
    """DDC staging names displays from the pass, not from its own enumeration.

    The page used to enumerate displays while it was being constructed, which
    put a hardware read inside window startup and let its selector name hardware
    no action had looked at.
    """
    combo = window.ddc._display_combo
    assert [combo.itemText(index) for index in range(combo.count())] == [FIXTURE_LABEL]
    assert window.ddc._current_monitor == {
        "name": FIXTURE_LABEL,
        "display_id": window.dashboard.observed.dashboard.displays[0].platform_display_id,
    }
