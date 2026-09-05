"""What the active window offers, proved by driving the real one.

The window renders every menu entry, tray entry, and the dashboard's primary
button from the session's own resolver. That claim is only worth anything if
the window is built and used, so these tests construct the real one against the
fake-acceptance composition: it reads a bundled fixture, writes only inside the
directory it is given, and reaches no display and no operator journal.

Five properties are being held down. A control offers what the session would
actually perform, the status line names files that exist, every card describes
the display the session observed rather than one the page looked up for itself,
no page keeps its own answer about what it is permitted to do, and no page runs
the work it is supposed to be showing.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

from calibrate_pro.application.outcomes import ActionError, ActionSuccess
from calibrate_pro.application.prediction import MODEL_NAME
from calibrate_pro.gui.pages.ddc_control import DDC_TRANSACTION
from calibrate_pro.gui.pages.settings import OUTPUT_REJECTED, OUTPUT_UNSET
from calibrate_pro.gui.pages.settings_diagnostics import NOT_PREVIEWED
from calibrate_pro.gui.pages.verify import NOT_RUN_NOTE
from calibrate_pro.sensorless.neuralux import COLORCHECKER_CLASSIC
from calibrate_pro.verification.provenance import EvidenceKind
from calibrate_pro.workflow import CalibrationMethod, WorkflowStage
from tests.fake_acceptance_support import MANIFEST_NAME, PRESET_ID, journal_records

CUBE_EXPORT = ".cube (Resolve / dwm_lut)"
CALIBRATE_ALL = "&Calibrate All"

#: The action behind the live readout the dashboard used to offer.
LIVE_SENSOR_ACTION = "measurement.live.toggle"

#: Surface prefix the manifest uses for controls that live on the calibrate page.
CALIBRATE_SURFACE = "calibrate."

#: Declared with a calibrate-page surface and given no control on that page.
#: The action is conditional, so a session could enable it, and this build
#: presents nothing that reaches it. The four presets set every field of a
#: target between them, and a custom correlated colour temperature has no preset
#: behind it, so a control here would submit a number the page invented rather
#: than one the session holds. The null is recorded rather than closed by
#: inventing the control that would make the two sets match.
DECLARED_WITHOUT_A_CONTROL = frozenset({"calibration.target.custom_cct"})


def calibrate_page_actions() -> set[str]:
    """Every action the manifest places on the calibrate page."""
    from calibrate_pro.application.actions import ActionRegistry

    surfaces_by_action = ActionRegistry.load_default().surfaces_by_action
    return {
        action_id
        for action_id, surfaces in surfaces_by_action.items()
        if any(surface.startswith(CALIBRATE_SURFACE) for surface in surfaces)
    }


#: What the bundled fixture display resolves to once the session has adopted it.
FIXTURE_LABEL = "Display - FAKE-ACCEPTANCE-PANEL"
FIXTURE_PANEL_KEY = "PG27UCDM"


def entries(window: object) -> dict[str, object]:
    """Every menu and tray entry the window built, by the text it shows."""
    from PySide6.QtGui import QAction

    return {action.text(): action for action in window.findChildren(QAction)}


def drive_to_verify(service: object) -> None:
    """Walk the session to the stage where a verification can be run."""
    steps = (
        service.detect,
        lambda: service.select_method(CalibrationMethod.SENSORLESS),
        lambda: service.set_target(PRESET_ID),
        service.generate,
        service.preview,
        service.confirm_plan,
        service.apply_confirmed_plan,
    )
    for step in steps:
        outcome = step()
        assert isinstance(outcome, ActionSuccess), f"the session stopped at {outcome}"


def drive_to_save_report(service: object) -> None:
    """Walk the session to the stage where there is something to publish."""
    drive_to_verify(service)
    outcome = service.verify()
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
    from calibrate_pro.gui import app
    from calibrate_pro.gui.app import SensorCard

    assert window.findChild(SensorCard) is not None
    assert stat_value(window, "_stat_sensor") == "Not detected"
    assert not hasattr(app, "LiveSensorCard")


def test_the_dashboard_offers_no_control_for_a_readout_the_manifest_hides(window: object) -> None:
    """A hidden action gets no button, whatever a page could do without one.

    A card under the sensor row held a Start button that opened the colorimeter
    over raw HID and polled it every 800ms, painting each reply as luminance,
    correlated colour temperature and tristimulus values. It had no evidence
    kind, no receipt and no journal entry, and the manifest had already declared
    the action behind it hidden until its workflow is specified.

    The manifest's own policy is read here rather than restated. A build that
    specifies that workflow and opens the action will fail this test, which is
    the point at which a control belongs on the page again.
    """
    from calibrate_pro.application.actions import ActionDisposition, ActionRegistry

    resolved = window.service.resolve(LIVE_SENSOR_ACTION)
    assert resolved.disposition is ActionDisposition.HIDDEN
    assert LIVE_SENSOR_ACTION in ActionRegistry.load_default().action_ids
    assert not [binding for binding in window._binder.bindings if binding.action_id == LIVE_SENSOR_ACTION]


def calibrate_bindings(window: object) -> list[object]:
    """Every binding the window holds for an action shown on the calibrate page."""
    declared = calibrate_page_actions()
    return [binding for binding in window._binder.bindings if binding.action_id in declared]


def test_every_calibrate_control_stands_for_a_declared_action(window: object) -> None:
    """Read in both directions: no control without an action, none left unbound.

    One direction alone lets a page drift. Checking only that each control has
    an action permits a declared surface to go unbuilt and unnoticed, and
    checking only that each action has a control invites a control invented to
    satisfy the count. The exception is written out with its reason instead.
    """
    bound = {binding.action_id for binding in calibrate_bindings(window)}

    assert bound == calibrate_page_actions() - DECLARED_WITHOUT_A_CONTROL


def test_the_preset_buttons_carry_a_label_for_every_target_the_session_holds(window: object) -> None:
    """The label table and the target table are two halves of one list.

    A preset in the target table with no label is drawn under its action id. A
    label with no target is a button that names a preset no session can be set
    to. HDR10 is the deliberate third case: it is declared and labelled with no
    target behind it, because the page presents it closed rather than leaving a
    gap where an operator would look for it.
    """
    from calibrate_pro.application.actions import PRESET_TARGETS
    from calibrate_pro.gui.pages.calibrate import HDR_PRESET_ACTION, PRESET_LABELS

    assert set(PRESET_LABELS) == set(PRESET_TARGETS) | {HDR_PRESET_ACTION}
    assert HDR_PRESET_ACTION not in PRESET_TARGETS
    assert set(PRESET_LABELS) <= calibrate_page_actions()


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


def ddc_bindings(window: object) -> list[object]:
    """Every binding the window holds for a DDC/CI action."""
    return [binding for binding in window._binder.bindings if binding.action_id.startswith("ddc.")]


def test_every_ddc_control_stands_for_a_declared_action(window: object) -> None:
    """The page keeps no control the manifest has not declared.

    A control the page held for itself would be one the session never answers
    for, which is what the page used to be built from. Checking the bound set
    against the manifest means a control cannot be added later without an
    action to justify it, and the one action with no control of its own is the
    transaction the rest depend on.
    """
    from calibrate_pro.application.actions import ActionRegistry

    declared = {action_id for action_id in ActionRegistry.load_default().action_ids if action_id.startswith("ddc.")}
    assert {binding.action_id for binding in ddc_bindings(window)} == declared - {DDC_TRANSACTION}


def test_a_ddc_control_shows_the_manifest_reason_rather_than_its_own(window: object) -> None:
    """Each control is disabled, and its tooltip is the resolver's sentence.

    The page used to write its own refusals, one of which named a version
    number, so it could disagree with what the session would actually do. Every
    reason on screen now comes from the resolver that enforces it, including
    the line under the cards, which reports the transaction they all need.
    """
    bindings = ddc_bindings(window)
    assert bindings, "expected the window to have bound the DDC page"

    for binding in bindings:
        reason = window.service.resolve(binding.action_id).reason
        assert reason, f"{binding.action_id} was refused without an explanation"
        assert not binding.control.isEnabled(), f"{binding.action_id} is offered but the session refuses it"
        assert binding.control.toolTip() == reason

    assert window.ddc._status_label.text() == window.service.resolve(DDC_TRANSACTION).reason


def test_using_a_ddc_control_asks_the_session_and_is_refused(window: object) -> None:
    """Performing one goes through the session, which answers with a refusal.

    Reaching past the disabled control is deliberate. A disabled button emits
    nothing, so the only way to see what a click would do is to invoke the
    binding the click is wired to. What comes back carries the resolver's own
    reason, and nothing was written to a monitor to find that out.
    """
    binding = next(b for b in ddc_bindings(window) if b.action_id == "ddc.raw_write")
    outcome = window._binder.invoke(binding)

    assert isinstance(outcome, ActionError)
    assert outcome.action_id == "ddc.raw_write"
    assert outcome.effect_state == "none"
    assert outcome.summary == window.service.resolve("ddc.raw_write").reason

    message, level = window.toasts[-1]
    assert level == "warning"
    assert outcome.summary in message


def test_the_ddc_page_stages_nothing_of_its_own(window: object) -> None:
    """Moving a control records nothing, because there is nowhere to record it.

    The page kept a dictionary of pending changes that no plan ever read, under
    a status line counting how many were staged. Both are gone, so the page
    cannot report progress toward an apply that was never being assembled.
    """
    page = window.ddc
    assert not hasattr(page, "_pending_changes")

    before = page._status_label.text()
    page._brightness_slider.setValue(page._brightness_slider.value() + 1)
    assert page._status_label.text() == before


def verify_controls(window: object) -> dict[str, object]:
    """Every binding on the verify page, keyed by the action it stands for.

    Keying by action would collide across pages, since more than one page binds
    the display selector. The controls are looked up by identity instead, which
    also means a control the page stopped binding disappears from this map
    rather than being answered by another page's binding.
    """
    page = window.verify_page
    owned = {id(page._display_combo), id(page._btn_verify), id(page._btn_measured), id(page._btn_export)}
    return {binding.action_id: binding for binding in window._binder.bindings if id(binding.control) in owned}


def test_the_verify_page_opens_with_references_and_no_figures(window: object) -> None:
    """An empty grid and a grid full of numbers would both be wrong here.

    The references are the target the model compares against, so they are drawn
    before anything has run, and every delta beside them says it was not
    measured until an action produces one.
    """
    page = window.verify_page
    patches = page._checker_grid._patches

    assert len(patches) == len(COLORCHECKER_CLASSIC)
    assert {patch._de.evidence for patch in patches} == {EvidenceKind.NOT_MEASURED}
    assert page._method_label.text() == NOT_RUN_NOTE
    assert page._stat_avg_de._value_label.text() == "Not measured"


def test_the_verify_page_lists_the_display_the_session_observed(window: object) -> None:
    """The selector names one detection pass rather than a lookup of its own.

    Every display enumerator is wired to raise in this fixture, so a page that
    read hardware on a timer would fail here instead of filling the list. What
    is in it arrived through the session and carries the label the session
    published for that display.
    """
    combo = window.verify_page._display_combo

    assert [combo.itemText(index) for index in range(combo.count())] == [FIXTURE_LABEL]


def test_measured_verification_states_why_it_is_closed_rather_than_offering_it(window: object) -> None:
    """The page used to announce measured verification when a sensor answered.

    The session refuses it in every state, by manifest instruction, so that
    line said the opposite of what the build does. Reaching past the disabled
    button is deliberate: a disabled control emits nothing, so invoking its
    binding is the only way to see what a click would have done.
    """
    binding = verify_controls(window)["verification.measured"]
    reason = window.service.resolve("verification.measured").reason
    assert reason

    assert not binding.control.isEnabled()
    assert binding.control.toolTip() == reason

    outcome = window._binder.invoke(binding)
    assert isinstance(outcome, ActionError)
    assert outcome.summary == reason
    assert outcome.effect_state == "none"


def test_running_verification_draws_the_result_the_session_produced(window: object) -> None:
    """Every figure on the page belongs to the result the session returned.

    The page used to build a worker and run the accuracy model in a thread of
    its own, so what appeared here was a second computation nothing recorded.
    The deltas now come from the session's own patches, the model that produced
    them is named on the page, and each one carries the evidence label the
    session attached rather than one the page chose.
    """
    page = window.verify_page
    binding = verify_controls(window)["verification.sensorless"]
    assert not binding.control.isEnabled()

    drive_to_verify(window.service)
    window._binder.refresh()
    assert binding.control.isEnabled()

    binding.control.click()

    patches = page._checker_grid._patches
    assert len(patches) == len(COLORCHECKER_CLASSIC)
    assert {patch._de.evidence for patch in patches} == {EvidenceKind.ESTIMATED}
    assert {patch._de.source for patch in patches} == {MODEL_NAME}
    assert page._stat_evidence._value_label.text() == MODEL_NAME
    assert MODEL_NAME in page._method_label.text()
    assert page._stat_avg_de._value_label.text().endswith("(estimated)")
    assert window.toasts == []


def test_redrawing_the_verify_page_does_not_discard_the_generated_plan(window: object) -> None:
    """Repainting the page is not an operator choosing a display.

    Repopulating the selector moves its current index, and adopting a display
    drops everything downstream of it. Unguarded, a detection pass after a plan
    was generated would throw the plan away, and the page would look no
    different while it happened. Either failure is visible here: the stage
    would move, or the selection would be refused and explained in a toast.
    """
    observed = window.service.detect()
    assert isinstance(observed, ActionSuccess)
    drive_to_save_report(window.service)
    stage = window.service.stage

    window.verify_page.render_session(observed.value)

    assert window.service.stage is stage
    assert window.toasts == []
    combo = window.verify_page._display_combo
    assert [combo.itemText(index) for index in range(combo.count())] == [FIXTURE_LABEL]


def local_settings(page: object, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point the settings page at a file, so a test writes no user settings."""
    store = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(page, "_settings", store)


