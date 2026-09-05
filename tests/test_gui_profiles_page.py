"""What the Profiles page shows, proved by driving the real window.

The page this replaces listed files it found by globbing a folder no part of
this application writes to, and described each one with a white point, a gamma,
and a gamut nobody had recorded. Its buttons copied, renamed, and deleted files
directly, with no action behind any of them.

These tests build the real window against the fake-acceptance composition and
use the page the way an operator would. Four properties are held down. Nothing
is read until the listing action reads it, every figure on the pane comes from
the manifest of the bundle it describes, the mutations this build does not
perform explain themselves with the resolver's own sentence, and the copy is
closed until the selected bundle has been checked and closes again the moment
that answer stops holding.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from calibrate_pro.application.assets import MANIFEST_FILENAME
from calibrate_pro.application.outcomes import ActionSuccess
from calibrate_pro.gui.pages.profile_detail import NO_SELECTION, SEALED
from calibrate_pro.gui.pages.profiles import (
    FOUND,
    NONE_FOUND,
    NOT_READ,
    NOT_THERE,
    NOWHERE_TO_LOOK,
    UNREADABLE,
)
from tests.fake_acceptance_support import MANIFEST_NAME
from tests.profile_support import CUBE, manifest_of, publish
from tests.test_gui_action_surface import CUBE_EXPORT, drive_to_save_report, entries

BUNDLE = "srgb"


def page(window: object) -> object:
    """The real Profiles page, or a failure naming what was built instead."""
    built = window.profiles_page
    assert built is window.stack.widget(3), "the profiles page is not where the navigation points"
    return built


def listed(profiles: object) -> list[str]:
    """Every row the list is currently showing, in order."""
    widget = profiles._list
    return [widget.item(row).text() for row in range(widget.count())]


def names(profiles: object) -> list[str]:
    """The bundle name each row leads with, without the line beneath it."""
    return [row.splitlines()[0] for row in listed(profiles)]


def fields(profiles: object) -> dict[str, str]:
    """Read the detail pane's figures as the pairs it has drawn."""
    grid = profiles._detail._grid
    drawn: dict[str, str] = {}
    for row in range(grid.rowCount()):
        name = grid.itemAtPosition(row, 0)
        value = grid.itemAtPosition(row, 1)
        if name is not None and value is not None:
            drawn[name.widget().text()] = value.widget().text()
    return drawn


def stocked(window: object, directory: Path) -> Path:
    """Point the session at a directory and publish one bundle under it."""
    outcome = window.service.set_export_directory(str(directory))
    assert isinstance(outcome, ActionSuccess), f"the session refused the directory: {outcome}"
    publish(directory / BUNDLE)
    window._binder.refresh()
    return directory


def refreshed(window: object) -> object:
    """Use the Refresh control, and hand back the page it redrew."""
    profiles = page(window)
    profiles._refresh_button.click()
    return profiles


def selected(window: object, row: int = 0) -> object:
    """Move to one row, which is what asks the session to check that bundle."""
    profiles = page(window)
    profiles._list.setCurrentRow(row)
    return profiles


def answer_copy_dialog(monkeypatch: pytest.MonkeyPatch, directory: Path | str) -> None:
    """Answer the page's copy dialog with one path, or with a withdrawal."""
    from calibrate_pro.gui.pages import profiles as profiles_page

    monkeypatch.setattr(
        profiles_page.QFileDialog,
        "getExistingDirectory",
        staticmethod(lambda *args, **kwargs: str(directory)),
    )


def test_the_page_opens_having_read_nothing(window: object, tmp_path: Path) -> None:
    """A bundle on disk is not listed until the listing action has run.

    The page states that rather than showing an empty list, because an empty
    list and a list nobody has asked for say different things about whether
    there are profiles.
    """
    stocked(window, tmp_path / "exports")
    profiles = page(window)

    assert profiles._where.text() == NOT_READ
    assert listed(profiles) == []
    assert profiles._detail._name.text() == NO_SELECTION
    assert fields(profiles) == {}


def test_a_refresh_with_nowhere_to_look_says_so(window: object) -> None:
    """No export directory is a different answer from an empty one."""
    profiles = refreshed(window)

    assert profiles._where.text() == NOWHERE_TO_LOOK
    assert listed(profiles) == []


def test_a_directory_that_stopped_being_there_is_not_redrawn_as_an_empty_one(
    window: object,
    tmp_path: Path,
) -> None:
    """The folder an export wrote to can be moved or deleted after the export.

    Refreshing then reads a path with nothing at it. Saying nothing was found
    under a directory it never opened is the reading that matters here, because
    the operator has bundles and is being told the folder holding them is empty.
    """
    directory = stocked(window, tmp_path / "exports")
    assert refreshed(window)._where.text() == FOUND.format(count=1, directory=directory)

    shutil.rmtree(directory)
    profiles = refreshed(window)

    assert profiles._where.text() == NOT_THERE.format(directory=directory)
    assert profiles._where.text() != NONE_FOUND.format(directory=directory)
    assert listed(profiles) == []


