"""Reading a panel profile file the operator chose, without adopting it.

The window used to do this itself. It opened a chooser, copied the file into the
directory the calibration engine reads, and registered whatever the file held,
with no action resolved and nothing journalled. The manifest declares the import
disabled pending its Phase 2 contract and the command line declines it by name,
so the window was performing work the rest of the build refuses.

What is here reads. A chosen file is parsed where it sits and described in the
terms it states about itself, so an operator can see what a file claims before
anything in this build is asked to trust it. Reading is an action like any
other: it is resolved against the manifest, journalled, and answered as an
outcome, which is why it lives here rather than in the surface that draws it.

Nothing here validates a profile. A file that parses is a file that parses. The
validated import this build will eventually offer is the disabled action next to
this one, and calling a parse a validation is the confusion that action exists
to prevent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from calibrate_pro.application.outcomes import ActionOutcome
from calibrate_pro.application.refusals import profile_unreadable
from calibrate_pro.application.runner import SessionActionRunner

#: What a preview shows for a field the chosen file did not state. It is worded
#: as an absence rather than left blank, so a missing manufacturer reads as one
#: the file omitted rather than one this build failed to show.
NOT_STATED = "not stated"


@dataclass(frozen=True)
class PanelProfileEntry:
    """One panel a chosen file describes, in that file's own words.

    Every field is what the file said, unparsed and unchecked. ``model_pattern``
    is carried beside ``display_name`` because a profile written by an earlier
    build states only the pattern, and reporting nothing for those would make a
    readable file look empty.
    """

    display_name: str
    model_pattern: str
    manufacturer: str
    panel_type: str

    @property
    def stated_name(self) -> str:
        """The best name this entry states for itself, or that it states none."""
        return self.display_name or self.model_pattern or NOT_STATED


@dataclass(frozen=True)
class PanelProfilePreview:
    """What one chosen file holds, read where it sits.

    An empty ``entries`` means the file parsed and described no panel. That is a
    different answer from a file that could not be read, which is a refusal, and
    the two are kept apart so a surface can say which one happened.
    """

    path: str
    entries: tuple[PanelProfileEntry, ...]


def read_panel_profile(path: Path) -> PanelProfilePreview:
    """Parse one panel profile file and report what it states.

    The refusal carries the filesystem's or the parser's own message, so an
    operator is told what stopped the read rather than that the file was
    rejected. A different file may well work, which is what makes it retryable.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise profile_unreadable(str(exc)) from exc
    stated = data if isinstance(data, list) else [data]
    return PanelProfilePreview(
        path=str(path),
        entries=tuple(_entry(item) for item in stated if isinstance(item, dict)),
    )


def _entry(item: dict) -> PanelProfileEntry:
    return PanelProfileEntry(
        display_name=_text(item.get("display_name")),
        model_pattern=_text(item.get("model_pattern")),
        manufacturer=_text(item.get("manufacturer")),
        panel_type=_text(item.get("panel_type")),
    )


def _text(value: object) -> str:
    """Read one stated field as text, treating anything else as unstated."""
    return value if isinstance(value, str) else ""


class PanelProfileActions:
    """Reading a panel profile a surface offered the operator."""

    _runner: SessionActionRunner

    def inspect_panel_profile(self, path: str | Path) -> ActionOutcome[PanelProfilePreview]:
        """Read a chosen panel profile and report what it holds.

        Nothing is copied, registered, or matched against a display. The panel
        database this session calibrates against is untouched by this call, and
        the file stays where the operator keeps it.
        """
        return self._runner.run("panel_profile.import.choose", lambda: read_panel_profile(Path(path)))


__all__ = [
    "NOT_STATED",
    "PanelProfileActions",
    "PanelProfileEntry",
    "PanelProfilePreview",
    "read_panel_profile",
]
