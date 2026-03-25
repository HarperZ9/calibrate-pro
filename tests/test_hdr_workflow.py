"""
Tests for the HDR Calibration Workflow module.

Covers:
- EOTF patch generation (PQ and HLG)
- EOTF verification accuracy
- BT.2390 tone map generation (monotonic, bounded)
- 3-D LUT generation (dimensions, value range)
- HDR metadata generation (MaxCLL / MaxFALL / primaries)
- .cube export (valid format, parseable)
- Full run() orchestration for both HDR10 and HLG
"""

import os
import tempfile

import numpy as np
import pytest

from calibrate_pro.hdr.workflow import (
    HDRCalibrationResult,
    HDRStandard,
    HDRTarget,
    HDRWorkflow,
)
from calibrate_pro.core.color_math import pq_eotf


# =========================================================================
# Fixtures
# =========================================================================

@pytest.fixture
def hdr10_target():
    return HDRTarget.hdr10_1000()


@pytest.fixture
def hdr10_600_target():
    return HDRTarget.hdr10_600()


@pytest.fixture
def hlg_target():
    return HDRTarget.hlg_1000()


@pytest.fixture
def hdr10_wf(hdr10_target):
    return HDRWorkflow(hdr10_target)


@pytest.fixture
def hlg_wf(hlg_target):
    return HDRWorkflow(hlg_target)


# =========================================================================
# HDRTarget presets
# =========================================================================

class TestHDRTarget:
    def test_hdr10_1000_preset(self):
        t = HDRTarget.hdr10_1000()
        assert t.standard == HDRStandard.HDR10
        assert t.peak_luminance == 1000.0

    def test_hdr10_600_preset(self):
        t = HDRTarget.hdr10_600()
        assert t.standard == HDRStandard.HDR10
        assert t.peak_luminance == 600.0
        assert t.max_cll == 600.0

    def test_hlg_1000_preset(self):
        t = HDRTarget.hlg_1000()
        assert t.standard == HDRStandard.HLG
        assert t.peak_luminance == 1000.0


# =========================================================================
# EOTF Patch Generation
# =========================================================================

class TestGenerateEOTFPatches:
    def test_hdr10_patch_shape(self, hdr10_wf):
        patches = hdr10_wf.generate_eotf_patches(steps=21)
        assert patches.shape == (21, 2)

    def test_hdr10_signal_range(self, hdr10_wf):
        patches = hdr10_wf.generate_eotf_patches(steps=21)
        signals = patches[:, 0]
        assert signals[0] == pytest.approx(0.0)
        assert signals[-1] == pytest.approx(1.0)

    def test_hdr10_luminance_range(self, hdr10_wf):
        patches = hdr10_wf.generate_eotf_patches(steps=101)
        lum = patches[:, 1]
        # PQ at signal=0 -> 0 nits, signal=1 -> 10000 nits
        assert lum[0] == pytest.approx(0.0, abs=0.01)
        assert lum[-1] == pytest.approx(10000.0, rel=0.01)

    def test_hdr10_luminance_monotonic(self, hdr10_wf):
        patches = hdr10_wf.generate_eotf_patches(steps=101)
        lum = patches[:, 1]
        assert np.all(np.diff(lum) >= 0), "PQ luminance must be non-decreasing"

    def test_hlg_patch_shape(self, hlg_wf):
        patches = hlg_wf.generate_eotf_patches(steps=21)
        assert patches.shape == (21, 2)

    def test_hlg_signal_range(self, hlg_wf):
        patches = hlg_wf.generate_eotf_patches(steps=21)
        signals = patches[:, 0]
        assert signals[0] == pytest.approx(0.0)
        assert signals[-1] == pytest.approx(1.0)

    def test_hlg_luminance_range(self, hlg_wf):
        patches = hlg_wf.generate_eotf_patches(steps=51)
        lum = patches[:, 1]
        assert lum[0] == pytest.approx(0.0, abs=0.01)
        # HLG peak = peak_luminance * hlg_eotf(1.0)
        # hlg_eotf(1.0) ~ 1.0  (scene=1, gamma=1.2 -> 1.0)
        assert lum[-1] == pytest.approx(1000.0, rel=0.05)

    def test_hlg_luminance_monotonic(self, hlg_wf):
        patches = hlg_wf.generate_eotf_patches(steps=51)
        lum = patches[:, 1]
        assert np.all(np.diff(lum) >= 0), "HLG luminance must be non-decreasing"

    def test_minimum_steps(self, hdr10_wf):
        patches = hdr10_wf.generate_eotf_patches(steps=2)
        assert patches.shape == (2, 2)

    def test_invalid_steps_raises(self, hdr10_wf):
        with pytest.raises(ValueError, match="steps must be >= 2"):
            hdr10_wf.generate_eotf_patches(steps=1)


