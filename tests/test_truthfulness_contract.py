"""Release-wide evidence and claim truthfulness contract."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from calibrate_pro.core.calibration_engine import CalibrationResult
from calibrate_pro.sensorless.auto_calibration import AutoCalibrationResult
from calibrate_pro.verification.provenance import EvidenceKind, MetricValue
from calibrate_pro.verification.report_generator import build_report_payload

ROOT = Path(__file__).resolve().parents[1]
PERFORMANCE_KEYS = {
    "delta_e",
    "delta_e_avg",
    "delta_e_max",
    "peak_luminance",
    "gamut_coverage_srgb",
    "gamut_coverage_p3",
    "gamut_coverage_bt2020",
}
BANNED_UNQUALIFIED = (
    re.compile(r"achiev(?:e|es|ing)\s+delta\s*e\s*<", re.I),
    re.compile(r"delta\s*e\s*<\s*(?:0\.5|1\.0)\s*(?:typical|accuracy)?", re.I),
    re.compile(r"(?:99\.2%\s+DCI-P3|87\.3%\s+BT\.2020|100%\s+coverage)", re.I),
)


def assert_metric(payload: object, evidence: str, source_prefix: str) -> None:
    assert isinstance(payload, dict)
    assert isinstance(payload["value"], (int, float))
    assert payload["evidence"] == evidence
    assert str(payload["source"]).startswith(source_prefix)


def test_release_runtime_contains_no_unqualified_accuracy_promises() -> None:
    files = sorted((ROOT / "calibrate_pro").rglob("*.py")) + [
        ROOT / "README.md",
        ROOT / "RELEASE_NOTES.md",
    ]
    offenders: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        for pattern in BANNED_UNQUALIFIED:
            if pattern.search(text):
                offenders.append(f"{path.relative_to(ROOT)}:{pattern.pattern}")
    assert offenders == []


@pytest.mark.parametrize("key", sorted(PERFORMANCE_KEYS))
def test_report_serializer_rejects_bare_numeric_performance_metric(key: str) -> None:
    with pytest.raises(ValueError, match="MetricValue"):
        build_report_payload({key: 0.42})


def test_missing_metric_renders_not_measured() -> None:
    metric = MetricValue(None, "dE2000", EvidenceKind.NOT_MEASURED)
    assert metric.display_text() == "Not measured"
    assert metric.to_dict() == {
        "value": None,
        "unit": "dE2000",
        "evidence": "not_measured",
        "source": None,
    }


@pytest.mark.parametrize(
    ("evidence", "label"),
    [
        (EvidenceKind.ESTIMATED, "estimated"),
        (EvidenceKind.MEASURED, "measured"),
        (EvidenceKind.SIMULATED, "simulated"),
        (EvidenceKind.REPLAYED, "replayed"),
    ],
)
def test_numeric_metric_display_always_names_its_evidence(evidence: EvidenceKind, label: str) -> None:
    metric = MetricValue(1.25, "dE2000", evidence, "receipt")
    assert metric.display_text() == f"1.25 dE2000 ({label})"


def test_sensorless_result_defaults_never_fabricate_observations() -> None:
    payload = AutoCalibrationResult().to_dict()
    assert payload["delta_e"]["value"] is None
    assert payload["delta_e"]["evidence"] == "not_measured"


def test_calibration_result_defaults_never_fabricate_observations() -> None:
    payload = CalibrationResult().to_dict()
    assert payload["delta_e_avg"]["value"] is None
    assert payload["delta_e_max"]["value"] is None


def test_report_payload_serializes_evidence_and_source() -> None:
    source = "panel-characterization:test-panel:" + "a" * 64
    result = {
        "mode": "sensorless",
        "delta_e": MetricValue(0.84, "dE2000", EvidenceKind.ESTIMATED, source),
    }
    payload = build_report_payload(result)
    assert payload["schema_version"] == 1
    assert_metric(payload["metrics"]["delta_e"], "estimated", "panel-characterization:")
    assert source in payload["source_receipts"]


def test_sensorless_verification_labels_summary_patch_and_gamut_evidence() -> None:
    from calibrate_pro.sensorless.auto_calibration import _label_estimated_verification

    source = "panel-characterization:test:sha256"
    verification = _label_estimated_verification(
        {
            "delta_e_avg": 0.5,
            "delta_e_max": 1.2,
            "cam16_delta_e_avg": 0.7,
            "patches": [{"name": "Red", "delta_e": 0.4, "cam16_delta_e": 0.6}],
            "gamut_coverage": {"srgb_pct": 99.1},
            "color_volume": {"p3_pct": 97.2},
            "grade": "Professional",
        },
        source,
    )

    assert verification["grade"] == "Estimated model diagnostics"
    for metric in (
        verification["delta_e_avg"],
        verification["delta_e_max"],
        verification["cam16_delta_e_avg"],
        verification["patches"][0]["delta_e"],
        verification["patches"][0]["cam16_delta_e"],
        verification["gamut_coverage"]["srgb_pct"],
        verification["color_volume"]["p3_pct"],
    ):
        assert isinstance(metric, MetricValue)
        assert metric.evidence is EvidenceKind.ESTIMATED
        assert metric.source == source
