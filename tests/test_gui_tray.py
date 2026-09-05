"""What the tray offers, proved by building a window that has one.

The tray this replaces filled a Switch Profile submenu by globbing
``~/Documents/Calibrate Pro/Calibrations`` for .cube files, a directory nothing
in this application writes to. Every entry took its name from a filename, one
was check-marked from a startup record, and choosing one applied nothing. None
of it went through an action.

A tray is invisible to the rest of this suite, because ``_build_tray`` returns
before building anything when Qt reports no system tray and the offscreen
platform reports none. These tests build the window where one exists and read
what it made. Four properties are held down: every entry stands for an action
the manifest declares on the tray, the entries are the same whatever is on
disk, the profile mutation this build does not perform carries the reason the
session gives for it, and the entry that navigates arrives at the Profiles
page.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from calibrate_pro.application.outcomes import ActionError
from calibrate_pro.gui.action_binding import DEFAULT_DISABLED_REASON
from calibrate_pro.gui.app import (
    NOTHING_OBSERVED,
    PROFILES_PAGE_INDEX,
    detection_sentence,
    tray_tooltip,
)
from tests.conftest import active_window

MANIFEST = Path(__file__).resolve().parents[1] / "calibrate_pro" / "resources" / "action-capabilities.json"

#: Every entry the tray builds, in menu order, with the action it stands for.
TRAY_ENTRIES = (
    ("Show Window", "window.show"),
    ("Calibrate All Displays", "calibration.all"),
    ("Restore Defaults", "display.restore_defaults"),
    ("Profiles", "navigation.profiles"),
    ("Switch Profile", "tray.switch_profile"),
    ("Exit", "application.exit"),
)

#: The menu entry that runs detection through the binder, which is what writes
#: the status line. The startup pass calls the same handler directly, so a
#: window that has only just opened has observed without having reported.
DETECT = "&Detect Displays"

#: Filenames of the shape the removed submenu read, planted where it read them.
PLANTED = ("srgb_display.cube", "hdr-panel.cube", "office.cube")


def declared(action_id: str) -> dict:
    """One action as the shipped manifest declares it."""
    document = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for entry in document["actions"]:
        if entry["action_id"] == action_id:
            return entry
    raise AssertionError(f"the manifest declares no action {action_id}")


def tray_actions(window: object) -> list[object]:
    """Every entry the tray menu holds, separators dropped."""
    return [action for action in window._tray.contextMenu().actions() if not action.isSeparator()]


def texts(window: object) -> list[str]:
    return [action.text() for action in tray_actions(window)]


def named(window: object, text: str) -> object:
    """The one tray entry showing this text."""
    found = [action for action in tray_actions(window) if action.text() == text]
    assert len(found) == 1, f"expected one {text!r} entry, found {len(found)}"
    return found[0]


def named_entry(window: object, text: str) -> object:
    """The one menu entry anywhere in the window showing this text."""
    from PySide6.QtGui import QAction

    found = [action for action in window.findChildren(QAction) if action.text() == text]
    assert len(found) == 1, f"expected one {text!r} entry, found {len(found)}"
    return found[0]


def binding_for(window: object, action: object) -> object:
    """What the window bound this control to, or a failure saying nothing did."""
    held = {id(binding.control): binding for binding in window._binder.bindings}
    found = held.get(id(action))
    assert found is not None, f"the tray entry {action.text()!r} is bound to no action"
    return found


def test_every_tray_entry_stands_for_an_action_declared_on_the_tray(tray_window: object) -> None:
    """A tray entry is a control like any other, so it is bound and declared.

    The manifest is what decides an action is offered from the tray, and a menu
    entry the manifest does not place there is a surface nobody reviewed.
    """
    entries = tray_actions(tray_window)

    assert texts(tray_window) == [text for text, _ in TRAY_ENTRIES]
    for action, (text, action_id) in zip(entries, TRAY_ENTRIES, strict=True):
        assert binding_for(tray_window, action).action_id == action_id
        surfaces = declared(action_id)["surfaces"]
        assert any(surface.startswith("tray.") for surface in surfaces), (text, surfaces)


def test_no_tray_entry_opens_a_submenu(tray_window: object) -> None:
    """The submenu that was here held entries nothing bound and nothing resolved."""
    for action in tray_actions(tray_window):
        assert action.menu() is None


def test_the_tray_is_the_same_whatever_the_folder_it_used_to_read_holds(
    qapp: object,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Files planted where the removed submenu globbed do not reach the tray.

    This is the false-success control for the entries above: with the old code
    in place, three .cube files here became three tray entries named by
    mangling their filenames.
    """
    from PySide6.QtWidgets import QSystemTrayIcon

    home = tmp_path / "home"
    calibrations = home / "Documents" / "Calibrate Pro" / "Calibrations"
    calibrations.mkdir(parents=True)
    for name in PLANTED:
        (calibrations / name).write_bytes(b"")
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: True))

    with active_window(monkeypatch, tmp_path) as built:
        assert texts(built) == [text for text, _ in TRAY_ENTRIES]