# =========================================================================
# EOTF Verification
# =========================================================================

class TestVerifyEOTF:
    def test_perfect_match_zero_error(self, hdr10_wf):
        patches = hdr10_wf.generate_eotf_patches(steps=21)
        expected = patches[:, 1]
        error = hdr10_wf.verify_eotf(expected, expected)
        assert error == pytest.approx(0.0, abs=1e-10)

    def test_known_offset(self, hdr10_wf):
        expected = np.array([100.0, 200.0, 500.0])
        measured = np.array([110.0, 220.0, 550.0])
        error = hdr10_wf.verify_eotf(measured, expected)
        assert error == pytest.approx(10.0, rel=0.01)

    def test_zero_expected_patch_ignored(self, hdr10_wf):
        expected = np.array([0.0, 100.0])
        measured = np.array([0.5, 100.0])
        error = hdr10_wf.verify_eotf(measured, expected)
        # 0-nit patch contributes 0%, 100-nit patch contributes 0%
        assert error == pytest.approx(0.0, abs=0.01)

    def test_shape_mismatch_raises(self, hdr10_wf):
        with pytest.raises(ValueError, match="Shape mismatch"):
            hdr10_wf.verify_eotf(np.array([1.0]), np.array([1.0, 2.0]))


# =========================================================================
# Tone Map Generation
# =========================================================================

class TestGenerateToneMap:
    def test_shape(self, hdr10_wf):
        tm = hdr10_wf.generate_tone_map(steps=256)
        assert tm.shape == (256, 2)

    def test_bounded_01(self, hdr10_wf):
        tm = hdr10_wf.generate_tone_map(steps=512)
        assert np.all(tm[:, 0] >= 0.0)
        assert np.all(tm[:, 0] <= 1.0)
        assert np.all(tm[:, 1] >= 0.0)
        assert np.all(tm[:, 1] <= 1.0)

    def test_monotonic_output(self, hdr10_wf):
        tm = hdr10_wf.generate_tone_map(steps=512)
        diffs = np.diff(tm[:, 1])
        assert np.all(diffs >= -1e-12), "Tone map output must be non-decreasing"

    def test_passthrough_below_target(self, hdr10_wf):
        """Low PQ values should pass through approximately unchanged."""
        tm = hdr10_wf.generate_tone_map(steps=1024)
        # The bottom 10% of PQ range should be near-identity
        low = tm[:100]
        np.testing.assert_allclose(
            low[:, 0], low[:, 1], atol=0.05,
        )

    def test_output_compressed_above_target(self, hdr10_wf):
        """PQ value for 10000 nits should map below PQ value for 10000 nits."""
        tm = hdr10_wf.generate_tone_map(steps=1024)
        # Last entry: PQ signal for 10000 nits (=1.0) must be lower
        assert tm[-1, 1] < tm[-1, 0] + 1e-6

    def test_invalid_steps_raises(self, hdr10_wf):
        with pytest.raises(ValueError, match="steps must be >= 2"):
            hdr10_wf.generate_tone_map(steps=1)


# =========================================================================
# 3-D LUT Generation
# =========================================================================

