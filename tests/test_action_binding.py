"""The rules a bound control follows, proved without a running QApplication.

The binder is the only thing standing between a control and the session, so
what it does with each answer is worth checking directly. These tests drive it
against a stub session and a stub control, which is enough because the binder
touches a control through three methods and a session through one.
"""

from __future__ import annotations

from typing import Any

import pytest

from calibrate_pro.application.actions import ActionDisposition, ResolvedAction
from calibrate_pro.application.outcomes import ActionError, ActionSuccess
from calibrate_pro.gui.action_binding import (
    DEFAULT_DISABLED_REASON,
    UNEXPECTED_FAILURE_MESSAGE,
    ActionBinder,
    refusal_message,
)
from calibrate_pro.workflow import WorkflowStage

ACTION = "display.detect"


class Signal:
    """The part of a Qt signal the binder uses."""

    def __init__(self) -> None:
        self._slots: list[Any] = []

    def connect(self, slot: Any) -> None:
        self._slots.append(slot)

    def emit(self) -> None:
        for slot in tuple(self._slots):
            slot()


class Control:
    """A control that records the states it was put into."""

    def __init__(self) -> None:
        self.triggered = Signal()
        self.enabled: bool | None = None
        self.visible: bool | None = None
        self.tooltip: str | None = None

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = enabled

    def setVisible(self, visible: bool) -> None:
        self.visible = visible

    def setToolTip(self, text: str) -> None:
        self.tooltip = text


class Session:
    """A session whose answer for one action can be set by a test."""

    def __init__(
        self,
        disposition: ActionDisposition = ActionDisposition.ENABLED,
        reason: str | None = None,
    ) -> None:
        self.disposition = disposition
        self.reason = reason
        self.resolved: list[str] = []

    def resolve(self, action_id: str) -> ResolvedAction:
        self.resolved.append(action_id)
        return ResolvedAction(
            action_id=action_id,
            disposition=self.disposition,
            reason=self.reason,
            handler="stub",
        )


def success(value: object = "done") -> ActionSuccess[object]:
    return ActionSuccess(action_id=ACTION, correlation_id="c1", stage=WorkflowStage.DETECT, value=value)


def recorder(log: list[str], outcome: Any) -> Any:
    """Build an operation that notes it ran, then answers with one outcome."""

    def operation() -> Any:
        log.append(ACTION)
        return outcome() if callable(outcome) else outcome

    return operation


def refusal(summary: str = "Not now.", next_action: str | None = "Detect first.") -> ActionError:
    return ActionError(
        action_id=ACTION,
        code="ACTION_NOT_AVAILABLE",
        summary=summary,
        retryable=False,
        next_action=next_action,
        stage=WorkflowStage.DETECT,
        category="policy",
        correlation_id="c1",
        effect_state="none",
        published_artifact=None,
        apply_phase_flags=(),
        recovery_guarantee=None,
    )


@pytest.fixture
def reports() -> list[tuple[str, str]]:
    return []


def make(
    session: Session,
    reports: list[tuple[str, str]],
    **kwargs: Any,
) -> ActionBinder:
    return ActionBinder(
        session,
        report=lambda message, level: reports.append((message, level)),
        **kwargs,
    )


# -- rendering ---------------------------------------------------------------


def test_an_enabled_action_renders_an_enabled_control_with_no_tooltip(
    reports: list[tuple[str, str]],
) -> None:
    control = Control()
    make(Session(), reports).bind(ACTION, control, success)
    assert (control.enabled, control.visible, control.tooltip) == (True, True, "")


def test_a_disabled_action_shows_the_resolver_s_own_reason(reports: list[tuple[str, str]]) -> None:
    control = Control()
    session = Session(ActionDisposition.DISABLED, "Physical mutation is not qualified.")
    make(session, reports).bind(ACTION, control, success)
    assert control.enabled is False
    assert control.visible is True
    assert control.tooltip == "Physical mutation is not qualified."


