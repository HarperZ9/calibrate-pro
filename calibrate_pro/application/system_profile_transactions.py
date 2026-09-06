"""The procedure that changes the system's colour profile store, and checks it.

Each operation reads the store, performs at most two native calls, and reads
again. The second reading is what the result is built from. Windows reports
success for a registration that leaves the display's default alone and for an
association naming a profile it does not hold, so a result assembled from
return values would describe the request rather than the machine.

Nothing here rolls back. An install that registers a file and fails to attach
it leaves the file registered, because undoing that means deleting a profile
out of a directory shared with the display vendor's own, to reverse a step that
may have failed for a reason the operator can clear in a second. The result
says which half landed, and the file is still there to attach.

The removal path detaches before it unregisters. Unregistering a profile a
display still names leaves that display pointing at a file that is gone, which
an operator meets as colour management that quietly stopped working rather than
as an error anything reported.

Every removal is bounded by the name. Only a profile whose basename this build
derives from a bundle it published can be uninstalled or detached here, so a
restore on a display carrying the vendor's own profile and one this product
installed takes back exactly the one it put there.
"""

from __future__ import annotations

from calibrate_pro.application.system_profile_results import (
    ProfileActivation,
    ProfileInstallation,
    ProfileRemoval,
    ProfileRestoration,
)
from calibrate_pro.application.system_profiles import (
    SystemProfileError,
    SystemProfilePort,
    SystemProfileReading,
    is_installed_name,
)


def _reason(exc: BaseException) -> str:
    """Name a colour management failure by its own message, or by its type."""
    text = str(exc).strip()
    return text if text else type(exc).__name__


def read_profiles(port: SystemProfilePort, display_id: str) -> SystemProfileReading:
    """Enumerate what the machine holds and what this display is using.

    A failure here stops every write that would follow it. Each of those is
    judged against a reading, so a write performed without one would have no
    way to report what it did.
    """
    try:
        return port.read(display_id)
    except SystemProfileError:
        raise
    except Exception as exc:
        raise SystemProfileError(f"The colour profile store did not answer: {_reason(exc)}") from exc


def _require_ours(name: str) -> None:
    if not is_installed_name(name):
        raise SystemProfileError(
            f"{name} was not installed by this product, so this build will not remove or detach it."
        )


def install_bundle_profile(
    port: SystemProfilePort,
    display_id: str,
    name: str,
    payload: bytes,
) -> ProfileInstallation:
    """Register one published bundle's profile and attach it to this display.

    A name already registered is left as it stands rather than written over.
    The digest in the name is derived from the bundle's manifest, so a file
    already sitting under it came from the same bundle, and replacing it would
    be a write with nothing to gain and a running application's open handle to
    lose.
    """
    if type(payload) is not bytes or not payload:
        raise SystemProfileError("a profile payload must be nonempty exact bytes")
    _require_ours(name)
    before = read_profiles(port, display_id)
    refusal: str | None = None

    if not before.holds(name):
        try:
            port.install(name, payload)
        except Exception as exc:
            raise SystemProfileError(f"{name} could not be installed: {_reason(exc)}") from exc

    if not before.associates(name):
        try:
            port.associate(name, display_id)
        except Exception as exc:
            refusal = _reason(exc)

    return ProfileInstallation(
        display_id=display_id,
        name=name,
        before=before,
        after=read_profiles(port, display_id),
        refusal=refusal,
    )


def activate_profile(port: SystemProfilePort, display_id: str, name: str) -> ProfileActivation:
    """Make one installed profile the display's default.

    The default is the profile Windows hands to colour-managed software, so
    this is the step that puts a calibration into effect. A profile the machine
    does not hold is refused here rather than passed to an API that would
    accept it and leave the display naming a file that does not exist.
    """
    before = read_profiles(port, display_id)
    if not before.holds(name):
        raise SystemProfileError(f"{name} is not installed on this machine, so it cannot be made the default.")

    try:
        if not before.associates(name):
            port.associate(name, display_id)
        port.make_default(name, display_id)
    except Exception as exc:
        raise SystemProfileError(f"{display_id} did not accept {name} as its default: {_reason(exc)}") from exc

    return ProfileActivation(
        display_id=display_id,
        name=name,
        before=before,
        after=read_profiles(port, display_id),
    )


def remove_profile(port: SystemProfilePort, display_id: str, name: str) -> ProfileRemoval:
    """Detach one of this product's profiles from a display and unregister it."""
    _require_ours(name)
    before = read_profiles(port, display_id)
    if not before.holds(name) and not before.associates(name):
        raise SystemProfileError(f"{name} is neither installed on this machine nor listed by {display_id}.")

    refusal: str | None = None
    if before.associates(name):
        try:
            port.disassociate(name, display_id)
        except Exception as exc:
            raise SystemProfileError(f"{name} could not be detached from {display_id}: {_reason(exc)}") from exc

    if before.holds(name):
        try:
            port.uninstall(name)
        except Exception as exc:
            refusal = _reason(exc)

    return ProfileRemoval(
        display_id=display_id,
        name=name,
        before=before,
        after=read_profiles(port, display_id),
        refusal=refusal,
    )


def restore_display_profiles(port: SystemProfilePort, display_id: str) -> ProfileRestoration:
    """Take every profile this product attached to a display back off it.

    The files stay installed. An operator restoring a display is undoing what
    this product did to that display, and a bundle attached to a second monitor
    would stop working if this removed the file as well. What the display falls
    back to is read afterwards rather than chosen here, because Windows decides
    that from what remains.
    """
    before = read_profiles(port, display_id)
    detached: list[str] = []
    for name in before.ours:
        try:
            port.disassociate(name, display_id)
        except Exception as exc:
            raise SystemProfileError(f"{name} could not be detached from {display_id}: {_reason(exc)}") from exc
        detached.append(name)

    return ProfileRestoration(
        display_id=display_id,
        removed=tuple(detached),
        before=before,
        after=read_profiles(port, display_id),
    )


__all__ = [
    "activate_profile",
    "install_bundle_profile",
    "read_profiles",
    "remove_profile",
    "restore_display_profiles",
]
