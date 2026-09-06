"""Where the system's own colour profile store enters the application.

Windows keeps one list of installed ICC profiles and, per display, a list of the
profiles associated with it and a single default. That default is what the
compositor hands to colour-managed software, so it is the thing an operator
means when they say a calibration is in effect. This build publishes bundles and
until now could not put one there, which left the last step of every run to be
done by hand in the Windows colour management dialog.

The store answers honestly, which is unusual among this product's hardware
lanes. An enumeration either returns the exact names Windows holds or it raises,
so a result here never has to be reconstructed from a call that returned success
and did nothing. What still has to be proved is the effect: registering a
profile, associating it with a display, and setting it as that display's default
are three separate native calls, and each one is checked by reading the store
back afterwards.

A bundle is installed under a name derived from its manifest digest rather than
under the filename it was published with. Every bundle this build publishes
carries the same basename, so installing two of them would collide inside a
single flat directory shared with the display vendor's own profiles. The digest
name also makes the question "is this bundle installed" answerable by a lookup
instead of by comparing bytes.

Nothing here imports :mod:`calibrate_pro.profiles`. The port is a protocol, the
Windows source that satisfies it lives in the adapter layer, and a session with
no profile route builds this module and loads no colour management API.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

#: What a session reports when nothing wired a port. It names the composition
#: rather than the machine, so a reader never mistakes it for a probe result.
NO_PORT_REASON = "this session was built without a system profile port"

#: What a source reports when the platform holds no colour profile store this
#: build can address, which is every machine that is not Windows.
NO_STORE_REASON = "this machine exposes no Windows colour profile store"

#: The installed name every bundle this build registers begins with. It reads as
#: a product name in the Windows colour management dialog, which is where an
#: operator will meet it, and it is what makes one of these safe to remove: the
#: lane only ever names a profile it can derive from a bundle it published.
INSTALLED_NAME_PREFIX = "Calibrate Pro "

#: How much of the manifest digest the installed name carries. Sixteen hex
#: characters is short enough to read off a dialog and long enough that two
#: bundles colliding is not a case this build has to handle.
INSTALLED_NAME_DIGEST_CHARACTERS = 16

_MANIFEST_DIGEST_RE = re.compile(r"[0-9a-f]{64}")


class SystemProfileUnavailable(RuntimeError):
    """No profile store answered, and the message names what was tried."""


class SystemProfileError(RuntimeError):
    """A store was addressed and its answer could not be trusted."""


def installed_name_for(manifest_sha256: str) -> str:
    """Name the file one published bundle is installed as.

    Derived from the manifest digest, so the same bundle always installs under
    the same name and a differing bundle can never be mistaken for it. A digest
    that is not the exact form a manifest carries is refused rather than
    truncated into a name that would look like a real one.
    """
    if type(manifest_sha256) is not str or _MANIFEST_DIGEST_RE.fullmatch(manifest_sha256) is None:
        raise SystemProfileError("a manifest digest is exactly 64 lowercase hexadecimal characters")
    return f"{INSTALLED_NAME_PREFIX}{manifest_sha256[:INSTALLED_NAME_DIGEST_CHARACTERS]}.icc"


def is_installed_name(name: object) -> bool:
    """Whether a name is one this build derived from a bundle it published.

    This is the bound on every removal the lane performs. A display's profile
    list holds the vendor's own profile and whatever else has accumulated over
    the machine's life, and none of that is this product's to uninstall.
    """
    if type(name) is not str or not name.startswith(INSTALLED_NAME_PREFIX) or not name.endswith(".icc"):
        return False
    digest = name[len(INSTALLED_NAME_PREFIX) : -len(".icc")]
    return len(digest) == INSTALLED_NAME_DIGEST_CHARACTERS and all(
        character in "0123456789abcdef" for character in digest
    )


def _names(value: object, field_name: str) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise SystemProfileError(f"{field_name} must be an exact tuple")
    for name in value:
        if type(name) is not str or not name.strip():
            raise SystemProfileError(f"{field_name} must hold nonblank exact strings")
    return value


@dataclass(frozen=True)
class SystemProfileReading:
    """What the colour profile store held for one display at one moment.

    The three lists answer three different questions and none of them stands in
    for another. A profile can be registered on the machine and attached to no
    display, attached to a display without being its default, or named as the
    default by a store that no longer holds the file. Windows will report each
    of those, so each is reported here.
    """

    display_id: str
    instrument: str
    installed: tuple[str, ...]
    associated: tuple[str, ...]
    default: str | None

    def __post_init__(self) -> None:
        for field_name in ("display_id", "instrument"):
            value = getattr(self, field_name)
            if type(value) is not str or not value.strip():
                raise SystemProfileError(f"{field_name} must be a nonblank exact string")
        _names(self.installed, "installed")
        _names(self.associated, "associated")
        if self.default is not None and (type(self.default) is not str or not self.default.strip()):
            raise SystemProfileError("default must be a nonblank exact string or None")

    def holds(self, name: str) -> bool:
        """Whether the machine has this profile registered under this exact name."""
        return any(held.casefold() == name.casefold() for held in self.installed)

    def associates(self, name: str) -> bool:
        """Whether this display's own profile list names it."""
        return any(held.casefold() == name.casefold() for held in self.associated)

    def is_default(self, name: str) -> bool:
        """Whether this display hands this profile to colour-managed software."""
        return self.default is not None and self.default.casefold() == name.casefold()

    @property
    def ours(self) -> tuple[str, ...]:
        """The associated profiles this build derived from bundles it published.

        What a restore is allowed to detach. Deciding it from the name rather
        than from a session list keeps a profile installed by an earlier run of
        this product removable, and keeps everything else on the display
        untouchable however the restore is invoked.
        """
        return tuple(name for name in self.associated if is_installed_name(name))

    @property
    def summary(self) -> str:
        listed = f"{len(self.installed)} profile(s) installed on this machine"
        attached = f"{len(self.associated)} associated with {self.display_id}"
        if self.default is None:
            return f"{listed}, {attached}, and it names no default."
        return f"{listed}, {attached}, and its default is {self.default}."


