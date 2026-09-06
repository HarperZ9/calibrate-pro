"""The Windows source that satisfies the system profile port.

Windows keeps colour profiles in one machine-wide directory and answers about
them by name, so nothing here holds a device handle the way the DDC/CI source
does. A port is a claim on the colour management API for the length of one
operation, and closing it refuses any later call rather than releasing a
resource.

Every read goes through the enumeration that raises. The convenience readers in
:mod:`calibrate_pro.profiles.profile_installer` swallow their exceptions and
return an empty list, which would be reported here as a display with no profiles
attached to it. That is the same sentence Windows uses for a display that really
has none, and this lane decides whether to install, activate, and remove from
exactly that answer.

The default is read after the enumeration and only its failure becomes ``None``.
A display that names no default and a colour management API that will not answer
raise the same exception from the same call, and taking the enumeration first
settles which of the two it was: an API that just enumerated is live, so what
followed is a display with nothing set.

An install stages the bytes under the exact basename the store will hold them
under. The legacy installer derives the destination name from the file it is
given, and every bundle this build publishes carries the same basename, so
installing straight from a bundle directory would put the second calibration at
the same path as the first and be refused for it.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from calibrate_pro.application.system_profiles import (
    NO_STORE_REASON,
    SystemProfileError,
    SystemProfilePort,
    SystemProfileReading,
    SystemProfileUnavailable,
)

#: What a reading from this source names as the instrument that produced it.
#: Windows Color System is the component that answers, and an operator reading a
#: refusal has to know it was the machine's colour management and not the panel.
INSTRUMENT = "Windows Color System"


def _load_installer() -> Any:
    """Import the colour management layer, naming the failure rather than passing it on."""
    try:
        from calibrate_pro.profiles import profile_installer
    except Exception as exc:
        raise SystemProfileUnavailable(f"{NO_STORE_REASON}: {exc}") from exc
    if not getattr(profile_installer, "MSCMS_AVAILABLE", False):
        raise SystemProfileUnavailable(NO_STORE_REASON)
    return profile_installer


def _accepted(result: object, what: str) -> None:
    """Turn one legacy ``(success, message)`` return into a refusal or nothing.

    The message is carried through unchanged. Windows distinguishes an install
    that wants an elevated account from one whose destination is already taken,
    and an operator can act on the difference.
    """
    if type(result) is not tuple or len(result) != 2 or type(result[0]) is not bool or type(result[1]) is not str:
        raise SystemProfileError(f"{what} returned something other than a (success, message) pair")
    accepted, message = result
    if not accepted:
        raise SystemProfileError(message)


class WindowsSystemProfilePort:
    """The Windows colour profile store, for as long as a caller holds it."""

    def __init__(self, installer: Any) -> None:
        self._installer = installer
        self._open = True

    def identity(self) -> str:
        return INSTRUMENT

    def close(self) -> None:
        """Refuse every later call on this port.

        Nothing is released. The store is addressed by name on each call, so a
        port holds no handle, and this exists so a defect that keeps a port past
        the operation it was opened for is refused instead of writing.
        """
        self._open = False

    def _api(self) -> Any:
        if not self._open:
            raise SystemProfileError("this system profile port is closed")
        return self._installer

    def read(self, display_id: str) -> SystemProfileReading:
        """Enumerate the machine's profiles, this display's, and its default."""
        api = self._api()
        try:
            installed = tuple(api._enumerate_system_profiles(None))
            associated = tuple(api._enumerate_system_profiles(display_id))
        except Exception as exc:
            raise SystemProfileError(f"{INSTRUMENT} would not enumerate its profiles: {exc}") from exc
        try:
            default: str | None = str(api.get_default_profile_for_display(display_id))
        except Exception:
            default = None
        return SystemProfileReading(
            display_id=display_id,
            instrument=INSTRUMENT,
            installed=installed,
            associated=associated,
            default=default,
        )

    def install(self, name: str, payload: bytes) -> None:
        """Register one profile with the machine under an exact name.

        The bytes are staged under that name first, because the installer takes
        a path and reads the destination basename off it. The staging directory
        goes whether the install lands or raises, and what it leaves behind is a
        copy in the system colour directory that Windows now owns.
        """
        api = self._api()
        with tempfile.TemporaryDirectory(prefix="calibrate-pro-install-") as staging:
            staged = Path(staging) / name
            staged.write_bytes(payload)
            _accepted(api.install_profile(staged), "install")

    def associate(self, name: str, display_id: str) -> None:
        """Attach an installed profile to a display without making it the default.

        Attaching and activating are separate calls in this lane because they
        are separate things to the operator. A profile can sit on a display as
        one of several choices, and putting it there is not a decision about
        which one colour-managed software is handed.
        """
        api = self._api()
        _accepted(api.associate_profile_with_display(name, display_id, make_default=False), "associate")

    def make_default(self, name: str, display_id: str) -> None:
        """Name an attached profile as the one this display hands out."""
        api = self._api()
        _accepted(api.set_default_profile_for_display(name, display_id), "activate")

    def disassociate(self, name: str, display_id: str) -> None:
        """Take a profile off a display, leaving it registered with the machine."""
        api = self._api()
        _accepted(api.disassociate_profile_from_display(name, display_id), "detach")

    def uninstall(self, name: str) -> None:
        """Unregister a profile and remove its file from the colour directory."""
        api = self._api()
        _accepted(api.uninstall_profile(name), "uninstall")


class WindowsSystemProfileSource:
    """Opens ports over the colour profile store this machine exposes."""

    def describe(self) -> str:
        """Say what the store is, or why there is none to address."""
        try:
            api = _load_installer()
        except SystemProfileUnavailable as exc:
            return str(exc)
        try:
            held = len(api._enumerate_system_profiles(None))
        except Exception as exc:
            return f"{INSTRUMENT} is present and would not enumerate its profiles: {exc}"
        return f"{INSTRUMENT} holds {held} installed profile(s)"

    def present(self) -> bool:
        """Whether the colour management API loaded and answered an enumeration."""
        try:
            api = _load_installer()
            api._enumerate_system_profiles(None)
        except Exception:
            return False
        return True

    def open(self) -> SystemProfilePort:
        """Take the store for one operation."""
        return WindowsSystemProfilePort(_load_installer())


__all__ = [
    "INSTRUMENT",
    "WindowsSystemProfilePort",
    "WindowsSystemProfileSource",
]
