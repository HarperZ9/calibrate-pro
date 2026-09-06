"""Where a session gets a pattern window, and what it says when it cannot.

The window itself lives in :mod:`calibrate_pro.adapters.qt_pattern_surface`,
and that module imports Qt at the top of the file. This one does not. It is
held by every calibration session whether or not a pattern is ever shown, so
importing Qt here would load a GUI toolkit into a terminal session that only
ever printed a report.

So the import sits inside :meth:`open`, which is the same discipline the
service uses for the patch window and the composition uses for the display
writer. What can be said before that import happens is only whether the
toolkit is installed, which is what :meth:`present` answers and no more.

A source that reported a surface it could not open would be worse than one
that reported nothing, so every failure on the way to a window becomes
:class:`PatternSurfaceUnavailable` carrying what was tried. The action layer
turns that into a refusal an operator can act on.
"""

from __future__ import annotations

from importlib.util import find_spec

from calibrate_pro.application.pattern_surface import (
    PatternSurfacePort,
    PatternSurfaceUnavailable,
)

#: What a pattern window is, in the words a report uses for it.
SURFACE_DESCRIPTION = "a fullscreen window on the selected display"

#: What this source says on a machine with no Qt installed. The frozen build
#: ships PySide6, so this is the source build running from a checkout that
#: installed the package without its GUI extra.
NO_TOOLKIT_REASON = "this build has no window toolkit installed, so no pattern surface can be opened"

#: The module a pattern window is painted with. Named once, and asked about
#: rather than imported, so nothing here loads Qt to find out whether Qt exists.
TOOLKIT_MODULE = "PySide6.QtWidgets"


def pattern_surface_present() -> bool:
    """Whether this machine has the toolkit a pattern window is built from.

    Asked by module lookup rather than import. A capability probe that loaded
    Qt would leave a toolkit in the process of any session that merely asked
    the question, including the read-only one.
    """
    try:
        return find_spec(TOOLKIT_MODULE) is not None
    except (ImportError, ValueError):
        return False


class WindowsPatternSurfaceSource:
    """Open one fullscreen pattern window on one display, and nothing else.

    Nothing is held between calls. A pattern window exists for as long as the
    caller holds the port it is given, and the caller closes it. That is the
    same lifetime the DDC/CI port has, for a different reason: there is no
    driver handle to leak here, but a fullscreen window left on top of the
    desktop with no way to dismiss it is worse than one.
    """

    def describe(self) -> str:
        """Name what would be opened, or say why nothing would be."""
        if not pattern_surface_present():
            return NO_TOOLKIT_REASON
        return SURFACE_DESCRIPTION

    def present(self) -> bool:
        """Whether a pattern window could be opened at all on this machine."""
        return pattern_surface_present()

    def open(self, display_id: str) -> PatternSurfacePort:
        """Open a window on one display and hand back the port that owns it.

        The display is named to Qt rather than left to it. Qt will hand out a
        primary screen for a name it cannot match, and a pattern shown on the
        wrong monitor is a judgement made about a display nobody asked about.
        """
        if type(display_id) is not str or not display_id.strip():
            raise PatternSurfaceUnavailable("a pattern window needs the name of the display to open on")
        try:
            from calibrate_pro.adapters.qt_pattern_surface import open_pattern_window
        except Exception as exc:
            raise PatternSurfaceUnavailable(f"{NO_TOOLKIT_REASON}: {exc}") from exc
        return open_pattern_window(device_name=display_id)


__all__ = [
    "NO_TOOLKIT_REASON",
    "SURFACE_DESCRIPTION",
    "TOOLKIT_MODULE",
    "WindowsPatternSurfaceSource",
    "pattern_surface_present",
]