def test_a_disabled_action_with_no_reason_still_explains_itself(
    reports: list[tuple[str, str]],
) -> None:
    control = Control()
    make(Session(ActionDisposition.DISABLED), reports).bind(ACTION, control, success)
    assert control.tooltip == DEFAULT_DISABLED_REASON


def test_a_hidden_action_removes_the_control_it_was_bound_to(
    reports: list[tuple[str, str]],
) -> None:
    control = Control()
    make(Session(ActionDisposition.HIDDEN), reports).bind(ACTION, control, success)
    assert (control.enabled, control.visible) == (False, False)


def test_a_control_that_anchors_a_layout_is_disabled_rather_than_removed(
    reports: list[tuple[str, str]],
) -> None:
    control = Control()
    make(Session(ActionDisposition.HIDDEN), reports).bind(ACTION, control, success, hides=False)
    assert (control.enabled, control.visible) == (False, True)


def test_binding_renders_before_the_operator_can_see_the_control(
    reports: list[tuple[str, str]],
) -> None:
    session = Session()
    control = Control()
    make(session, reports).bind(ACTION, control, success)
    assert session.resolved == [ACTION]
    assert control.enabled is True


def test_a_control_with_no_trigger_is_a_binding_error(reports: list[tuple[str, str]]) -> None:
    class Unwired:
        def setEnabled(self, enabled: bool) -> None: ...
        def setVisible(self, visible: bool) -> None: ...
        def setToolTip(self, text: str) -> None: ...

    with pytest.raises(TypeError, match="no triggered or clicked signal"):
        make(Session(), reports).bind(ACTION, Unwired(), success)  # type: ignore[arg-type]


def test_a_button_is_bound_through_clicked_when_it_has_no_triggered(
    reports: list[tuple[str, str]],
) -> None:
    class Button(Control):
        def __init__(self) -> None:
            super().__init__()
            del self.triggered
            self.clicked = Signal()

    button = Button()
    performed: list[str] = []
    make(Session(), reports).bind(ACTION, button, recorder(performed, success))
    button.clicked.emit()
    assert performed == [ACTION]


# -- performing --------------------------------------------------------------


def test_using_a_control_performs_the_action_and_reports_nothing(
    reports: list[tuple[str, str]],
) -> None:
    control = Control()
    seen: list[object] = []
    make(Session(), reports).bind(ACTION, control, success, on_success=seen.append)
    control.triggered.emit()
    assert seen == ["done"]
    assert reports == []


def test_a_refusal_is_reported_as_the_summary_and_the_next_action(
    reports: list[tuple[str, str]],
) -> None:
    control = Control()
    make(Session(), reports).bind(ACTION, control, refusal)
    control.triggered.emit()
    assert reports == [("Not now. Detect first.", "warning")]


def test_a_refusal_with_no_next_action_reports_only_what_happened() -> None:
    assert refusal_message(refusal(next_action=None)) == "Not now."


def test_a_binding_may_handle_its_own_refusal(reports: list[tuple[str, str]]) -> None:
    control = Control()
    caught: list[ActionError] = []
    make(Session(), reports).bind(ACTION, control, refusal, on_refusal=caught.append)
    control.triggered.emit()
    assert [error.code for error in caught] == ["ACTION_NOT_AVAILABLE"]
    assert reports == []


def test_withdrawing_before_the_action_is_attempted_reports_nothing(
    reports: list[tuple[str, str]],
) -> None:
    control = Control()
    seen: list[object] = []
    binder = make(Session(), reports)
    binding = binder.bind(ACTION, control, lambda: None, on_success=seen.append)
    assert binder.invoke(binding) is None
    assert (seen, reports) == ([], [])


def test_an_operation_that_raises_is_logged_and_answered_rather_than_propagated(
    reports: list[tuple[str, str]],
) -> None:
    control = Control()

    def explode() -> Any:
        raise RuntimeError("the worker died")

    binder = make(Session(), reports)
    binding = binder.bind(ACTION, control, explode)
    assert binder.invoke(binding) is None
    assert reports == [(UNEXPECTED_FAILURE_MESSAGE, "warning")]


