"""What the calibrate page shows after an instrument reads the display.

A run is worth offering only if the surface reporting it says what was read and
by what. The page has three places to get that wrong: it can leave the previous
bundle on screen next to the new reading, it can print the two measured labels
without carrying the numbers behind them, and it can offer a card that looks
like a run and performs nothing.

These tests build the page against a run taken from the synthetic display the
measurement suite shares, so no colorimeter is opened and no patch covers a real
screen. The window tests below read the bindings the page registered rather than
pressing anything, because what is under test there is which action a control
stands for and what it runs, not whether a click reaches Qt.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from calibrate_pro.application.actions import ActionDisposition
from calibrate_pro.application.contracts import CharacterizationKind
from calibrate_pro.application.correction_state import UNCOVERED_LAYERS
from calibrate_pro.application.measurement import measure_characterization
from calibrate_pro.application.results import GenerationResult, MeasurementSummary
from calibrate_pro.verification.provenance import EvidenceKind
from tests.measurement_support import SyntheticDisplay, base_panel

DISPLAY_ID = "FAKE-ACCEPTANCE-DISPLAY"
STEPS = 5
QUALIFIED = f"The display's gamma table read within 0 codes of identity. {UNCOVERED_LAYERS}"

#: A bundle from the panel database, used where a test needs the page to have
#: something on its result card that a run then replaces.
SEALED = GenerationResult(
    plan_sha256="c" * 64,
    filenames=("Calibrate_Pro.cube",),
    panel_name="Generic Unknown Display",
    characterization_kind=CharacterizationKind.EXPLICIT_GENERIC,
    evidence_kind=EvidenceKind.ESTIMATED,
)


@pytest.fixture(scope="module")
def summary() -> MeasurementSummary:
    """One run, reported the way the session reports it to a surface."""
    display = SyntheticDisplay()
    measured = measure_characterization(
        instrument=display,
        patches=display,
        base=base_panel(),
        steps=STEPS,
        settle=lambda: None,
    )
    return MeasurementSummary(display_id=DISPLAY_ID, characterization=measured, correction_state=QUALIFIED)


@pytest.fixture
def page(qapp: object) -> Iterator[object]:
    from calibrate_pro.gui.pages.calibrate import CalibratePage

    built = CalibratePage()
    try:
        yield built
    finally:
        built.close()


def stats(page: object) -> tuple[str, str, str]:
    return (
        page._stat_panel._value_label.text(),
        page._stat_characterization._value_label.text(),
        page._stat_evidence._value_label.text(),
    )


# What the page says about a run --------------------------------------------


def test_the_page_reports_the_run_in_the_terms_the_session_recorded(page: object, summary: MeasurementSummary) -> None:
    from calibrate_pro.gui.pages.calibrate import MEASURED_NOTE

    page.render_measurement(summary)

    assert page._result_heading.text() == MEASURED_NOTE
    assert stats(page) == (
        summary.characterization.panel.name,
        CharacterizationKind.MEASURED.value,
        EvidenceKind.MEASURED.value,
    )


def test_the_reading_on_screen_names_the_device_and_what_it_read(page: object, summary: MeasurementSummary) -> None:
    """Two measured labels without these would be a claim with no reading under it."""
    page.render_measurement(summary)
    line = page._digest_label.text()

    assert line == summary.summary
    assert summary.characterization.instrument in line, "nothing on screen names the device that read the display"
    assert str(summary.characterization.patch_count) in line
    assert summary.characterization.patch_geometry in line, "an OLED peak depends on the field it was read from"


def test_the_page_carries_what_the_qualification_could_not_see(page: object, summary: MeasurementSummary) -> None:
    """The run's own caveat travels onto the screen with it.

    The gamma table is one of several places a correction can sit. A page that
    printed the qualifying half and dropped the rest would report a display as
    clean on the strength of the one layer the check reads.
    """
    page.render_measurement(summary)

    assert page._files_label.text() == summary.correction_state
    assert UNCOVERED_LAYERS in page._files_label.text()


def test_a_run_returns_the_workflow_to_the_target_step(page: object, summary: MeasurementSummary) -> None:
    """A measurement does not undo a target, so the page does not go to the start."""
    page.render_measurement(summary)

    assert page._progress_bar.value() == 2


def test_the_card_describes_only_the_last_thing_produced(page: object, summary: MeasurementSummary) -> None:
    """The card carries nothing from the render before it, in either direction.

    A run replaces the record the next bundle is built from, so a digest sealed
    against the record it replaced would name a plan nothing downstream can
    still cite. Going the other way is the false-success control on every
    assertion above: a page that wrote the measured words unconditionally would
    satisfy them all, and has to put the estimated labels back when what
    produced the bundle was the database.
    """
    page.render_generation(SEALED)
    assert SEALED.plan_sha256 in page._digest_label.text()

    page.render_measurement(summary)

    assert SEALED.plan_sha256 not in page._digest_label.text()
    assert SEALED.filenames[0] not in page._files_label.text()
    assert stats(page)[0] != SEALED.panel_name

    page.render_generation(SEALED)

    assert stats(page) == (
        SEALED.panel_name,
        CharacterizationKind.EXPLICIT_GENERIC.value,
        EvidenceKind.ESTIMATED.value,
    )
    assert summary.characterization.instrument not in page._digest_label.text()
    assert summary.correction_state not in page._files_label.text()


# What the controls are wired to --------------------------------------------


def binding_for(window: object, action_id: str) -> object:
    matches = [binding for binding in window._binder.bindings if binding.action_id == action_id]
    assert len(matches) == 1, f"{action_id} is bound {len(matches)} times"
    return matches[0]


def test_the_measured_card_performs_rather_than_refusing(window: object) -> None:
    """The card stands for the method action and runs the session's selection.

    The page used to decide this for itself, by asking the USB bus what was
    attached, which is how it came to offer a method the manifest was holding
    shut. The resolver decides now, and the control's job is to carry the
    action id it is resolved under.
    """
    page = window.calibrate_page
    measured = binding_for(window, "calibration.method.measured")

    assert measured.control is page._mode_measured
    assert measured.on_success == page.render_method, "the card performs and reports what the session committed to"


def test_a_method_this_build_does_not_handle_is_bound_as_closed(window: object) -> None:
    """The contrast that makes the previous test mean something.

    Hybrid is declared and unhandled, so its card is bound with no success
    handler. If measured were bound the same way, the assertion above would be
    reading a control that answers a refusal.
    """
    hybrid = binding_for(window, "calibration.method.hybrid")

    assert hybrid.on_success is None
    assert hybrid.control is window.calibrate_page._mode_hybrid


def test_the_measure_button_runs_a_measurement_and_reports_it(window: object) -> None:
    page = window.calibrate_page
    measure = binding_for(window, "calibration.measure")

    assert measure.control is page._btn_measure
    assert measure.on_success == page.render_measurement


def test_the_session_this_window_holds_reports_no_instrument(window: object) -> None:
    """Why this window cannot be driven through a run, stated rather than assumed.

    The fake acceptance session wires no measurement port, so the controls above
    resolve closed here. The run itself is covered against the arithmetic ports
    in the measurement service tests; what this file establishes is that the
    surface is attached to it.
    """
    assert window.service._state.measured_qualified is False
    assert window.service.resolve("calibration.measure").disposition is not ActionDisposition.ENABLED
