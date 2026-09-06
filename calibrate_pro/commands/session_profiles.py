"""Putting a published bundle into Windows colour management from a terminal.

A calibration that stays in a folder changes nothing. The ICC profile has to be
registered with the machine, attached to the display it was generated for, and
named as that display's default before colour-managed software reads it. Until
this family existed a headless run ended with a bundle on disk and an
instruction to open the Windows colour management dialog by hand.

Every write reads the store first and reads it back afterwards. Windows reports
a registration that left the display's default alone the same way it reports one
that took, so the exit code is decided by the second reading rather than by a
call returning. A run without ``--confirm`` prints what it found and what it
would do, then stops.

Only what this product published is installed, and only what it installed is
removed. The name a bundle registers under is derived from its manifest digest,
and a display carrying its vendor's own profile keeps it through everything
here.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from calibrate_pro.application.profiles import ProfileInspection, ProfileListing, ProfileRecord
    from calibrate_pro.application.service import FunctionalRecoveryService
    from calibrate_pro.application.system_profiles import SystemProfileReading

#: Printed in place of a write the operator did not confirm. It names the store
#: rather than the display, because registering a profile changes the machine
#: and only the default is per-display.
NOTHING_WRITTEN = "Nothing was written. Pass --confirm to change this machine's colour management."


def _marks(reading: SystemProfileReading, name: str) -> str:
    """Say what one installed profile is to this display, if it is anything.

    The three facts are separate and Windows will report any combination of
    them, so a name is annotated with whichever hold rather than sorted into a
    single category that would hide the rest.
    """
    from calibrate_pro.application.system_profiles import is_installed_name

    marks = []
    if reading.associates(name):
        marks.append("on this display")
    if reading.is_default(name):
        marks.append("default")
    if is_installed_name(name):
        marks.append("published by this product")
    return f"  ({', '.join(marks)})" if marks else ""


def _print_reading(reading: SystemProfileReading) -> None:
    """Print the store as it answered, including what it names and cannot hold.

    A display can name a default the machine no longer holds a file for, which
    an operator meets as colour management that quietly stopped working. That
    case is printed rather than dropped, because a list of installed profiles
    alone would show nothing wrong.
    """
    print(f"{reading.instrument} on {reading.display_id}")
    for name in reading.installed:
        print(f"  {name}{_marks(reading, name)}")
    for name in reading.associated:
        if not reading.holds(name):
            print(f"  {name}{_marks(reading, name)}  (the machine holds no file under this name)")
    print(f"  {reading.summary}")


def _read_store(service: FunctionalRecoveryService, args: Any) -> SystemProfileReading:
    """Detect, select the display the operator named, and read the profile store."""
    from calibrate_pro.commands.session import value

    value(service.detect())
    display_id = getattr(args, "display", None)
    if display_id:
        value(service.select_display(display_id))
    reading: SystemProfileReading = value(service.read_system_profiles())
    _print_reading(reading)
    return reading


def system_profiles(service: FunctionalRecoveryService, args: Any) -> int:
    """Report what the machine holds and what the selected display is using."""
    _read_store(service, args)
    return 0


def _no_bundle_at(directory: str, listing: ProfileListing) -> str:
    """Say what was at a path that named no bundle, naming what was found under it.

    A directory of bundles is what ``generate-profiles`` writes into when it is
    given a parent, so an operator naming the parent here is making an ordinary
    mistake and the answer is the list of paths that would have worked.
    """
    if listing.profiles:
        found = ", ".join(entry.directory for entry in listing.profiles)
        return f"No published bundle at {directory}. Bundles were found under it: {found}. Name one of those."
    return f"No published bundle at {directory}. Publish one with 'generate-profiles' first."


def _select_bundle(service: FunctionalRecoveryService, directory: str) -> tuple[ProfileRecord, ProfileInspection]:
    """Find the bundle at one exact path and check its files against its manifest.

    The listing reads the named directory and one level below it, so the match
    is made on the resolved path rather than on the first record returned. An
    operator who names a parent gets told which of its children are bundles
    instead of having one of them chosen for them.
    """
    from calibrate_pro.commands.session import CommandError, value

    value(service.set_export_directory(directory))
    listing: ProfileListing = value(service.list_profiles())
    if not listing.searched or not listing.existed:
        raise CommandError(f"No directory at {directory}. Nothing was read.")
    wanted = Path(directory).resolve()
    record = next((entry for entry in listing.profiles if Path(entry.directory).resolve() == wanted), None)
    if record is None:
        raise CommandError(_no_bundle_at(directory, listing))
    inspection: ProfileInspection = value(service.inspect_profile(record.directory))
    return record, inspection


def _print_bundle(
    record: ProfileRecord,
    inspection: ProfileInspection,
    reading: SystemProfileReading,
    name: str,
) -> None:
    """Print the bundle a write is about, and the name it occupies in the store."""
    print(f"{record.name}  {'sealed' if inspection.sealed else 'CHANGED'}")
    print(f"  directory      {record.directory}")
    print(f"  panel          {record.panel_name}")
    print(f"  installs as    {name}")
    for check in inspection.broken:
        print(f"  {'changed' if check.present else 'missing'}        {check.filename}")
    held = "already installed on this machine" if reading.holds(name) else "not installed on this machine"
    print(f"  {held}")


def _bundle_write(service: FunctionalRecoveryService, args: Any) -> tuple[SystemProfileReading, str] | None:
    """Read the store, choose the bundle, print both, and say whether to go on.

    Returning ``None`` is the unconfirmed run. Install and remove read exactly
    the same things in the same order before they diverge, and a display whose
    store was never read cannot judge either of them.
    """
    from calibrate_pro.application.system_profiles import installed_name_for

    reading = _read_store(service, args)
    record, inspection = _select_bundle(service, args.bundle)
    name = installed_name_for(record.manifest_sha256)
    print("")
    _print_bundle(record, inspection, reading, name)
    print("")
    if not getattr(args, "confirm", False):
        print(NOTHING_WRITTEN)
        return None
    return reading, name


def install_profile(service: FunctionalRecoveryService, args: Any) -> int:
    """Register a published bundle's ICC profile and attach it to the display.

    Attaching is not activating. Windows lets a display carry several profiles
    and hands one of them to colour-managed software, so ``--activate`` is a
    second word for the second step rather than something the install does on
    the operator's behalf.
    """
    from calibrate_pro.commands.session import value

    confirmed = _bundle_write(service, args)
    if confirmed is None:
        return 0
    installation = value(service.install_selected_profile())
    print(installation.summary)
    if not installation.accepted or not getattr(args, "activate", False):
        return 0 if installation.accepted else 1
    activation = value(service.activate_selected_profile())
    print(activation.summary)
    return 0 if activation.accepted else 1


def remove_profile(service: FunctionalRecoveryService, args: Any) -> int:
    """Detach a published bundle's profile from the display and unregister it.

    The bundle on disk is untouched. This takes back what was put into Windows
    colour management, and an operator who wants the folder gone deletes the
    folder.
    """
    from calibrate_pro.commands.session import value

    confirmed = _bundle_write(service, args)
    if confirmed is None:
        return 0
    removal = value(service.remove_selected_profile())
    print(removal.summary)
    return 0 if removal.accepted else 1


def switch_profile(service: FunctionalRecoveryService, args: Any) -> int:
    """Make an installed profile the display's default, named by the operator.

    Any registered profile may be named, including the display vendor's own,
    because choosing which profile is in effect takes nothing away. A name the
    machine does not hold is refused here rather than sent to the store, so the
    answer can list what is available.
    """
    from calibrate_pro.commands.session import CommandError, value

    reading = _read_store(service, args)
    print("")
    if not reading.holds(args.name):
        installed = ", ".join(reading.installed) or "none"
        raise CommandError(f"{args.name} is not installed on this machine. Installed: {installed}.")
    if not getattr(args, "confirm", False):
        print(NOTHING_WRITTEN)
        return 0
    activation = value(service.switch_display_profile(args.name))
    print(activation.summary)
    return 0 if activation.accepted else 1


def restore_profiles(service: FunctionalRecoveryService, args: Any) -> int:
    """Take every profile this product attached to the display back off it.

    The files stay registered with the machine. A bundle attached to a second
    monitor would stop working if this removed the file, and an operator
    restoring one display has said nothing about the other.
    """
    from calibrate_pro.commands.session import value

    reading = _read_store(service, args)
    print("")
    if not reading.ours:
        print(f"{reading.display_id} lists no profile from this product. Nothing was taken off it.")
        return 0
    for name in reading.ours:
        print(f"  {name}")
    print("")
    if not getattr(args, "confirm", False):
        print(NOTHING_WRITTEN)
        return 0
    restoration = value(service.restore_display_profiles())
    print(restoration.summary)
    return 0 if restoration.accepted else 1


__all__ = [
    "NOTHING_WRITTEN",
    "install_profile",
    "remove_profile",
    "restore_profiles",
    "switch_profile",
    "system_profiles",
]
