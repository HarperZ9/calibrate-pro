"""Changing a display's own controls, and finding out whether it listened.

DDC/CI is the one protocol in this product where a successful call carries no
information about whether anything happened. A panel that drove the value, a
panel that ignored it, and a panel that landed somewhere else all return the
same success. So every test here judges the lane by what the panel reads at
afterwards, and the ones that matter most arrange a panel that answers well and
does nothing.

The other half is a set that fails partway. Brightness written and a channel
gain refused leaves a display in a state no calibration was built against, so
the codes already written go back and the result says which. A rollback that is
itself refused is reported rather than absorbed, because a half changed display
is the one outcome an operator has to be told about.
"""

from __future__ import annotations

import pytest

from calibrate_pro.application.control_results import ControlTransaction
from calibrate_pro.application.control_transactions import (
    apply_controls,
    read_controls,
    read_raw,
    restore_factory_defaults,
    write_raw,
)
from calibrate_pro.application.monitor_controls import (
    BLUE_GAIN,
    BRIGHTNESS,
    CONTRAST,
    RED_GAIN,
    RESTORE_FACTORY_DEFAULTS,
    STAGEABLE_CODES,
    MonitorControlError,
)
from tests.monitor_control_support import DISPLAY_ID, INSTRUMENT, FakePanel

#: A code no control table in this build names, which a panel may still answer
#: for. Used where the point is a code reached only through the raw path.
UNNAMED = 0x22


def settled() -> None:
    """Stand in for the wait a real write needs, without spending it."""


def apply(panel: FakePanel, requests: dict[int, int]) -> ControlTransaction:
    """Run one transaction against the panel, with the wait taken out."""
    return apply_controls(panel, DISPLAY_ID, requests, settle=settled)


# -- what a panel is allowed to be asked for ----------------------------------


def test_a_value_past_the_range_the_display_reported_is_refused_before_any_write() -> None:
    """The range comes from the panel, not from a table in this build."""
    panel = FakePanel()

    with pytest.raises(MonitorControlError) as caught:
        apply(panel, {BRIGHTNESS: 150})

    assert "Brightness accepts 0 through 100, and 150 was staged for it" in str(caught.value)
    assert panel.writes() == []


def test_a_negative_value_is_refused_the_same_way() -> None:
    panel = FakePanel()

    with pytest.raises(MonitorControlError):
        apply(panel, {BRIGHTNESS: -1})

    assert panel.writes() == []


def test_each_control_is_checked_against_its_own_reported_ceiling() -> None:
    """A gain reporting 255 takes a value brightness reporting 100 would not."""
    panel = FakePanel()

    transaction = apply(panel, {RED_GAIN: 200})

    assert transaction.accepted
    assert panel.values[RED_GAIN] == 200


def test_a_boolean_is_not_an_integer_this_lane_will_write() -> None:
    """``True`` is an int in Python and is not a value a panel was asked for."""
    panel = FakePanel()

    with pytest.raises(MonitorControlError) as caught:
        apply(panel, {BRIGHTNESS: True})

    assert "must be an exact integer" in str(caught.value)
    assert panel.calls == []


def test_a_set_with_nothing_in_it_is_refused_rather_than_reported_as_done() -> None:
    panel = FakePanel()

    with pytest.raises(MonitorControlError) as caught:
        apply(panel, {})

    assert "no control value was staged" in str(caught.value)


def test_a_control_that_will_not_answer_stops_the_set_before_anything_is_written() -> None:
    """A value with no way to check it is worse than a value not written."""
    panel = FakePanel()
    panel.refuse_read(CONTRAST, "DDC/CI is off in the panel menu")

    with pytest.raises(MonitorControlError) as caught:
        apply(panel, {BRIGHTNESS: 40, CONTRAST: 60})

    assert "Contrast did not answer" in str(caught.value)
    assert panel.writes() == []


# -- what the panel did with it -----------------------------------------------


