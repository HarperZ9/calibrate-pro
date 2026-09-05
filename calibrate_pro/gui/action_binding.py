"""Binding a surface control to the action the session would actually perform.

Controls used to call workers directly. A button could therefore be offered for
something the session would refuse, and the operator learned that only after
clicking it. This module removes that gap: one binder holds every control, asks
the session's resolver what each action is right now, and renders that answer.

The binder decides nothing. It reads the same ResolvedAction the runner
enforces, so a control is enabled only when performing it would be permitted,
and the text on a disabled control is the resolver's own reason rather than a
second explanation written for the UI.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any, Protocol, runtime_checkable

from calibrate_pro.application.actions import ActionDisposition, ResolvedAction
from calibrate_pro.application.outcomes import ActionError, ActionOutcome, ActionSuccess

logger = logging.getLogger(__name__)

#: What a control says when the resolver disabled it without giving a reason.
#: The resolver almost always supplies one; this covers the case where it does
#: not, so a disabled control is never silently inexplicable.
DEFAULT_DISABLED_REASON = "Not available in the current session state."

#: What the operator is told when an operation raised instead of returning an
#: outcome. The message says the action did not complete, which is the only
#: thing that can be claimed without knowing where it stopped.
UNEXPECTED_FAILURE_MESSAGE = "The action did not complete. See the diagnostics log."

#: How restrictive each disposition is. Combining two answers takes the higher
#: number, which is what makes a restriction one-way: a surface can narrow what
#: the resolver allows and can never widen it.
_SEVERITY = {
    ActionDisposition.ENABLED: 0,
    ActionDisposition.DISABLED: 1,
    ActionDisposition.HIDDEN: 2,
}


@runtime_checkable
class Control(Protocol):
    """The part of a Qt control the binder touches.

    Both QAction and QWidget answer this, and so does a plain object in a test,
    which is what lets the binding rules be proved without a running
    QApplication.
    """

    def setEnabled(self, enabled: bool) -> None: ...

    def setVisible(self, visible: bool) -> None: ...

    def setToolTip(self, text: str) -> None: ...


class Session(Protocol):
    """The part of the session service a binder uses."""

    def resolve(self, action_id: str) -> ResolvedAction: ...


Reporter = Callable[[str, str], None]

#: A surface's own narrowing rule, applied to every action it binds. It reads
#: the resolver's answer and returns the answer it would prefer; only a stricter
#: preference has any effect. Preview mode is the reason this exists: a build
#: that must not touch a display narrows every action that could, without the
#: session having to carry a second notion of what is permitted.
Restriction = Callable[[ResolvedAction], ResolvedAction]

#: What an operation returns. ``None`` means the operator withdrew before
#: anything was attempted, such as closing a file dialog, which is neither a
#: success to report nor a refusal to explain.
Operation = Callable[[], "ActionOutcome[Any] | None"]


@dataclass(frozen=True)
class SurfaceBinding:
    """One control, the action it stands for, and what performing it runs.

    ``action_id`` is what the resolver is asked about. ``operation`` is what
    runs when the control is used, and it must go through the session so the
    action is resolved, journaled, and answered as an outcome. Keeping the two
    fields separate is deliberate: the identity a control renders and the call
    it makes are stated once each, in the same place, where they can be read
    together.
    """

    action_id: str
    control: Control
    operation: Operation
    on_success: Callable[[Any], None] | None = None
    on_refusal: Callable[[ActionError], None] | None = None
    #: Whether a HIDDEN disposition removes the control. A menu entry is hidden;
    #: a control that anchors a page's layout is disabled in place instead.
    hides: bool = True
    #: Every disposition rendered so far, so a surface can read what it is
    #: showing without re-resolving and getting a newer answer than it displays.
    rendered: list[ResolvedAction] = field(default_factory=list, compare=False)

    @property
    def last_resolved(self) -> ResolvedAction | None:
        return self.rendered[-1] if self.rendered else None


class ActionBinder:
    """Hold every bound control and keep all of them in step with the session."""

    def __init__(
        self,
        service: Session,
        *,
        report: Reporter | None = None,
        restrict: Restriction | None = None,
    ) -> None:
        self._service = service
        self._report: Reporter = report or _discard
        self._restrict = restrict
        self._bindings: list[SurfaceBinding] = []

    @property
    def bindings(self) -> tuple[SurfaceBinding, ...]:
        return tuple(self._bindings)

    def bind(
        self,
        action_id: str,
        control: Control,
        operation: Operation,
        *,
        on_success: Callable[[Any], None] | None = None,
        on_refusal: Callable[[ActionError], None] | None = None,
        hides: bool = True,
        connect: bool = True,
    ) -> SurfaceBinding:
        """Register one control and wire its trigger to the action.

        The control is rendered immediately, so a surface never shows a control
        in a state the session has not been asked about.
        """
        binding = SurfaceBinding(
            action_id=action_id,
            control=control,
            operation=operation,
            on_success=on_success,
            on_refusal=on_refusal,
            hides=hides,
        )
        self._bindings.append(binding)
        if connect:
            signal = _trigger_signal(control)
            if signal is None:
                raise TypeError(f"{action_id}: control exposes no triggered or clicked signal")
            signal.connect(lambda *_ignored, bound=binding: self.invoke(bound))
        self.render(binding)
        return binding

    def refresh(self) -> None:
        """Re-resolve every bound control against the session's current state."""
        for binding in self._bindings:
            self.render(binding)

    def render(self, binding: SurfaceBinding) -> ResolvedAction:
        """Ask the resolver about one action and show exactly what it answered."""
        resolved = self.disposition_of(binding.action_id)
        control = binding.control
        enabled = resolved.disposition is ActionDisposition.ENABLED
        hidden = resolved.disposition is ActionDisposition.HIDDEN
        control.setEnabled(enabled)
        control.setVisible(not (hidden and binding.hides))
        control.setToolTip("" if enabled else (resolved.reason or DEFAULT_DISABLED_REASON))
        binding.rendered.append(resolved)
        return resolved

    def disposition_of(self, action_id: str) -> ResolvedAction:
        """Answer for one action, with this surface's own narrowing applied.

        The resolver decides first. A restriction can then make the answer
        stricter, and the combining rule refuses to let it do anything else, so
        a surface cannot enable an action the session would refuse.
        """
        return self._narrow(self._service.resolve(action_id))

    def _narrow(self, resolved: ResolvedAction) -> ResolvedAction:
        """Combine the resolver's answer with this surface's restriction."""
        if self._restrict is None:
            return resolved
        proposed = self._restrict(resolved)
        if _SEVERITY[proposed.disposition] <= _SEVERITY[resolved.disposition]:
            return resolved
        return replace(
            resolved,
            disposition=proposed.disposition,
            reason=proposed.reason or resolved.reason,
        )

    def invoke(self, binding: SurfaceBinding) -> ActionOutcome[Any] | None:
        """Perform one bound action and report what came back.

        The session decides whether the action is allowed: the operation goes
        through it, and it resolves the action again and refuses if the state
        moved between rendering the control and using it. The one thing decided
        here is this surface's own restriction, because nothing downstream knows
        about it. An action the resolver would allow and the restriction forbids
        is answered here and never attempted.
        """
        resolved = self._service.resolve(binding.action_id)
        restricted = self._narrow(resolved)
        if restricted.disposition is not resolved.disposition:
            self._report(restricted.reason or DEFAULT_DISABLED_REASON, "warning")
            self.refresh()
            return None

        try:
            outcome = binding.operation()
        except Exception:
            # Reported rather than re-raised: a Qt slot has nowhere to raise to,
            # and an operator who used a control is owed an answer. The
            # traceback goes to the log with the action that produced it.
            logger.exception("action %s raised instead of returning an outcome", binding.action_id)
            self._report(UNEXPECTED_FAILURE_MESSAGE, "warning")
            self.refresh()
            return None

        if outcome is None:
            # The operator withdrew before the action was attempted. Nothing
            # happened, so there is nothing to report and nothing to explain.
            self.refresh()
            return None

        if isinstance(outcome, ActionSuccess):
            if binding.on_success is not None:
                binding.on_success(outcome.value)
        elif isinstance(outcome, ActionError):
            self._refuse(binding, outcome)
        else:
            logger.error("action %s returned %r, which is not an outcome", binding.action_id, outcome)
            self._report(UNEXPECTED_FAILURE_MESSAGE, "warning")
        self.refresh()
        return outcome

    def _refuse(self, binding: SurfaceBinding, error: ActionError) -> None:
        if binding.on_refusal is not None:
            binding.on_refusal(error)
            return
        self._report(refusal_message(error), "warning")


def refusal_message(error: ActionError) -> str:
    """Read a refusal as one line an operator can act on."""
    if error.next_action:
        return f"{error.summary} {error.next_action}"
    return error.summary


def _trigger_signal(control: Control) -> Any:
    """Find the signal a control emits when it is used.

    QAction emits ``triggered`` and a button emits ``clicked``. Looking for both
    keeps the binder usable from a menu and from a page without either surface
    having to say which kind of control it holds.
    """
    for name in ("triggered", "clicked"):
        signal = getattr(control, name, None)
        if signal is not None and hasattr(signal, "connect"):
            return signal
    return None


def _discard(message: str, level: str) -> None:
    """Drop a report when no surface offered somewhere to put it."""
    logger.debug("unreported %s: %s", level, message)


__all__ = [
    "DEFAULT_DISABLED_REASON",
    "UNEXPECTED_FAILURE_MESSAGE",
    "ActionBinder",
    "Control",
    "Operation",
    "Restriction",
    "Session",
    "SurfaceBinding",
    "refusal_message",
]
