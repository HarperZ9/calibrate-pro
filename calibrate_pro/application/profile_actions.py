"""The session actions that read back and copy bundles already published.

A published bundle is finished work. Nothing in this module can change the plan,
break the seal, or move the workflow stage, so it sits beside the calibration
session rather than inside it, and the service inherits it. A surface still
calls one object.

The one gate worth naming is on export. A profile may be copied only after its
files have been read back and checked against the manifest that came with them,
which is what ``inspect_profile`` does and the only thing that opens it.
"""

from __future__ import annotations

from pathlib import Path

from calibrate_pro.application.assets import ExportBundle
from calibrate_pro.application.exporting import copy_selected_profile
from calibrate_pro.application.outcomes import ActionOutcome
from calibrate_pro.application.profiles import (
    ProfileInspection,
    ProfileListing,
    discover_profiles,
    reparse_profile,
)
from calibrate_pro.application.refusals import no_such_profile
from calibrate_pro.application.runner import SessionActionRunner
from calibrate_pro.application.session import SessionState


class ProfileActions:
    """Listing, checking, and copying the bundles this application wrote."""

    _state: SessionState
    _runner: SessionActionRunner

    def list_profiles(self) -> ActionOutcome[ProfileListing]:
        """Read back every bundle published under the chosen export directory.

        A profile here is a bundle this application wrote, so the place to look
        is the directory it writes to. With no directory chosen the listing says
        that, rather than reporting an empty folder.
        """
        return self._runner.run("profile.list.refresh", self._list_profiles)

    def _list_profiles(self) -> ProfileListing:
        state = self._state
        listing = discover_profiles(state.export_directory if state.export_directory_valid else None)
        state.profiles = listing.profiles
        selected = state.selected_profile
        if selected is not None and selected.record not in listing.profiles:
            state.selected_profile = None
        return listing

    def inspect_profile(self, directory: str) -> ActionOutcome[ProfileInspection]:
        """Re-hash one published bundle against the manifest it carries.

        Selecting a profile is not enough to export it. The files have to still
        be the files its manifest describes, and that answer is recomputed on
        every selection rather than remembered from an earlier one.
        """
        return self._runner.run("profile.inspect", lambda: self._inspect_profile(directory))

    def _inspect_profile(self, directory: str) -> ProfileInspection:
        state = self._state
        record = next((entry for entry in state.profiles if entry.directory == directory), None)
        if record is None:
            raise no_such_profile()
        inspection = reparse_profile(record)
        state.selected_profile = inspection
        return inspection

    def export_profile(self, directory: str | Path) -> ActionOutcome[ExportBundle]:
        """Copy the inspected profile, byte for byte, into a chosen directory."""
        return self._runner.run("profile.export", lambda: copy_selected_profile(self._state, directory))


__all__ = ["ProfileActions"]
