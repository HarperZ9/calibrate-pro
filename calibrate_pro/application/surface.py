"""What a surface needs from a session, separated from the calibration work.

A window renders controls, switches pages, and reports refusals. None of that
is calibration, but all of it is still gated by the same manifest and recorded
in the same journal. Keeping it here lets the session service stay about the
workflow, and lets a surface read one small contract rather than the whole
service.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import NoReturn, TypeVar

from calibrate_pro.application.actions import ActionClassification, ResolvedAction
from calibrate_pro.application.outcomes import ActionFailure, ActionOutcome
from calibrate_pro.application.refusals import no_handler, not_a_ui_action
from calibrate_pro.application.runner import SessionActionRunner

T = TypeVar("T")


class SurfaceActions:
    """The action plumbing every surface uses, whatever session it is driving."""

    _runner: SessionActionRunner

    def resolve(self, action_id: str) -> ResolvedAction:
        """Report what one action is right now, for rendering a control."""
        return self._runner.resolve(action_id)

    def action_ids(self) -> frozenset[str]:
        """Every action this build declares, for a surface that lists them.

        A window binds the controls it was written with. A report over the whole
        manifest has to ask what the manifest holds, and asking here keeps it
        from loading a second copy that could answer differently.
        """
        return self._runner.action_ids()

    def classification(self, action_id: str) -> ActionClassification | None:
        """Report what kind of effect one action has, or None if unknown."""
        return self._runner.classification(action_id)

    def perform_ui(self, action_id: str, effect: Callable[[], T]) -> ActionOutcome[T]:
        """Run one interface-only action through the gate every action passes.

        Switching a page, opening the about box, and closing the window change
        nothing outside this process, so their work lives in the surface rather
        than in the session. They are still actions: the manifest decides
        whether they are offered, and the journal records that they happened.

        The classification check is what keeps this from becoming a way around
        the typed session methods. An action that writes a file or touches a
        display is refused here even when the manifest would enable it.
        """
        if self._runner.classification(action_id) is not ActionClassification.UI_ONLY:
            return self._runner.run(action_id, lambda: _raise(not_a_ui_action(action_id)))
        return self._runner.run(action_id, effect)

    def unhandled(self, action_id: str) -> ActionOutcome[object]:
        """Answer for an action this build offers no way to perform.

        A surface still binds these controls, because the manifest is what
        decides they are hidden or disabled and the surface should read that
        decision rather than carry its own copy of it.
        """
        return self._runner.run(action_id, lambda: _raise(no_handler(action_id)))


def _raise(failure: ActionFailure) -> NoReturn:
    """Raise a prepared refusal from inside a lambda."""
    raise failure


__all__ = ["SurfaceActions"]
