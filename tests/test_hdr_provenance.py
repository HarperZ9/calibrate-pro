"""Evidence provenance contract for HDR workflow metrics."""

from __future__ import annotations

import numpy as np
import pytest

from calibrate_pro.hdr.workflow import HDRTarget, HDRWorkflow
from calibrate_pro.verification.provenance import EvidenceKind, MetricValue


def test_hdr_package_reexports_evidence_contract() -> None:
    from calibrate_pro.hdr import EvidenceKind as PackageEvidenceKind
    from calibrate_pro.hdr import MetricValue

    assert PackageEvidenceKind is EvidenceKind
    assert MetricValue(None, "nits", EvidenceKind.NOT_MEASURED).value is None


def test_default_hdr_run_reports_no_measurements() -> None:
    result = HDRWorkflow(HDRTarget.hdr10_1000()).run(lut_size=5)
    assert result.eotf_error.value is None
    assert result.peak_luminance.value is None
    assert result.gamut_coverage_bt2020.value is None
    assert result.eotf_error.evidence is EvidenceKind.NOT_MEASURED


def test_simulation_requires_explicit_evidence() -> None:
    result = HDRWorkflow(HDRTarget.hdr10_1000()).run(
        lut_size=5,
        evidence=EvidenceKind.SIMULATED,
        evidence_source="ST 2084 reference replay",
    )
    assert result.eotf_error.value == pytest.approx(0.0)
    assert result.peak_luminance.value == pytest.approx(1000.0)
    assert result.eotf_error.evidence is EvidenceKind.SIMULATED
    assert result.gamut_coverage_bt2020.value is None


def test_simulation_requires_evidence_source() -> None:
    with pytest.raises(ValueError, match="evidence_source"):
        HDRWorkflow(HDRTarget.hdr10_1000()).run(
            lut_size=5,
            evidence=EvidenceKind.SIMULATED,
        )


def test_numeric_readings_require_explicit_source() -> None:
    readings = np.linspace(0.0, 1000.0, 21)
    with pytest.raises(ValueError, match="evidence_source"):
        HDRWorkflow(HDRTarget.hdr10_1000()).run(
            measured_luminances=readings,
            evidence=EvidenceKind.MEASURED,
            lut_size=5,
        )


def test_replayed_readings_require_explicit_source() -> None:
    readings = np.linspace(0.0, 1000.0, 21)
    with pytest.raises(ValueError, match="evidence_source"):
        HDRWorkflow(HDRTarget.hdr10_1000()).run(
            measured_luminances=readings,
            evidence=EvidenceKind.REPLAYED,
            lut_size=5,
        )


def test_measured_readings_serialize_source() -> None:
    workflow = HDRWorkflow(HDRTarget.hdr10_1000())
    expected = workflow.generate_eotf_patches(steps=21)[:, 1]
    result = workflow.run(
        measured_luminances=expected,
        evidence=EvidenceKind.MEASURED,
        evidence_source="i1Display3 serial-redacted receipt 42",
        lut_size=5,
    )
    payload = result.to_dict()
    assert payload["peak_luminance"]["evidence"] == "measured"
    assert payload["peak_luminance"]["source"] == "i1Display3 serial-redacted receipt 42"
    assert payload["gamut_coverage_bt2020"]["value"] is None


def test_replayed_readings_serialize_source() -> None:
    workflow = HDRWorkflow(HDRTarget.hdr10_1000())
    expected = workflow.generate_eotf_patches(steps=21)[:, 1]
    result = workflow.run(
        measured_luminances=expected,
        evidence=EvidenceKind.REPLAYED,
        evidence_source="test fixture",
        lut_size=5,
    )
    payload = result.to_dict()
    assert payload["eotf_error"]["evidence"] == "replayed"
    assert payload["eotf_error"]["source"] == "test fixture"
    assert payload["gamut_coverage_bt2020"]["evidence"] == "not_measured"