def test_a_write_the_panel_acted_on_reads_back_at_the_value_asked_for() -> None:
    panel = FakePanel()

    transaction = apply(panel, {BRIGHTNESS: 40})

    write = transaction.writes[0]
    assert transaction.accepted
    assert (write.before, write.requested, write.after) == (75, 40, 40)
    assert write.line == "Brightness: 75 to 40"


def test_a_panel_that_answers_a_write_and_holds_its_old_value_is_not_reported_as_having_taken_it() -> None:
    """The false-success control.

    Writing an advertised control a panel does not drive raises nothing and
    returns success. A result assembled from the calls would report brightness
    at 40 on a display still running at 75.
    """
    panel = FakePanel()
    panel.ignore(BRIGHTNESS)

    transaction = apply(panel, {BRIGHTNESS: 40})

    write = transaction.writes[0]
    assert not transaction.accepted
    assert not write.moved
    assert write.after == 75
    assert write.line == "Brightness: asked for 40, still reads 75"
    assert transaction.rejected == (write,)


def test_a_panel_that_lands_on_a_value_of_its_own_reports_the_number_it_chose() -> None:
    """A clamp moves the display and still fails what was asked for."""
    panel = FakePanel()
    panel.clamp(BRIGHTNESS, 60)

    transaction = apply(panel, {BRIGHTNESS: 90})

    write = transaction.writes[0]
    assert not transaction.accepted
    assert write.moved
    assert (write.requested, write.after) == (90, 60)
    assert write.line == "Brightness: asked for 90, reads 60"
    assert "1 of 1 did not take the value asked for" in transaction.summary


def test_a_read_taken_after_the_write_that_will_not_answer_reports_the_value_held_before() -> None:
    """The conservative answer: nobody got the read, so nothing is claimed.

    The panel here does take the write. What it stops doing is answering, and
    a lane that reported the requested value on the strength of a read nobody
    got would be reporting its own request back.
    """
    panel = FakePanel()
    panel.refuse_read(BRIGHTNESS, "the bus went quiet", after=1)

    transaction = apply(panel, {BRIGHTNESS: 40})

    assert not transaction.accepted
    assert transaction.writes[0].after == 75
    assert panel.values[BRIGHTNESS] == 40


def test_a_set_is_written_in_the_order_a_panel_lists_its_own_menu() -> None:
    """Two identical sets write identically, whatever order they were built in."""
    panel = FakePanel(values={UNNAMED: 5}, maxima={UNNAMED: 10})

    transaction = apply(panel, {UNNAMED: 7, BLUE_GAIN: 100, BRIGHTNESS: 40})

    assert panel.written_codes() == [BRIGHTNESS, BLUE_GAIN, UNNAMED]
    assert [write.code for write in transaction.writes] == [BRIGHTNESS, BLUE_GAIN, UNNAMED]
    assert transaction.writes[2].label == "VCP 0x22"


# -- a set that fails partway --------------------------------------------------


def test_a_write_that_fails_partway_puts_back_every_code_already_written() -> None:
    panel = FakePanel()
    panel.refuse_write(CONTRAST, "the display is busy")

    transaction = apply(panel, {BRIGHTNESS: 40, CONTRAST: 60})

    assert not transaction.accepted
    assert transaction.writes == ()
    assert transaction.restored == (BRIGHTNESS,)
    assert panel.values[BRIGHTNESS] == 75
    assert panel.written_codes() == [BRIGHTNESS, CONTRAST, BRIGHTNESS]
    assert "Contrast refused the write: the display is busy" in transaction.summary
    assert "Brightness put back to the value read before the write" in transaction.summary


def test_a_rollback_the_display_also_refused_is_named_rather_than_absorbed() -> None:
    """The one state an operator has to be told about: a display left half changed."""
    panel = FakePanel()
    panel.refuse_write(BRIGHTNESS, "the bus is busy", after=1)
    panel.refuse_write(CONTRAST, "the display is busy")

    transaction = apply(panel, {BRIGHTNESS: 40, CONTRAST: 60})

    assert transaction.restored == ()
    assert panel.values[BRIGHTNESS] == 40
    assert "Brightness would not go back to 75: the bus is busy" in transaction.summary


