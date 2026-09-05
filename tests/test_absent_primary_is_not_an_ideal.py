"""An absent chromaticity must not be filled in with the value it is scored against.

Gamut analysis took a dict of measured primaries and reached for a default
twice. A missing R, G or B became the target primary for the space being
scored, so the delta against that target came out at exactly 0.0 and the panel
reported a perfect primary. A missing W became D65, so a panel whose white
nobody read was published at 6504K with a Duv of 0.0000, in the console
summary, the PDF, the HTML report and the JSON.

These tests run on chromaticity arithmetic. None of them opens a display,
talks to a colorimeter or writes a profile.
"""

import pytest

from calibrate_pro.verification.gamut_volume import GamutAnalyzer, print_gamut_summary
from calibrate_pro.verification.reports import _wp_num, _wp_xy

# A plausible wide-gamut panel, offset from sRGB so a zero delta means the
# fallback fired rather than the panel happening to be exact.
MEASURED = {
    "R": (0.6750, 0.3220),
    "G": (0.2100, 0.6930),
    "B": (0.1490, 0.0620),
    "W": (0.3135, 0.3291),
}


class TestAMissingPrimaryIsRefused:
    """The analysis needs a red, a green and a blue, and says which is absent."""

    @pytest.mark.parametrize("absent", ["R", "G", "B"])
    def test_analyze_refuses_and_names_the_missing_channel(self, absent):
        primaries = {k: v for k, v in MEASURED.items() if k != absent}
        with pytest.raises(ValueError) as excinfo:
            GamutAnalyzer().analyze(primaries)
        assert absent in str(excinfo.value)

    def test_the_message_lists_every_missing_channel(self):
        with pytest.raises(ValueError) as excinfo:
            GamutAnalyzer().analyze({"W": MEASURED["W"]})
        message = str(excinfo.value)
        assert "R" in message and "G" in message and "B" in message

    def test_a_complete_set_is_accepted(self):
        """Control: the refusal is about absence, not about strictness."""
        result = GamutAnalyzer().analyze(MEASURED)
        assert result.measured_primaries == MEASURED


class TestAPrimaryIsScoredAgainstWhatWasMeasured:
    """The delta compares two different numbers, never a number with itself."""

    def test_measured_primaries_are_not_replaced_by_targets(self):
        result = GamutAnalyzer().analyze(MEASURED)
        for primary in result.srgb_coverage.primaries:
            assert primary.measured_xy == MEASURED[primary.name]

    def test_a_panel_off_target_does_not_report_a_zero_delta(self):
        result = GamutAnalyzer().analyze(MEASURED)
        for primary in result.srgb_coverage.primaries:
            assert primary.delta_xy > 0.0, f"{primary.name} scored itself"
        assert result.srgb_coverage.primary_accuracy_mean > 0.0

    def test_an_exact_match_still_reports_zero(self):
        """Control: a real zero survives, so the test above is about substitution."""
        exact = {"R": (0.64, 0.33), "G": (0.30, 0.60), "B": (0.15, 0.06), "W": MEASURED["W"]}
        result = GamutAnalyzer().analyze(exact)
        for primary in result.srgb_coverage.primaries:
            assert primary.delta_xy == pytest.approx(0.0, abs=1e-9)


class TestAnUnmeasuredWhitePointStaysEmpty:
    """No white in, no white point out, on every surface that prints one."""

    @staticmethod
    def _without_white():
        return GamutAnalyzer().analyze({k: v for k, v in MEASURED.items() if k != "W"})

    def test_the_result_carries_none_not_d65(self):
        result = self._without_white()
        assert result.white_point_xy is None
        assert result.white_point_cct is None
        assert result.white_point_duv is None

    def test_a_measured_white_is_still_reported(self):
        """Control: the field is empty because nothing was measured."""
        result = GamutAnalyzer().analyze(MEASURED)
        assert result.white_point_xy == MEASURED["W"]
        assert result.white_point_cct is not None
        assert result.white_point_cct > 0

    def test_the_console_summary_says_not_measured(self, capsys):
        print_gamut_summary(self._without_white())
        out = capsys.readouterr().out
        assert "White Point: not measured" in out
        assert "6504" not in out

    def test_the_report_formatters_say_not_measured(self):
        result = self._without_white()
        assert _wp_xy(result) == "not measured"
        assert _wp_num(result.white_point_cct, "{:.0f}K") == "not measured"
        assert _wp_num(result.white_point_duv, "{:.4f}") == "not measured"

    def test_the_report_formatters_still_format_a_real_reading(self):
        """Control: the formatters are not stuck on the empty answer."""
        result = GamutAnalyzer().analyze(MEASURED)
        assert _wp_xy(result).startswith("(0.3135")
        assert _wp_num(result.white_point_cct, "{:.0f}K").endswith("K")
