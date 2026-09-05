"""Reaching the redacted journal every action already writes to.

A session records each action it runs, redacted, before that action is allowed
to report success. Until an operator can read those records back, the writing is
a private habit rather than a support story, so this module is the seam between
the journal on disk and the three actions the manifest declares for it: preview
what a bundle would contain, publish that exact bundle, and open the folder it
lives in.

Nothing here decides what is safe to publish. The preview names each member and
its digest, creation republishes those bytes under the token that preview
issued, and both answers come from the bundle manager. What an operator is shown
is what an operator sends.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from calibrate_pro.application.journal import (
    BundlePreview,
    DiagnosticBundleManager,
    DiagnosticBundleReceipt,
    FolderOpener,
)
from calibrate_pro.application.outcomes import ActionOutcome
from calibrate_pro.application.refusals import policy_refusal
from calibrate_pro.application.runner import SessionActionRunner
from calibrate_pro.application.session import SessionState

NO_DIAGNOSTIC_BUNDLES = "NO_DIAGNOSTIC_BUNDLES"

_NO_MANAGER_SUMMARY = "This session was built without a diagnostic bundle manager."
_NO_MANAGER_NEXT = "Start the application again so the session opens its journal."


def windows_folder_opener() -> FolderOpener | None:
    """The opener this platform can offer, or nothing for one that cannot.

    Returning ``None`` rather than a callable that fails later is what lets the
    manager refuse before it has done anything, with a sentence about the
    environment instead of a sentence about an error.
    """
    if sys.platform != "win32":
        return None
    startfile = getattr(os, "startfile", None)
    if startfile is None:
        return None

    def open_folder(folder: Path) -> None:
        startfile(folder)

    return open_folder


def preview_bundle(state: SessionState, manager: DiagnosticBundleManager) -> BundlePreview:
    """Take one preview and record that its token is live.

    The token itself stays in the manager and in the hand of whoever asked. The
    session keeps only the fact that one is outstanding, because that is what
    the resolver reads to decide whether creation is offered.
    """
    preview = manager.preview()
    state.diagnostic_bundle_preview_live = True
    return preview


def create_bundle(
    state: SessionState,
    manager: DiagnosticBundleManager,
    token: str,
    destination: Path,
) -> DiagnosticBundleReceipt:
    """Publish the previewed bundle, and retire the token whatever happens.

    A token is spent by the attempt rather than by the success. Clearing the
    flag in a ``finally`` is what stops a failed creation from leaving the
    action enabled against a grant the manager has already dropped.
    """
    try:
        return manager.create(token, destination)
    finally:
        state.diagnostic_bundle_preview_live = False


class DiagnosticsActions:
    """The three actions that expose the journal, and none that write to it."""

    _state: SessionState
    _runner: SessionActionRunner
    _bundles: DiagnosticBundleManager | None

    def preview_diagnostics(self) -> ActionOutcome[BundlePreview]:
        """List what a diagnostic bundle would contain, before one is written.

        The preview is journalled before its token is handed back, so a bundle
        an operator holds always has a record of the moment it was offered.
        """
        return self._runner.run_diagnostic_preview(
            "diagnostics.bundle.preview",
            self._preview_diagnostics,
        )

    def _preview_diagnostics(self) -> BundlePreview:
        return preview_bundle(self._state, self._manager())

    def create_diagnostics_bundle(
        self,
        token: str,
        destination: str | Path,
    ) -> ActionOutcome[DiagnosticBundleReceipt]:
        """Write the previewed bundle to a path the operator named.

        The token comes from a preview taken earlier in this same session. It
        cannot come from another process, and the manager refuses one whose
        journal has changed since the preview read it.
        """
        return self._runner.run(
            "diagnostics.bundle.create",
            lambda: create_bundle(self._state, self._manager(), token, Path(destination)),
        )

    def open_diagnostics_folder(self) -> ActionOutcome[None]:
        """Open the folder the journal is kept in, on a platform that can."""
        return self._runner.run("diagnostics.folder.open", self._open_diagnostics_folder)

    def _open_diagnostics_folder(self) -> None:
        self._manager().open_folder("diagnostics.folder.open")

    @property
    def diagnostics_folder(self) -> Path | None:
        """Where this session keeps its journal, or nothing if it kept none.

        A plain read of a configured path, so it takes no receipt and refuses
        nothing. Returning ``None`` rather than raising is what keeps a surface
        free to print the folder beside a refusal it is already showing.
        """
        return None if self._bundles is None else self._bundles.folder

    def _manager(self) -> DiagnosticBundleManager:
        """The bundle manager this session was built with, or a refusal.

        A session assembled without one can still resolve the three actions,
        because the manifest answers from policy rather than from wiring. The
        refusal is raised inside the action so it is journalled and worded like
        every other refusal, rather than returned around the boundary.
        """
        manager = self._bundles
        if manager is None:
            raise policy_refusal(NO_DIAGNOSTIC_BUNDLES, _NO_MANAGER_SUMMARY, _NO_MANAGER_NEXT)
        return manager


__all__ = [
    "NO_DIAGNOSTIC_BUNDLES",
    "DiagnosticsActions",
    "create_bundle",
    "preview_bundle",
    "windows_folder_opener",
]