def test_an_operation_that_returns_something_else_is_treated_as_a_defect(
    reports: list[tuple[str, str]],
) -> None:
    control = Control()
    binder = make(Session(), reports)
    wrong: Any = lambda: "not an outcome"  # noqa: E731
    binding = binder.bind(ACTION, control, wrong)
    binder.invoke(binding)
    assert reports == [(UNEXPECTED_FAILURE_MESSAGE, "warning")]


def test_every_control_is_re_rendered_after_any_action(reports: list[tuple[str, str]]) -> None:
    session = Session()
    first, second = Control(), Control()
    binder = make(session, reports)
    binder.bind(ACTION, first, success)
    binder.bind("calibration.generate", second, success)
    session.disposition = ActionDisposition.DISABLED
    first.triggered.emit()
    assert (first.enabled, second.enabled) == (False, False)


def test_the_rendered_history_is_what_the_surface_is_showing(
    reports: list[tuple[str, str]],
) -> None:
    session = Session()
    binder = make(session, reports)
    binding = binder.bind(ACTION, Control(), success)
    session.disposition = ActionDisposition.HIDDEN
    binder.refresh()
    assert binding.last_resolved is not None
    assert binding.last_resolved.disposition is ActionDisposition.HIDDEN
    assert len(binding.rendered) == 2


# -- restriction -------------------------------------------------------------


def disable_everything(resolved: ResolvedAction) -> ResolvedAction:
    return ResolvedAction(
        action_id=resolved.action_id,
        disposition=ActionDisposition.DISABLED,
        reason="This build performs no physical mutation.",
        handler=resolved.handler,
    )


def enable_everything(resolved: ResolvedAction) -> ResolvedAction:
    return ResolvedAction(
        action_id=resolved.action_id,
        disposition=ActionDisposition.ENABLED,
        reason=None,
        handler=resolved.handler,
    )


def test_a_restriction_narrows_an_action_the_resolver_would_allow(
    reports: list[tuple[str, str]],
) -> None:
    control = Control()
    make(Session(), reports, restrict=disable_everything).bind(ACTION, control, success)
    assert control.enabled is False
    assert control.tooltip == "This build performs no physical mutation."


def test_a_restriction_cannot_enable_what_the_resolver_refuses(
    reports: list[tuple[str, str]],
) -> None:
    control = Control()
    session = Session(ActionDisposition.DISABLED, "Action is unavailable during the detect stage.")
    make(session, reports, restrict=enable_everything).bind(ACTION, control, success)
    assert control.enabled is False
    assert control.tooltip == "Action is unavailable during the detect stage."


def test_a_restriction_cannot_reveal_what_the_resolver_hides(
    reports: list[tuple[str, str]],
) -> None:
    control = Control()
    session = Session(ActionDisposition.HIDDEN)
    make(session, reports, restrict=enable_everything).bind(ACTION, control, success)
    assert (control.enabled, control.visible) == (False, False)


def test_a_restricted_action_is_answered_without_being_attempted(
    reports: list[tuple[str, str]],
) -> None:
    performed: list[str] = []
    binder = make(Session(), reports, restrict=disable_everything)
    binding = binder.bind(ACTION, Control(), recorder(performed, success))
    assert binder.invoke(binding) is None
    assert performed == []
    assert reports == [("This build performs no physical mutation.", "warning")]


def test_an_action_the_resolver_refuses_still_reaches_the_session(
    reports: list[tuple[str, str]],
) -> None:
    """The session owns the refusal, so it is asked and it journals the attempt."""
    attempted: list[str] = []
    session = Session(ActionDisposition.DISABLED, "Not in this stage.")
    binder = make(session, reports, restrict=disable_everything)
    binding = binder.bind(ACTION, Control(), recorder(attempted, refusal))
    binder.invoke(binding)
    assert attempted == [ACTION]
