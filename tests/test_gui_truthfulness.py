"""GUI contracts for evidence-labelled calibration metrics."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from calibrate_pro.verification.provenance import EvidenceKind, MetricValue

ROOT = Path(__file__).resolve().parents[1]
GUI_TRUTHFULNESS_FILES = (
    "calibrate_pro/gui/app.py",
    "calibrate_pro/gui/calibration_details.py",
    "calibrate_pro/gui/calibration_wizard.py",
    "calibrate_pro/gui/dialogs.py",
    "calibrate_pro/gui/measurement_view.py",
    "calibrate_pro/gui/pages/calibrate.py",
    "calibrate_pro/gui/pages/calibration_page.py",
    "calibrate_pro/gui/pages/dashboard_page.py",
    "calibrate_pro/gui/pages/verification_page.py",
    "calibrate_pro/gui/pages/verify.py",
)

SEEDED_PERFORMANCE_PATTERNS = (
    re.compile(r"Average Delta E:\s*[0-9]", re.I),
    re.compile(r"Max(?:imum)? Delta E:\s*[0-9]", re.I),
    re.compile(r"Delta E\s+[0-9]+(?:\.[0-9]+)?", re.I),
    re.compile(r"(?:99\.2%\s+DCI-P3|87\.3%\s+BT\.2020|100%\s+coverage)", re.I),
    re.compile(r"(?:Excellent accuracy|Professional color-critical|REFERENCE GRADE)", re.I),
    re.compile(r"(?:delta_e|delta_e_avg|delta_e_max)[\"']?\s*[,=:]\s*0\.0", re.I),
)

UNPERFORMED_OPERATION_CLAIMS = (
    "Creating ICC profile...",
    "Generating 3D LUT...",
    "Installing profile...",
    "Profile installed successfully!",
    "Reading sensor...",
    "Measurement sequence complete!",
)


def _sources() -> dict[str, str]:
    return {relative: (ROOT / relative).read_text(encoding="utf-8") for relative in GUI_TRUTHFULNESS_FILES}


def test_gui_sources_do_not_generate_random_or_simulated_performance_metrics() -> None:
    violations: list[str] = []
    for relative, source in _sources().items():
        tree = ast.parse(source, filename=relative)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                modules = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                if "random" in modules:
                    violations.append(f"{relative}:{node.lineno}: imports random")
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
                marker in node.name for marker in ("simulate_calibration", "seed_grayscale")
            ):
                violations.append(f"{relative}:{node.lineno}: {node.name}")
    assert violations == []


def test_gui_sources_contain_no_seeded_performance_values_or_unsupported_grades() -> None:
    violations = [
        f"{relative}:{pattern.pattern}"
        for relative, source in _sources().items()
        for pattern in SEEDED_PERFORMANCE_PATTERNS
        if pattern.search(source)
    ]
    assert violations == []


def test_preview_only_gui_does_not_claim_unperformed_operations() -> None:
    violations = [
        f"{relative}:{claim}"
        for relative, source in _sources().items()
        for claim in UNPERFORMED_OPERATION_CLAIMS
        if claim in source
    ]
    assert violations == []


def test_measurement_defaults_are_explicitly_not_measured() -> None:
    from calibrate_pro.gui.measurement_view import Measurement

    measurement = Measurement(index=0)
    assert measurement.measured_xyz is None
    assert measurement.measured_lab is None
    assert measurement.measured_xy is None
    assert measurement.delta_e == MetricValue(None, "dE2000", EvidenceKind.NOT_MEASURED)


def test_delta_e_widget_requires_metric_evidence(qapp: object) -> None:
    from calibrate_pro.gui.measurement_view import DeltaEDisplay

    widget = DeltaEDisplay()
    assert widget.value_label.text() == "Not measured"
    assert widget.evidence_label.text() == "Evidence: not measured"

    metric = MetricValue(0.42, "dE2000", EvidenceKind.MEASURED, "instrument:i1display:receipt-123")
    widget.set_value(metric)
    assert widget.value_label.text() == "0.420 dE2000 (measured)"
    assert widget.evidence_label.text() == "Source: instrument:i1display:receipt-123"

    with pytest.raises(TypeError, match="MetricValue"):
        widget.set_value(0.42)  # type: ignore[arg-type]


def test_color_patch_missing_metric_is_not_rendered_as_zero(qapp: object) -> None:
    from calibrate_pro.gui.pages.verify import ColorPatchWidget

    patch = ColorPatchWidget(name="Dark Skin")
    assert isinstance(patch._de, MetricValue)
    assert patch._de.evidence is EvidenceKind.NOT_MEASURED
    assert "Not measured" in patch.toolTip()
