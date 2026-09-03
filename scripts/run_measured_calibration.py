"""Run one exact-display, measured SDR calibration with rollback.

This is intentionally narrower than the legacy hardware scripts: it never
writes DDC controls, ICC associations, gamma ramps, HDR state, or another
monitor's LUT.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import math
import statistics
import sys
import time
import tkinter as tk
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import hid
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from calibrate_pro.calibration.measured_runner import (
    ApplyDecision,
    DisplayTarget,
    MeasuredCalibrationRun,
    PatchResult,
    VerificationSummary,
    apply_and_verify,
    require_device_id_token,
    select_exact_display,
    sha256_file,
    target_hdr_enabled,
    validate_run_evidence,
)
from calibrate_pro.calibration.native_loop import (
    COLORCHECKER_REF_LAB,
    COLORCHECKER_SRGB,
    build_correction_lut,
    compute_de,
    profile_display,
)
from calibrate_pro.core.lut_engine import LUTFormat
from calibrate_pro.display.hdr_detect import detect_hdr_state
from calibrate_pro.hardware.i1d3_native import I1D3Driver
from calibrate_pro.lut_system.dwm_lut import (
    apply_lut,
    get_lut_status,
    list_monitors,
    remove_lut,
)
from calibrate_pro.panels.detection import enumerate_displays


OLED_FALLBACK_MATRIX = [
    [0.03836831, -0.02175997, 0.01696057],
    [0.01449629, 0.01611903, 0.00057150],
    [-0.00004481, 0.00035042, 0.08032401],
]
EVIDENCE_GRADE = "research_fallback_oled_matrix"


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def parse_geometry(value: str) -> tuple[int, int, int, int]:
    try:
        geometry = tuple(int(part.strip()) for part in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("geometry must contain four integers") from exc
    if len(geometry) != 4 or geometry[2] <= 0 or geometry[3] <= 0:
        raise argparse.ArgumentTypeError("geometry must be x,y,width,height")
    return geometry


def discover_targets() -> list[DisplayTarget]:
    targets = []
    for display in enumerate_displays():
        targets.append(
            DisplayTarget(
                device_name=display.device_name,
                device_id=display.device_id,
                geometry=(
                    display.position_x,
                    display.position_y,
                    display.width,
                    display.height,
                ),
                name=display.monitor_name or display.model or display.device_string,
            )
        )
    return targets


class PatchPresenter:
    def __init__(self, geometry: tuple[int, int, int, int]) -> None:
        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except (AttributeError, OSError):
            pass
        x, y, width, height = geometry
        self._root = tk.Tk()
        self._root.overrideredirect(True)
        self._root.attributes("-topmost", True)
        self._root.geometry(f"{width}x{height}+{x}+{y}")
        self._canvas = tk.Canvas(self._root, highlightthickness=0, cursor="none")
        self._canvas.pack(fill=tk.BOTH, expand=True)
        self.last_rgb = (0.0, 0.0, 0.0)

    def show(self, r: float, g: float, b: float, settle: float = 1.0) -> None:
        rgb = tuple(float(np.clip(value, 0.0, 1.0)) for value in (r, g, b))
        encoded = tuple(int(value * 255.0 + 0.5) for value in rgb)
        self._canvas.configure(bg=f"#{encoded[0]:02x}{encoded[1]:02x}{encoded[2]:02x}")
        self._root.update_idletasks()
        self._root.update()
        self.last_rgb = rgb
        time.sleep(settle)

    def close(self) -> None:
        self._root.destroy()


class InstrumentSession:
    def __init__(self) -> None:
        self._device = hid.device()
        self._device.open(0x0765, 0x5020)
        self._driver = I1D3Driver(transport=self._device)
        self._driver._cal_matrix = OLED_FALLBACK_MATRIX
        self._driver._black_offset = [0.0, 0.0, 0.0]
        self._driver._cal_source = "fallback_approximate"
        self.receipts: list[dict] = []
        if not self._driver.unlock():
            self.close()
            raise RuntimeError("the connected 0765:5020 instrument did not accept a known unlock key")

    def measure(
        self,
        integration_seconds: float,
        phase: str,
        rgb: tuple[float, float, float],
    ) -> np.ndarray | None:
        measured = self._driver.measure(integration_seconds)
        receipt = {
            "timestamp_utc": utc_now(),
            "phase": phase,
            "displayed_rgb": list(rgb),
            "integration_seconds": integration_seconds,
            "valid": measured is not None,
        }
        if measured is None:
            self.receipts.append(receipt)
            return None
        xyz = np.array([measured.X, measured.Y, measured.Z], dtype=float)
        receipt.update(
            {
                "xyz": xyz.tolist(),
                "sensor_frequency": [
                    measured.red_count,
                    measured.green_count,
                    measured.blue_count,
                ],
            }
        )
        self.receipts.append(receipt)
        return xyz

    def close(self) -> None:
        self._driver.close()


def measure_colorchecker(
    instrument: InstrumentSession,
    presenter: PatchPresenter,
    white_y: float,
    phase: str,
    correction=None,
) -> VerificationSummary:
    results: list[PatchResult] = []
    for index, (name, r, g, b) in enumerate(COLORCHECKER_SRGB, start=1):
        requested = (float(r), float(g), float(b))
        displayed_array = (
            np.asarray(correction.apply(np.array(requested)), dtype=float)
            if correction is not None
            else np.asarray(requested, dtype=float)
        )
        displayed = tuple(float(value) for value in np.clip(displayed_array, 0.0, 1.0))
        presenter.show(*displayed, settle=1.0)
        xyz = instrument.measure(1.0, phase, displayed)
        if xyz is None or not np.all(np.isfinite(xyz)) or xyz[1] <= 0.0:
            print(f"  [{index:02d}/24] {name}: no valid reading", flush=True)
            continue
        delta_e = compute_de(xyz, white_y, COLORCHECKER_REF_LAB[name])
        print(f"  [{index:02d}/24] {name}: dE2000={delta_e:.3f}", flush=True)
        results.append(
            PatchResult(
                name=name,
                requested_rgb=requested,
                displayed_rgb=displayed,
                xyz=tuple(float(value) for value in xyz),
                delta_e=float(delta_e),
            )
        )
    delta_values = [result.delta_e for result in results]
    average = statistics.fmean(delta_values) if delta_values else math.nan
    maximum = max(delta_values) if delta_values else math.nan
    return VerificationSummary(
        valid_patches=len(results),
        delta_e_average=average,
        delta_e_maximum=maximum,
        patch_results=tuple(results),
    )


class ExactDwmPort:
    def __init__(self, expected_target: DisplayTarget) -> None:
        self.expected_target = expected_target

    def target_for(self, device_name: str) -> DisplayTarget:
        return select_exact_display(discover_targets(), device_name, self.expected_target.geometry)

    def _monitor(self, device_name: str) -> dict:
        target = self.target_for(device_name)
        x, y, width, height = target.geometry
        matches = [
            monitor
            for monitor in list_monitors()
            if tuple(monitor["position"]) == (x, y) and tuple(monitor["size"]) == (width, height)
        ]
        if len(matches) != 1:
            raise RuntimeError(f"expected one DWM monitor for {device_name}; found {len(matches)}")
        return matches[0]

    def has_active_lut(self, device_name: str) -> bool:
        monitor = self._monitor(device_name)
        return monitor["sdr_lut_name"] in get_lut_status()["active_luts"]

    def apply(self, device_name: str, lut_path: str) -> bool:
        monitor = self._monitor(device_name)
        applied = apply_lut(lut_path, monitor_index=int(monitor["index"]), lut_type="sdr")
        time.sleep(3.0)
        status = get_lut_status()
        if not applied or not status["running"]:
            remove_lut(monitor_index=int(monitor["index"]), lut_type="sdr")
            return False
        return monitor["sdr_lut_name"] in status["active_luts"]

    def unload(self, device_name: str) -> bool:
        monitor = self._monitor(device_name)
        return remove_lut(monitor_index=int(monitor["index"]), lut_type="sdr")


def summary_payload(summary: VerificationSummary) -> dict:
    return asdict(summary)


def write_html_report(
    path: Path,
    run: MeasuredCalibrationRun,
    decision: ApplyDecision | None,
) -> None:
    post = decision.post_apply if decision else None
    rows = [
        ("Baseline", run.baseline),
        ("Direct correction", run.direct_correction),
    ]
    if post is not None:
        rows.append(("Post-apply", post))
    table_rows = "".join(
        f"<tr><td>{label}</td><td>{summary.valid_patches}</td>"
        f"<td>{summary.delta_e_average:.3f}</td><td>{summary.delta_e_maximum:.3f}</td></tr>"
        for label, summary in rows
    )
    verdict = decision.reason if decision else "not applied"
    path.write_text(
        "<!doctype html><meta charset='utf-8'><title>Samsung calibration receipt</title>"
        "<style>body{font:16px system-ui;max-width:900px;margin:40px auto;line-height:1.5}"
        "table{border-collapse:collapse}td,th{padding:8px 12px;border:1px solid #bbb}</style>"
        f"<h1>Measured calibration: {run.target.name}</h1>"
        f"<p><b>Target:</b> {run.target.device_name} {run.target.geometry}</p>"
        f"<p><b>Verdict:</b> {verdict}</p>"
        "<table><tr><th>Stage</th><th>Valid patches</th><th>Average dE2000</th>"
        f"<th>Maximum dE2000</th></tr>{table_rows}</table>"
        "<p><b>Limitation:</b> The fallback OLED colorimeter matrix makes this "
        "research evidence for same-instrument optimization. It does not establish "
        "reference-instrument accuracy or standards conformance.</p>",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--display-device", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--display-id-token", required=True)
    parser.add_argument("--geometry", required=True, type=parse_geometry)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    target = select_exact_display(discover_targets(), args.display_device, args.geometry)
    require_device_id_token(target, args.display_id_token)

    dwm_status_before = get_lut_status()
    dwm_port = ExactDwmPort(target)
    monitor = dwm_port._monitor(target.device_name)
    if target_hdr_enabled(detect_hdr_state(), target.device_name):
        raise RuntimeError("target is currently in HDR; this runner is deliberately SDR-only")
    if dwm_port.has_active_lut(target.device_name):
        raise RuntimeError("Samsung already has an active DWM LUT; refusing to overwrite it")

    print(f"TARGET: {target}", flush=True)
    print(f"DWM BEFORE: {json.dumps(dwm_status_before, default=str)}", flush=True)

    presenter: PatchPresenter | None = None
    instrument: InstrumentSession | None = None
    decision: ApplyDecision | None = None
    try:
        presenter = PatchPresenter(target.geometry)
        instrument = InstrumentSession()

        print("PROTOCOL SMOKE: controlled white", flush=True)
        presenter.show(1.0, 1.0, 1.0, settle=1.5)
        white_xyz = instrument.measure(1.0, "protocol_smoke", presenter.last_rgb)
        if white_xyz is None or not 1.0 <= white_xyz[1] <= 10_000.0:
            raise RuntimeError(f"implausible controlled-white measurement: {white_xyz}")
        white_y = float(white_xyz[1])
        white_sum = float(np.sum(white_xyz))
        print(
            f"WHITE: Y={white_y:.3f} xy=({white_xyz[0] / white_sum:.5f},"
            f"{white_xyz[1] / white_sum:.5f})",
            flush=True,
        )

        print("BASELINE: 24 ColorChecker patches", flush=True)
        baseline = measure_colorchecker(instrument, presenter, white_y, "baseline")
        if baseline.valid_patches != 24:
            raise RuntimeError(f"baseline incomplete: {baseline.valid_patches}/24")
        print(
            f"BASELINE SUMMARY: avg={baseline.delta_e_average:.3f} "
            f"max={baseline.delta_e_maximum:.3f}",
            flush=True,
        )

        print("PROFILE: 17 steps across white, red, green, blue ramps", flush=True)
        profile_phase = "profile"

        def show_profile(r: float, g: float, b: float) -> None:
            presenter.show(r, g, b, settle=0.9)

        def measure_profile(r: float, g: float, b: float) -> np.ndarray | None:
            level = max(r, g, b)
            integration = 2.0 if level < 0.05 else 1.25 if level < 0.20 else 0.8
            return instrument.measure(integration, profile_phase, presenter.last_rgb)

        profile = profile_display(
            measure_profile,
            show_profile,
            n_steps=17,
            progress_fn=lambda message, fraction: print(
                f"  {message} {fraction * 100:.0f}%",
                flush=True,
            ),
        )
        profile_arrays = (
            profile.levels,
            profile.trc_r,
            profile.trc_g,
            profile.trc_b,
            profile.M_display,
        )
        if not all(np.all(np.isfinite(values)) for values in profile_arrays):
            raise RuntimeError("profile contains non-finite values")
        if not 1.0 <= profile.white_Y <= 10_000.0:
            raise RuntimeError(f"profile white luminance is implausible: {profile.white_Y}")
        if abs(float(np.linalg.det(profile.M_display))) < 1e-9:
            raise RuntimeError("profile primary matrix is singular")

        print("LUT: generate 33-cube correction", flush=True)
        lut = build_correction_lut(profile, size=33)
        lut.title = f"Calibrate Pro measured SDR - {target.name}"

        print("DIRECT VALIDATION: 24 pre-corrected ColorChecker patches", flush=True)
        direct = measure_colorchecker(instrument, presenter, white_y, "direct_correction", correction=lut)
        if direct.valid_patches != 24:
            raise RuntimeError(f"direct correction incomplete: {direct.valid_patches}/24")
        print(
            f"DIRECT SUMMARY: avg={direct.delta_e_average:.3f} "
            f"max={direct.delta_e_maximum:.3f}",
            flush=True,
        )
        if direct.delta_e_average >= baseline.delta_e_average:
            raise RuntimeError("direct correction did not improve; no LUT will be written or applied")

        lut_path = output / "odyssey-g85sb-measured-sdr.cube"
        lut.save(lut_path, LUTFormat.CUBE)
        lut_digest = sha256_file(lut_path)
        receipt_path = output / "odyssey-g85sb-measured-sdr.json"
        receipt = {
            "schema_version": 1,
            "created_at_utc": utc_now(),
            "target": asdict(target),
            "display_name_requested": args.display_name,
            "icc_association_preserved": next(
                (
                    display.current_profile
                    for display in enumerate_displays()
                    if display.device_name == target.device_name
                ),
                None,
            ),
            "dwm_before": dwm_status_before,
            "instrument": {
                "vid": "0x0765",
                "pid": "0x5020",
                "matrix_source": "fallback_approximate_oled",
            },
            "profile": {
                "levels": profile.levels.tolist(),
                "trc_r": profile.trc_r.tolist(),
                "trc_g": profile.trc_g.tolist(),
                "trc_b": profile.trc_b.tolist(),
                "primary_matrix_xyz": profile.M_display.tolist(),
                "white_y": profile.white_Y,
                "black_xyz": profile.black_xyz.tolist(),
                "white_xy": profile.white_xy,
                "red_xy": profile.red_xy,
                "green_xy": profile.green_xy,
                "blue_xy": profile.blue_xy,
                "gamma_r": profile.gamma_r,
                "gamma_g": profile.gamma_g,
                "gamma_b": profile.gamma_b,
            },
            "baseline": summary_payload(baseline),
            "direct_correction": summary_payload(direct),
            "measurements": instrument.receipts,
            "lut_path": str(lut_path),
            "lut_sha256": lut_digest,
            "evidence_grade": EVIDENCE_GRADE,
            "limitations": [
                "Fallback OLED colorimeter matrix, not a per-unit reference-instrument correction.",
                "Same-instrument improvement is research evidence, not standards certification.",
                "Ambient light, panel warmup, repeatability, and preset state were not independently certified.",
            ],
        }
        receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")

        run = MeasuredCalibrationRun(
            target=target,
            baseline=baseline,
            direct_correction=direct,
            lut_path=str(lut_path),
            lut_sha256=lut_digest,
            receipt_path=str(receipt_path),
            evidence_grade=EVIDENCE_GRADE,
        )
        validate_run_evidence(run)

        if args.apply:
            print("APPLY: Samsung SDR DWM LUT only", flush=True)

            def verify_post_apply() -> VerificationSummary:
                print("POST-APPLY: 24 ColorChecker patches", flush=True)
                return measure_colorchecker(instrument, presenter, white_y, "post_apply")

            decision = apply_and_verify(run, dwm_port, verify_post_apply)
            print(f"VERDICT: {decision}", flush=True)
        else:
            print("VERDICT: measured LUT generated but not applied", flush=True)

        final_payload = json.loads(receipt_path.read_text(encoding="utf-8"))
        final_payload["apply_decision"] = asdict(decision) if decision else None
        final_payload["dwm_after"] = get_lut_status()
        receipt_path.write_text(json.dumps(final_payload, indent=2), encoding="utf-8")
        html_path = output / "odyssey-g85sb-measured-sdr.html"
        write_html_report(html_path, run, decision)
        print(f"LUT: {lut_path}", flush=True)
        print(f"RECEIPT: {receipt_path}", flush=True)
        print(f"REPORT: {html_path}", flush=True)

        if args.apply and (decision is None or not decision.verified):
            return 2
        return 0
    finally:
        if presenter is not None:
            presenter.close()
        if instrument is not None:
            instrument.close()


if __name__ == "__main__":
    raise SystemExit(main())
