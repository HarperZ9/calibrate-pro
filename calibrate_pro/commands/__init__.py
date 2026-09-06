"""Shared command implementations for source and frozen entrypoints."""

from __future__ import annotations

from calibrate_pro import __version__


def banner() -> str:
    """The one line every listing leads with.

    It lives here rather than beside one of the listings so that a module
    carrying a single command does not import a module carrying the others.
    The frozen build ships the target listing and refuses the panel listings,
    and a shared import between them would put the refused code in the binary.
    """
    return f"Calibrate Pro v{__version__}"


__all__ = ["banner"]
