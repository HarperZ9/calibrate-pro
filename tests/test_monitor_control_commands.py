"""Driving a display's own controls from a terminal.

What is judged here is the run an operator actually performs: the flags the
command offers, what it prints before anything moves, and the exit code a
script reads afterwards. The transaction layer and the session are judged
elsewhere, so nothing here re-checks what a panel did with a write beyond the
part the terminal has to report.

Two of these matter more than the rest. A run without ``--confirm`` reaches a
display for the reading and for nothing else, which is the whole reason the
flag exists. And a confirmed run whose control did not move exits nonzero, so a
script driving this command can tell a panel that took the value from one that
answered the write and went on holding its old number.
"""

from __future__ import annotations

from pathlib import Path

from calibrate_pro.application.monitor_controls import BRIGHTNESS, CONTRAST, RED_GAIN, STAGEABLE_CODES
from calibrate_pro.commands.session_ddc import control_flags
from tests.monitor_control_support import FakePanel, build_monitor_service
from tests.session_support import lines, run

#: What a refused command exits with, which is neither a clean run nor a
#: display that answered and did not move.
REFUSED = 2


def listed(text: str) -> list[str]:
    """The control lines a reading printed, which each open with the VCP code."""
    return [line for line in lines(text) if line.strip().startswith("0x")]


# -- reading ---------------------------------------------------------------------


def test_reading_names_every_control_the_display_answered_and_the_flag_that_writes_it(tmp_path: Path) -> None:
    """An operator reads this once and knows what to type next.

    The code is printed beside the label because a display's own menu names
    these differently than this build does, and the number is what the two have
    in common.
    """
    panel = FakePanel()
    service = build_monitor_service(tmp_path, panel)

    code, text = run("ddc-info", service)

    assert code == 0
    assert len(listed(text)) == len(STAGEABLE_CODES)
    assert "0x10  Brightness: 75 of 100" in text
    assert "0x16  Red gain: 128 of 255" in text
    for flag in control_flags():
        assert flag in text, f"{flag} was not offered for a control the display answered"


def test_a_control_that_did_not_answer_is_listed_with_the_reason(tmp_path: Path) -> None:
    """Left out, it would read as a control this build never asked for."""
    panel = FakePanel()
    panel.refuse_read(RED_GAIN, "unsupported VCP code")
    service = build_monitor_service(tmp_path, panel)

    code, text = run("ddc-info", service)

    assert code == 0
    assert "0x16  Red gain: not answered (" in text
    assert "unsupported VCP code" in text
    assert len(listed(text)) == len(STAGEABLE_CODES)


def test_a_display_with_ddc_switched_off_is_refused_before_the_port_is_opened(tmp_path: Path) -> None:
    panel = FakePanel()
    service = build_monitor_service(tmp_path, panel, ddc=False)

    code, _ = run("ddc-info", service)

    assert code == REFUSED
    assert panel.opens == 0


# -- a run that writes nothing ----------------------------------------------------


def test_a_run_without_confirm_reads_the_display_and_changes_nothing(tmp_path: Path) -> None:
    """The reading is taken, both numbers are printed, and the panel is left alone.

    Staging against a reading taken in this run is what makes the printed
    numbers worth anything: the range each value was checked against came from
    the display a moment earlier rather than from a table in this build.
    """
    panel = FakePanel()
    service = build_monitor_service(tmp_path, panel)

    code, text = run("ddc-calibrate", service, brightness=40, contrast=60)

    assert code == 0
    assert "Brightness: reads 75, staged at 40" in text
    assert "Contrast: reads 50, staged at 60" in text
    assert lines(text)[-1] == "Nothing was written. Pass --confirm to change the display."
    assert panel.writes() == []


def test_a_run_naming_no_control_is_refused_and_reaches_no_display(tmp_path: Path) -> None:
    """The refusal carries the flags, because that is what the operator needs next."""
    panel = FakePanel()
    service = build_monitor_service(tmp_path, panel)

    code, text = run("ddc-calibrate", service, confirm=True)

    assert code == REFUSED
    assert "Name at least one control to set, or pass --restore-defaults." in text
    for flag in control_flags():
        assert flag in text
    assert panel.opens == 0


def test_a_restore_asked_for_alongside_a_staged_value_is_refused(tmp_path: Path) -> None:
    """The two disagree about what the run is for.

    A staged number was checked against a reading the restore is about to make
    untrue, so writing it afterwards would set the panel to a value chosen
    against a state it no longer holds.
    """
    panel = FakePanel()
    service = build_monitor_service(tmp_path, panel)

    code, text = run("ddc-calibrate", service, brightness=40, restore_defaults=True, confirm=True)

    assert code == REFUSED
    assert "--restore-defaults asks the display to choose its own values" in text
    assert panel.opens == 0


def test_a_value_past_the_range_the_display_reported_is_refused_before_any_write(tmp_path: Path) -> None:
    panel = FakePanel()
    service = build_monitor_service(tmp_path, panel)

    code, text = run("ddc-calibrate", service, brightness=150, confirm=True)

    assert code == REFUSED
    assert "Brightness accepts 0 through 100, and 150 was staged for it" in text
    assert panel.writes() == []


# -- a run that writes ------------------------------------------------------------


def test_a_confirmed_run_writes_and_reports_what_the_display_reads_at(tmp_path: Path) -> None:
    panel = FakePanel()
    service = build_monitor_service(tmp_path, panel)

    code, text = run("ddc-calibrate", service, brightness=40, contrast=60, confirm=True)

    assert code == 0
    assert "Brightness: 75 to 40" in text
    assert "Contrast: 50 to 60" in text
    assert (panel.values[BRIGHTNESS], panel.values[CONTRAST]) == (40, 60)


def test_a_control_that_answered_the_write_and_did_not_move_exits_nonzero(tmp_path: Path) -> None:
    """The false-success control, at the level a script reads.

    A panel advertising a control it does not drive answers the write exactly
    as one that drove it. The exit code comes from the read-back rather than
    from the call returning, so a script can tell the two apart.
    """
    panel = FakePanel()
    panel.ignore(BRIGHTNESS)
    service = build_monitor_service(tmp_path, panel)

    code, text = run("ddc-calibrate", service, brightness=40, confirm=True)

    assert code == 1
    assert "Brightness: asked for 40, still reads 75" in text
    assert panel.values[BRIGHTNESS] == 75


def test_a_run_that_failed_partway_names_the_control_that_refused_and_the_rollback(tmp_path: Path) -> None:
    """A display left half changed is the one outcome an operator has to be told about."""
    panel = FakePanel()
    panel.refuse_write(CONTRAST, "the display is busy")
    service = build_monitor_service(tmp_path, panel)

    code, text = run("ddc-calibrate", service, brightness=40, contrast=60, confirm=True)

    assert code == 1
    assert "The write stopped: Contrast refused the write: the display is busy" in text
    assert "Brightness put back to the value read before the write" in text
    assert panel.values[BRIGHTNESS] == 75


def test_a_restore_run_reports_what_moved_between_the_two_readings(tmp_path: Path) -> None:
    """The display chose these values, and the second reading is its own account of them."""
    panel = FakePanel()
    panel.restores_to(brightness=50, contrast=75)
    service = build_monitor_service(tmp_path, panel)

    code, text = run("ddc-calibrate", service, restore_defaults=True, confirm=True)

    assert code == 0
    assert "restored its factory settings. Brightness 75 to 50; Contrast 50 to 75." in text
    assert (panel.values[BRIGHTNESS], panel.values[CONTRAST]) == (50, 75)
