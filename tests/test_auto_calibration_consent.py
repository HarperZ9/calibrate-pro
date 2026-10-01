"""The library calibration path must not grant itself hardware consent.

`one_click_calibrate` used to build a HIGH-risk `UserConsent` itself, with
`backup_created=True` asserted rather than checked, and `run_calibration` ran a
DDC/CI auto-setup on every call whatever the consent said. `auto_calibrate_all`
then wrote an HKCU Run key without asking. These tests replace every hardware
step with a recorder, so nothing here touches a monitor or the registry.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from calibrate_pro.sensorless import auto_calibration as ac
from calibrate_pro.sensorless.auto_calibration import (
    AutoCalibrationEngine,
    AutoCalibrationResult,
    CalibrationRisk,
    UserConsent,
)

FULL_BACKUP = {
    name: {"current": 50, "max": 100}
    for name in (
        "brightness",
        "contrast",
        "red_gain",
        "green_gain",
        "blue_gain",
        "color_preset",
        "red_black_level",
        "green_black_level",
        "blue_black_level",
        "image_mode",
        "gamma",
    )
}


def _approved(**overrides) -> UserConsent:
    fields = dict(
        timestamp=1.0,
        risk_level=CalibrationRisk.HIGH,
        display_name="Test",
        operation="test",
        user_acknowledged_risks=True,
        hardware_modification_approved=True,
    )
    fields.update(overrides)
    return UserConsent(**fields)


@pytest.fixture
def calls(monkeypatch):
    """Replace every hardware-touching engine step with a recorder."""
    log: list[str] = []
    state = {"backup": dict(FULL_BACKUP), "rec": None}
    panel = SimpleNamespace(name="Fake Panel", panel_type="IPS", manufacturer="Fake")

    def rec(name, value=None):
        def _step(self, *a, **k):
            log.append(name)
            return value

        return _step

    def read_backup(self, display_index):
        log.append("read_ddc_settings")
        return dict(state["backup"])

    def write_file(name):
        def _step(self, panel, target, path, **k):
            log.append(name)
            Path(path).write_text("x")

        return _step

    monkeypatch.setattr(AutoCalibrationEngine, "_detect_display", rec("detect", {"name": "Test"}))
    monkeypatch.setattr(AutoCalibrationEngine, "_match_panel", rec("match", panel))
    monkeypatch.setattr(AutoCalibrationEngine, "_read_ddc_settings", read_backup)
    monkeypatch.setattr(AutoCalibrationEngine, "_calculate_corrections", rec("corrections", {}))
    monkeypatch.setattr(AutoCalibrationEngine, "_apply_ddc_corrections", rec("WRITE_ddc_corrections", {"ok": 1}))
    monkeypatch.setattr(AutoCalibrationEngine, "_ddc_recommendations", rec("recommendations", None), raising=False)
    monkeypatch.setattr(AutoCalibrationEngine, "_run_ddc_auto_setup", rec("WRITE_ddc_auto_setup", []), raising=False)
    monkeypatch.setattr(AutoCalibrationEngine, "_generate_icc_profile", write_file("icc"))
    monkeypatch.setattr(AutoCalibrationEngine, "_generate_3d_lut", write_file("lut"))
    monkeypatch.setattr(AutoCalibrationEngine, "_install_profile", rec("install_profile"))
    monkeypatch.setattr(AutoCalibrationEngine, "_apply_lut", rec("apply_lut", ""))
    monkeypatch.setattr(AutoCalibrationEngine, "_verify_calibration", rec("verify", {}))
    # The pre-fix auto-setup lived in _auto_ddc_setup and wrote straight through
    # DDCCIController; stub its controller so a regression is recorded, not executed.
    import calibrate_pro.hardware.ddc_ci as ddc_ci

    class _NoController:
        def __init__(self, *a, **k):
            log.append("WRITE_ddc_auto_setup")
            raise RuntimeError("hardware is stubbed in this test")

    monkeypatch.setattr(ddc_ci, "DDCCIController", _NoController)
    monkeypatch.setattr(ac, "_persist_calibration", lambda *a, **k: log.append("persist"))
    return SimpleNamespace(log=log, state=state)


def _writes(log):
    return [c for c in log if c.startswith("WRITE_")]


def _run(tmp_path, **kw):
    return AutoCalibrationEngine().run_calibration(output_dir=tmp_path, apply_lut=False, install_profile=False, **kw)


# --- one_click_calibrate: no self-minted consent ------------------------------


def test_one_click_without_consent_makes_no_ddc_write(calls, tmp_path):
    result = ac.one_click_calibrate(output_dir=tmp_path, use_ddc=True, persist=False)
    assert _writes(calls.log) == []
    assert any("consent" in w.lower() for w in result.warnings)


def test_one_click_source_never_constructs_user_consent():
    """A structural guard: the function body builds no UserConsent of its own."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(ac.one_click_calibrate)))
    built = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) == "UserConsent"
    ]
    assert built == []


def test_one_click_passes_a_caller_consent_through(calls, tmp_path):
    ac.one_click_calibrate(output_dir=tmp_path, use_ddc=True, persist=False, consent=_approved())
    assert "WRITE_ddc_corrections" in calls.log


# --- run_calibration: consent and a verified backup before any DDC write ------


def test_no_ddc_requested_means_no_ddc_write_at_all(calls, tmp_path):
    _run(tmp_path, apply_ddc=False)
    assert _writes(calls.log) == []


