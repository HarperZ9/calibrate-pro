"""What each terminal command prints, driven over a display nobody owns.

These tests run the commands themselves, against the session shape a shipped
terminal builds, and read the text an operator would read. Four properties are
held down across them. A command reports what the action returned rather than a
sentence written for the command line, a refusal arrives in the session's own
words, a figure is printed beside the plain statement of where it came from, and
a command that writes says so by writing exactly the files it named.

The reading commands are held to the same standard as the writing one. Three
answers end in no profiles, and the one that means nothing was read is refused
rather than tallied, because a zero there reports a folder that was looked in.

Nothing here reaches a display. The synthetic panel arrives through the test
helper, so a plan is generated, sealed, and read back without a real one.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from calibrate_pro.application.actions import ActionDisposition
from calibrate_pro.application.assets import MANIFEST_FILENAME
from calibrate_pro.application.outcomes import ActionError, refusal_message
from calibrate_pro.application.service import FunctionalRecoveryService
from calibrate_pro.commands.session import preset_names
from tests.session_support import PRESET, build_cli_service, field, lines, run

#: A digest is printed as a name for one exact plan, so a test reads it as one.
HEX = set("0123456789abcdef")


def session_at(tmp_path: Path, name: str = "session") -> FunctionalRecoveryService:
    """One session, journalled under its own directory so writes stay visible."""
    return build_cli_service(tmp_path / name)


def published(tmp_path: Path, name: str = "out") -> Path:
    """Drive one calibration through to a bundle, and hand back where it landed."""
    directory = tmp_path / name
    code, _ = run("generate-profiles", session_at(tmp_path, f"publish-{name}"), output=str(directory))
    assert code == 0, "the publishing run this test depends on was refused"
    return directory


def test_detect_names_the_display_and_where_its_characterization_came_from(tmp_path: Path) -> None:
    """Every line is a fact the detection action returned, down to its source."""
    observed = session_at(tmp_path, "direct").detect().value.dashboard.displays[0]

    code, text = run("detect", session_at(tmp_path))

    assert code == 0
    assert lines(text)[0].startswith("1 display(s) observed at ")
    assert f" * {observed.platform_display_id}  {observed.safe_label}" in text
    assert field(text, "characterization:") == observed.characterization.provenance


def test_status_counts_the_actions_this_session_can_run(tmp_path: Path) -> None:
    """The count is the resolver's answer, not a number kept beside it.

    Both halves are read off the same session after the same detection pass, so
    a count that drifted from what the resolver says would fail here rather than
    tell an operator they have more open to them than they do.
    """
    built = session_at(tmp_path)

    code, text = run("status", built)

    declared = built.action_ids()
    open_now = [name for name in declared if built.resolve(name).disposition is ActionDisposition.ENABLED]
    assert code == 0
    assert f"Actions: {len(open_now)} of {len(declared)} available in this session" in text
    assert len(open_now) < len(declared), "a session with nothing closed would prove nothing here"
    for action_id in declared:
        assert action_id in text


def test_the_closed_listing_drops_every_action_that_is_open(tmp_path: Path) -> None:
    """A shorter listing has to be a subset, or it is a second listing."""
    _, full = run("status", session_at(tmp_path, "full"))

    code, closed = run("status", session_at(tmp_path, "closed"), closed=True)

    assert code == 0
    assert "  enabled  " in full
    assert "  enabled  " not in closed
    assert set(lines(closed)) <= set(lines(full))


def test_verify_prints_a_sealed_plan_and_says_no_display_was_measured(tmp_path: Path) -> None:
    """The figures are predicted, and the line beneath them says exactly that."""
    code, text = run("verify", session_at(tmp_path))

    digest = lines(text)[0].removeprefix("Plan ")
    assert code == 0
    assert len(digest) == 64
    assert set(digest) <= HEX
    assert field(text, "target") == PRESET
    assert field(text, "evidence") == "estimated"
    assert field(text, "average dE").endswith("(estimated)")
    assert "No display was measured and no sensor was read." in text


def test_verify_writes_nothing_but_its_own_journal(tmp_path: Path) -> None:
    """A prediction is not a publication, so nothing lands where a bundle would."""
    root = tmp_path / "session"

    run("verify", build_cli_service(root))

    assert sorted(path.name for path in tmp_path.iterdir()) == ["session"]
    assert sorted(path.name for path in root.iterdir()) == ["diagnostics"]


def test_generate_publishes_exactly_the_files_it_named(tmp_path: Path) -> None:
    """What the run said it generated is what is on disk, sealed by its manifest.

    The digest is re-computed from the bytes that were written rather than read
    back out of the manifest, so a manifest describing a bundle it does not seal
    fails here instead of reading as a published bundle.
    """
    directory = tmp_path / "out"

    code, text = run("generate-profiles", session_at(tmp_path), output=str(directory))

    generated = [line.split()[-1] for line in lines(text) if line.strip().startswith("generated ")]
    assert code == 0
    assert f"Published to {directory}" in text
    assert sorted(path.name for path in directory.iterdir()) == sorted([MANIFEST_FILENAME, *generated])
    manifest = directory / MANIFEST_FILENAME
    assert field(text, MANIFEST_FILENAME) == hashlib.sha256(manifest.read_bytes()).hexdigest()


def test_a_dry_run_stops_at_the_plan_and_writes_nothing(tmp_path: Path) -> None:
    """The plan is the whole output, so no verification figure is printed either."""
    directory = tmp_path / "out"

    code, text = run("generate-profiles", session_at(tmp_path), output=str(directory), dry_run=True)

    assert code == 0
    assert lines(text)[0].startswith("Plan ")
    assert lines(text)[-1] == "Stopped at the plan. Nothing was written."
    assert "Verification source" not in text
    assert "Published to" not in text
    assert not directory.exists()


def test_profiles_reads_back_the_bundle_generate_published(tmp_path: Path) -> None:
    """The loop closes: what one command wrote is what the other one finds."""
    directory = published(tmp_path)

    code, text = run("profiles", session_at(tmp_path, "list"), directory=str(directory))

    assert code == 0
    assert lines(text)[0] == f"{directory.name}  sealed"
    assert field(text, "directory") == str(directory)
    assert field(text, "target") == PRESET
    assert lines(text)[-1] == "1 of 1 sealed, 0 unreadable"


def test_a_bundle_whose_files_changed_is_reported_as_changed(tmp_path: Path) -> None:
    """A seal that no longer holds is named, and the run reports that it failed."""
    directory = published(tmp_path)
    cube = next(path for path in directory.iterdir() if path.suffix == ".cube")
    cube.write_text("edited", encoding="utf-8")

    code, text = run("profiles", session_at(tmp_path, "list"), directory=str(directory))

    assert code == 1
    assert lines(text)[0] == f"{directory.name}  CHANGED"
    assert f"changed        {cube.name}" in text
    assert lines(text)[-1] == "0 of 1 sealed, 0 unreadable"


def test_a_path_with_nothing_at_it_is_not_reported_as_an_empty_directory(tmp_path: Path) -> None:
    """Two ways of naming a path that is not there, and neither is a zero.

    The first is a path the session will hold, having nothing to read at it. The
    second it will not hold at all, because nothing above it exists either. Both
    mean the same thing to whoever typed the path, so both are refused.
    """
    for absent in (tmp_path / "absent", tmp_path / "absent" / "deeper" / "still"):
        code, text = run("profiles", session_at(tmp_path, "list"), directory=str(absent))

        assert code == 2
        assert text.strip() == f"profiles: No directory at {absent}. Nothing was read."
        assert "sealed" not in text


def test_an_empty_directory_says_it_was_read_and_held_none(tmp_path: Path) -> None:
    """A directory that is there and holds nothing is a different answer again."""
    empty = tmp_path / "empty"
    empty.mkdir()

    code, text = run("profiles", session_at(tmp_path), directory=str(empty))

    assert code == 0
    assert text.strip() == f"No published bundle under {empty}."


def test_an_unknown_target_names_the_targets_that_exist(tmp_path: Path) -> None:
    """The mistake was the name, so the answer is the names there are.

    Handing this to the session would answer that no such action is declared.
    That is true and it is not what was got wrong, so the check happens where
    the names can be read back off the targets themselves.
    """
    code, text = run("verify", session_at(tmp_path), target="srgb")

    assert code == 2
    assert "No target named 'srgb'" in text
    for name in preset_names():
        assert name in text


def test_a_refused_action_is_printed_in_the_words_the_session_refused_it_in(tmp_path: Path) -> None:
    """One sentence, rendered once. A terminal does not write its own refusals."""
    built = session_at(tmp_path, "direct")
    built.detect()
    refused = built.select_display("NO-SUCH-DISPLAY")
    assert isinstance(refused, ActionError), "this test needs an action the session declines"

    code, text = run("verify", session_at(tmp_path), display="NO-SUCH-DISPLAY")

    assert code == 2
    assert text.strip() == f"verify: {refusal_message(refused)}"
