"""GUI contracts for evidence-labelled calibration metrics."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from calibrate_pro.verification.provenance import EvidenceKind, MetricValue

ROOT = Path(__file__).resolve().parents[1]
WINDOW_ROOT = "calibrate_pro/gui/app.py"

#: Modules the gate covered when the list was written by hand. Seven of them are
#: not reachable from the window this build launches, and they are kept here so
#: retiring the list does not quietly stop reading a file it used to read.
LEGACY_GUI_FILES = (
    "calibrate_pro/gui/calibration_details.py",
    "calibrate_pro/gui/calibration_wizard.py",
    "calibrate_pro/gui/dialogs.py",
    "calibrate_pro/gui/measurement_view.py",
    "calibrate_pro/gui/pages/calibration_page.py",
    "calibrate_pro/gui/pages/dashboard_page.py",
    "calibrate_pro/gui/pages/verification_page.py",
)


def _module_path(module: str) -> Path:
    return ROOT / (module.replace(".", "/") + ".py")


def _gui_imports(tree: ast.AST) -> list[str]:
    """Every ``calibrate_pro.gui`` name one module imports, module or symbol.

    A ``from`` import is expanded into the module and each name under it,
    because ``from calibrate_pro.gui.pages import verify`` and
    ``from calibrate_pro.gui.pages.verify import VerifyPage`` reach the same
    file and only one of them names it in ``node.module``.
    """
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.append(node.module)
            names.extend(f"{node.module}.{alias.name}" for alias in node.names)
    return [name for name in names if name.startswith("calibrate_pro.gui")]


def window_module_closure() -> tuple[str, ...]:
    """The GUI files the shipped window reaches, read off the imports.

    The list this replaced was maintained by hand, and nine of the fourteen
    modules the window reaches were absent from it, among them both dialogs, the
    DDC page, the settings page, and the binder every control is registered
    with. A file joins the gate here by being imported rather than by being
    remembered.
    """
    seen: set[str] = set()
    queue = ["calibrate_pro.gui.app"]
    while queue:
        module = queue.pop()
        if module in seen:
            continue
        path = _module_path(module)
        if not path.exists():
            continue
        seen.add(module)
        queue.extend(_gui_imports(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))))
    return tuple(sorted(module.replace(".", "/") + ".py" for module in seen))


GUI_TRUTHFULNESS_FILES = tuple(sorted({*window_module_closure(), *LEGACY_GUI_FILES}))

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
    # Claimed by the old export handler, which showed a save dialog and then
    # reported the chosen filename without writing anything to it.
    "Exported: ",
    # Claimed by the old Calibrate All handler, which set this label and did
    # nothing else at all.
    "Calibrating all displays...",
)


def _sources() -> dict[str, str]:
    return {relative: (ROOT / relative).read_text(encoding="utf-8") for relative in GUI_TRUTHFULNESS_FILES}


def test_every_file_the_window_reaches_is_read_by_these_gates() -> None:
    """The gate reads the window, so a new surface cannot open outside it.

    The three source gates below read a list, and a list of filenames is a claim
    about what the window is made of. It was written once and the window moved,
    which is the failure this catches: a module the window imports and the gate
    never opened would report as covered on a green suite.
    """
    missing = [name for name in window_module_closure() if name not in GUI_TRUTHFULNESS_FILES]

    assert missing == []
    assert WINDOW_ROOT in GUI_TRUTHFULNESS_FILES
    for relative in GUI_TRUTHFULNESS_FILES:
        assert (ROOT / relative).exists(), f"{relative} is gated and is not there"


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
