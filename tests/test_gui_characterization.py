"""Calibrating a display the bundled panel database does not name.

Detection adopts a display it cannot match rather than rejecting it, and it
adopts that display as uncharacterized. Every calibration method and every
target after it requires a characterization, so the session stopped there. The
manifest declares the one action that supplies one,
``display.characterization.use_generic``, and names its surface
``dashboard.characterization.use_generic``. No window presented it, so a
monitor outside the bundled database reached the Calibrate page and was refused
by every control on it.

The bundled fake display cannot reach that state, because its database key
resolves and the session adopts it as matched. These tests blank the key at the
composition boundary, which is the one place the display enters the session, so
everything after it is the real detection path.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from pathlib import Path

import pytest

from calibrate_pro.application.actions import ActionDisposition
from calibrate_pro.application.contracts import CharacterizationKind
from calibrate_pro.application.outcomes import ActionSuccess
from tests.conftest import active_window
from tests.fake_acceptance_support import journal_records

#: What the manifest says when the session already holds a characterization.
ALREADY_CHARACTERIZED = "Generic characterization is available only for an uncharacterized selected display."


@pytest.fixture
def unmatched_window(qapp: object, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[object]:
    """The window, built against a display the panel database does not name.

    Only the database key is dropped. The bundled model and monitor names match
    no record either, so detection runs its whole matching path and arrives at
    uncharacterized the way it would for a real monitor nobody has profiled.
    """
    from calibrate_pro.application import composition

    bundled = composition.load_fake_display
    monkeypatch.setattr(
        composition,
        "load_fake_display",
        lambda: dataclasses.replace(bundled(), panel_database_key=""),
    )
    with active_window(monkeypatch, tmp_path) as built:
        yield built


def selected_kind(window: object) -> CharacterizationKind:
    return window.service.selection.characterization_kind


def test_a_display_outside_the_database_is_adopted_uncharacterized(unmatched_window: object) -> None:
    """The state this surface exists for is reachable, and is not a rejection.

    A display the database cannot name is still a display, so the pass adopts
    it and reports it. What it cannot report is a description of the panel, and
    that is what closes everything downstream.
    """
    window = unmatched_window

    assert selected_kind(window) is CharacterizationKind.UNKNOWN
    assert window._observed.rejected == ()
    assert len(window._observed.dashboard.displays) == 1
    assert window.service.resolve("calibration.method.sensorless").disposition is ActionDisposition.DISABLED


def test_the_dashboard_offers_the_generic_path_for_such_a_display(unmatched_window: object) -> None:
    """The declared surface exists, is open, and stands for the declared action."""
    window = unmatched_window
    bound = {id(binding.control): binding.action_id for binding in window._binder.bindings}

    button = window.dashboard.use_generic_btn
    assert bound[id(button)] == "display.characterization.use_generic"
    assert button.isEnabled()
    assert not button.isHidden()


def test_a_matched_session_is_told_why_the_generic_path_is_closed(window: object) -> None:
    """The control is disabled in place with the reason the manifest declares.

    Hiding it would leave an operator with a matched display looking for a
    button an unmatched one has, and the row anchors the page either way.
    """
    assert selected_kind(window) is CharacterizationKind.MATCHED

    button = window.dashboard.use_generic_btn
    assert not button.isEnabled()
    assert not button.isHidden()
    assert button.toolTip() == ALREADY_CHARACTERIZED
    assert (
        window._binder.disposition_of("display.characterization.use_generic").disposition is ActionDisposition.DISABLED
    )


def test_taking_the_generic_path_journals_it_and_opens_the_method(unmatched_window: object) -> None:
    """The defect this closes, stated as the thing the window could not do.

    Before this control the session could detect an unnamed display and reach
    nothing else. One click is journalled, and the method the whole workflow
    runs on opens behind it.
    """
    window = unmatched_window
    assert not window.calibrate_page._mode_sensorless.isEnabled()

    window.dashboard.use_generic_btn.click()

    assert selected_kind(window) is CharacterizationKind.EXPLICIT_GENERIC
    assert [record["action_id"] for record in journal_records(window.session_root)] == [
        "display.detect",
        "display.characterization.use_generic",
    ]
    assert window.calibrate_page._mode_sensorless.isEnabled()
    assert not window.dashboard.use_generic_btn.isEnabled()


def test_the_generic_session_runs_the_workflow_through_to_a_confirmed_plan(unmatched_window: object) -> None:
    """A generic characterization carries the session as far as a matched one.

    The point of the control is not that it changes a label. It is that the
    stages after it open, so this drives the session to a sealed plan and reads
    back that the plan is about the display that had no record.
    """
    from tests.fake_acceptance_support import PRESET_ID

    window = unmatched_window
    window.dashboard.use_generic_btn.click()

    from calibrate_pro.workflow import CalibrationMethod

    for step in (
        lambda: window.service.select_method(CalibrationMethod.SENSORLESS),
        lambda: window.service.set_target(PRESET_ID),
        window.service.generate,
        window.service.preview,
    ):
        outcome = step()
        assert isinstance(outcome, ActionSuccess), f"the session stopped at {outcome}"

    assert outcome.value.plan.display_id == window.service.selection.display_id
    assert outcome.value.physical_apply_performed is False


def test_the_row_says_which_characterization_the_session_holds(unmatched_window: object) -> None:
    """The sentence names the state, and changes when the state changes."""
    from calibrate_pro.gui.app import characterization_note

    window = unmatched_window
    label = window.dashboard._characterization_label

    assert label.text() == characterization_note(window.service.selection)
    assert "not in the bundled panel database" in label.text()

    window.dashboard.use_generic_btn.click()

    assert "generic characterization" in label.text()
    assert "nominal sRGB panel rather than this unit" in label.text()


def test_the_row_reads_the_session_rather_than_the_observation(unmatched_window: object) -> None:
    """Where the two disagree, the row states the one the resolver works from.

    Taking the generic path is a decision the session records. The detection
    pass behind it is unchanged, so the card still reports an uncharacterized
    panel, which is true of the observation and no longer true of the session.
    A row drawn off the observation would tell the operator the workflow is
    still closed while every control after it is open.
    """
    window = unmatched_window
    observation = window._observed.dashboard.displays[0]

    window.dashboard.use_generic_btn.click()

    assert observation.characterization.kind is CharacterizationKind.UNKNOWN
    assert selected_kind(window) is CharacterizationKind.EXPLICIT_GENERIC
    assert "generic characterization" in window.dashboard._characterization_label.text()


def test_the_row_survives_a_redraw_of_the_cards(unmatched_window: object) -> None:
    """A later pass rebuilds the cards, and the row is not one of them.

    ``_populate`` clears the cards and the sensor block. The row is added to the
    page rather than to either, so a control the binder holds a reference to is
    not deleted underneath it.
    """
    window = unmatched_window
    button = window.dashboard.use_generic_btn

    window.dashboard.render_session(window._observed)

    assert window.dashboard.use_generic_btn is button
    assert button.isEnabled()


def test_a_window_that_detected_nothing_says_so_rather_than_guessing() -> None:
    """With no selection the row states that, and the control is closed."""
    from calibrate_pro.gui.app import characterization_note

    assert characterization_note(None) == "No display is selected. Run a detection pass to select one."


# Builds the production service, whose journal root is the Windows
# per-user application directory. Running it where that directory does not
# exist would test a faked environment rather than the shipped one.
@pytest.mark.windows
def test_the_preview_window_describes_its_fixture_rather_than_a_selection(qapp: object) -> None:
    """A preview draws cards from a bundled fixture and detects nothing.

    The starting sentence a real window shows says no display is selected yet,
    which reads as a claim about this machine on a surface whose cards came
    from a file. The preview says where its cards came from instead, and the
    control stays closed because the preview session holds no selection.
    """
    from calibrate_pro.gui.app import CalibrateProWindow

    window = CalibrateProWindow(preview_mode=True)

    assert window.dashboard._characterization_label.text() == (
        "These cards come from a bundled fixture. No session selected a display."
    )
    assert not window.dashboard.use_generic_btn.isEnabled()
    assert not window.dashboard.use_generic_btn.isHidden()


def test_returning_to_the_dashboard_rereads_the_session(unmatched_window: object) -> None:
    """The Calibrate page can move the selection while nobody is watching it.

    Selecting a display there is an action of its own, and the dashboard is not
    on screen when it runs. The row is read back off the session when the page
    comes forward rather than pushed from the surface that changed it.
    """
    from calibrate_pro.gui.app import DASHBOARD_PAGE_INDEX

    window = unmatched_window
    window._switch_page(1)
    assert isinstance(window.service.use_generic_characterization(), ActionSuccess)
    assert "not in the bundled panel database" in window.dashboard._characterization_label.text()

    window._switch_page(DASHBOARD_PAGE_INDEX)

    assert "generic characterization" in window.dashboard._characterization_label.text()
