"""Whether a display is emitting its own light or somebody else's correction.

A characterization run answers what the panel does. It cannot answer that while
a correction sits between the signal and the light, because the instrument then
reads the panel and the correction together and the run describes a chain the
next calibration would be stacked on top of. Building a second correction from
those numbers doubles the first one.

So a run is qualified before it starts. The video card gamma table is read back
and compared against the identity table, and the run is refused when the table
carries anything else. Refusing is the whole action here: this module reads and
never writes, so clearing a table stays something the operator does, in the tool
that loaded it.

What this establishes is one layer. The video card table is where Windows keeps
a VCGT curve and where nearly every calibration tool on the platform puts its
correction, so it catches the case that matters. It does not catch a DWM LUT, an
ICC profile a colour-managed application applies to its own window, or a
correction the monitor is running in its own hardware. Those stay uncovered, and
the sentence this returns says so rather than implying a clean display.

Verification does not use any of this. A verification run is supposed to read a
correction, because reading the correction is what tells the operator whether it
worked.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, cast

from calibrate_pro.application.measurement import MeasurementRefused

#: Entries a video card gamma table holds per channel. The Windows API takes
#: exactly this and a table of another length did not come from it.
RAMP_ENTRIES = 256

#: Largest value an entry can hold. The table is sixteen bits deep while its
#: index is eight, so the identity entry for index i is i * IDENTITY_STEP.
RAMP_MAXIMUM = 65535
IDENTITY_STEP = RAMP_MAXIMUM // (RAMP_ENTRIES - 1)

#: How far an entry may sit from identity and still be identity. One 8-bit code
#: is the granularity a driver rounds to, so a table built by scaling an 8-bit
#: identity table lands inside this. Every real correction lands far outside it:
#: a 2.2-to-2.4 tone change alone moves midtones by thousands of codes.
IDENTITY_TOLERANCE = IDENTITY_STEP

#: What this check covers, stated with the answer rather than in a manual. A
#: sentence saying the display is uncorrected would be a claim about layers this
#: never looked at.
UNCOVERED_LAYERS = (
    "A DWM LUT, a colour-managed application's own profile, and a correction "
    "running inside the monitor are not covered by this check."
)

#: Reads the video card gamma table for one display, or answers None. The
#: platform reader is resolved when a run needs it so that qualifying a run is
#: what pulls the module in, rather than importing this one.
RampReader = Callable[[str], Any]


def _platform_reader(display_id: str) -> Any:
    """Read the table through the platform, importing the reader on the way.

    The import sits in the body for the reason every other platform import in
    this layer does: a session that never measures never loads it, and the
    read-only build can still say that nothing which writes to a display was
    pulled into its process.
    """
    from calibrate_pro.panels.detection import get_gamma_ramp

    return get_gamma_ramp(display_id)


def _channel_entries(channel: object, *, name: str) -> list[int]:
    """Turn one channel of a table into integers, refusing anything else."""
    if isinstance(channel, (str, bytes, bytearray)):
        raise MeasurementRefused(f"the {name} gamma table came back as text rather than as entries")
    try:
        entries = list(cast(Iterable[Any], channel))
    except TypeError as exc:
        raise MeasurementRefused(f"the {name} gamma table entries could not be read") from exc
    if len(entries) != RAMP_ENTRIES:
        raise MeasurementRefused(f"the {name} gamma table holds {len(entries)} entries rather than {RAMP_ENTRIES}")
    values = []
    for entry in entries:
        try:
            value = int(entry)
        except (TypeError, ValueError) as exc:
            raise MeasurementRefused(f"the {name} gamma table holds a value that is not a number") from exc
        if value < 0 or value > RAMP_MAXIMUM:
            raise MeasurementRefused(f"the {name} gamma table holds {value}, outside the range the table can carry")
        values.append(value)
    return values


def identity_deviation(ramp: object) -> int:
    """Report how far a table sits from identity, in sixteen-bit codes.

    Zero is the table Windows loads when nothing has corrected the display.
    """
    if isinstance(ramp, (str, bytes, bytearray)):
        raise MeasurementRefused("the gamma table came back as text rather than as three channels")
    try:
        channels = tuple(cast(Iterable[Any], ramp))
    except TypeError as exc:
        raise MeasurementRefused("the gamma table did not come back as three channels") from exc
    if len(channels) != 3:
        raise MeasurementRefused(f"the gamma table came back as {len(channels)} channels rather than three")
    worst = 0
    for name, channel in zip(("red", "green", "blue"), channels, strict=True):
        for index, value in enumerate(_channel_entries(channel, name=name)):
            worst = max(worst, abs(value - index * IDENTITY_STEP))
    return worst


def qualify_uncorrected(display_id: str, *, reader: RampReader | None = None) -> str:
    """Refuse a characterization run against a corrected display, or say so.

    The returned sentence travels with the run. A measurement is only
    reproducible next to the state the display was in when it was taken, and a
    check whose result is thrown away is a check the report cannot show.
    """
    read = _platform_reader if reader is None else reader
    try:
        ramp = read(display_id)
    except Exception as exc:  # noqa: BLE001  (any platform failure is one answer)
        raise MeasurementRefused(f"the display's gamma table could not be read: {exc}") from exc
    if ramp is None:
        # Unreadable is not uncorrected. The reader answers None both for a
        # display that refused a device context and for a call that failed, and
        # measuring anyway would build a calibration on top of whatever was
        # loaded without anything in the record saying so.
        raise MeasurementRefused(
            "the display's gamma table could not be read, so this run cannot establish that no correction is loaded"
        )
    deviation = identity_deviation(ramp)
    if deviation > IDENTITY_TOLERANCE:
        raise MeasurementRefused(
            f"the display is loading a gamma table {deviation} codes from identity, so a run would "
            "measure that correction together with the panel; clear it and measure again"
        )
    return f"The display's gamma table read within {deviation} codes of identity before this run. {UNCOVERED_LAYERS}"


__all__ = [
    "IDENTITY_STEP",
    "IDENTITY_TOLERANCE",
    "RAMP_ENTRIES",
    "RAMP_MAXIMUM",
    "UNCOVERED_LAYERS",
    "RampReader",
    "identity_deviation",
    "qualify_uncorrected",
]