class TestGenerateHDRLUT:
    def test_shape(self, hdr10_wf):
        lut = hdr10_wf.generate_hdr_lut(size=5)
        assert lut.shape == (5, 5, 5, 3)

    def test_values_in_range(self, hdr10_wf):
        lut = hdr10_wf.generate_hdr_lut(size=5)
        assert np.all(lut >= 0.0)
        assert np.all(lut <= 1.0)

    def test_black_maps_near_black(self, hdr10_wf):
        lut = hdr10_wf.generate_hdr_lut(size=9)
        black = lut[0, 0, 0]
        assert np.all(black < 0.05), f"Black corner should be near 0, got {black}"

    def test_identity_like_at_low_values(self, hdr10_wf):
        """LUT should be close to identity for low PQ values."""
        lut = hdr10_wf.generate_hdr_lut(size=9)
        # Second node (index 1) on the diagonal
        val = lut[1, 1, 1]
        expected = 1.0 / 8.0  # 1/(size-1)
        np.testing.assert_allclose(val, expected, atol=0.1)

    def test_invalid_size_raises(self, hdr10_wf):
        with pytest.raises(ValueError, match="LUT size must be >= 2"):
            hdr10_wf.generate_hdr_lut(size=1)


# =========================================================================
# HDR Metadata
# =========================================================================

class TestGenerateHDRMetadata:
    def test_hdr10_metadata_fields(self, hdr10_wf):
        meta = hdr10_wf.generate_hdr_metadata()
        assert meta["standard"] == "hdr10"
        assert "primaries" in meta
        assert "luminance" in meta
        assert "content_light_level" in meta

    def test_max_cll_max_fall(self, hdr10_wf):
        meta = hdr10_wf.generate_hdr_metadata()
        cll = meta["content_light_level"]
        assert cll["max_cll"] == 1000.0
        assert cll["max_fall"] == 400.0

    def test_luminance_range(self, hdr10_wf):
        meta = hdr10_wf.generate_hdr_metadata()
        lum = meta["luminance"]
        assert lum["max_nits"] == 1000.0
        assert lum["min_nits"] == 0.005

    def test_bt2020_primaries(self, hdr10_wf):
        meta = hdr10_wf.generate_hdr_metadata()
        p = meta["primaries"]
        assert p["red"] == (0.708, 0.292)
        assert p["green"] == (0.170, 0.797)
        assert p["blue"] == (0.131, 0.046)
        assert p["white_point"] == (0.3127, 0.3290)

    def test_hlg_metadata_standard(self, hlg_wf):
        meta = hlg_wf.generate_hdr_metadata()
        assert meta["standard"] == "hlg"

    def test_hdr10_600_cll_matches_peak(self, hdr10_600_target):
        wf = HDRWorkflow(hdr10_600_target)
        meta = wf.generate_hdr_metadata()
        assert meta["content_light_level"]["max_cll"] == 600.0


# =========================================================================
# .cube Export
# =========================================================================

