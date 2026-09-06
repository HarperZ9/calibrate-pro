"""What a session does when a surface asks it for a test pattern.

This lane produces nothing. No file is written, no panel control moves, no
evidence is recorded, and the workflow stage does not advance. That makes the
things worth testing here narrow and specific: which display the window is
opened on, what happens on every path that does not reach a window, and whether
the window is closed afterwards.

The last one is the reason the lane closes in a finally. A pattern window is
frameless, fullscreen, and on top of everything else. One left open by a
refusal is not a failed action, it is a machine the operator has to reach for
the power button on.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from calibrate_pro.application.outcomes import ActionError, ActionOutcome, ActionSuccess
from calibrate_pro.application.pattern_surface import PatternPresentation
from calibrate_pro.application.refusals import NO_SUCH_PATTERN, PATTERN_SURFACE_REFUSED
from calibrate_pro.application.runner import ACTION_NOT_AVAILABLE
from calibrate_pro.application.service import FunctionalRecoveryService
from calibrate_pro.application.session import SessionState
from calibrate_pro.workflow import WorkflowStage
from tests.monitor_control_support import DISPLAY_ID
from tests.pattern_surface_support import FakeSurface, FakeSurfaceSource, build_pattern_service


def succeeded(outcome: ActionOutcome[PatternPresentation]) -> PatternPresentation:
    assert isinstance(outcome, ActionSuccess), f"expected a success, got {outcome}"
    return outcome.value


def refused(outcome: ActionOutcome[object]) -> ActionError:
    assert isinstance(outcome, ActionError), f"expected a refusal, got {outcome}"
    return outcome


def detected(service: FunctionalRecoveryService) -> FunctionalRecoveryService:
    """Run detection, which is what selects the display a pattern opens on."""
    assert isinstance(service.detect(), ActionSuccess)
    return service


# -- the path that reaches a window ----------------------------------------------


def test_the_window_is_opened_on_the_display_this_session_selected(tmp_path: Path) -> None:
    """A pattern on the wrong monitor is a judgement about a display nobody chose.

    Nothing downstream of the window could notice that, because every fact the
    presentation carries would be true of the wrong screen too. So the id the
    session holds is read back off the source that was asked to open.
    """
    source = FakeSurfaceSource(FakeSurface())
    service = detected(build_pattern_service(tmp_path, source))

    presentation = succeeded(service.show_test_pattern("pluge"))

    assert source.opened == [DISPLAY_ID]
    assert presentation.qualification.display_id == DISPLAY_ID
    assert presentation.pattern_id == "pluge"


def test_showing_a_pattern_advances_nothing_and_writes_nothing(tmp_path: Path) -> None:
    """The one lane in this product that produces no artefact, and says so.

    A pattern is judged by a person and leaves nothing behind. An action that
    moved the workflow forward would let a later stage read a pattern having
    been shown as a step having been completed, which is a claim nobody made.
    The directory check is there because the other lanes all write into it.
    """
    service = detected(build_pattern_service(tmp_path, FakeSurfaceSource(FakeSurface())))
    before = service.stage

    outcome = service.show_test_pattern("black")

    assert isinstance(outcome, ActionSuccess)
    assert service.stage == before == WorkflowStage.METHOD
    assert [entry.name for entry in tmp_path.iterdir()] == ["diagnostics"]


def test_the_window_is_closed_when_the_operator_dismisses_it(tmp_path: Path) -> None:
    surface = FakeSurface()
    service = detected(build_pattern_service(tmp_path, FakeSurfaceSource(surface)))

    succeeded(service.show_test_pattern("white"))

    assert surface.closes == 1


def test_a_second_pattern_opens_a_second_window(tmp_path: Path) -> None:
    """Nothing is held between calls, so a closed window is not reopened."""
    source = FakeSurfaceSource(FakeSurface())
    service = detected(build_pattern_service(tmp_path, source))

    succeeded(service.show_test_pattern("grey"))
    succeeded(service.show_test_pattern("grey-ramp"))

    assert source.opened == [DISPLAY_ID, DISPLAY_ID]


# -- the paths that do not ------------------------------------------------------


def test_a_session_with_no_display_selected_opens_nothing(tmp_path: Path) -> None:
    """A surface is wired and no display is chosen, so the resolver answers.

    The gate is ahead of the action, so the refusal arrives with no window on
    screen. That is the whole reason it sits where it does: a window opened and
    then closed again is a flash on a panel somebody is judging black on.
    """
    source = FakeSurfaceSource(FakeSurface())
    service = build_pattern_service(tmp_path, source)

    error = refused(service.show_test_pattern("pluge"))

    assert error.code == ACTION_NOT_AVAILABLE
    assert "selected display" in error.summary
    assert source.opened == []


def test_a_session_with_no_surface_wired_is_declined_by_the_manifest(tmp_path: Path) -> None:
    """A display is chosen and no surface is wired, and the same gate answers.

    This is the machine with no window toolkit installed. The action layer is
    never entered, so what the operator reads is the reason the manifest
    carries, which is the same text the menu entry renders as a tooltip.
    """
    service = detected(build_pattern_service(tmp_path))

    error = refused(service.show_test_pattern("pluge"))

    assert error.code == ACTION_NOT_AVAILABLE
    assert "pattern surface" in error.summary


def test_the_lane_needs_both_a_surface_and_a_display_and_neither_alone(tmp_path: Path) -> None:
    """The capability behind that gate, stated as its own truth table.

    Deliberately shaped unlike every other capability in this session, which
    all pair a wired route with a probed panel capability. A pattern asks
    nothing of the panel: it writes no file, moves no control, and produces no
    evidence, so a probe answering would let a passing gate be read as proof of
    something this lane never establishes.
    """
    state = SessionState()

    assert not state.patterns_qualified

    state.patterns_route = True
    assert not state.patterns_qualified

    state.patterns_route = False
    state.selected_display_id = DISPLAY_ID
    assert not state.patterns_qualified

    state.patterns_route = True
    assert state.patterns_qualified


def test_a_pattern_name_this_build_does_not_carry_never_reaches_a_window(tmp_path: Path) -> None:
    """The name is resolved before the port, so a typo opens nothing."""
    source = FakeSurfaceSource(FakeSurface())
    service = detected(build_pattern_service(tmp_path, source))

    error = refused(service.show_test_pattern("gradient-sweep"))

    assert error.code == NO_SUCH_PATTERN
    assert "gradient-sweep" in error.summary
    assert source.opened == []


def test_a_surface_that_cannot_be_opened_is_reported_with_what_was_tried(tmp_path: Path) -> None:
    """The toolkit was there when the route was wired and gone at the open.

    Retryable, because every way this fails is a state of the machine an
    operator can change. The reason arrives from the source unchanged, because
    a generic message would not say which of them it was.
    """
    source = FakeSurfaceSource(reason="the desktop no longer has that screen")
    service = detected(build_pattern_service(tmp_path, source))

    error = refused(service.show_test_pattern("pluge"))

    assert error.code == PATTERN_SURFACE_REFUSED
    assert error.summary == "the desktop no longer has that screen"
    assert error.retryable


def test_a_surface_that_cannot_carry_the_pattern_is_closed_before_the_refusal(tmp_path: Path) -> None:
    """The window is up when the refusal happens, and it does not stay up.

    A crosshatch on a scaled surface is the case: the window opens, reports its
    ratio, and the pattern is withheld. Without the close in a finally the
    operator is left looking at a blank fullscreen window with the refusal
    printed behind it.
    """
    surface = FakeSurface(pixel_ratio=1.5)
    service = detected(build_pattern_service(tmp_path, FakeSurfaceSource(surface)))

    error = refused(service.show_test_pattern("crosshatch"))

    assert error.code == PATTERN_SURFACE_REFUSED
    assert "one pixel wide" in error.summary
    assert surface.closes == 1
    assert surface.presented == []


def test_a_surface_too_small_for_the_pattern_is_closed_before_the_refusal(tmp_path: Path) -> None:
    """The other refusal taken after the window exists, closed the same way."""
    surface = FakeSurface(device_pixels=(300, 200))
    service = detected(build_pattern_service(tmp_path, FakeSurfaceSource(surface)))

    error = refused(service.show_test_pattern("pluge"))

    assert error.code == PATTERN_SURFACE_REFUSED
    assert "needs a surface of at least" in error.summary
    assert surface.closes == 1


@pytest.mark.parametrize("pattern_id", ["", "   ", "PLUGE"])
def test_a_name_that_is_not_an_id_is_refused_rather_than_guessed_at(tmp_path: Path, pattern_id: str) -> None:
    """No case folding and no nearest match. An id is a name that was typed."""
    source = FakeSurfaceSource(FakeSurface())
    service = detected(build_pattern_service(tmp_path, source))

    assert refused(service.show_test_pattern(pattern_id)).code == NO_SUCH_PATTERN
    assert source.opened == []