def test_the_profile_mutation_this_build_does_not_perform_carries_its_reason(tray_window: object) -> None:
    """The entry stays, closed, showing the sentence the session gives for it.

    Dropping it would hide a decision an operator can otherwise read. Leaving
    it open over a handler that changes nothing is what the tray did before.
    The wording is the resolver's rather than the tray's. The manifest records
    why the action is unavailable at all, the session narrows that to the state
    it is in, and a sentence written beside the widget would drift from both.
    """
    action = named(tray_window, "Switch Profile")
    resolved = tray_window.service.resolve("tray.switch_profile")

    assert not action.isEnabled()
    assert action.toolTip() == resolved.reason
    assert resolved.reason != DEFAULT_DISABLED_REASON
    assert declared("tray.switch_profile")["unavailable_reason"]


def test_the_tray_and_the_status_line_report_one_detection_pass(tray_window: object) -> None:
    """Both surfaces draw the same sentence, so neither can go stale alone.

    The tray this replaces wrote its own line out of a startup record and a
    folder listing while the status line described the pass the session had
    just run, which let one window carry two answers about its own displays.
    Detection is run through its menu entry here, because that is the path that
    writes to both.
    """
    detect = binding_for(tray_window, named_entry(tray_window, DETECT))

    tray_window._binder.invoke(detect)
    summary = tray_window._observed

    assert summary is not None, "the detection reported nothing to draw"
    assert tray_window._status.text() == detection_sentence(summary)
    assert tray_window._tray.toolTip() == tray_tooltip(summary)
    assert detection_sentence(summary) in tray_window._tray.toolTip()
    assert str(len(summary.dashboard.displays)) in tray_window._status.text()


def test_a_window_that_has_not_detected_reports_no_observation(
    qapp: object,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Before a pass has run there is nothing to report, and the tray says that.

    Startup detection is stubbed out here to hold the window in the state it
    passes through while it is being built. A count of zero displays would be a
    claim about hardware nothing had looked at, so the two answers are kept
    apart.
    """
    from PySide6.QtWidgets import QSystemTrayIcon

    from calibrate_pro.gui.app import CalibrateProWindow

    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: True))
    monkeypatch.setattr(CalibrateProWindow, "_prime_session", lambda self: None)

    with active_window(monkeypatch, tmp_path) as built:
        assert built._observed is None
        assert built._tray.toolTip() == tray_tooltip(None)
        assert NOTHING_OBSERVED in built._tray.toolTip()
        assert "detected" not in built._tray.toolTip()


def test_using_the_closed_switch_is_refused_rather_than_performed(tray_window: object) -> None:
    """A disabled control emits nothing, so the action is asked for directly.

    What answers is the session. The refusal is the guarantee that the entry
    would still change nothing if a surface reached past the disabled state.
    """
    binding = binding_for(tray_window, named(tray_window, "Switch Profile"))

    outcome = tray_window._binder.invoke(binding)

    assert isinstance(outcome, ActionError)
    assert outcome.effect_state == "none"


def test_the_profiles_entry_shows_the_window_on_the_page_that_reads_bundles(tray_window: object) -> None:
    """Navigating is the whole of what this entry does, and it is done here.

    The window is hidden first because that is the state the tray is used
    from, so bringing it back is part of what the entry has to perform.
    """
    tray_window.hide()

    named(tray_window, "Profiles").trigger()

    assert tray_window.isVisible()
    assert tray_window.stack.currentIndex() == PROFILES_PAGE_INDEX
    assert tray_window.stack.currentWidget() is tray_window.profiles_page