@pytest.mark.parametrize("evidence", [EvidenceKind.NOT_MEASURED, EvidenceKind.ESTIMATED, EvidenceKind.SIMULATED])
def test_numeric_readings_require_measured_or_replayed_evidence(evidence: EvidenceKind) -> None:
    readings = np.linspace(0.0, 1000.0, 21)
    with pytest.raises(ValueError, match="MEASURED or REPLAYED"):
        HDRWorkflow(HDRTarget.hdr10_1000()).run(
            measured_luminances=readings,
            evidence=evidence,
            evidence_source="test fixture",
            lut_size=5,
        )


@pytest.mark.parametrize("evidence", [EvidenceKind.MEASURED, EvidenceKind.REPLAYED, EvidenceKind.ESTIMATED])
def test_absent_readings_reject_numeric_evidence(evidence: EvidenceKind) -> None:
    with pytest.raises(ValueError, match="measured_luminances"):
        HDRWorkflow(HDRTarget.hdr10_1000()).run(
            evidence=evidence,
            evidence_source="test fixture",
            lut_size=5,
        )


@pytest.mark.parametrize(
    ("target", "peak_luminance"),
    [(HDRTarget.hdr10_1000(), 1000.0), (HDRTarget.hdr10_600(), 600.0)],
)
def test_hdr10_patch_ramp_is_bounded_to_target(target: HDRTarget, peak_luminance: float) -> None:
    patches = HDRWorkflow(target).generate_eotf_patches(steps=21)
    assert patches[-1, 0] < 1.0
    assert patches[-1, 1] == pytest.approx(peak_luminance, rel=1e-12)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_run_rejects_non_finite_readings(value: float) -> None:
    workflow = HDRWorkflow(HDRTarget.hdr10_1000())
    readings = workflow.generate_eotf_patches(steps=21)[:, 1]
    readings[5] = value
    with pytest.raises(ValueError, match="finite"):
        workflow.run(
            measured_luminances=readings,
            evidence=EvidenceKind.REPLAYED,
            evidence_source="test fixture",
            lut_size=5,
        )


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), float("-inf")])
def test_measured_metric_requires_a_finite_reading(value: float | None) -> None:
    from calibrate_pro.verification.provenance import MetricValue

    with pytest.raises(ValueError, match="finite"):
        MetricValue(value, "nits", EvidenceKind.MEASURED, "instrument receipt")


def test_estimate_requires_characterization_source() -> None:
    from calibrate_pro.verification.provenance import MetricValue

    with pytest.raises(ValueError, match="source"):
        MetricValue(1.2, "dE2000", EvidenceKind.ESTIMATED)


def test_not_measured_metric_rejects_a_numeric_value() -> None:
    from calibrate_pro.verification.provenance import MetricValue

    with pytest.raises(ValueError, match="not-measured"):
        MetricValue(0.0, "percent", EvidenceKind.NOT_MEASURED)


def test_metric_serialization_and_display_keep_evidence_label() -> None:
    metric = MetricValue(1.25, "percent", EvidenceKind.SIMULATED, "ST 2084 reference replay")
    assert metric.display_text() == "1.25 percent (simulated)"
    assert metric.to_dict() == {
        "value": 1.25,
        "unit": "percent",
        "evidence": "simulated",
        "source": "ST 2084 reference replay",
    }


@pytest.mark.parametrize("evidence", [member.value for member in EvidenceKind])
def test_metric_rejects_raw_string_evidence(evidence: str) -> None:
    with pytest.raises(TypeError, match="EvidenceKind"):
        MetricValue(1.0, "nits", evidence, "instrument receipt")  # type: ignore[arg-type]


@pytest.mark.parametrize("with_readings", [False, True])
def test_hdr_run_rejects_raw_string_evidence(with_readings: bool) -> None:
    workflow = HDRWorkflow(HDRTarget.hdr10_1000())
    readings = workflow.generate_eotf_patches(steps=21)[:, 1] if with_readings else None
    with pytest.raises(TypeError, match="EvidenceKind"):
        workflow.run(
            measured_luminances=readings,
            evidence="measured",  # type: ignore[arg-type]
            evidence_source="instrument receipt",
            lut_size=5,
        )
