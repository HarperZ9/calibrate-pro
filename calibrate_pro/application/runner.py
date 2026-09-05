"""The single path every session action takes to reach the action boundary.

One place resolves the action, one place wraps its value, one place learns
whether the diagnostic journal is healthy. A surface that wants to do something
calls a service method; the service method calls :meth:`SessionActionRunner.run`
and nothing else. There is no second route, so an action cannot be performed
without first being resolved against the manifest.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TypeVar

from calibrate_pro.application.actions import (
    ActionClassification,
    ActionDisposition,
    ActionRegistry,
    ResolvedAction,
)
from calibrate_pro.application.outcomes import (
    ActionBoundary,
    ActionError,
    ActionFailure,
    ActionOutcome,
    ActionSuccess,
    CorrelationIdFactory,
)
from calibrate_pro.application.session import SessionState

T = TypeVar("T")

#: Every journal-health failure the boundary can return carries this category.
#: Reading it is how the session learns the journal stopped accepting records,
#: without writing a probe record of its own and without reserving an ID it
#: would then have to explain.
_DIAGNOSTICS_CATEGORY = "diagnostics"

ACTION_NOT_AVAILABLE = "ACTION_NOT_AVAILABLE"
_DEFAULT_UNAVAILABLE_SUMMARY = "This action is not available in the current session state."
_DEFAULT_NEXT_ACTION = "Complete the earlier steps this action depends on."


class IssuedCorrelationId:
    """Remember the correlation ID the boundary issued for the running action.

    The boundary requires the operation to return an outcome carrying the
    invocation's own correlation ID, but it calls the operation with no
    arguments. It also calls the factory exactly once, before the operation
    starts. Wrapping the factory is therefore enough to hand the ID to the
    operation, and the runner clears it afterwards so a later read cannot pick
    up an ID belonging to an invocation that already finished.

    The slot is per thread. The boundary issues the ID and runs the operation on
    one thread, so two invocations running at once would otherwise overwrite each
    other's ID and produce an outcome stamped with another invocation's identity.
    """

    def __init__(self, factory: CorrelationIdFactory) -> None:
        self._factory = factory
        self._issued = threading.local()

    def __call__(self) -> str:
        issued = self._factory()
        self._issued.value = issued if type(issued) is str else None
        return issued

    @property
    def current(self) -> str:
        value = getattr(self._issued, "value", None)
        if value is None:
            raise RuntimeError("no correlation ID has been issued for this invocation")
        return value

    def release(self) -> None:
        self._issued.value = None


class SessionActionRunner:
    """Resolve, invoke, and journal one action against one session."""

    def __init__(
        self,
        state: SessionState,
        registry: ActionRegistry,
        boundary: ActionBoundary,
        correlation_ids: IssuedCorrelationId,
    ) -> None:
        self._state = state
        self._registry = registry
        self._boundary = boundary
        self._correlation_ids = correlation_ids

    def run(self, action_id: str, operation: Callable[[], T]) -> ActionOutcome[T]:
        """Run one action, or answer why it was refused.

        The stage is read once, before anything happens, and is the stage the
        outcome and its journal record carry. An operation that advances the
        workflow is still recorded against the stage it was permitted from.
        """
        stage = self._state.stage

        def guarded() -> ActionOutcome[T]:
            self.require_enabled(action_id)
            value = operation()
            return ActionSuccess(
                action_id=action_id,
                correlation_id=self._correlation_ids.current,
                stage=stage,
                value=value,
            )

        try:
            outcome = self._boundary.invoke(action_id, stage, guarded)
        finally:
            self._correlation_ids.release()
        self._state.journal_ready = not (
            isinstance(outcome, ActionError) and outcome.category == _DIAGNOSTICS_CATEGORY
        )
        return outcome

    def resolve(self, action_id: str) -> ResolvedAction:
        """Ask the manifest what this action is right now.

        Surfaces call this to decide whether a control is enabled, disabled, or
        hidden, and they read the same answer the runner enforces. One resolver
        serves both, so a control cannot be offered for an action that would be
        refused.
        """
        return self._registry.resolve(action_id, self._state.to_context())

    def action_ids(self) -> frozenset[str]:
        """Every action the manifest declares, for a surface that enumerates."""
        return self._registry.action_ids

    def classification(self, action_id: str) -> ActionClassification | None:
        """Report what kind of effect one action has, for a surface's own rule."""
        return self._registry.classification_of(action_id)

    def require_enabled(self, action_id: str) -> None:
        """Refuse an action the manifest does not currently enable.

        The refusal reuses the resolver's own reason text, so what the operator
        reads after attempting an action matches what a disabled control would
        have told them beforehand.
        """
        resolved = self.resolve(action_id)
        if resolved.disposition is ActionDisposition.ENABLED:
            return
        raise ActionFailure(
            code=ACTION_NOT_AVAILABLE,
            summary=resolved.reason or _DEFAULT_UNAVAILABLE_SUMMARY,
            retryable=False,
            next_action=_DEFAULT_NEXT_ACTION,
            category="policy",
        )


__all__ = [
    "ACTION_NOT_AVAILABLE",
    "IssuedCorrelationId",
    "SessionActionRunner",
]
