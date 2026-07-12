"""Evidence-preserving report and export boundaries."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from calibrate_pro.sensorless.auto_calibration import AutoCalibrationResult
from calibrate_pro.verification.provenance import EvidenceKind, MetricValue
from calibrate_pro.verification.report_generator import build_report_payload, generate_calibration_report
from calibrate_pro.verification.reports import (
    ReportConfig,
    ReportFormat,
    ReportGenerator,
    ReportMetadata,
    VerificationSummary,
)


def _fake_panel() -> object:
    def point(x: float, y: float) -> object:
        return SimpleNamespace(x=x, y=y)

    return SimpleNamespace(
        native_primaries=SimpleNamespace(
            red=point(0.64, 0.33),
            green=point(0.30, 0.60),
            blue=point(0.15, 0.06),
            white=point(0.3127, 0.3290),
        ),
        gamma_red=SimpleNamespace(gamma=2.2),
        gamma_green=SimpleNamespace(gamma=2.2),
        gamma_blue=SimpleNamespace(gamma=2.2),
        panel_type="IPS",
        manufacturer="Test Vendor",
        model_pattern="Test Panel",
    )


def _metadata() -> ReportMetadata:
    return ReportMetadata(title="Truthful report", display_name="Display 1", profile_name="Profile 1")


def test_report_payload_materializes_missing_performance_metrics_as_not_measured() -> None:
    payload = build_report_payload({"mode": "sensorless"})
    metrics = cast(dict[str, dict[str, object]], payload["metrics"])

    assert metrics["delta_e"] == {
        "value": None,
        "unit": "dE2000",
        "evidence": "not_measured",
        "source": None,
    }
    assert metrics["peak_luminance"]["value"] is None
    assert payload["source_receipts"] == []


@pytest.mark.parametrize(
    "metric",
    [
        0.42,
        {"value": 0.42, "unit": "dE2000", "evidence": "measured", "source": None},
        {"value": 0.42, "unit": "dE2000", "evidence": "invented", "source": "receipt"},
    ],
)
def test_report_payload_rejects_untyped_or_invalid_metric_evidence(metric: object) -> None:
    with pytest.raises((TypeError, ValueError), match="MetricValue|evidence|source"):
        build_report_payload({"delta_e": metric})


def test_calibration_html_renders_metric_label_receipt_and_missing_data(tmp_path: Path) -> None:
    source = "panel-characterization:test-panel:" + "a" * 64
    result = AutoCalibrationResult(
        display_name="Display 1",
        panel_matched="Test Panel",
        panel_type="IPS",
        delta_e_predicted=MetricValue(0.84, "dE2000", EvidenceKind.ESTIMATED, source),
        delta_e_max=MetricValue(1.31, "dE2000", EvidenceKind.ESTIMATED, source),
    )

    path = generate_calibration_report(result, _fake_panel(), {}, tmp_path / "report.html")
    html = path.read_text(encoding="utf-8")

    assert "0.8400 dE2000 (estimated)" in html
    assert "1.3100 dE2000 (estimated)" in html
    assert source in html
    assert "Not measured" in html


def test_calibration_html_rejects_bare_verification_metric(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="MetricValue"):
        generate_calibration_report(
            AutoCalibrationResult(),
            _fake_panel(),
            {"delta_e_avg": 0.0},
            tmp_path / "report.html",
        )


def test_legacy_report_html_and_json_use_structured_metrics_and_receipts(tmp_path: Path) -> None:
    source = "instrument:i1display:redacted-receipt-42"
    summary = VerificationSummary(
        metrics={
            "delta_e": MetricValue(0.57, "dE2000", EvidenceKind.MEASURED, source),
            "peak_luminance": MetricValue(None, "nits", EvidenceKind.NOT_MEASURED),
        }
    )
    html_generator = ReportGenerator(ReportConfig(format=ReportFormat.HTML))
    html = html_generator._build_html_content(summary, _metadata())

    assert "0.57 dE2000 (measured)" in html
    assert source in html
    assert "Not measured" in html

    output = tmp_path / "report.json"
    json_generator = ReportGenerator(ReportConfig(format=ReportFormat.JSON, output_path=str(output)))
    json_generator.generate(summary, _metadata())
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert payload["schema_version"] == 1
    assert payload["metrics"]["delta_e"]["evidence"] == "measured"
    assert payload["metrics"]["delta_e"]["source"] == source
    assert payload["metrics"]["peak_luminance"]["value"] is None
    assert payload["source_receipts"] == [source]


def test_legacy_report_rejects_bare_numeric_metric_mapping() -> None:
    summary = VerificationSummary(metrics=cast(dict[str, MetricValue], {"delta_e": 0.42}))
    generator = ReportGenerator(ReportConfig(format=ReportFormat.HTML))

    with pytest.raises(ValueError, match="MetricValue"):
        generator._build_html_content(summary, _metadata())
