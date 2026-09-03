"""Safety and evidence tests for exact-display measured calibration."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from calibrate_pro.calibration.measured_runner import (
    DisplayTarget,
    MeasuredCalibrationRun,
    PatchResult,
    VerificationSummary,
    apply_and_verify,
    require_device_id_token,
    select_exact_display,
    target_hdr_enabled,
    validate_run_evidence,
)

SAMSUNG = DisplayTarget(
    device_name=r"\\.\DISPLAY1",
    device_id=r"DISPLAY\SAM72F2",
    geometry=(3840, 1235, 3440, 1440),
    name="Odyssey G85SB",
)
ASUS = DisplayTarget(
    device_name=r"\\.\DISPLAY2",
    device_id=r"DISPLAY\AUS",
    geometry=(0, 0, 3840, 2160),
    name="ASUS PG27UCDM",
)


def _summary(average: float, count: int = 24) -> VerificationSummary:
    patches = tuple(
        PatchResult(
            name=f"Patch {index + 1}",
            requested_rgb=(0.5, 0.5, 0.5),
            displayed_rgb=(0.5, 0.5, 0.5),
            xyz=(0.2, 0.2, 0.2),
            delta_e=average,
        )
        for index in range(count)
    )
    return VerificationSummary(
        valid_patches=count,
        delta_e_average=average,
        delta_e_maximum=average,
        patch_results=patches,
    )


def _run(tmp_path: Path, direct_average: float = 3.0) -> MeasuredCalibrationRun:
    lut_path = tmp_path / "samsung.cube"
    lut_path.write_text("LUT_3D_SIZE 2\n", encoding="utf-8")
    digest = hashlib.sha256(lut_path.read_bytes()).hexdigest()
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps({"lut_sha256": digest}), encoding="utf-8")
    return MeasuredCalibrationRun(
        target=SAMSUNG,
        baseline=_summary(6.0),
        direct_correction=_summary(direct_average),
        lut_path=str(lut_path),
        lut_sha256=digest,
        receipt_path=str(receipt_path),
        evidence_grade="research_fallback_oled_matrix",
    )


def test_select_exact_display_requires_one_identity_and_geometry_match() -> None:
    selected = select_exact_display(
        [ASUS, SAMSUNG],
        device_name=r"\\.\DISPLAY1",
        geometry=(3840, 1235, 3440, 1440),
    )
    assert selected == SAMSUNG

    with pytest.raises(ValueError, match="exactly one"):
        select_exact_display([ASUS], r"\\.\DISPLAY1", SAMSUNG.geometry)
    with pytest.raises(ValueError, match="geometry"):
        select_exact_display([SAMSUNG], r"\\.\DISPLAY1", (0, 0, 3440, 1440))
    with pytest.raises(ValueError, match="exactly one"):
        select_exact_display([SAMSUNG, SAMSUNG], r"\\.\DISPLAY1", SAMSUNG.geometry)


def test_hdr_gate_uses_the_exact_display_state_not_a_global_capability_flag() -> None:
    class State:
        def __init__(self, device_path: str, hdr_enabled: bool) -> None:
            self.device_path = device_path
            self.hdr_enabled = hdr_enabled

    states = [State(ASUS.device_name, True), State(SAMSUNG.device_name, False)]
    assert target_hdr_enabled(states, SAMSUNG.device_name) is False
    with pytest.raises(ValueError, match="exactly one"):
        target_hdr_enabled([], SAMSUNG.device_name)


def test_device_id_token_binds_generic_windows_monitor_names() -> None:
    require_device_id_token(SAMSUNG, "SAM72F2")
    with pytest.raises(ValueError, match="identity token"):
        require_device_id_token(SAMSUNG, "AUS27F5")


def test_run_evidence_requires_complete_patches_and_matching_lut_digest(tmp_path: Path) -> None:
    run = _run(tmp_path)
    validate_run_evidence(run)

    with pytest.raises(ValueError, match="24"):
        validate_run_evidence(replace(run, direct_correction=_summary(3.0, count=23)))

    Path(run.lut_path).write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="digest"):
        validate_run_evidence(run)


class FakeDwmPort:
    def __init__(self, current_target: DisplayTarget = SAMSUNG, active: bool = False) -> None:
        self.current_target = current_target
        self.active = active
        self.applied_targets: list[str] = []
        self.unloaded_targets: list[str] = []

    def target_for(self, device_name: str) -> DisplayTarget:
        assert device_name == SAMSUNG.device_name
        return self.current_target

    def has_active_lut(self, device_name: str) -> bool:
        return self.active

    def apply(self, device_name: str, lut_path: str) -> bool:
        self.applied_targets.append(device_name)
        self.active = True
        return True

    def unload(self, device_name: str) -> bool:
        self.unloaded_targets.append(device_name)
        self.active = False
        return True


def test_apply_targets_only_samsung_and_keeps_measured_improvement(tmp_path: Path) -> None:
    run = _run(tmp_path)
    dwm = FakeDwmPort()

    decision = apply_and_verify(run, dwm, lambda: _summary(2.5))

    assert decision.applied is True
    assert decision.verified is True
    assert decision.rolled_back is False
    assert dwm.applied_targets == [r"\\.\DISPLAY1"]
    assert r"\\.\DISPLAY2" not in dwm.applied_targets


@pytest.mark.parametrize("post", [_summary(6.0), _summary(7.0), _summary(2.0, count=23)])
def test_apply_rolls_back_when_post_apply_evidence_is_not_better(
    tmp_path: Path,
    post: VerificationSummary,
) -> None:
    run = _run(tmp_path)
    dwm = FakeDwmPort()

    decision = apply_and_verify(run, dwm, lambda: post)

    assert decision.applied is True
    assert decision.verified is False
    assert decision.rolled_back is True
    assert dwm.unloaded_targets == [r"\\.\DISPLAY1"]


def test_apply_rolls_back_when_post_apply_change_is_only_measurement_drift(
    tmp_path: Path,
) -> None:
    run = _run(tmp_path)
    dwm = FakeDwmPort()

    decision = apply_and_verify(run, dwm, lambda: _summary(5.9))

    assert decision.applied is True
    assert decision.verified is False
    assert decision.rolled_back is True
    assert "meaningful" in decision.reason
    assert dwm.unloaded_targets == [r"\\.\DISPLAY1"]


def test_apply_aborts_when_direct_correction_gain_is_only_measurement_drift(
    tmp_path: Path,
) -> None:
    run = _run(tmp_path, direct_average=5.9)

    with pytest.raises(ValueError, match="meaningful"):
        apply_and_verify(run, FakeDwmPort(), lambda: _summary(2.0))


def test_apply_aborts_on_identity_change_or_existing_lut(tmp_path: Path) -> None:
    run = _run(tmp_path)
    changed = replace(SAMSUNG, device_id=r"DISPLAY\SAM-CHANGED")

    with pytest.raises(ValueError, match="identity"):
        apply_and_verify(run, FakeDwmPort(current_target=changed), lambda: _summary(2.0))
    with pytest.raises(ValueError, match="active"):
        apply_and_verify(run, FakeDwmPort(active=True), lambda: _summary(2.0))
