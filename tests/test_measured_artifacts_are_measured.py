"""A file named for a measured run holds what the instrument read.

The hardware path in ``CalibrationEngine`` wrote two artifacts, an ICC profile
and a 3D LUT, both named ``*_measured.*``, and neither was built the way its
name says.

The ICC builder substituted the Rec.709 primaries and D65 for any chromaticity
the sweep failed to produce, and substituted 2.2 for a gamma it could not fit.
Those describe a standard, not this display, and they went into a profile whose
description ends "(Measured)" that every colour managed application on the
machine then trusts. The LUT builder never opened the measurements at all: it
read the panel database entry for the model string, so a run with an instrument
attached discarded every reading and gave two displays of the same model
identical corrections. Verification closed the loop by reporting a Delta E of
0.0, marked as measured evidence, when it had measured no patches.

None of the four paths could be reached without a display callback either, and
the sweep took every reading with nothing on screen.

PRODUCT.md: the interface must never convert modeled, simulated, replayed, or
placeholder values into apparent instrument observations. A modelled value
written into an artifact named for a measurement is that conversion, one step
further from the reader than a fabricated readout.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from calibrate_pro.core.calibration_engine import CalibrationEngine, CalibrationMode

#: The Rec.709 primaries and D65 the ICC builder substituted for a missing
#: measurement, and the gamma the fit fell back to.
REC709_RED = (0.64, 0.33)
D65_WHITE_XY = (0.3127, 0.3290)
FALLBACK_GAMMA = 2.2

#: A panel whose measured primaries are nowhere near Rec.709, so a substitution
#: is visible in the artifact rather than hiding inside rounding.
MEASURED_PRIMARIES = {
    "red": {"xy": (0.681, 0.312)},
    "green": {"xy": (0.243, 0.688)},
    "blue": {"xy": (0.148, 0.052)},
    "white": {"xy": (0.3095, 0.3242)},
}


def _grayscale(gamma: float = 2.4, steps: int = 21) -> list[dict]:
    """A neutral ramp whose luminances follow a known gamma."""
    return [{"level": i / (steps - 1), "luminance": 120.0 * (i / (steps - 1)) ** gamma} for i in range(steps)]


def _panel() -> SimpleNamespace:
    """Stands in for the database entry, which titles the LUT and nothing else."""
    return SimpleNamespace(manufacturer="ASUS", model_pattern="PA32UCG|PA32UCX")


@pytest.fixture
def engine():
    return CalibrationEngine(mode=CalibrationMode.COLORIMETER)


# ---------------------------------------------------------------------------
# Reading a patch that was never shown
# ---------------------------------------------------------------------------


class _CountingColorimeter:
    """Counts reads so a test can show that none happened."""

    def __init__(self):
        self.reads = 0

    def measure_spot(self):
        self.reads += 1
        return None


def test_a_patch_is_not_read_without_something_to_show_it(engine):
    """No callback means the reading would be of the previous screen contents."""
    engine.colorimeter = _CountingColorimeter()

    assert engine._measure_with_display((1.0, 0.0, 0.0)) is None
    assert engine.colorimeter.reads == 0


def test_the_skipped_patch_is_named_on_the_progress_channel(engine):
    """A silent None would look like an instrument that returned nothing."""
    engine.colorimeter = _CountingColorimeter()
    messages: list[str] = []
    engine.set_progress_callback(lambda msg, pct: messages.append(msg))

    engine._measure_with_display((1.0, 0.0, 0.0))

    assert any("patch display" in m for m in messages)


def test_a_hardware_run_refuses_up_front_rather_than_sweeping_a_static_screen(engine, tmp_path):
    """One clear error beats twenty-one readings of one unchanged image."""
    engine.colorimeter = _CountingColorimeter()

    with pytest.raises(ValueError) as raised:
        engine.calibrate_hardware("ASUS PA32UCG", tmp_path)

    assert "display_callback" in str(raised.value)
    assert engine.colorimeter.reads == 0


# ---------------------------------------------------------------------------
# ICC profiles
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("absent", ["red", "green", "blue", "white"])
def test_a_missing_chromaticity_is_not_filled_in_from_a_standard(engine, absent):
    """Rec.709 and D65 describe a standard, so neither stands in for a reading."""
    primaries = {name: xy for name, xy in MEASURED_PRIMARIES.items() if name != absent}
    cal_data = {"primaries": primaries, "grayscale": _grayscale()}

    with pytest.raises(ValueError) as raised:
        engine._create_icc_from_measurements(cal_data, _panel())

    assert absent in str(raised.value)


def test_a_measured_profile_carries_the_measured_primaries(engine):
    """With every chromaticity measured the profile is built and keeps them."""
    cal_data = {"primaries": MEASURED_PRIMARIES, "grayscale": _grayscale()}

    profile = engine._create_icc_from_measurements(cal_data, _panel())

    assert profile is not None


def test_a_gamma_that_cannot_be_fitted_is_not_replaced_by_a_default(engine):
    """2.2 published as the measured tone response is an assumption, not a fit."""
    with pytest.raises(ValueError) as raised:
        engine._calculate_gamma_from_grayscale([{"level": 0.5, "luminance": 25.0}])

    assert str(FALLBACK_GAMMA) not in str(raised.value)


def test_a_ramp_with_too_few_usable_points_is_refused(engine):
    """The end points and any that normalize to zero drop out before the fit."""
    ramp = [
        {"level": 0.0, "luminance": 0.0},
        {"level": 0.25, "luminance": 0.0},
        {"level": 0.5, "luminance": 0.0},
        {"level": 0.75, "luminance": 0.0},
        {"level": 1.0, "luminance": 100.0},
    ]

    with pytest.raises(ValueError) as raised:
        engine._calculate_gamma_from_grayscale(ramp)

    assert "usable" in str(raised.value)


def test_a_point_with_no_luminance_is_not_read_as_a_nominal_endpoint(engine):
    """A missing white used to read as 100 and a missing black as 0.

    Those two set the normalization every other point is fitted against, so an
    assumed endpoint reshapes the exponent the profile publishes as measured.
    """
    ramp = _grayscale()
    ramp[-1] = {"level": 1.0}

    with pytest.raises(ValueError) as raised:
        engine._calculate_gamma_from_grayscale(ramp)

    assert "luminance" in str(raised.value)


def test_a_ramp_with_no_measured_range_is_refused_rather_than_dividing_by_zero(engine):
    """Equal endpoints mean the display was off, saturated, or read shuttered."""
    ramp = [{"level": level, "luminance": 4.0} for level in (0.0, 0.25, 0.5, 0.75, 1.0)]

    with pytest.raises(ValueError) as raised:
        engine._calculate_gamma_from_grayscale(ramp)

    assert "no measured range" in str(raised.value)


@pytest.mark.parametrize("exponent", [1.2, 4.0])
def test_a_fit_outside_the_displayable_range_is_refused_not_clamped(engine, exponent):
    """The fit used to be clamped into 1.8 to 3.0 and returned as measured.

    A ramp that fits outside that range is not a power law, so no single gamma
    describes it, and the nearest in-range number is a modelled value.
    """
    with pytest.raises(ValueError) as raised:
        engine._calculate_gamma_from_grayscale(_grayscale(gamma=exponent))

    assert "1.8" in str(raised.value)


def test_a_fitted_gamma_follows_the_ramp_it_was_given(engine):
    """The fit reads the measurements, so a 2.4 ramp does not return 2.2."""
    fitted = engine._calculate_gamma_from_grayscale(_grayscale(gamma=2.4))

    assert fitted == pytest.approx(2.4, abs=0.05)


# ---------------------------------------------------------------------------
# 3D LUTs
# ---------------------------------------------------------------------------


def test_the_lut_is_built_from_the_measurements_not_the_panel_database(engine):
    """A different measured gamma has to produce a different LUT.

    The builder used to read the database entry for the model string and ignore
    ``cal_data`` entirely, so every display of a model got the same correction
    whatever the instrument read off the panel in front of it.
    """
    panel = _panel()
    steep = engine._create_lut_from_measurements(
        {"primaries": MEASURED_PRIMARIES, "grayscale": _grayscale(gamma=2.6)}, panel, size=5
    )
    shallow = engine._create_lut_from_measurements(
        {"primaries": MEASURED_PRIMARIES, "grayscale": _grayscale(gamma=1.9)}, panel, size=5
    )

    assert not (steep.data == shallow.data).all()


@pytest.mark.parametrize("absent", ["red", "green", "blue", "white"])
def test_a_missing_chromaticity_is_not_filled_in_from_the_panel_database(engine, absent):
    """The database entry substituted here would go into a file named measured."""
    primaries = {name: xy for name, xy in MEASURED_PRIMARIES.items() if name != absent}

    with pytest.raises(ValueError) as raised:
        engine._create_lut_from_measurements({"primaries": primaries, "grayscale": _grayscale()}, _panel(), size=5)

    assert absent in str(raised.value)


def test_a_lut_without_a_measured_ramp_is_refused(engine):
    """No ramp, no fitted gamma, so no correction to write."""
    with pytest.raises(ValueError):
        engine._create_lut_from_measurements({"primaries": MEASURED_PRIMARIES, "grayscale": []}, _panel(), size=5)


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def test_verification_that_measured_nothing_does_not_report_a_perfect_delta_e(engine):
    """Zero is the best possible number, and it came from an empty list.

    The caller wrapped it as a measured metric and set the run successful, so a
    display nothing was read from was published as the best result the tool can
    produce.
    """
    engine.colorimeter = _CountingColorimeter()

    with pytest.raises(RuntimeError) as raised:
        engine._verify_hardware(lambda patch: None)

    assert "none of the" in str(raised.value)


def test_verification_without_a_display_refuses_rather_than_reporting_zero(engine):
    """The missing callback reaches the same refusal by the measurement guard."""
    engine.colorimeter = _CountingColorimeter()

    with pytest.raises(RuntimeError):
        engine._verify_hardware()

    assert engine.colorimeter.reads == 0