def answer_directory_dialog(monkeypatch: pytest.MonkeyPatch, directory: Path) -> None:
    """Answer the settings page's folder dialog with one path."""
    from calibrate_pro.gui.pages import settings as settings_page

    monkeypatch.setattr(
        settings_page.QFileDialog,
        "getExistingDirectory",
        staticmethod(lambda *args, **kwargs: str(directory)),
    )


def test_saving_the_report_writes_the_files_the_page_names(
    window: object,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A reported save is a save that ran, read back off disk.

    The verify page used to write a file itself, straight from a save dialog,
    with nothing gating the write and nothing recording it. Saving is a
    declared action now and it stays closed until an output directory has been
    accepted, which is a second action on another page. Both surfaces are
    driven here because the pair is the product path: what the settings page
    accepts is what decides whether the save button can be used at all.
    """
    page = window.settings_page
    button = verify_controls(window)["report.save"].control
    drive_to_save_report(window.service)
    window._binder.refresh()

    assert not button.isEnabled()
    assert "output directory" in button.toolTip()
    assert page._output_field.text() == OUTPUT_UNSET

    destination = tmp_path / "report"
    local_settings(page, monkeypatch, tmp_path)
    answer_directory_dialog(monkeypatch, destination)
    assert page._output_browse.isEnabled()
    page._output_browse.click()

    assert page._output_field.text() == str(destination)
    assert button.isEnabled()
    button.click()

    assert MANIFEST_NAME in sorted(path.name for path in destination.iterdir())
    line = window.verify_page._export_label.text()
    assert str(destination) in line
    assert MANIFEST_NAME in line
    assert window.toasts == []


def test_a_directory_the_session_refuses_leaves_the_save_closed(
    window: object,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Choosing a folder is not the same as the session accepting one.

    A path that cannot be written to is recorded as chosen and invalid. The
    page shows which path was turned down, says why saving stays closed, and
    does not remember it, so the next dialog does not open on a folder the
    session already rejected.
    """
    page = window.settings_page
    button = verify_controls(window)["report.save"].control
    drive_to_save_report(window.service)

    local_settings(page, monkeypatch, tmp_path)
    unusable = tmp_path / "missing" / "deeper"
    answer_directory_dialog(monkeypatch, unusable)
    page._output_browse.click()

    assert page._output_field.text() == str(unusable)
    assert page._output_note.text() == OUTPUT_REJECTED
    assert page._settings.value("paths/output_dir", "") == ""
    assert not button.isEnabled()



#: Surface prefix the manifest uses for controls that live on the settings page.
SETTINGS_SURFACE = "settings."


def settings_page_actions() -> set[str]:
    """Every action the manifest places on the settings page."""
    from calibrate_pro.application.actions import ActionRegistry

    surfaces_by_action = ActionRegistry.load_default().surfaces_by_action
    return {
        action_id
        for action_id, surfaces in surfaces_by_action.items()
        if any(surface.startswith(SETTINGS_SURFACE) for surface in surfaces)
    }


def test_the_settings_page_binds_every_action_the_session_will_answer(window: object) -> None:
    """Read in both directions, and let the manifest say which ones those are.

    Nine controls on this page were drawn without a binding. Seven of them wrote
    into the application's configuration store, which nothing read back, so a
    checkbox could be ticked, survive a restart, and change nothing. The hidden
    set is computed from the session rather than listed here, so a build that
    specifies one of those workflows and opens the action fails this test, which
    is the point at which its control belongs on the page again.
    """
    from calibrate_pro.application.actions import ActionDisposition

    declared = settings_page_actions()
    hidden = {
        action_id
        for action_id in declared
        if window.service.resolve(action_id).disposition is ActionDisposition.HIDDEN
    }
    bound = {binding.action_id for binding in window._binder.bindings if binding.action_id in declared}

    assert len(hidden) == 8
    assert bound == declared - hidden


def test_no_control_on_the_settings_page_is_left_for_the_operator_to_press(window: object) -> None:
    """A drawn control the resolver never sees is the defect this page had.

    Checking the bindings alone would not have caught it, because a control can
    be built, connected to a handler of its own, and simply never handed over.
    The page's own widgets are read here instead, so anything interactive has to
    be accounted for by a binding.
    """
    from PySide6.QtWidgets import QCheckBox, QComboBox, QPushButton

    page = window.settings_page
    bound = {id(binding.control) for binding in window._binder.bindings}
    interactive = [
        *page.findChildren(QCheckBox),
        *page.findChildren(QComboBox),
        *page.findChildren(QPushButton),
    ]

    assert len(interactive) == 6
    assert [widget for widget in interactive if id(widget) not in bound] == []


def test_hdr_is_drawn_closed_rather_than_left_off_the_page(window: object) -> None:
    """Removing the box would read as a build that never had the feature.

    HDR is declared disabled, which is a different statement from hidden: there
    is a contract behind it that this build does not qualify against. The box
    stays on the page carrying the session's own sentence, so an operator
    looking for HDR reads why it is closed.
    """
    from calibrate_pro.application.actions import ActionDisposition

    page = window.settings_page
    resolved = window.service.resolve("settings.hdr")

    assert resolved.disposition is ActionDisposition.DISABLED
    assert not page._hdr_cb.isHidden()
    assert not page._hdr_cb.isEnabled()
    assert not page._hdr_cb.isChecked()
    assert page._hdr_cb.toolTip() == resolved.reason


def test_the_grid_selector_opens_on_what_the_session_holds(window: object) -> None:
    """The page shows a preference it read, not one it chose for itself.

    A selector that opens on its first item reports a grid nobody picked, and
    the first generation would then be built on a different one. The value is
    read at bind time and the signal is blocked while the selector moves, so
    opening the page asks the session for nothing.
    """
    page = window.settings_page

    assert page._lut_combo.currentText() == str(window.service.lut_size)
    assert page._lut_combo.isEnabled()
    assert [record["action_id"] for record in journal_records(window.session_root)] == ["display.detect"]


def test_choosing_a_grid_reaches_the_session_and_is_journalled(window: object) -> None:
    """The choice is an action, so it is resolved and recorded like any other.

    What the operator picked is what the next generation uses. The journal is
    read here rather than the session's own attribute, because a preference
    that changes an in-memory field and leaves no record is the shape of the
    defect this replaced.
    """
    page = window.settings_page
    page._lut_combo.setCurrentText("65")

    assert window.service.lut_size == 65
    assert page._lut_combo.currentText() == "65"
    assert journal_records(window.session_root)[-1]["action_id"] == "settings.lut_size"
    assert window.toasts == []


def test_a_refused_grid_puts_the_selector_back(
    window: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A selector left on a refused value would misreport the next generation.

    The refusal is a real one, taken from the session by asking it for a grid
    this build does not generate, and then substituted for the page's answer.
    The substitution is needed because the selector only offers grids the build
    generates, so its own refusal is unreachable from the page. A refusal from
    any other cause arrives the same way and the selector has to end on what the
    session holds either way.
    """
    from calibrate_pro.application.outcomes import ActionError

    page = window.settings_page
    refusal = window.service.set_lut_size(9)
    assert isinstance(refusal, ActionError)
    monkeypatch.setattr(page, "_set_lut_size", lambda size: refusal)

    page._lut_combo.setCurrentText("65")

    assert page._lut_combo.currentText() == str(window.service.lut_size) == "33"
    assert [message for message, level in window.toasts] == [
        "A 9-point LUT grid is not one this build generates. "
        "Choose one of the grids this build generates: 17, 33, 65."
    ]

def answer_save_dialog(monkeypatch: pytest.MonkeyPatch, destination: Path | None) -> None:
    """Answer the diagnostics save dialog with one path, or with a withdrawal."""
    from calibrate_pro.gui.pages import settings_diagnostics

    answer = "" if destination is None else str(destination)
    monkeypatch.setattr(
        settings_diagnostics.QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *args, **kwargs: (answer, "")),
    )


def diagnostics_section(window: object) -> object:
    """The diagnostics block the settings page builds."""
    return window.settings_page._diagnostics_section


def test_the_diagnostics_section_opens_with_nothing_read(window: object) -> None:
    """The page names the journal folder without reading anything in it.

    Naming a configured path is not an observation, so the folder line is
    filled at bind time. Everything else stays empty until an action runs, and
    publishing stays closed because no preview has issued a token.
    """
    section = diagnostics_section(window)

    assert section._preview_button.isEnabled()
    assert not section._save_button.isEnabled()
    assert "preview" in section._save_button.toolTip().lower()
    assert section._listing.text() == NOT_PREVIEWED
    assert section._receipt.text() == ""
    assert str(window.session_root / "diagnostics") in section._folder.text()
    assert window.toasts == []


def test_publishing_writes_exactly_the_files_the_listing_named(
    window: object,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """What the listing promises before the write is what lands after it.

    An operator sending a bundle is sending the members named here, so the
    published archive is opened back off disk and every entry in it is checked
    against the listing the preview drew.
    """
    section = diagnostics_section(window)
    section._preview_button.click()

    listing = section._listing.text()
    assert "diagnostics.jsonl" in listing
    assert section._save_button.isEnabled()

    destination = tmp_path / "bundle.zip"
    answer_save_dialog(monkeypatch, destination)
    section._save_button.click()

    with zipfile.ZipFile(destination) as archive:
        published = sorted(archive.namelist())
    assert published
    for basename in published:
        assert basename in listing

    receipt = section._receipt.text()
    assert str(destination) in receipt
    assert "verified" in receipt
    assert not section._save_button.isEnabled()
    assert window.toasts == []


def test_a_refused_publish_spends_the_preview_it_was_offered(
    window: object,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A token is spent by the attempt, not by the attempt succeeding.

    The session refuses a destination that already exists and drops the grant
    on the way out. Leaving the button enabled would offer a second attempt
    against a token nothing would accept, so the control closes with the grant.
    """
    section = diagnostics_section(window)
    section._preview_button.click()

    taken = tmp_path / "taken.zip"
    taken.write_bytes(b"")
    answer_save_dialog(monkeypatch, taken)
    section._save_button.click()

    assert taken.read_bytes() == b""
    assert section._receipt.text() == ""
    assert not section._save_button.isEnabled()
    assert len(window.toasts) == 1


def test_closing_the_save_dialog_reports_nothing_and_keeps_the_preview(
    window: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A withdrawn choice never reaches the journal.

    Nothing is written, nothing is said, and the token the preview issued is
    still the one the next attempt would use.
    """
    section = diagnostics_section(window)
    section._preview_button.click()

    answer_save_dialog(monkeypatch, None)
    section._save_button.click()

    assert section._receipt.text() == ""
    assert section._save_button.isEnabled()
    assert window.toasts == []


def test_opening_the_folder_reaches_the_folder_the_page_named(
    window: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The button opens the folder the line above it names, and no other.

    The opener is substituted because the real one hands a path to the shell.
    Substituting it also removes the platform from the question, so the wiring
    is held to the same claim wherever the suite runs.
    """
    section = diagnostics_section(window)
    opened: list[Path] = []
    monkeypatch.setattr(window.service._bundles, "_folder_opener", opened.append)

    section._open_button.click()

    assert opened == [window.session_root / "diagnostics"]
    assert str(opened[0]) in section._folder.text()
    assert window.toasts == []


#: A panel profile written the way the panel database writes one.
PANEL_FILE = {
    "manufacturer": "Example Optics",
    "model_pattern": "EX-2700U",
    "display_name": "Example EX-2700U",
    "panel_type": "QD-OLED",
}


def open_add_display(window: object) -> object:
    """Open the add-profile dialog the way the dashboard button opens it."""
    window.dashboard.add_display_btn.click()
    dialog = window._add_display_dialog
    assert dialog is not None
    return dialog


def answer_open_dialog(monkeypatch: pytest.MonkeyPatch, chosen: Path | None) -> None:
    """Answer the dialog's file chooser with one path, or with a withdrawal.

    The real chooser blocks until a person answers it, offscreen platform or
    not, so a test that clicked Browse without this would never return.
    """
    from calibrate_pro.gui import add_display

    answer = "" if chosen is None else str(chosen)
    monkeypatch.setattr(
        add_display.QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *args, **kwargs: (answer, "")),
    )


def test_opening_the_profile_dialog_is_an_action_and_the_only_one(window: object) -> None:
    """Opening is declared, so it is journalled, and nothing else is.

    The dialog draws the selected display before its selector is bound. Binding
    first would make opening the dialog look like a choice somebody made, and
    the journal would carry a selection no operator performed.
    """
    dialog = open_add_display(window)

    assert dialog.isVisible()
    assert [record["action_id"] for record in journal_records(window.session_root)] == [
        "display.detect",
        "panel_profile.dialog.open",
    ]


def test_every_control_in_the_profile_dialog_stands_for_a_declared_action(window: object) -> None:
    """A drawn control the resolver never sees is the defect this dialog had.

    Reading the bindings alone would not catch it, because a control can be
    built, connected to a handler of its own, and never handed over. That is
    what both write buttons used to be, so the dialog's own widgets are read
    here and every interactive one has to be accounted for.
    """
    from PySide6.QtWidgets import QComboBox, QPushButton

    dialog = open_add_display(window)
    bound = {id(binding.control) for binding in dialog._binder.bindings}
    interactive = [*dialog.findChildren(QComboBox), *dialog.findChildren(QPushButton)]

    assert len(interactive) == 4
    assert [widget for widget in interactive if id(widget) not in bound] == []


def test_the_two_writes_the_profile_dialog_draws_are_closed_by_the_session(window: object) -> None:
    """Both stay on the dialog, disabled, carrying the resolver's own sentence.

    Removing them would read as a build that never had the feature. They are
    declared disabled, which is a different statement: there is a Phase 2
    contract behind each one that this build does not qualify against, and an
    operator looking for either needs to read why it is closed.
    """
    from calibrate_pro.application.actions import ActionDisposition

    dialog = open_add_display(window)

    for action_id, control in (
        ("panel_profile.edid.create", dialog._create_btn),
        ("panel_profile.import", dialog._import_btn),
    ):
        resolved = window.service.resolve(action_id)
        assert resolved.disposition is ActionDisposition.DISABLED
        assert not control.isEnabled()
        assert not control.isHidden()
        assert control.toolTip() == resolved.reason


def test_browsing_hands_the_file_to_the_session_and_draws_what_it_holds(
    window: object,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The dialog shows a reading it was given, not one it performed.

    The file stays where the operator keeps it. Copying it into the directory
    the calibration engine reads is the disabled action beside this one, and
    the journal is read here because the copy this replaced left no record.
    """
    chosen = tmp_path / "panel.json"
    chosen.write_text(json.dumps(PANEL_FILE), encoding="utf-8")
    answer_open_dialog(monkeypatch, chosen)
    dialog = open_add_display(window)

    dialog._browse_btn.click()

    assert dialog._path_label.text() == str(chosen)
    assert "Example EX-2700U" in dialog._preview_label.text()
    assert "QD-OLED" in dialog._preview_label.text()
    assert chosen.exists()
    assert journal_records(window.session_root)[-1]["action_id"] == "panel_profile.import.choose"
    assert window.toasts == []


def test_withdrawing_from_the_profile_chooser_reads_nothing(
    window: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A closed chooser is neither a success to report nor a refusal to explain."""
    from calibrate_pro.gui.add_display import NO_FILE_CHOSEN

    answer_open_dialog(monkeypatch, None)
    dialog = open_add_display(window)
    before = journal_records(window.session_root)

    dialog._browse_btn.click()

    assert dialog._path_label.text() == NO_FILE_CHOSEN
    assert dialog._preview_label.text() == ""
    assert journal_records(window.session_root) == before
    assert window.toasts == []


def test_a_file_the_session_cannot_read_is_refused_inside_the_dialog(
    window: object,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The window's toasts appear in a corner this dialog covers.

    A refusal shown there is a refusal the operator never reads, so the message
    goes to the dialog and the toast list has to stay empty. The field is put
    back at the same time, so it never names a file that was turned down.
    """
    from calibrate_pro.gui.add_display import NO_FILE_CHOSEN

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    answer_open_dialog(monkeypatch, broken)
    dialog = open_add_display(window)

    dialog._browse_btn.click()

    assert "could not be read" in dialog._message.text()
    assert dialog._message.isVisible()
    assert dialog._path_label.text() == NO_FILE_CHOSEN
    assert dialog._preview_label.text() == ""
    assert window.toasts == []


def test_the_profile_dialog_can_reach_nothing_that_writes() -> None:
    """No route through this surface reaches the panel database or the disk.

    The behaviour is proved above, one path at a time. This reads the module
    instead, because a write that is added later would be added as an import
    and a call rather than as one of the paths a test already drives.
    """
    import ast

    from calibrate_pro.gui import add_display

    source = Path(add_display.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name if isinstance(node, ast.Import) else (node.module or "")
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }

    assert [name for name in imported if name.startswith("calibrate_pro.panels")] == []
    assert [name for name in imported if name in {"shutil", "os"}] == []
    assert [name for name in ("write_text", "mkdir", "copyfile", "save_panel") if name in source] == []
