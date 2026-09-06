"""A characterization run has to establish what it is measuring first.

An instrument pointed at a corrected display reads the panel and the correction
together. A profile built from those numbers describes the chain, and loading it
applies the correction twice. So the run is qualified before it starts, and the
qualification is a read of the video card gamma table.

These tests hold the two halves of that. The table has to be believed only when
it is really identity, which is what the malformed-shape and boundary cases are
for. And the sentence the check returns has to say what it did not look at,
because a run that reported a clean display would be claiming something about
layers it never read.
"""

from __future__ import annotations

import pytest

from calibrate_pro.application.correction_state import (
    IDENTITY_STEP,
    IDENTITY_TOLERANCE,
    RAMP_ENTRIES,
    RAMP_MAXIMUM,
    UNCOVERED_LAYERS,
    identity_deviation,
    qualify_uncorrected,
)
from calibrate_pro.application.measurement import MeasurementRefused

DISPLAY = "\\\\.\\DISPLAY1"


def identity_channel() -> list[int]:
    """The table Windows loads when nothing has corrected the display."""
    return [index * IDENTITY_STEP for index in range(RAMP_ENTRIES)]


def identity_table() -> tuple[list[int], list[int], list[int]]:
    return (identity_channel(), identity_channel(), identity_channel())


def tone_curve(exponent: float) -> list[int]:
    """A channel carrying a real correction, of the size a tool would load."""
    return [round(((index / (RAMP_ENTRIES - 1)) ** exponent) * RAMP_MAXIMUM) for index in range(RAMP_ENTRIES)]


class Reader:
    """A stand-in for the platform read, which records what it was asked."""

    def __init__(self, answer: object, *, raises: Exception | None = None) -> None:
        self.answer = answer
        self.raises = raises
        self.calls: list[str] = []

    def __call__(self, display_id: str) -> object:
        self.calls.append(display_id)
        if self.raises is not None:
            raise self.raises
        return self.answer


# The clean case ------------------------------------------------------------


def test_an_identity_table_qualifies_the_run_and_says_what_it_did_not_check() -> None:
    reader = Reader(identity_table())

    sentence = qualify_uncorrected(DISPLAY, reader=reader)

    assert reader.calls == [DISPLAY], "the check reads the table for the display it was asked about, once"
    assert "within 0 codes of identity" in sentence
    assert UNCOVERED_LAYERS in sentence, "a sentence without this reads as a claim that the display is clean"


def test_the_sentence_names_the_layers_this_check_cannot_see() -> None:
    for layer in ("DWM LUT", "colour-managed application", "inside the monitor"):
        assert layer in UNCOVERED_LAYERS


def test_a_table_rounded_from_eight_bit_identity_still_qualifies() -> None:
    """A driver that rebuilds identity at 8-bit precision must not fail this."""
    channel = identity_channel()
    channel[128] += IDENTITY_TOLERANCE
    reader = Reader((channel, identity_channel(), identity_channel()))

    sentence = qualify_uncorrected(DISPLAY, reader=reader)

    assert f"within {IDENTITY_TOLERANCE} codes" in sentence


# The corrected case --------------------------------------------------------


def test_a_loaded_correction_refuses_the_run_and_names_the_deviation() -> None:
    reader = Reader((tone_curve(2.2 / 2.4), identity_channel(), identity_channel()))

    with pytest.raises(MeasurementRefused) as refusal:
        qualify_uncorrected(DISPLAY, reader=reader)

    message = str(refusal.value)
    assert "codes from identity" in message
    assert "clear it and measure again" in message, "the operator has to be told what to do about it"
    deviation = identity_deviation((tone_curve(2.2 / 2.4), identity_channel(), identity_channel()))
    assert str(deviation) in message
    assert deviation > 1000, "a tone change of this size is nowhere near the rounding allowance"


def test_one_code_past_the_allowance_is_a_correction() -> None:
    channel = identity_channel()
    channel[128] += IDENTITY_TOLERANCE + 1

    with pytest.raises(MeasurementRefused):
        qualify_uncorrected(DISPLAY, reader=Reader((channel, identity_channel(), identity_channel())))


def test_a_correction_in_any_channel_refuses() -> None:
    for position in range(3):
        channels = [identity_channel(), identity_channel(), identity_channel()]
        channels[position] = tone_curve(1.0 / 1.2)
        with pytest.raises(MeasurementRefused):
            qualify_uncorrected(DISPLAY, reader=Reader(tuple(channels)))


# Unreadable is not uncorrected ---------------------------------------------


def test_a_table_that_could_not_be_read_refuses_rather_than_assuming_identity() -> None:
    with pytest.raises(MeasurementRefused) as refusal:
        qualify_uncorrected(DISPLAY, reader=Reader(None))

    assert "cannot establish that no correction is loaded" in str(refusal.value)


def test_a_reader_that_raises_refuses_and_carries_what_it_said() -> None:
    reader = Reader(None, raises=OSError("the display refused a device context"))

    with pytest.raises(MeasurementRefused) as refusal:
        qualify_uncorrected(DISPLAY, reader=reader)

    assert "could not be read" in str(refusal.value)
    assert "refused a device context" in str(refusal.value)


# Shapes that did not come from the API -------------------------------------


@pytest.mark.parametrize(
    ("label", "ramp"),
    [
        ("text instead of channels", "identity"),
        ("bytes instead of channels", b"identity"),
        ("two channels", (identity_channel(), identity_channel())),
        ("four channels", (identity_channel(),) * 4),
        ("a channel of text", ("identity", identity_channel(), identity_channel())),
        ("a short channel", (identity_channel()[:255], identity_channel(), identity_channel())),
        ("a long channel", (identity_channel() + [0], identity_channel(), identity_channel())),
        ("a channel of nothing", (None, identity_channel(), identity_channel())),
        ("an entry that is not a number", (["x"] + identity_channel()[1:], identity_channel(), identity_channel())),
        ("a negative entry", ([-1] + identity_channel()[1:], identity_channel(), identity_channel())),
        (
            "an entry past sixteen bits",
            ([RAMP_MAXIMUM + 1] + identity_channel()[1:], identity_channel(), identity_channel()),
        ),
    ],
)
def test_a_table_that_did_not_come_from_the_api_refuses(label: str, ramp: object) -> None:
    with pytest.raises(MeasurementRefused):
        qualify_uncorrected(DISPLAY, reader=Reader(ramp))


def test_the_deviation_of_an_identity_table_is_zero() -> None:
    assert identity_deviation(identity_table()) == 0


def test_the_deviation_is_the_worst_entry_across_all_three_channels() -> None:
    channel = identity_channel()
    channel[10] += 4
    channel[200] -= 9
    assert identity_deviation((identity_channel(), channel, identity_channel())) == 9
