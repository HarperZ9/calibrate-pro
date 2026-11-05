"""Unit tests for the closed loop's parts: intent clipping, gamut, plan bounds, caps."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from calibrate_pro.calibration.closed_loop import (
    DisplayIntent,
    PanelCapability,
    PanelTruth,
    PlanApproval,
    PlanRefused,
    SimulatedPanel,
    build_plan,
    resolve_intent,
)
from calibrate_pro.calibration.closed_loop.controls import SimulatedClock, loop_controls_from_vcp
from calibrate_pro.calibration.closed_loop.gamut import coverage
from calibrate_pro.calibration.closed_loop.intent import GAMUTS, hlg_system_gamma
from calibrate_pro.calibration.closed_loop.ledger import Ledger
from calibrate_pro.calibration.closed_loop.metrics import delta_e_itp, xy_to_xyz
from calibrate_pro.calibration.closed_loop.plan import BoundedWriter
from calibrate_pro.hardware.mccs_caps import parse_capabilities
from calibrate_pro.verification.provenance import EvidenceKind

K32 = json.loads((Path(__file__).parent / "data" / "sceptre-k32-ddc-capabilities.json").read_text())


def _capability(peak: float = 250.0, contrast: float = 1000.0, primaries=GAMUTS["srgb"]) -> PanelCapability:
    return PanelCapability(peak, contrast, primaries, (0.3127, 0.3290), EvidenceKind.SIMULATED, "test")


def test_gamut_coverage_planted_values() -> None:
    assert coverage(GAMUTS["srgb"], GAMUTS["srgb"]) == pytest.approx(1.0, abs=1e-9)
    assert coverage(GAMUTS["bt2020"], GAMUTS["srgb"]) == pytest.approx(1.0, abs=1e-9)
    srgb_in_p3 = coverage(GAMUTS["srgb"], GAMUTS["display_p3"])
    assert 0.70 < srgb_in_p3 < 0.85


def test_intent_inside_capability_is_not_clipped() -> None:
    target = resolve_intent(DisplayIntent("ok", white_luminance=120.0), _capability())
    assert target.clips == ()
    assert target.white_luminance == 120.0
    assert target.black_luminance == pytest.approx(0.12)


def test_intent_beyond_capability_reports_each_clip() -> None:
    intent = DisplayIntent("hdr", white_luminance=1000.0, eotf="pq", black_luminance=0.0005, gamut="bt2020")
    target = resolve_intent(intent, _capability(peak=180.0))
    fields = {clip.field for clip in target.clips}
    assert fields == {"white_luminance", "black_luminance", "gamut_coverage", "hdr_reference_white"}
    assert target.white_luminance == pytest.approx(180.0 * 0.98)


def test_hlg_system_gamma_follows_bt2100() -> None:
    assert hlg_system_gamma(1000.0) == pytest.approx(1.2)
    assert hlg_system_gamma(400.0) == pytest.approx(1.2 + 0.42 * -0.39794, abs=1e-4)


def test_delta_e_itp_zero_and_luminance_step() -> None:
    white = xy_to_xyz((0.3127, 0.3290), 100.0)
    assert delta_e_itp(white, white) == pytest.approx(0.0, abs=1e-12)
    one = delta_e_itp(white * 1.01, white)
    # A one per cent step at 100 cd/m2 sits just under one JND (BT.2124 scaling),
    # and the metric is close to linear for small steps.
    assert 0.5 < one < 1.0
    assert delta_e_itp(white * 1.02, white) == pytest.approx(2.0 * one, rel=0.05)


def test_approval_is_single_use_and_bound_to_the_plan() -> None:
    panel = SimulatedPanel(PanelTruth(), SimulatedClock())
    plan = build_plan("sim", DisplayIntent("a", white_luminance=120.0), panel)
    other = build_plan("sim", DisplayIntent("b", white_luminance=100.0), panel)
    approval = PlanApproval(plan)
    with pytest.raises(PlanRefused):
        approval.consume(other)
    approval.consume(plan)
    with pytest.raises(PlanRefused):
        approval.consume(plan)


def test_writer_refuses_writes_outside_the_plan() -> None:
    panel = SimulatedPanel(PanelTruth(), SimulatedClock())
    plan = build_plan("sim", DisplayIntent("a", white_luminance=120.0), panel, max_step=5, max_writes=1)
    writer = BoundedWriter(plan, panel, Ledger())
    with pytest.raises(PlanRefused):
        writer.write("contrast", 60)
    with pytest.raises(PlanRefused):
        writer.write("brightness", 101)
    with pytest.raises(PlanRefused):
        writer.write("brightness", 60)
    assert writer.write("brightness", 55)
    with pytest.raises(PlanRefused):
        writer.write("brightness", 50)
    assert panel.write_count == 1


def test_k32_capabilities_parse_with_nested_value_lists() -> None:
    parsed = parse_capabilities(K32["raw_capabilities"])
    assert parsed.codes[:9] == (0x02, 0x04, 0x05, 0x08, 0x10, 0x12, 0x14, 0x16, 0x18)
    assert {0x1A, 0x52, 0x60, 0xDC, 0xDF, 0xFD} <= set(parsed.codes)
    assert 0x0B not in parsed.codes and 0x0C not in parsed.codes
    assert parsed.values[0x14] == (0x05, 0x08, 0x0B, 0x0C)
    assert parsed.values[0x60] == (0x11, 0x12, 0x0F, 0x10)
    assert parsed.values[0xDC] == (0x00, 0x02, 0x03, 0x05)
    assert parsed.mccs_version == "2.1"
    assert parsed.display_type == "lcd"


def test_k32_loop_controls_are_gains_and_brightness_without_offsets() -> None:
    parsed = parse_capabilities(K32["raw_capabilities"])
    maxima = {int(code, 16): read[1] for code, read in K32["reads"].items()}
    names = {spec.name for spec in loop_controls_from_vcp(parsed.codes, maxima)}
    assert names == {"brightness", "red_gain", "green_gain", "blue_gain"}
    assert 0x6C not in parsed.codes, "offsets answer reads on the K32 but are not advertised"