class SystemProfilePort(Protocol):
    """The colour profile store, for as long as a caller holds it.

    Windows addresses this store globally and takes the display as an argument,
    so the port is opened without naming one and every call that concerns a
    display names it. Writing the DDC lane's per-display signature here would
    describe a device session that does not exist.
    """

    def identity(self) -> str: ...

    def read(self, display_id: str) -> SystemProfileReading: ...

    def install(self, name: str, payload: bytes) -> None: ...

    def associate(self, name: str, display_id: str) -> None: ...

    def make_default(self, name: str, display_id: str) -> None: ...

    def disassociate(self, name: str, display_id: str) -> None: ...

    def uninstall(self, name: str) -> None: ...

    def close(self) -> None: ...


class SystemProfileSource(Protocol):
    """Where a session gets a port, and how it answers before it has one."""

    def describe(self) -> str: ...

    def present(self) -> bool: ...

    def open(self) -> SystemProfilePort: ...


class NoSystemProfileSource:
    """The default source, which reports no store and opens nothing.

    A session that wired no source has proved nothing about the machine.
    Reporting an installed profile it never enumerated would put the display's
    colour state behind a reading no store produced.
    """

    def __init__(self, reason: str = NO_PORT_REASON) -> None:
        if type(reason) is not str or not reason.strip():
            raise TypeError("reason must be a nonblank exact string")
        self._reason = reason

    def describe(self) -> str:
        return self._reason

    def present(self) -> bool:
        return False

    def open(self) -> SystemProfilePort:
        raise SystemProfileUnavailable(self._reason)


__all__ = [
    "INSTALLED_NAME_DIGEST_CHARACTERS",
    "INSTALLED_NAME_PREFIX",
    "NO_PORT_REASON",
    "NO_STORE_REASON",
    "NoSystemProfileSource",
    "SystemProfileError",
    "SystemProfilePort",
    "SystemProfileReading",
    "SystemProfileSource",
    "SystemProfileUnavailable",
    "installed_name_for",
    "is_installed_name",
]
