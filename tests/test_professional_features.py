"""Tests for professional calibration features."""

import numpy as np


class TestCalibrationTargets:
    def test_all_targets_exist(self):
        from calibrate_pro.calibration.targets import ALL_TARGETS

        assert len(ALL_TARGETS) >= 13

    def test_rec709_specs(self):
        from calibrate_pro.calibration.targets import REC709_BT1886

        assert REC709_BT1886.eotf == "bt1886"
        assert REC709_BT1886.gamma == 2.4
        assert REC709_BT1886.peak_luminance == 100.0
        assert REC709_BT1886.white_cct == 6504

    def test_hdr10_specs(self):
        from calibrate_pro.calibration.targets import HDR10_1000

        assert HDR10_1000.eotf == "pq"
        assert HDR10_1000.peak_luminance == 1000.0
        assert HDR10_1000.sdr_reference_white == 203.0

    def test_netflix_sdr(self):
        from calibrate_pro.calibration.targets import NETFLIX_SDR

        assert NETFLIX_SDR.delta_e_target == 1.0
        assert NETFLIX_SDR.white_point_tolerance == 0.003

    def test_get_target(self):
        from calibrate_pro.calibration.targets import get_target

        assert get_target("rec709") is not None
        assert get_target("srgb") is not None
        assert get_target("nonexistent") is None

    def test_list_targets(self):
        from calibrate_pro.calibration.targets import list_targets

        targets = list_targets()
        assert len(targets) >= 13
        assert all("name" in t for t in targets)

    def test_category_filter(self):
        from calibrate_pro.calibration.targets import get_targets_by_category

        broadcast = get_targets_by_category("broadcast")
        assert len(broadcast) >= 2
        hdr = get_targets_by_category("hdr")
        assert len(hdr) >= 3


class TestPatchSets:
    def test_all_sets_exist(self):
        from calibrate_pro.verification.patch_sets import list_patch_sets

        sets = list_patch_sets()
        assert len(sets) >= 12

    def test_colorchecker_24(self):
        from calibrate_pro.verification.patch_sets import get_patch_set

        cc = get_patch_set("COLORCHECKER_CLASSIC")
        assert len(cc) == 24

    def test_grayscale_21(self):
        from calibrate_pro.verification.patch_sets import get_patch_set

        gs = get_patch_set("GRAYSCALE_21")
        assert len(gs) == 21
        # First should be black, last should be white
        assert gs[0].r == 0.0
        assert gs[-1].r == 1.0

    def test_comprehensive_100(self):
        from calibrate_pro.verification.patch_sets import get_patch_set

        comp = get_patch_set("COMPREHENSIVE_100")
        assert len(comp) >= 100

    def test_patch_values_in_range(self):
        from calibrate_pro.verification.patch_sets import get_patch_set, list_patch_sets

        for name, _ in list_patch_sets():
            for patch in get_patch_set(name):
                assert 0 <= patch.r <= 1, f"{name}/{patch.name}: r={patch.r}"
                assert 0 <= patch.g <= 1, f"{name}/{patch.name}: g={patch.g}"
                assert 0 <= patch.b <= 1, f"{name}/{patch.name}: b={patch.b}"


class TestCLFFormat:
    def test_clf_export(self):
        import os
        import tempfile

        from calibrate_pro.core.lut_engine import LUT3D

        lut = LUT3D.create_identity(5)
        path = os.path.join(tempfile.gettempdir(), "test_export.clf")
        lut.save_clf(path)
        assert os.path.exists(path)
        with open(path) as f:
            content = f.read()
        assert "ProcessList" in content
        assert "LUT3D" in content
        assert 'compCLFversion="3.0"' in content
        os.unlink(path)


class TestCCSSImport:
    def test_list_builtins(self):
        from calibrate_pro.calibration.ccss_import import list_builtin_corrections

        builtins = list_builtin_corrections()
        assert len(builtins) >= 1
        assert builtins[0]["technology"] == "QD-OLED"

    def test_get_builtin_ccmx(self):
        from calibrate_pro.calibration.ccss_import import get_builtin_ccmx

        ccmx = get_builtin_ccmx("QD-OLED (i1Display3 - PG27UCDM)")
        assert ccmx.shape == (3, 3)
        # Diagonal dominant
        assert abs(ccmx[0, 0]) > 0.9
        assert abs(ccmx[1, 1]) > 0.9
        assert abs(ccmx[2, 2]) > 0.9

    def test_apply_ccmx(self):
        from calibrate_pro.calibration.ccss_import import apply_ccmx

        xyz = np.array([0.95, 1.0, 1.09])
        identity = np.eye(3)
        result = apply_ccmx(xyz, identity)
        np.testing.assert_array_almost_equal(result, xyz)


class TestWarmupMonitor:
    def test_basic_flow(self):
        from calibrate_pro.hardware.warmup_monitor import WarmupMonitor

        readings = [100.0, 102.0, 101.5, 101.2, 101.1, 101.05]
        idx = [0]

        def measure():
            if idx[0] < len(readings):
                val = readings[idx[0]]
                idx[0] += 1
                return val
            return None

        monitor = WarmupMonitor(measure, interval_seconds=1, stability_count=2)
        for _ in range(6):
            monitor.take_reading()
        status = monitor.get_status()
        assert status.readings_count == 6

    def test_recommended_warmup(self):
        from calibrate_pro.hardware.warmup_monitor import get_recommended_warmup

        assert get_recommended_warmup("QD-OLED") == 30
        assert get_recommended_warmup("CCFL") == 90
        assert get_recommended_warmup("IPS") == 30


class TestDriftCompensator:
    def test_no_drift(self):
        from calibrate_pro.hardware.drift_compensation import DriftCompensator

        comp = DriftCompensator()
        ref = np.array([0.95, 1.0, 1.09])
        comp.set_initial_reference(ref)
        # No drift: compensated should equal input
        result = comp.compensate(ref, 0)
        np.testing.assert_array_almost_equal(result, ref)

    def test_drift_correction(self):
        from calibrate_pro.hardware.drift_compensation import DriftCompensator

        comp = DriftCompensator(reference_interval=10)
        initial = np.array([1.0, 1.0, 1.0])
        comp.set_initial_reference(initial)
        # Add a drifted reference
        drifted = np.array([1.1, 1.0, 0.9])
        comp.add_reference(drifted, 10)
        # A measurement at patch 5 should be partially compensated
        measurement = np.array([1.05, 1.0, 0.95])
        compensated = comp.compensate(measurement, 5)
        # Should be closer to initial than measurement
        assert np.sum(np.abs(compensated - initial)) < np.sum(np.abs(measurement - initial))


class TestPanelDatabase:
    def test_58_panels(self):
        from calibrate_pro.panels.database import PanelDatabase

        db = PanelDatabase()
        assert len(db.list_panels()) >= 58

    def test_ddc_recommendations(self):
        from calibrate_pro.panels.database import PanelDatabase

        db = PanelDatabase()
        # At least 40 panels should have DDC recommendations
        ddc_count = sum(1 for key in db.list_panels() if (p := db.get_panel(key)) and hasattr(p, "ddc") and p.ddc)
        assert ddc_count >= 40

    def test_panel_types(self):
        from calibrate_pro.panels.database import PanelDatabase

        db = PanelDatabase()
        types = set()
        for key in db.list_panels():
            p = db.get_panel(key)
            if p:
                types.add(p.panel_type)
        assert "QD-OLED" in types
        assert "WOLED" in types
        assert "IPS" in types
        assert "VA" in types