def test_a_rollback_puts_the_codes_back_in_the_reverse_of_the_order_they_went() -> None:
    """Undoing a set in the order it was made would drive the panel forwards."""
    panel = FakePanel()
    panel.refuse_write(RED_GAIN, "the display is busy")

    transaction = apply(panel, {BRIGHTNESS: 40, CONTRAST: 60, RED_GAIN: 200})

    assert panel.written_codes() == [BRIGHTNESS, CONTRAST, RED_GAIN, CONTRAST, BRIGHTNESS]
    assert transaction.restored == (BRIGHTNESS, CONTRAST)
    assert (panel.values[BRIGHTNESS], panel.values[CONTRAST]) == (75, 50)


# -- reading --------------------------------------------------------------------


def test_a_reading_keeps_the_controls_that_did_not_answer() -> None:
    """A panel driving six of these eight is normal, and the two are the news."""
    panel = FakePanel()
    panel.refuse_read(RED_GAIN, "unsupported VCP code")
    panel.refuse_read(BLUE_GAIN, "unsupported VCP code")

    reading = read_controls(panel, DISPLAY_ID)

    assert len(reading.controls) == len(STAGEABLE_CODES) - 2
    assert reading.codes == frozenset(STAGEABLE_CODES) - {RED_GAIN, BLUE_GAIN}
    assert [refused.label for refused in reading.refused] == ["Red gain", "Blue gain"]
    assert "unsupported VCP code" in reading.refused[0].reason
    assert "2 of the controls read did not answer" in reading.summary


def test_a_display_that_answers_and_reports_nothing_is_not_reported_as_a_reading() -> None:
    panel = FakePanel()
    for code in STAGEABLE_CODES:
        panel.refuse_read(code, "DDC/CI is off in the panel menu")

    reading = read_controls(panel, DISPLAY_ID)

    assert reading.controls == ()
    assert reading.codes == frozenset()
    assert f"{INSTRUMENT} answered on DDC/CI and reported none of the 8 controls read." == reading.summary


def test_a_raw_read_of_a_code_the_panel_does_not_answer_reports_it_rather_than_raising() -> None:
    panel = FakePanel()

    reading = read_raw(panel, DISPLAY_ID, UNNAMED)

    assert reading.controls == ()
    assert reading.refused[0].label == "VCP 0x22"
    assert "is not supported by this display" in reading.refused[0].reason


def test_a_raw_write_to_a_code_that_will_not_read_is_refused() -> None:
    """A write with no read-back is a request an operator cannot check."""
    panel = FakePanel()

    with pytest.raises(MonitorControlError):
        write_raw(panel, DISPLAY_ID, UNNAMED, 5, settle=settled)

    assert panel.writes() == []


# -- the factory restore --------------------------------------------------------


def test_a_panel_that_implements_no_restore_produces_readings_that_match() -> None:
    """The restore code cannot be read, so the panel never says what it did."""
    panel = FakePanel()

    restore = restore_factory_defaults(panel, DISPLAY_ID, settle=settled)

    assert restore.moved == ()
    assert "every control this build reads came back at the value it held" in restore.summary
    assert panel.written_codes() == [RESTORE_FACTORY_DEFAULTS]


def test_a_restore_is_reported_by_what_moved_between_the_two_readings() -> None:
    panel = FakePanel()
    panel.restores_to(brightness=50, contrast=75)

    restore = restore_factory_defaults(panel, DISPLAY_ID, settle=settled)

    assert restore.moved == ("Brightness 75 to 50", "Contrast 50 to 75")
    assert "restored its factory settings" in restore.summary


def test_a_restore_the_display_refused_is_raised_rather_than_reported_as_done() -> None:
    panel = FakePanel()
    panel.refuse_write(RESTORE_FACTORY_DEFAULTS, "the display is busy")

    with pytest.raises(MonitorControlError) as caught:
        restore_factory_defaults(panel, DISPLAY_ID, settle=settled)

    assert "the display refused the factory restore: the display is busy" in str(caught.value)
