"""The session actions that put a published bundle into Windows colour management.

This is the last step of a calibration and the one this build used to leave to
the operator. A bundle on disk changes nothing: the ICC profile has to be
registered with the machine, attached to the display it was generated for, and
named as that display's default before any colour-managed application reads it.
Until this lane existed, a finished run ended with a folder and an instruction
to open the Windows colour management dialog by hand.

Only the bytes a manifest seals are installed. The ICC file is re-hashed against
the digest its own manifest recorded, and a bundle that has drifted is refused
rather than registered, so the profile the system holds is the profile this
application generated and not whatever is currently sitting at that path.

Only what this product installed can be removed. The name a bundle installs
under is derived from its manifest digest, and both the removal and the restore
refuse any name that is not one of those. A display carrying its vendor's own
profile keeps it through everything in this module.

Nothing here decides whether an action is offered. The manifest and the resolver
do that, and every method routes through the runner for it.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from calibrate_pro.application.assets import AssetFormat
from calibrate_pro.application.outcomes import ActionOutcome
from calibrate_pro.application.profiles import ProfileRecord
from calibrate_pro.application.refusals import (
    no_display_selected,
    no_profile_reading,
    no_such_asset,
    no_verified_profile,
    profile_seal_broken,
    profile_unreadable,
    system_profile_refused,
)
from calibrate_pro.application.runner import SessionActionRunner
from calibrate_pro.application.session import SessionState
from calibrate_pro.application.system_profile_results import (
    ProfileActivation,
    ProfileInstallation,
    ProfileRemoval,
    ProfileRestoration,
)
from calibrate_pro.application.system_profile_session import ProfileOutcome
from calibrate_pro.application.system_profile_transactions import (
    activate_profile,
    install_bundle_profile,
    read_profiles,
    remove_profile,
    restore_display_profiles,
)
from calibrate_pro.application.system_profiles import (
    SystemProfileError,
    SystemProfilePort,
    SystemProfileReading,
    SystemProfileSource,
    SystemProfileUnavailable,
    installed_name_for,
)

T = TypeVar("T")


def _sealed_icc_payload(record: ProfileRecord) -> bytes:
    """Read the bundle's ICC profile, refusing bytes its manifest no longer seals.

    The same rule the exporter applies to a copy. A profile registered with the
    machine outlives the session that installed it, so installing a file that
    has drifted from its manifest would leave the operator's display driven by
    something no record accounts for.
    """
    asset = next((entry for entry in record.assets if entry.format == AssetFormat.ICC.value), None)
    if asset is None:
        raise no_such_asset()
    try:
        payload = (Path(record.directory) / asset.filename).read_bytes()
    except OSError as exc:
        raise profile_unreadable(str(exc)) from exc
    if hashlib.sha256(payload).hexdigest() != asset.sha256:
        raise profile_seal_broken()
    return payload


class SystemProfileActions:
    """Reading, installing, activating, and removing system colour profiles."""

    _state: SessionState
    _runner: SessionActionRunner
    _system_profiles: SystemProfileSource

    def _invalidate_after_profile_write(self) -> None:
        """Drop what a change of the display's default profile invalidated.

        Supplied by the session service, which owns the measurement record this
        has to clear. Declared here so a reader of the lane can see that every
        write that moves the default goes through it.
        """
        raise NotImplementedError

    # -- reading ------------------------------------------------------------

    def read_system_profiles(self) -> ActionOutcome[SystemProfileReading]:
        """Enumerate what the machine holds and what the selected display uses.

        Every write in this lane is judged against a reading: whether the
        selected bundle is already registered, whether this display lists it,
        and what the display falls back to when it stops. None of that is
        answerable from the bundle on disk, so nothing is offered until the
        store has been read.
        """
        return self._runner.run("profile.system.read", self._read_system_profiles)

    def _read_system_profiles(self) -> SystemProfileReading:
        display_id = self._require_display()
        reading = self._with_store(lambda port: read_profiles(port, display_id))
        self._state.system_profiles.record_reading(reading)
        return reading

    @property
    def installed_system_profiles(self) -> tuple[str, ...]:
        """Every profile the last reading found registered with this machine.

        A plain read of what the session already holds, so it takes no receipt
        and refuses nothing. A surface offering a choice of profile draws it
        from here, which keeps the list to what the store answered with rather
        than to filenames a surface went looking for.
        """
        return self._state.system_profiles.installed

    # -- writing ------------------------------------------------------------

    def install_selected_profile(self) -> ActionOutcome[ProfileInstallation]:
        """Register the inspected bundle's ICC profile and attach it to the display.

        Attaching is not activating. Windows lets a display carry several
        profiles and hands one of them to colour-managed software, so this puts
        the bundle where it can be chosen and leaves the choice to the operator.
        """
        return self._runner.run("profile.install", self._install_selected_profile)

    def _install_selected_profile(self) -> ProfileInstallation:
        display_id = self._require_display()
        record = self._require_sealed_record()
        payload = _sealed_icc_payload(record)
        name = installed_name_for(record.manifest_sha256)
        installation = self._with_store(lambda port: install_bundle_profile(port, display_id, name, payload))
        self._record_write(installation)
        return installation

    def activate_selected_profile(self) -> ActionOutcome[ProfileActivation]:
        """Make the inspected bundle's profile the display's default."""
        return self._runner.run("profile.activate", self._activate_selected_profile)

    def _activate_selected_profile(self) -> ProfileActivation:
        record = self._require_sealed_record()
        return self._activate(installed_name_for(record.manifest_sha256))

    def switch_display_profile(self, name: str) -> ActionOutcome[ProfileActivation]:
        """Make any installed profile the display's default, named by the operator.

        The tray offers this so a display can be moved between profiles without
        opening the application, which is what an operator wants when one
        profile suits daylight and another suits a graded print. Any registered
        profile may be chosen here, including the display vendor's own, because
        choosing which profile is in effect takes nothing away.
        """
        return self._runner.run("tray.switch_profile", lambda: self._activate(name))

    def _activate(self, name: str) -> ProfileActivation:
        display_id = self._require_display()
        self._require_reading()
        activation = self._with_store(lambda port: activate_profile(port, display_id, name))
        self._record_write(activation)
        return activation

    def remove_selected_profile(self) -> ActionOutcome[ProfileRemoval]:
        """Detach the inspected bundle's profile from the display and unregister it.

        The bundle on disk is untouched. This removes what was put into Windows
        colour management, which is a different thing from deleting the work,
        and an operator who wants the folder gone deletes the folder.
        """
        return self._runner.run("profile.delete", self._remove_selected_profile)

    def _remove_selected_profile(self) -> ProfileRemoval:
        display_id = self._require_display()
        record = self._require_sealed_record()
        self._require_reading()
        name = installed_name_for(record.manifest_sha256)
        removal = self._with_store(lambda port: remove_profile(port, display_id, name))
        self._record_write(removal)
        return removal

    def restore_display_profiles(self) -> ActionOutcome[ProfileRestoration]:
        """Take every profile this product attached to the display back off it.

        The files stay registered with the machine. A bundle attached to a
        second monitor would stop working if this removed the file, and an
        operator restoring one display has said nothing about the other.
        """
        return self._runner.run("display.restore_defaults", self._restore_display_profiles)

    def _restore_display_profiles(self) -> ProfileRestoration:
        display_id = self._require_display()
        self._require_reading()
        restoration = self._with_store(lambda port: restore_display_profiles(port, display_id))
        self._record_write(restoration)
        return restoration

    # -- shared helpers -----------------------------------------------------

    def _require_display(self) -> str:
        display_id = self._state.selected_display_id
        if display_id is None:
            raise no_display_selected()
        return display_id

    def _require_reading(self) -> SystemProfileReading:
        reading = self._state.system_profiles.reading
        if reading is None:
            raise no_profile_reading()
        return reading

    def _require_sealed_record(self) -> ProfileRecord:
        inspection = self._state.selected_profile
        if inspection is None:
            raise no_verified_profile()
        if not inspection.sealed:
            raise profile_seal_broken()
        return inspection.record

    def _record_write(self, outcome: ProfileOutcome) -> None:
        """Keep the result, and drop a measurement the display no longer matches.

        Only a write that moved the default invalidates a run. Registering a
        profile and attaching it to a display changes what colour-managed
        software may choose, and changes nothing about the light the panel is
        emitting. Naming a profile as the default can change it, because
        Windows loads that profile's calibration curve when the machine is set
        to, so a run taken beforehand is dropped rather than carried across a
        transfer curve that may have moved underneath it.
        """
        self._state.system_profiles.record_write(outcome)
        if outcome.before.default != outcome.after.default:
            self._invalidate_after_profile_write()

    def _with_store(self, work: Callable[[SystemProfilePort], T]) -> T:
        """Hold the profile store for one operation, and release it however it ends.

        A refusal from the colour management API becomes a retryable refusal
        rather than an unexpected error. An install into the system colour
        directory wanting an elevated account is a state of the machine, and an
        operator can act on being told which.
        """
        try:
            port = self._system_profiles.open()
        except SystemProfileUnavailable as exc:
            raise system_profile_refused(str(exc)) from exc
        try:
            return work(port)
        except (SystemProfileError, SystemProfileUnavailable) as exc:
            raise system_profile_refused(str(exc)) from exc
        finally:
            port.close()


__all__ = ["SystemProfileActions"]
