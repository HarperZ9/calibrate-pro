"""Reading the session journal back from a terminal.

Every action a session runs is written to a redacted journal before it is
allowed to report success. This command is the terminal end of that: it lists
what a support bundle would contain, writes that exact bundle when a path is
given, and opens the folder the journal lives in.

The preview token is held in memory by the session that issued it, so a preview
taken in one run cannot be spent by the next. That is why one command does both
halves rather than two commands sharing a grant across processes, and it is why
the listing an operator reads is the listing of the bundle they then send.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from calibrate_pro.application.journal import BundlePreview, DiagnosticBundleReceipt
    from calibrate_pro.application.service import FunctionalRecoveryService


def destination_path(raw: str) -> Path:
    """Read a destination off the command line as an absolute path.

    The manager takes absolute paths only, because a relative one means nothing
    to a session that never changed directory. A terminal is the one surface
    where a relative path is a reasonable thing to type, so this is where the
    current directory is applied rather than where the path is rejected.
    """
    return Path(raw).expanduser().resolve()


def _print_preview(preview: BundlePreview, folder: Path | None) -> None:
    """Name every file the bundle would carry, and the digest of each one."""
    if folder is not None:
        print(f"Journal folder {folder}")
    print(f"{len(preview.members)} file(s) would be published, token valid until {preview.expires_utc}")
    for member in preview.members:
        print(f"  {member.basename}  {member.byte_length} bytes  {member.sha256}")


def _print_receipt(receipt: DiagnosticBundleReceipt) -> None:
    """Print what landed on disk, named by the digest of the bytes that landed."""
    print(f"Published to {receipt.published_path}")
    print(f"  bundle         {receipt.bundle_sha256}")
    print(f"  byte length    {receipt.byte_length}")
    print(f"  readback       {'verified' if receipt.readback_verified else 'NOT VERIFIED'}")
    for basename, digest in receipt.member_hashes:
        print(f"  member         {basename}  {digest}")


def diagnostics(service: FunctionalRecoveryService, args: Any) -> int:
    """Preview the journal, publish it when asked, and open its folder when asked.

    A refusal from any of the three ends the command, including one that arrives
    after a bundle was already written. The lines printed up to that point say
    what did happen, and the exit code says the command did not finish.
    """
    from calibrate_pro.commands.session import value

    preview = value(service.preview_diagnostics())
    _print_preview(preview, service.diagnostics_folder)
    destination = getattr(args, "bundle", None)
    if destination:
        print("")
        _print_receipt(value(service.create_diagnostics_bundle(preview.token, destination_path(destination))))
    if getattr(args, "open", False):
        print("")
        value(service.open_diagnostics_folder())
        print("Opened the folder holding the journal.")
    return 0


__all__ = ["destination_path", "diagnostics"]