def test_the_page_lists_the_bundle_this_application_exported(
    window: object,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The loop closes: what the export wrote is what the listing reads back.

    Nothing is published behind the window here. The session is driven through
    a calibration, the export entry writes a bundle, and the page then finds
    that bundle through the same directory the export used.
    """
    from calibrate_pro.gui import app as gui_app

    destination = tmp_path / "exports"
    drive_to_save_report(window.service)
    window._binder.refresh()
    monkeypatch.setattr(
        gui_app.QFileDialog,
        "getExistingDirectory",
        staticmethod(lambda *args, **kwargs: str(destination)),
    )
    entries(window)[CUBE_EXPORT].trigger()

    profiles = refreshed(window)

    assert profiles._where.text() == FOUND.format(count=1, directory=str(destination))
    assert names(profiles) == ["cube"]
    assert (destination / "cube" / MANIFEST_NAME).is_file()


def test_selecting_a_row_draws_the_figures_that_bundle_recorded(window: object, tmp_path: Path) -> None:
    """Every field is read out of the manifest, down to the digest sealing it."""
    exports = stocked(window, tmp_path / "exports")
    document = manifest_of(exports / BUNDLE)
    refreshed(window)

    profiles = selected(window)
    drawn = fields(profiles)

    assert profiles._detail._name.text() == BUNDLE
    assert drawn["Display"] == document["display_id"]
    assert drawn["White point"] == document["target"]["white_point"]
    assert drawn["Gamut mode"] == document["target"]["gamut_mode"]
    assert drawn["Tone response"] == document["target"]["tone_response"]
    assert drawn["Evidence"] == document["evidence_kind"]
    assert drawn["Directory"] == str(exports / BUNDLE)
    assert profiles._detail._seal.text() == SEALED


def test_every_mutation_this_build_does_not_perform_explains_itself(window: object, tmp_path: Path) -> None:
    """Four controls stand for actions with no handler, so none of them acts.

    Each carries the manifest's own reason. A control that did the work anyway
    would be the defect this page was rewritten to remove, and one disabled
    without a sentence would leave the operator guessing at a policy.
    """
    stocked(window, tmp_path / "exports")
    refreshed(window)
    profiles = selected(window)
    detail = profiles._detail

    closed = (
        profiles._generate_button,
        detail.activate_button,
        detail.rename_button,
        detail.delete_button,
    )
    for button in closed:
        assert not button.isEnabled()
        assert button.toolTip()


def test_the_copy_is_closed_until_the_selected_bundle_has_been_checked(window: object, tmp_path: Path) -> None:
    stocked(window, tmp_path / "exports")
    profiles = refreshed(window)

    assert not profiles._detail.export_button.isEnabled()
    assert profiles._detail.export_button.toolTip()

    selected(window)

    assert profiles._detail.export_button.isEnabled()


def test_copying_writes_the_files_the_pane_names(
    window: object,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A reported copy is a copy that ran, and it carries the source manifest."""
    exports = stocked(window, tmp_path / "exports")
    refreshed(window)
    profiles = selected(window)
    destination = tmp_path / "copy"
    answer_copy_dialog(monkeypatch, destination)

    profiles._detail.export_button.click()

    written = destination / BUNDLE
    assert str(written) in profiles._detail._copied.text()
    assert MANIFEST_FILENAME in profiles._detail._copied.text()
    assert (written / MANIFEST_FILENAME).read_bytes() == (exports / BUNDLE / MANIFEST_FILENAME).read_bytes()
    assert (written / CUBE).read_bytes() == (exports / BUNDLE / CUBE).read_bytes()
    assert window.toasts == []


def test_withdrawing_from_the_copy_dialog_writes_nothing(
    window: object,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Closing the dialog is not a refusal, so nothing is written or explained."""
    stocked(window, tmp_path / "exports")
    refreshed(window)
    profiles = selected(window)
    answer_copy_dialog(monkeypatch, "")

    profiles._detail.export_button.click()

    assert profiles._detail._copied.text() == ""
    assert window.toasts == []
    assert sorted(path.name for path in tmp_path.iterdir()) == ["exports", "session"]


def test_a_refresh_that_finds_a_changed_bundle_closes_the_pane_and_the_copy(
    window: object,
    tmp_path: Path,
) -> None:
    """A rewritten manifest is a different record, so the drawing goes with it.

    Leaving the figures on screen would describe a bundle the session no longer
    holds, and the copy button beside them would be disabled for a reason that
    read as though it were about the profile still being shown.
    """
    exports = stocked(window, tmp_path / "exports")
    refreshed(window)
    profiles = selected(window)
    assert profiles._detail.export_button.isEnabled()

    manifest = exports / BUNDLE / MANIFEST_FILENAME
    manifest.write_text(json.dumps(manifest_of(exports / BUNDLE)), encoding="utf-8")
    refreshed(window)

    assert profiles._detail._name.text() == NO_SELECTION
    assert fields(profiles) == {}
    assert not profiles._detail.export_button.isEnabled()


def test_a_bundle_this_build_cannot_read_is_named_with_its_reason(window: object, tmp_path: Path) -> None:
    """A profile that has become unreadable is something an operator must see."""
    exports = stocked(window, tmp_path / "exports")
    broken = publish(exports / "broken")
    (broken / MANIFEST_FILENAME).write_text("{ not json", encoding="utf-8")

    profiles = refreshed(window)

    assert names(profiles) == [BUNDLE]
    assert profiles._unreadable.text().startswith(UNREADABLE)
    assert str(broken) in profiles._unreadable.text()
