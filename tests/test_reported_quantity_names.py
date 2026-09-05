"""A reported number carries the name of the quantity it actually is.

Two values were filed under the wrong name. The DDC/CI white point loop
computed a CIE 1976 u'v' chromaticity distance, scaled it by 100, and stored it
as ``delta_e``, where it would be read against Delta E tolerances that do not
share its scale. The uniformity simulation built ``xyz=(0, luminance, 0)``
beside a chromaticity pair that describes a different color, so a consumer
converting the tristimulus values got an answer the chromaticity contradicts.

Neither is a fabricated measurement, so neither reaches PRODUCT.md the way the
refusals do. Both still put a number in front of a reader under a label that
misstates what it is.
"""

from __future__ import annotations

import pytest

from calibrate_pro.advanced.uniformity import UniformityGrid, create_test_measurements

#: Chromaticity agreement tolerance. The simulation adds 1% luminance noise, so
#: this covers float round-trip only, not the noise.
CHROMATICITY_TOLERANCE = 1e-9


@pytest.mark.windows
def test_white_point_loop_reports_a_chromaticity_distance_by_that_name():
    """The white point result carries ``delta_uv``, and no ``delta_e`` at all.

    The loop never measures the target luminance, so no CIE Delta E is
    available from it. A u'v' distance published as Delta E reads as roughly
    fifty times worse than it is against a Delta E 2000 tolerance.
    """
    from calibrate_pro.hardware.ddc_ci import HardwareCalibrationResult

    result = HardwareCalibrationResult()

    assert hasattr(result, "delta_uv")
    assert not hasattr(result, "delta_e")


@pytest.mark.windows
def test_chromaticity_distance_is_not_scaled_into_delta_e_range():
    """The stored distance is raw u'v', where a just-noticeable shift is ~0.002."""
    from calibrate_pro.hardware.ddc_ci import HardwareCalibrationResult

    assert HardwareCalibrationResult().delta_uv == 0.0


@pytest.mark.parametrize(
    "grid",
    [UniformityGrid.GRID_3X3, UniformityGrid.GRID_5X5, UniformityGrid.GRID_9X9],
)
def test_simulated_tristimulus_matches_the_chromaticity_beside_it(grid):
    """X, Y, Z convert back to the chromaticity the same record reports."""
    for measurement in create_test_measurements(grid_size=grid):
        big_x, big_y, big_z = measurement.xyz
        total = big_x + big_y + big_z

        assert total > 0
        assert abs(big_x / total - measurement.chromaticity_x) < CHROMATICITY_TOLERANCE
        assert abs(big_y / total - measurement.chromaticity_y) < CHROMATICITY_TOLERANCE


def test_simulated_luminance_matches_its_own_y():
    """The Y a record reports is the luminance it reports, after the clamp."""
    for measurement in create_test_measurements():
        assert measurement.xyz[1] == measurement.luminance
        assert measurement.luminance >= 0.0


@pytest.mark.windows
def test_the_two_calibration_result_classes_have_separate_export_names():
    """The package hands out the DDC/CI result and the engine result apart.

    Both modules name their result class ``HardwareCalibrationResult`` and the
    two hold different fields. The lazy exporter had a branch for each under
    that one name, so the second branch never ran and a caller reaching for the
    DDC/CI white point result got the engine's class instead.
    """
    import calibrate_pro.hardware as hardware
    from calibrate_pro.hardware.ddc_ci import HardwareCalibrationResult as DDCResult
    from calibrate_pro.hardware.hardware_calibration import (
        HardwareCalibrationResult as EngineResult,
    )

    assert hardware.DDCCalibrationResult is DDCResult
    assert hardware.HardwareCalibrationResult is EngineResult
    assert DDCResult is not EngineResult


@pytest.mark.windows
def test_every_declared_hardware_export_resolves():
    """No name in ``__all__`` is shadowed by an earlier branch of the same name."""
    import calibrate_pro.hardware as hardware

    unresolved = [name for name in hardware.__all__ if not hasattr(hardware, name)]

    assert unresolved == []
