"""A CAM16 figure is computed, or it is absent. It is never CIEDE2000 renamed.

When the CAM16 conversion failed for a patch, the engine assigned that patch's
CIEDE2000 distance to ``cam16_de`` and carried on. The number then travelled
under CAM16 names: into the patch record, into the averages, and into the HTML
report's "dE CAM16-UCS" field. Two different measures of two different things,
printed side by side in one report, with the second silently holding a copy of
the first.

The grade made it worse. It took ``max(delta_e_avg, cam16_delta_e_avg)`` and
called that the stricter of the two metrics, which under the substitution was
one metric compared against itself.

Nothing failed and nothing looked wrong, which is why these tests drive the
failure deliberately rather than waiting for a degenerate patch to find it.
"""

from __future__ import annotations

import logging

import pytest

from calibrate_pro.sensorless import neuralux
from calibrate_pro.sensorless.neuralux import NeuralUXEngine

CAM16_KEYS = ("cam16_delta_e_values", "cam16_delta_e_avg", "cam16_delta_e_max")


def _engine(panel_database, panel) -> NeuralUXEngine:
    engine = NeuralUXEngine(panel_database=panel_database)
    engine.current_panel = panel
    return engine


def _break_cam16(monkeypatch: pytest.MonkeyPatch, *, on_patch: str | None = None) -> None:
    """Make the CAM16 conversion raise, for one patch or for all of them."""
    real = neuralux.xyz_to_cam16
    seen: list[int] = []

    def failing(xyz, env):  # noqa: ANN001, ANN202 - mirrors the function it replaces
        seen.append(1)
        if on_patch is None or len(seen) <= 2:
            raise ValueError("simulated degenerate CAM16 input")
        return real(xyz, env)

    monkeypatch.setattr(neuralux, "xyz_to_cam16", failing)


def test_cam16_is_reported_when_it_computes(panel_database, qd_oled_panel) -> None:
    """The ordinary path is unchanged, which is what makes the absence meaningful."""
    result = _engine(panel_database, qd_oled_panel).verify_calibration(qd_oled_panel)

    for key in CAM16_KEYS:
        assert key in result
    assert "cam16_unavailable" not in result
    assert len(result["cam16_delta_e_values"]) == len(result["delta_e_values"])
    for patch in result["patches"]:
        assert "cam16_delta_e" in patch


def test_a_failed_cam16_is_dropped_rather_than_filled_in(
    panel_database, qd_oled_panel, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The defect itself. Every CAM16 name is absent, not holding a copy."""
    _break_cam16(monkeypatch)
    result = _engine(panel_database, qd_oled_panel).verify_calibration(qd_oled_panel)

    for key in CAM16_KEYS:
        assert key not in result, f"{key} survived a CAM16 failure"
    for patch in result["patches"]:
        assert "cam16_delta_e" not in patch
    assert result["delta_e_values"], "the CIEDE2000 figures are unaffected and still reported"


def test_a_failed_cam16_never_equals_the_ciede2000_figure(
    panel_database, qd_oled_panel, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The false-success control.

    A build that substitutes passes every other test in this file that only
    checks for the presence of a number. It fails here, because the substituted
    value is by construction the CIEDE2000 one. Written as a comparison rather
    than an absence check so it stays meaningful if a later change reintroduces
    the key with a computed-looking value.
    """
    _break_cam16(monkeypatch)
    result = _engine(panel_database, qd_oled_panel).verify_calibration(qd_oled_panel)

    assert result.get("cam16_delta_e_avg") != result["delta_e_avg"]
    assert result.get("cam16_delta_e_max") != result["delta_e_max"]
    for patch in result["patches"]:
        assert patch.get("cam16_delta_e") != patch["delta_e"]


def test_a_failed_cam16_says_why(panel_database, qd_oled_panel, monkeypatch: pytest.MonkeyPatch) -> None:
    """An absent metric carries its reason, so the gap is legible rather than blank."""
    _break_cam16(monkeypatch)
    result = _engine(panel_database, qd_oled_panel).verify_calibration(qd_oled_panel)

    reason = result.get("cam16_unavailable")
    assert isinstance(reason, str) and reason
    assert "simulated degenerate CAM16 input" in reason


def test_a_partial_cam16_failure_drops_the_whole_metric(
    panel_database, qd_oled_panel, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A mean over the patches that converged has a different denominator.

    It would print beside the CIEDE2000 mean in the same report with nothing
    saying the two were computed over different patch sets, so the metric is
    reported for every patch or for none.
    """
    _break_cam16(monkeypatch, on_patch="some")
    result = _engine(panel_database, qd_oled_panel).verify_calibration(qd_oled_panel)

    for key in CAM16_KEYS:
        assert key not in result
    assert "cam16_unavailable" in result


def test_the_grade_survives_a_dropped_cam16(panel_database, qd_oled_panel, monkeypatch: pytest.MonkeyPatch) -> None:
    """The grade takes the stricter of the metrics that exist, not of a fixed two.

    Control: a build that still reads ``results["cam16_delta_e_avg"]``
    unconditionally raises KeyError here instead of grading.
    """
    graded = _engine(panel_database, qd_oled_panel).verify_calibration(qd_oled_panel)
    _break_cam16(monkeypatch)
    dropped = _engine(panel_database, qd_oled_panel).verify_calibration(qd_oled_panel)

    assert isinstance(dropped["grade"], str) and dropped["grade"]
    assert dropped["delta_e_avg"] == pytest.approx(graded["delta_e_avg"])


def test_a_dropped_cam16_is_logged(
    panel_database, qd_oled_panel, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The reason reaches a log record rather than only stdout.

    The engine used to print the failure once per patch, straight into whatever
    a caller was writing, which on a 24-patch chart meant 24 lines through the
    middle of a report.
    """
    _break_cam16(monkeypatch)
    with caplog.at_level(logging.WARNING, logger="calibrate_pro.sensorless.neuralux"):
        _engine(panel_database, qd_oled_panel).verify_calibration(qd_oled_panel)

    warnings = [record for record in caplog.records if "CAM16-UCS dropped" in record.getMessage()]
    assert len(warnings) == 1, "logged once for the run, not once per patch"


def test_nothing_is_printed_to_stdout(
    panel_database, qd_oled_panel, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Library code writing to stdout corrupts the machine-readable command output."""
    _break_cam16(monkeypatch)
    _engine(panel_database, qd_oled_panel).verify_calibration(qd_oled_panel)

    assert capsys.readouterr().out == ""