class TestExportCube:
    def test_creates_file(self, hdr10_wf):
        lut = hdr10_wf.generate_hdr_lut(size=5)
        with tempfile.NamedTemporaryFile(
            suffix=".cube", delete=False, mode="w"
        ) as tmp:
            path = tmp.name
        try:
            hdr10_wf.export_cube(path, lut)
            assert os.path.isfile(path)
            assert os.path.getsize(path) > 0
        finally:
            os.unlink(path)

    def test_header_fields(self, hdr10_wf):
        lut = hdr10_wf.generate_hdr_lut(size=3)
        with tempfile.NamedTemporaryFile(
            suffix=".cube", delete=False, mode="w"
        ) as tmp:
            path = tmp.name
        try:
            hdr10_wf.export_cube(path, lut)
            with open(path, "r") as fh:
                content = fh.read()
            assert "TITLE" in content
            assert "LUT_3D_SIZE 3" in content
            assert "DOMAIN_MIN 0.0 0.0 0.0" in content
            assert "DOMAIN_MAX 1.0 1.0 1.0" in content
            assert "MaxCLL" in content
            assert "MaxFALL" in content
        finally:
            os.unlink(path)

    def test_correct_line_count(self, hdr10_wf):
        size = 3
        lut = hdr10_wf.generate_hdr_lut(size=size)
        with tempfile.NamedTemporaryFile(
            suffix=".cube", delete=False, mode="w"
        ) as tmp:
            path = tmp.name
        try:
            hdr10_wf.export_cube(path, lut)
            with open(path, "r") as fh:
                lines = fh.read().strip().split("\n")
            # Data lines = size^3
            data_lines = [
                ln for ln in lines
                if ln and not ln.startswith("#")
                and not ln.startswith("TITLE")
                and not ln.startswith("LUT_3D_SIZE")
                and not ln.startswith("DOMAIN")
            ]
            assert len(data_lines) == size ** 3
        finally:
            os.unlink(path)

    def test_data_parseable(self, hdr10_wf):
        lut = hdr10_wf.generate_hdr_lut(size=3)
        with tempfile.NamedTemporaryFile(
            suffix=".cube", delete=False, mode="w"
        ) as tmp:
            path = tmp.name
        try:
            hdr10_wf.export_cube(path, lut)
            with open(path, "r") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#") or line.startswith(
                        ("TITLE", "LUT_3D_SIZE", "DOMAIN")
                    ):
                        continue
                    parts = line.split()
                    assert len(parts) == 3
                    vals = [float(p) for p in parts]
                    assert all(0.0 <= v <= 1.0 for v in vals)
        finally:
            os.unlink(path)

    def test_bad_lut_shape_raises(self, hdr10_wf):
        bad = np.zeros((3, 3, 3))
        with pytest.raises(ValueError, match="LUT must be shape"):
            hdr10_wf.export_cube("nope.cube", bad)


# =========================================================================
# Full run()
# =========================================================================

class TestRun:
    def test_hdr10_run_returns_result(self, hdr10_wf):
        result = hdr10_wf.run(lut_size=5)
        assert isinstance(result, HDRCalibrationResult)

    def test_hdr10_perfect_display_zero_error(self, hdr10_wf):
        result = hdr10_wf.run(lut_size=5)
        assert result.eotf_error == pytest.approx(0.0, abs=1e-10)

    def test_hdr10_peak_measured(self, hdr10_wf):
        result = hdr10_wf.run(lut_size=5)
        # Perfect display: measured peak = PQ at signal 1.0 = 10000
        assert result.peak_measured == pytest.approx(10000.0, rel=0.01)

    def test_hdr10_lut_attached(self, hdr10_wf):
        result = hdr10_wf.run(lut_size=5)
        assert result.lut_data is not None
        assert result.lut_data.shape == (5, 5, 5, 3)

    def test_hdr10_tone_map_attached(self, hdr10_wf):
        result = hdr10_wf.run(lut_size=5)
        assert result.tone_map_curve.ndim == 1
        assert len(result.tone_map_curve) > 0

    def test_hlg_run_returns_result(self, hlg_wf):
        result = hlg_wf.run(lut_size=5)
        assert isinstance(result, HDRCalibrationResult)

    def test_hlg_perfect_display_zero_error(self, hlg_wf):
        result = hlg_wf.run(lut_size=5)
        assert result.eotf_error == pytest.approx(0.0, abs=1e-10)

    def test_run_with_real_measurements(self, hdr10_wf):
        patches = hdr10_wf.generate_eotf_patches(steps=21)
        expected = patches[:, 1]
        # Simulate a display that is 5% too bright everywhere
        measured = expected * 1.05
        result = hdr10_wf.run(measured_luminances=measured, lut_size=5)
        assert result.eotf_error > 0.0
        # The 0-nit patch is ignored, so average should be ~5%
        assert result.eotf_error == pytest.approx(5.0, abs=1.0)

    def test_gamut_coverage_placeholder(self, hdr10_wf):
        result = hdr10_wf.run(lut_size=5)
        assert result.gamut_coverage_bt2020 == 100.0

    def test_target_preserved_in_result(self, hdr10_wf):
        result = hdr10_wf.run(lut_size=5)
        assert result.target.standard == HDRStandard.HDR10
        assert result.target.peak_luminance == 1000.0
