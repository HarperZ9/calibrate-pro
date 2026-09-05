"""An absent reading must not arrive as a number.

Three places converted a missing reading into a plausible value: a cancelled
manual measurement returned pure black, a convex hull that could not be built
returned a volume of zero, and coverage for a display nobody sampled reported a
volume ratio of exactly 1.0. Each one is indistinguishable from a real result.

None of these tests opens a display, talks to a colorimeter, or writes a
profile. They call arithmetic and formatting directly.
"""

from __future__ import annotations

import numpy as np
import pytest

from calibrate_pro.verification.gamut_volume import (
    ColorSpace,
    GamutAnalyzer,
    calculate_gamut_volume_lab,
    calculate_gamut_volume_ratio,
    print_gamut_summary,
)
from calibrate_pro.verification.measured_verify import _manual_measure_xyz
from calibrate_pro.verification.reports import _num_or

MEASURED = {
    "R": (0.6750, 0.3220),
    "G": (0.2100, 0.6930),
    "B": (0.1490, 0.0620),
    "W": (0.3135, 0.3291),
}

# Three collinear points. A convex hull needs volume, so this is the cheapest
# input that makes the hull fail for a reason other than a missing scipy.
DEGENERATE = np.array([[50.0, 0.0, 0.0], [60.0, 0.0, 0.0], [70.0, 0.0, 0.0]])

# Eight corners of a box in Lab. Enough for a hull with a volume of 8000.
SOLID = np.array([[lightness, a, b] for lightness in (30.0, 50.0) for a in (-10.0, 10.0) for b in (-10.0, 10.0)])


class TestACancelledPatchIsNotABlackReading:
    """Ctrl+C at the prompt used to file (0, 0, 0) as the measurement."""

    def test_end_of_input_raises_instead_of_returning_black(self, monkeypatch):
        def no_input(*_args):
            raise EOFError

        monkeypatch.setattr("builtins.input", no_input)
        with pytest.raises(RuntimeError):
            _manual_measure_xyz(1.0, 1.0, 1.0)

    def test_an_interrupt_raises_instead_of_returning_black(self, monkeypatch):
        def interrupted(*_args):
            raise KeyboardInterrupt

        monkeypatch.setattr("builtins.input", interrupted)
        with pytest.raises(RuntimeError):
            _manual_measure_xyz(1.0, 1.0, 1.0)

    def test_the_error_says_no_reading_was_taken(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda *_a: (_ for _ in ()).throw(EOFError))
        with pytest.raises(RuntimeError, match="No reading was taken"):
            _manual_measure_xyz(1.0, 1.0, 1.0)

    def test_a_typed_reading_is_still_returned(self, monkeypatch):
        """Control. The prompt must still accept a measurement."""
        monkeypatch.setattr("builtins.input", lambda *_a: "95.047 100.0 108.883")
        assert _manual_measure_xyz(1.0, 1.0, 1.0) == (95.047, 100.0, 108.883)

    def test_a_short_entry_reprompts_rather_than_raising(self, monkeypatch):
        """Control. A typo is not a cancellation."""
        answers = iter(["95.047 100.0", "95.047 100.0 108.883"])
        monkeypatch.setattr("builtins.input", lambda *_a: next(answers))
        assert _manual_measure_xyz(1.0, 1.0, 1.0) == (95.047, 100.0, 108.883)


class TestAVolumeNobodyComputedStaysEmpty:
    """A hull that cannot be built has no volume, not a volume of zero."""

    def test_degenerate_samples_give_none_not_zero(self):
        assert calculate_gamut_volume_lab(DEGENERATE) is None

    def test_a_ratio_needs_both_volumes(self):
        assert calculate_gamut_volume_ratio(DEGENERATE, ColorSpace.SRGB) is None

    def test_a_real_sample_set_still_computes_a_volume(self):
        """Control. The working path must keep working."""
        volume = calculate_gamut_volume_lab(SOLID)
        assert volume is not None
        assert volume == pytest.approx(8000.0)

    def test_a_real_ratio_is_still_a_number(self):
        """Control."""
        ratio = calculate_gamut_volume_ratio(SOLID, ColorSpace.SRGB)
        assert ratio is not None
        assert ratio > 0


class TestUnsampledCoverageIsNotAPerfectMatch:
    """analyze() without samples used to report a ratio of exactly 1.0."""

    def _result(self):
        return GamutAnalyzer().analyze(MEASURED)

    def test_volume_ratio_is_absent_without_samples(self):
        assert self._result().srgb_coverage.volume_ratio is None

    def test_volume_lab_is_absent_without_samples(self):
        assert self._result().srgb_coverage.volume_lab is None

    def test_total_volume_is_absent_without_samples(self):
        assert self._result().total_volume_lab is None

    def test_every_target_space_reports_the_same_absence(self):
        result = self._result()
        for coverage in (
            result.srgb_coverage,
            result.p3_coverage,
            result.bt2020_coverage,
            result.adobe_rgb_coverage,
        ):
            assert coverage.volume_ratio is None

    def test_the_console_summary_says_not_computed(self, capsys):
        print_gamut_summary(self._result())
        assert "not computed" in capsys.readouterr().out

    def test_coverage_percent_is_still_reported(self):
        """Control. 2D coverage comes from the primaries and needs no samples."""
        assert self._result().srgb_coverage.coverage_percent > 0


class TestTheReportFormatterNamesAnAbsentVolume:
    """The HTML and PDF cells route through one formatter."""

    def test_an_absent_volume_reads_not_computed(self):
        assert _num_or(None, "{:.2f}", "not computed") == "not computed"

    def test_an_absent_white_point_still_reads_not_measured(self):
        assert _num_or(None, "{:.0f}K") == "not measured"

    def test_a_real_volume_still_formats(self):
        """Control."""
        assert _num_or(0.982, "{:.2f}", "not computed") == "0.98"