def test_hardware_flag_without_acknowledged_risks_is_not_consent(calls, tmp_path):
    _run(tmp_path, apply_ddc=True, consent=_approved(user_acknowledged_risks=False))
    assert _writes(calls.log) == []


def test_empty_backup_blocks_every_ddc_write(calls, tmp_path):
    calls.state["backup"] = {}
    result = _run(tmp_path, apply_ddc=True, consent=_approved())
    assert _writes(calls.log) == []
    assert any("backup" in w.lower() for w in result.warnings)


def test_partial_backup_blocks_the_correction_write(calls, tmp_path):
    calls.state["backup"] = {k: v for k, v in FULL_BACKUP.items() if k != "red_gain"}
    result = _run(tmp_path, apply_ddc=True, consent=_approved())
    assert "WRITE_ddc_corrections" not in calls.log
    assert any("red_gain" in w for w in result.warnings)


def test_caller_asserted_backup_is_not_trusted(calls, tmp_path):
    calls.state["backup"] = {}
    _run(tmp_path, apply_ddc=True, consent=_approved(backup_created=True))
    assert _writes(calls.log) == []


def test_full_backup_is_read_before_the_first_write(calls, tmp_path):
    result = _run(tmp_path, apply_ddc=True, consent=_approved())
    writes = [i for i, c in enumerate(calls.log) if c.startswith("WRITE_")]
    assert writes, calls.log
    assert calls.log.index("read_ddc_settings") < writes[0]
    assert result.ddc_backup_verified is True
    assert result.ddc_backup_display_index == 0


# --- auto_calibrate_all: ask before the HKCU Run key --------------------------


class _Startup:
    enabled: list[bool] = []

    def is_startup_enabled(self):
        return False

    def enable_startup(self, silent=True):
        _Startup.enabled.append(silent)
        return True


@pytest.fixture
def all_displays(monkeypatch):
    import calibrate_pro.panels.detection as detection
    import calibrate_pro.utils.startup_manager as startup_manager

    _Startup.enabled = []
    seen: list[tuple[int, object]] = []
    displays = [SimpleNamespace(monitor_name="A"), SimpleNamespace(monitor_name="B")]
    monkeypatch.setattr(detection, "enumerate_displays", lambda: displays)
    monkeypatch.setattr(detection, "get_display_name", lambda d: d.monitor_name, raising=False)
    monkeypatch.setattr(startup_manager, "StartupManager", _Startup)

    def fake_one_click(**kw):
        seen.append((kw["display_index"], kw.get("consent")))
        return AutoCalibrationResult(success=True, display_name=str(kw["display_index"]))

    monkeypatch.setattr(ac, "one_click_calibrate", fake_one_click)
    return seen


def test_auto_calibrate_all_never_writes_the_run_key_unasked(all_displays):
    results = ac.auto_calibrate_all(persist=True)
    assert _Startup.enabled == []
    assert any("startup" in w.lower() for w in results[0].warnings)


def test_auto_calibrate_all_respects_a_no(all_displays):
    prompts: list[str] = []
    ac.auto_calibrate_all(persist=True, confirm_startup=lambda msg: prompts.append(msg) or False)
    assert _Startup.enabled == []
    assert prompts and "Run" in prompts[0]


def test_auto_calibrate_all_writes_the_run_key_on_a_yes(all_displays):
    ac.auto_calibrate_all(persist=True, confirm_startup=lambda msg: True)
    assert _Startup.enabled == [True]


def test_auto_calibrate_all_asks_consent_per_display(all_displays):
    asked: list[tuple[int, str]] = []
    marker = _approved()

    def provider(index, name):
        asked.append((index, name))
        return marker if index == 1 else None

    ac.auto_calibrate_all(persist=False, consent=provider)
    assert asked == [(0, "A"), (1, "B")]
    assert all_displays == [(0, None), (1, marker)]


# --- restore uses the display the backup came from ---------------------------


def test_restore_writes_back_to_the_backed_up_display(monkeypatch):
    import calibrate_pro.hardware.ddc_ci as ddc_ci

    written: list[tuple[object, int, int]] = []

    class _Controller:
        available = True

        def enumerate_monitors(self):
            return [{"handle": "first"}, {"handle": "second"}]

        def set_vcp(self, monitor, code, value):
            written.append((monitor["handle"], code, value))
            return True

        def close(self):
            pass

    monkeypatch.setattr(ddc_ci, "DDCCIController", _Controller)
    result = AutoCalibrationResult(
        original_ddc_settings={"brightness": {"current": 33, "max": 100}},
        ddc_backup_display_index=1,
    )
    assert AutoCalibrationEngine().restore_original_settings(result) is True
    assert written and {h for h, _, _ in written} == {"second"}


def test_backup_read_covers_every_writable_control_and_passes_the_monitor_dict(monkeypatch):
    """get_vcp indexes monitor["handle"]; passing the bare handle raised TypeError."""
    import calibrate_pro.hardware.ddc_ci as ddc_ci
    from calibrate_pro.sensorless.ddc_backup import BACKUP_CODES

    class _Controller:
        available = True

        def enumerate_monitors(self):
            return [{"handle": "first"}, {"handle": "second"}]

        def get_vcp(self, monitor, code):
            assert monitor == {"handle": "second"}
            return (40, 100)

        def close(self):
            pass

    monkeypatch.setattr(ddc_ci, "DDCCIController", _Controller)
    backup = AutoCalibrationEngine()._read_ddc_settings(1)
    assert set(backup) == set(BACKUP_CODES)
    assert all(v == {"current": 40, "max": 100} for v in backup.values())
