"""Planted-truth tests for the one-click closed loop, on a simulated panel.

Each case plants a known truth in the simulated panel and checks the loop
against it with numbers fixed before the run. "True" errors are computed from
the panel's noise-free emission, which only a simulation can expose; the loop
itself sees only the noisy simulated instrument.
"""

from __future__ import annotations

import pytest

from calibrate_pro.calibration.closed_loop import (
    DisplayIntent,
    PanelTruth,
    PlanApproval,
    SimulatedInstrument,
    SimulatedPanel,
    Tolerances,
    build_plan,
    run_closed_loop,
)
from calibrate_pro.calibration.closed_loop.controls import SimulatedClock
from calibrate_pro.calibration.closed_loop.ledger import verify_chain
from calibrate_pro.calibration.closed_loop.metrics import delta_e_relative, target_white_xyz
from calibrate_pro.verification.provenance import EvidenceKind

#: A cool-white panel set wrong on purpose: red gain at 90, brightness at 30,
#: three per cent warm-up drift with a five-minute time constant.
MISCALIBRATED = PanelTruth(
    channel_peak_y=(55.0, 190.0, 24.0),
    warmup_amplitude=0.03,
    warmup_tau_s=300.0,
    initial={"brightness": 30, "red_gain": 90},
)

#: Channel peaks in the sRGB luminance ratios, so full gains give D65 exactly.
PERFECT = PanelTruth(channel_peak_y=(0.2126 * 240, 0.7152 * 240, 0.0722 * 240), initial={"brightness": 50})


def _run(truth: PanelTruth, intent: DisplayIntent, **noise: float):
    clock = SimulatedClock()
    panel = SimulatedPanel(truth, clock)
    instrument = SimulatedInstrument(panel, clock, **noise)  # type: ignore[arg-type]
    plan = build_plan("simulated panel", intent, panel)
    result = run_closed_loop(plan, PlanApproval(plan), panel, panel, instrument, clock)
    panel.show((1.0, 1.0, 1.0))
    true_de = delta_e_relative(result.target, panel.emitted_xyz(), target_white_xyz(result.target))
    return result, panel, true_de


def test_known_miscalibration_is_recovered_within_tolerance() -> None:
    result, panel, true_de = _run(MISCALIBRATED, DisplayIntent("D65 120", white_luminance=120.0))

    assert result.stop_reason == "converged"
    assert result.iterations <= 8
    assert true_de <= 1.0
    assert result.white_de.value is not None and result.white_de.value <= 1.0
    assert abs(panel.emitted_xyz()[1] - 120.0) / 120.0 <= 0.03
    assert result.writes == panel.write_count <= 40
    assert result.verification is not None and result.verification.passed
    assert result.verification.worst("gray") <= 2.0


def test_target_outside_capability_is_clipped_and_reported_not_chased() -> None:
    intent = DisplayIntent(
        "beyond the panel", white_luminance=400.0, black_luminance=0.05, gamut="display_p3", min_gamut_coverage=0.9
    )
    result, panel, true_de = _run(MISCALIBRATED, intent)
    clips = {clip.field: clip for clip in result.target.clips}

    assert set(clips) == {"white_luminance", "black_luminance", "gamut_coverage"}
    assert clips["white_luminance"].requested == 400.0
    assert 230.0 <= clips["white_luminance"].achievable <= 260.0
    assert clips["black_luminance"].achievable > 0.05
    assert clips["gamut_coverage"].achievable < 0.9
    assert all(clip.evidence is EvidenceKind.SIMULATED for clip in clips.values())
    assert result.stop_reason == "converged"
    assert result.iterations <= 5
    assert true_de <= 1.0
    assert result.verification is not None
    ungraded = [p.name for p in result.verification.patches if not p.graded]
    assert {"red 75", "green 75"} <= set(ungraded)


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4])
def test_noisy_instrument_stops_at_the_noise_floor(seed: int) -> None:
    intent = DisplayIntent("tighter than noise", white_luminance=120.0, tolerances=Tolerances(white_de2000=0.05))
    result, _, true_de = _run(MISCALIBRATED, intent, relative_sigma=0.01, seed=seed)
    floor = result.noise_floor_de.value

    assert floor is not None and floor >= 0.5
    assert result.stop_reason == "noise_floor"
    assert result.iterations < 12
    assert true_de <= floor


def test_perfect_panel_needs_zero_writes() -> None:
    clock = SimulatedClock()
    reference = SimulatedPanel(PERFECT, clock)
    reference.show((1.0, 1.0, 1.0))
    intent = DisplayIntent("already right", white_luminance=float(reference.emitted_xyz()[1]))

    result, panel, true_de = _run(PERFECT, intent)

    assert result.stop_reason == "converged"
    assert result.writes == 0
    assert panel.write_count == 0
    assert result.iterations == 0
    assert true_de <= 0.05


def test_unstable_warmup_refuses_to_write() -> None:
    drifting = PanelTruth(warmup_amplitude=0.3, warmup_tau_s=3000.0)
    result, panel, _ = _run(drifting, DisplayIntent("D65 120", white_luminance=120.0))

    assert result.stop_reason == "warmup_unstable"
    assert panel.write_count == 0
    assert result.warmup is not None and not result.warmup.stable


def test_hdr_intent_is_refused_before_any_write() -> None:
    result, panel, _ = _run(MISCALIBRATED, DisplayIntent("PQ", white_luminance=600.0, eotf="pq"))

    assert result.stop_reason == "hdr_not_built"
    assert panel.write_count == 0


def test_every_metric_is_labelled_simulated_and_the_record_is_sealed() -> None:
    result, _, _ = _run(MISCALIBRATED, DisplayIntent("D65 120", white_luminance=120.0))

    assert result.white_de.evidence is EvidenceKind.SIMULATED
    assert result.white_luminance.evidence is EvidenceKind.SIMULATED
    assert result.noise_floor_de.evidence is EvidenceKind.SIMULATED
    assert result.verification is not None
    assert all(p.delta_e.evidence is EvidenceKind.SIMULATED for p in result.verification.patches)
    assert all("simulated" in (p.delta_e.source or "") for p in result.verification.patches)
    assert verify_chain(result.ledger)
    assert result.seal == result.ledger[-1]["digest"]
    tampered = list(result.ledger)
    tampered[3] = {**tampered[3], "payload": {"edited": True}}
    assert not verify_chain(tuple(tampered))
