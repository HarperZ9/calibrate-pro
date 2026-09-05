"""A modelled number must not reach a caller wearing the word measured.

Three paths produced values a model invented and handed them on with nothing
attached: the measurement coordinator's simulated mode, the hybrid engine that
consumes it, and the uniformity command's synthetic report. The engine's own
fields are named final_measured_delta_e and measured_patches, so a value
arriving in them is claimed as an instrument reading by the name alone.

These tests hold the marker in place. None of them opens a patch window, talks
to a colorimeter, or touches a display, because the simulated path is
arithmetic and the coordinator only reaches tkinter inside measure().
"""

import argparse

import numpy as np
import pytest

from calibrate_pro.calibration.hybrid import HybridCalibrationEngine, HybridCalibrationResult
from calibrate_pro.display.uniformity import cmd_uniformity
from calibrate_pro.hardware.measurement import MeasurementConfig, MeasurementCoordinator, create_measure_fn


class TestSimulatedMeasurementIsStamped:
    """create_measure_fn hands out a function that says where it gets values."""

    def test_simulated_function_carries_its_source(self):
        measure = create_measure_fn(MeasurementConfig(mode="simulated"))
        assert measure is not None
        assert measure.measurement_source == "simulated"

    def test_manual_function_carries_its_source(self):
        measure = create_measure_fn(MeasurementConfig(mode="manual"))
        assert measure is not None
        assert measure.measurement_source == "manual"

    def test_simulated_reading_is_the_ideal_answer_for_the_patch(self):
        """The docstring claims the simulated display is already correct.

        If that were false the mode would be a plausible stand-in for a panel
        and the marker would matter less. It is true, so a calibration run fed
        by this mode converges on an identity correction, and the test pins the
        claim rather than trusting the comment.
        """
        from calibrate_pro.core.color_math import SRGB_TO_XYZ, srgb_gamma_expand

        coordinator = MeasurementCoordinator(MeasurementConfig(mode="simulated"))
        r, g, b = 0.5, 0.25, 0.75
        ideal = SRGB_TO_XYZ @ srgb_gamma_expand(np.array([r, g, b]))

        got = np.array(coordinator._measure_simulated(r, g, b))

        # The only difference from the ideal is the noise the method adds,
        # which is drawn at sigma 0.002 on values around 0.2.
        assert np.allclose(got, ideal, atol=0.02)


class TestEngineNamesItsSource:
    """The engine records what fed it, and refuses to guess an instrument."""

    def test_no_measure_fn_is_none(self):
        assert HybridCalibrationEngine().measurement_source == "none"

    def test_a_stamped_function_keeps_its_name(self):
        measure = create_measure_fn(MeasurementConfig(mode="simulated"))
        assert HybridCalibrationEngine(measure_fn=measure).measurement_source == "simulated"

    def test_an_unstamped_callable_is_unknown_not_an_instrument(self):
        """A caller's own colorimeter method carries no stamp.

        Recording it as an instrument would make the missing stamp the same as
        a present one, which is the failure this field exists to prevent.
        """

        def somebody_elses_measure(r, g, b):
            return (0.2, 0.2, 0.2)

        engine = HybridCalibrationEngine(measure_fn=somebody_elses_measure)
        assert engine.measurement_source == "unknown"
        assert engine.measurement_source not in ("argyll", "manual")


class TestUnmeasuredAccuracyStaysEmpty:
    """A Delta E field holds a reading or nothing, never a prediction."""

    def test_result_starts_with_no_measured_accuracy(self):
        result = HybridCalibrationResult()
        assert result.final_measured_delta_e is None
        assert result.final_measured_delta_e_max is None
        assert result.measurement_source == "none"

    def test_sensorless_only_run_leaves_the_measured_field_empty(self, tmp_path, monkeypatch):
        """The run used to copy the sensorless prediction into it.

        A caller reading final_measured_delta_e then got a modelled number from
        a run with no instrument in it at all.
        """
        import calibrate_pro.sensorless.neuralux as neuralux

        class _Lut:
            def save(self, path):
                path.write_text("stub", encoding="utf-8")

        class _Engine:
            current_panel = None

            def create_3d_lut(self, panel, size, target, hdr_mode):
                return _Lut()

            def verify_calibration(self, panel):
                return {"delta_e_avg": 1.75}

        monkeypatch.setattr(neuralux, "SensorlessEngine", _Engine)
        panel = argparse.Namespace(name="Test Panel")

        result = HybridCalibrationEngine().calibrate(panel, tmp_path)

        assert result.success is True
        assert result.sensorless_delta_e == pytest.approx(1.75)
        assert result.final_measured_delta_e is None
        assert result.measurement_source == "none"


class TestSyntheticUniformityReportSaysSo:
    """Every block of the synthetic report carries the marker, not just one."""

    @staticmethod
    def _run(capsys, **kwargs):
        args = argparse.Namespace(rows=3, cols=3, width=3840, height=2160, **kwargs)
        assert cmd_uniformity(args) == 0
        return capsys.readouterr().out

    def test_each_reported_block_is_marked(self, capsys):
        out = self._run(capsys, simulated=True)

        # Each of these prints numbers shaped like a colorimeter report.
        for heading in ("Uniformity Statistics", "Luminance Map (cd/m2)", "Correction Factors"):
            line = next(ln for ln in out.splitlines() if heading in ln)
            assert "[synthetic]" in line, line

    def test_the_grade_is_marked(self, capsys):
        out = self._run(capsys, simulated=True)

        grade = next(ln for ln in out.splitlines() if ln.startswith("Uniformity Grade:"))
        assert "[synthetic]" in grade, grade
        assert "No colorimeter read this display." in out

    def test_the_marker_is_not_printed_unconditionally(self, capsys):
        """A hardcoded marker would pass every test above and mean nothing.

        Without --simulated the command has no data to report and says so, and
        the word synthetic must not appear in that run.
        """
        out = self._run(capsys, simulated=False)

        assert "[synthetic]" not in out
        assert "Connect a colorimeter" in out
