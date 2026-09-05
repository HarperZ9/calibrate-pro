"""The session preferences a settings surface is allowed to change.

The window used to write these into the application's own configuration store,
where nothing read them back. A preference that survives being set and changes
nothing is worse than an absent one, because it reports success for work that
never happened.

Both actions here run through the runner, so each is resolved against the
manifest, journalled, and answered as an outcome. What the operator chose is
what the next generated bundle and the next saved report use.
"""

from __future__ import annotations

from pathlib import Path

from calibrate_pro.application.assets import SUPPORTED_LUT_SIZES
from calibrate_pro.application.exporting import choose_directory
from calibrate_pro.application.outcomes import ActionFailure, ActionOutcome
from calibrate_pro.application.refusals import policy_refusal
from calibrate_pro.application.results import ExportDirectory
from calibrate_pro.application.runner import SessionActionRunner
from calibrate_pro.application.session import SessionState

UNSUPPORTED_LUT_SIZE = "UNSUPPORTED_LUT_SIZE"


def unsupported_lut_size(size: int) -> ActionFailure:
    """Refuse a grid this build cannot generate, and name the ones it can."""
    offered = ", ".join(str(value) for value in sorted(SUPPORTED_LUT_SIZES))
    return policy_refusal(
        UNSUPPORTED_LUT_SIZE,
        f"A {size}-point LUT grid is not one this build generates.",
        f"Choose one of the grids this build generates: {offered}.",
    )


class PreferenceActions:
    """Where a session writes its reports, and how fine its next LUT grid is."""

    _state: SessionState
    _runner: SessionActionRunner
    _lut_size: int

    def set_export_directory(self, directory: str | Path) -> ActionOutcome[ExportDirectory]:
        """Record where this session writes reports and exports.

        A directory that cannot be written to is recorded as rejected rather
        than dropped, so the resolver can keep every export closed and name the
        folder that closed them.
        """
        return self._runner.run("settings.output_directory", lambda: choose_directory(self._state, directory))

    def set_lut_size(self, size: int) -> ActionOutcome[int]:
        """Choose the grid the next generated LUT is built on.

        The size applies at the next generation. A sealed plan keeps the grid it
        was built with and records that grid in its own manifest, so choosing a
        different one here cannot restate what a published bundle holds.
        """
        return self._runner.run("settings.lut_size", lambda: self._accept_lut_size(size))

    @property
    def lut_size(self) -> int:
        """The grid the next generation would use, for a surface that shows it.

        A plain read of a configured value, so it takes no receipt and refuses
        nothing. A surface that opens on this shows the grid the session holds
        rather than a number the surface chose for itself.
        """
        return self._lut_size

    def _accept_lut_size(self, size: int) -> int:
        if size not in SUPPORTED_LUT_SIZES:
            raise unsupported_lut_size(size)
        self._lut_size = size
        return size


__all__ = [
    "UNSUPPORTED_LUT_SIZE",
    "PreferenceActions",
    "unsupported_lut_size",
]
