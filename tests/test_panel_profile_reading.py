"""Reading a panel profile the operator chose, and stopping there.

The window used to open a chooser, copy the file into the directory the
calibration engine reads, and register whatever it held, with no action resolved
and nothing journalled. The manifest declares that import disabled pending its
Phase 2 contract, so the work being proved here is deliberately smaller than what
the old path did: a chosen file is parsed where it sits and described in the
terms it states about itself.

Nothing here validates a profile. A file that parses is a file that parses, and
these tests are written to hold that line: a file stating a panel type this build
has never heard of reads back exactly as written.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from calibrate_pro.application.composition import FAKE_JOURNAL_DIRNAME
from calibrate_pro.application.outcomes import ActionFailure
from calibrate_pro.application.panel_profiles import NOT_STATED, read_panel_profile
from calibrate_pro.application.refusals import PROFILE_UNREADABLE
from tests.fake_acceptance_support import build_service, journal_records, refused, succeeded

ONE_PANEL = {
    "manufacturer": "Example Optics",
    "model_pattern": "EX-2700U",
    "display_name": "Example EX-2700U",
    "panel_type": "QD-OLED",
}


def write_profile(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_a_file_describing_one_panel_reads_back_in_its_own_words(tmp_path: Path) -> None:
    """Every field is what the file said, and the path is where it still is."""
    path = write_profile(tmp_path / "panel.json", ONE_PANEL)

    preview = read_panel_profile(path)

    assert preview.path == str(path)
    assert len(preview.entries) == 1
    entry = preview.entries[0]
    assert entry.manufacturer == "Example Optics"
    assert entry.model_pattern == "EX-2700U"
    assert entry.display_name == "Example EX-2700U"
    assert entry.panel_type == "QD-OLED"
    assert entry.stated_name == "Example EX-2700U"


def test_a_file_listing_several_panels_reports_all_of_them(tmp_path: Path) -> None:
    """A profile written by an earlier build is a list, and both shapes read.

    The list form is what the panel database itself writes, so refusing it would
    make this build unable to read a file it produced.
    """
    payload = [dict(ONE_PANEL, model_pattern=f"EX-{index}") for index in range(3)]
    path = write_profile(tmp_path / "panels.json", payload)

    preview = read_panel_profile(path)

    assert [entry.model_pattern for entry in preview.entries] == ["EX-0", "EX-1", "EX-2"]


def test_an_entry_naming_only_a_pattern_still_states_a_name(tmp_path: Path) -> None:
    """Reporting nothing for those would make a readable file look empty."""
    path = write_profile(tmp_path / "pattern.json", {"model_pattern": "EX-2700U"})

    entry = read_panel_profile(path).entries[0]

    assert entry.display_name == ""
    assert entry.stated_name == "EX-2700U"
    assert entry.manufacturer == ""


def test_an_entry_naming_nothing_says_so_rather_than_reading_empty(tmp_path: Path) -> None:
    """An absence is worded, so a missing name reads as one the file omitted."""
    path = write_profile(tmp_path / "anonymous.json", {"panel_type": "IPS"})

    assert read_panel_profile(path).entries[0].stated_name == NOT_STATED


def test_a_field_that_is_not_text_is_treated_as_unstated(tmp_path: Path) -> None:
    """A number where a name belongs is not a name, and is not printed as one.

    Nothing here validates, so a file like this is still read. What it is not
    allowed to do is put a value the file never stated as text in front of an
    operator as though the file had.
    """
    path = write_profile(tmp_path / "typed.json", {"display_name": 7, "manufacturer": None})

    entry = read_panel_profile(path).entries[0]

    assert entry.display_name == ""
    assert entry.manufacturer == ""
    assert entry.stated_name == NOT_STATED


def test_a_file_holding_no_panel_is_read_rather_than_refused(tmp_path: Path) -> None:
    """Parsed and empty is a different answer from could not be read.

    The two are kept apart so a surface can say which one happened. A file that
    parsed to a list of nothing this build recognises is the first, and it is
    reported as an empty reading rather than as a failure to read.
    """
    path = write_profile(tmp_path / "empty.json", ["not a panel", 12])

    preview = read_panel_profile(path)

    assert preview.entries == ()
    assert preview.path == str(path)


def test_an_unparseable_file_refuses_with_the_parser_own_words(tmp_path: Path) -> None:
    """The operator is told what stopped the read, not that it was rejected."""
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(ActionFailure) as caught:
        read_panel_profile(path)

    failure = caught.value
    assert failure.code == PROFILE_UNREADABLE
    assert failure.retryable is True
    assert "Expecting" in failure.summary


def test_a_file_that_is_not_there_refuses_and_stays_retryable(tmp_path: Path) -> None:
    """A different file may well work, which is what makes this retryable."""
    with pytest.raises(ActionFailure) as caught:
        read_panel_profile(tmp_path / "absent.json")

    assert caught.value.code == PROFILE_UNREADABLE
    assert caught.value.retryable is True


def test_the_session_journals_the_read_and_copies_nothing(tmp_path: Path) -> None:
    """Reading is an action, so it is resolved and recorded like any other.

    The whole session root is swept afterwards rather than one directory,
    because the defect this replaced was a copy nobody asked for and naming the
    one place it went would only prove that particular copy is gone. The journal
    is what recording the action costs, so it is what the sweep excludes, and
    everything else has to still be nothing.
    """
    service = build_service(tmp_path)
    root = tmp_path / "session"
    chosen = write_profile(tmp_path / "chosen.json", ONE_PANEL)

    preview = succeeded(service.inspect_panel_profile(chosen))

    assert preview.entries[0].display_name == "Example EX-2700U"
    assert chosen.exists()
    journal_dir = (root / FAKE_JOURNAL_DIRNAME).resolve()
    written = [path for path in root.rglob("*") if path.is_file() and journal_dir not in path.parents]
    assert written == []
    assert [record["action_id"] for record in journal_records(root)] == ["panel_profile.import.choose"]


def test_the_session_answers_an_unreadable_file_as_a_refusal(tmp_path: Path) -> None:
    """The refusal reaches the caller as an outcome rather than an exception.

    A surface that has to catch to find out what happened would be back to the
    dialog handling its own errors, which is the arrangement this replaced.
    """
    service = build_service(tmp_path)
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")

    error = refused(service.inspect_panel_profile(broken))

    assert error.code == PROFILE_UNREADABLE
    assert error.retryable is True
    assert error.next_action == "Choose a .json panel profile this account can read."
