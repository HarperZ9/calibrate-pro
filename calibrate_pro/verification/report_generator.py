"""
Calibration Report Generator - Calibrate Pro

Generates self-contained HTML calibration reports with inline SVG diagrams.
No external CSS/JS dependencies required.

Reports include:
- CIE 1931 chromaticity diagram with gamut triangles
- Calibration results summary
- ColorChecker patch results table
- Per-channel gamma curves
- White point information
"""

import math
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from calibrate_pro.core.colorchecker import COLORCHECKER_PATCHES
from calibrate_pro.verification.provenance import EvidenceKind, MetricValue

# Type imports for documentation; runtime access via duck typing
# from calibrate_pro.sensorless.auto_calibration import AutoCalibrationResult
# from calibrate_pro.panels.database import PanelCharacterization


_PERFORMANCE_METRIC_UNITS = {
    "delta_e": "dE2000",
    "delta_e_avg": "dE2000",
    "delta_e_max": "dE2000",
    "cam16_delta_e_avg": "dE CAM16-UCS",
    "peak_luminance": "nits",
    "gamut_coverage_srgb": "percent",
    "gamut_coverage_p3": "percent",
    "gamut_coverage_bt2020": "percent",
}
_PERFORMANCE_METRIC_KEYS = frozenset(_PERFORMANCE_METRIC_UNITS)


def _not_measured_metric(key: str, *, unit: str | None = None) -> MetricValue:
    return MetricValue(None, unit or _PERFORMANCE_METRIC_UNITS.get(key, ""), EvidenceKind.NOT_MEASURED)


def _serialized_metric(value: object, *, key: str) -> dict[str, object]:
    """Return a validated serialized metric without inventing evidence."""
    if isinstance(value, MetricValue):
        return value.to_dict()
    if isinstance(value, Mapping):
        required = {"value", "unit", "evidence", "source"}
        if set(value) >= required:
            raw_value = value["value"]
            if raw_value is not None and (isinstance(raw_value, bool) or not isinstance(raw_value, (int, float))):
                raise TypeError(f"performance metric {key!r} value must be a finite number or None")
            unit = value["unit"]
            if not isinstance(unit, str) or not unit.strip():
                raise TypeError(f"performance metric {key!r} unit must be a non-empty string")
            raw_evidence = value["evidence"]
            try:
                evidence = EvidenceKind(raw_evidence)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"performance metric {key!r} has invalid evidence") from exc
            source = value["source"]
            if source is not None and not isinstance(source, str):
                raise TypeError(f"performance metric {key!r} source must be a string or None")
            metric = MetricValue(
                None if raw_value is None else float(raw_value),
                unit,
                evidence,
                source,
            )
            return metric.to_dict()
    raise ValueError(f"performance metric {key!r} must be a MetricValue")


def _metric_from_serialized(value: object, *, key: str) -> MetricValue:
    serialized = _serialized_metric(value, key=key)
    return MetricValue(
        serialized["value"],  # type: ignore[arg-type]
        str(serialized["unit"]),
        EvidenceKind(str(serialized["evidence"])),
        serialized["source"],  # type: ignore[arg-type]
    )


def _metric_html(metric: MetricValue, *, decimals: int = 4) -> str:
    text = _html_escape(metric.display_text(decimals))
    if metric.source:
        text += f'<div class="metric-source">Source: {_html_escape(metric.source)}</div>'
    return text


def build_report_payload(result: object) -> dict[str, object]:
    """Build the evidence-bearing schema consumed by report serializers.

    Bare performance numbers are rejected at this boundary.  Callers must
    explicitly identify whether each observation was measured, estimated,
    simulated, replayed, or not measured.
    """
    if isinstance(result, Mapping):
        raw = dict(result)
    else:
        serializer = getattr(result, "to_dict", None)
        if not callable(serializer):
            raise TypeError("report result must be a mapping or expose to_dict()")
        raw = dict(serializer())

    nested_metrics = raw.get("metrics")
    candidates: dict[str, object] = {}
    if isinstance(nested_metrics, Mapping):
        candidates.update(nested_metrics)
    for key in _PERFORMANCE_METRIC_KEYS:
        if key in raw:
            candidates[key] = raw[key]
    if "delta_e_predicted" in raw and "delta_e" not in candidates:
        candidates["delta_e"] = raw["delta_e_predicted"]

    metrics = {key: _not_measured_metric(key).to_dict() for key in sorted(_PERFORMANCE_METRIC_KEYS)}
    metrics.update({key: _serialized_metric(value, key=key) for key, value in sorted(candidates.items())})
    receipts = sorted(
        {
            str(metric["source"])
            for metric in metrics.values()
            if metric.get("source") is not None and str(metric["source"]).strip()
        }
    )
    mode = raw.get("mode", "unknown")
    if hasattr(mode, "value"):
        mode = mode.value
    generated_at = raw.get("generated_at") or raw.get("timestamp") or datetime.now(timezone.utc).isoformat()
    if hasattr(generated_at, "isoformat"):
        generated_at = generated_at.isoformat()
    return {
        "schema_version": 1,
        "mode": str(mode),
        "metrics": metrics,
        "source_receipts": receipts,
        "generated_at": str(generated_at),
    }


# =============================================================================
# CIE 1931 Spectral Locus Data
# =============================================================================

# Standard CIE 1931 xy chromaticity coordinates for the spectral locus
# Key wavelength points from 380nm to 700nm
SPECTRAL_LOCUS_XY = [
    (0.1741, 0.0050),  # 380nm
    (0.1740, 0.0050),  # 385nm
    (0.1738, 0.0049),  # 390nm
    (0.1736, 0.0049),  # 395nm
    (0.1733, 0.0048),  # 400nm
    (0.1726, 0.0048),  # 405nm
    (0.1714, 0.0051),  # 410nm
    (0.1689, 0.0069),  # 415nm
    (0.1644, 0.0109),  # 420nm
    (0.1566, 0.0177),  # 425nm
    (0.1440, 0.0297),  # 430nm
    (0.1241, 0.0578),  # 435nm
    (0.0913, 0.1327),  # 440nm
    (0.0687, 0.2007),  # 445nm
    (0.0454, 0.2950),  # 450nm
    (0.0235, 0.4127),  # 455nm
    (0.0082, 0.5384),  # 460nm
    (0.0039, 0.6548),  # 465nm
    (0.0139, 0.7502),  # 470nm
    (0.0389, 0.8120),  # 475nm
    (0.0743, 0.8338),  # 480nm
    (0.1142, 0.8262),  # 485nm
    (0.1547, 0.8059),  # 490nm
    (0.1929, 0.7816),  # 495nm
    (0.2296, 0.7543),  # 500nm
    (0.2658, 0.7243),  # 505nm
    (0.3016, 0.6923),  # 510nm
    (0.3373, 0.6589),  # 515nm
    (0.3731, 0.6245),  # 520nm
    (0.4087, 0.5896),  # 525nm
    (0.4441, 0.5547),  # 530nm
    (0.4788, 0.5202),  # 535nm
    (0.5125, 0.4866),  # 540nm
    (0.5448, 0.4544),  # 545nm
    (0.5752, 0.4242),  # 550nm
    (0.6029, 0.3965),  # 555nm
    (0.6270, 0.3725),  # 560nm
    (0.6482, 0.3514),  # 565nm
    (0.6658, 0.3340),  # 570nm
    (0.6801, 0.3197),  # 575nm
    (0.6915, 0.3083),  # 580nm
    (0.7006, 0.2993),  # 585nm
    (0.7079, 0.2920),  # 590nm
    (0.7140, 0.2859),  # 595nm
    (0.7190, 0.2809),  # 600nm
    (0.7230, 0.2770),  # 605nm
    (0.7260, 0.2740),  # 610nm
    (0.7283, 0.2717),  # 615nm
    (0.7300, 0.2700),  # 620nm
    (0.7311, 0.2689),  # 625nm
    (0.7320, 0.2680),  # 630nm
    (0.7327, 0.2673),  # 635nm
    (0.7334, 0.2666),  # 640nm
    (0.7340, 0.2660),  # 645nm
    (0.7344, 0.2656),  # 650nm
    (0.7346, 0.2654),  # 655nm
    (0.7347, 0.2653),  # 660nm
    (0.7347, 0.2653),  # 665nm
    (0.7347, 0.2653),  # 670nm
    (0.7347, 0.2653),  # 675nm
    (0.7347, 0.2653),  # 680nm
    (0.7347, 0.2653),  # 685nm
    (0.7347, 0.2653),  # 690nm
    (0.7347, 0.2653),  # 695nm
    (0.7347, 0.2653),  # 700nm
]

# sRGB primaries in CIE xy
SRGB_RED = (0.6400, 0.3300)
SRGB_GREEN = (0.3000, 0.6000)
SRGB_BLUE = (0.1500, 0.0600)
D65_WHITE = (0.3127, 0.3290)

# The chart is defined once, in calibrate_pro.core.colorchecker, because a
# patch's reference Lab and the signal that drives a display to it are derived
# from each other. Copies of the pair had drifted apart on ten patches, which
# graded a display reproducing sRGB exactly at 2.27 dE2000 average.
COLORCHECKER_SRGB = {patch.name: patch.srgb for patch in COLORCHECKER_PATCHES}


# =============================================================================
# CCT Calculation
# =============================================================================


def _xy_to_cct(x: float, y: float) -> float:
    """
    Approximate correlated color temperature from CIE xy chromaticity.

    Uses McCamy's approximation (accurate for 2000K-12500K).
    """
    if y == 0:
        return 0.0
    n = (x - 0.3320) / (0.1858 - y)
    cct = 449.0 * n**3 + 3525.0 * n**2 + 6823.3 * n + 5520.33
    return max(0.0, cct)


# =============================================================================
# Lab to sRGB approximation (for predicted colors in report)
# =============================================================================


def _lab_to_approx_srgb(lab: tuple[float, float, float]) -> tuple[float, float, float]:
    """
    Convert CIE Lab (D50) to approximate sRGB values for display in the report.

    This is a simplified conversion suitable for visual representation.
    """
    L, a, b = lab

    # Lab to XYZ (D50 illuminant)
    fy = (L + 16.0) / 116.0
    fx = a / 500.0 + fy
    fz = fy - b / 200.0

    epsilon = 0.008856
    kappa = 903.3

    # D50 reference white
    xr = 0.9642
    yr = 1.0000
    zr = 0.8251

    if fx**3 > epsilon:
        x_val = fx**3
    else:
        x_val = (116.0 * fx - 16.0) / kappa

    if kappa * epsilon < L:
        y_val = fy**3
    else:
        y_val = L / kappa

    if fz**3 > epsilon:
        z_val = fz**3
    else:
        z_val = (116.0 * fz - 16.0) / kappa

    X = x_val * xr
    Y = y_val * yr
    Z = z_val * zr

    # Simple Bradford adaptation D50 -> D65
    # Using a simplified linear adaptation
    X65 = X * 0.9555766 + Y * (-0.0230393) + Z * 0.0631636
    Y65 = X * (-0.0282895) + Y * 1.0099416 + Z * 0.0210077
    Z65 = X * 0.0122982 + Y * (-0.0204830) + Z * 1.3299098

    # XYZ to linear sRGB
    r_lin = 3.2404542 * X65 - 1.5371385 * Y65 - 0.4985314 * Z65
    g_lin = -0.9692660 * X65 + 1.8760108 * Y65 + 0.0415560 * Z65
    b_lin = 0.0556434 * X65 - 0.2040259 * Y65 + 1.0572252 * Z65

    # Gamma compress (sRGB)
    def gamma_compress(v: float) -> float:
        v = max(0.0, min(1.0, v))
        if v <= 0.0031308:
            return 12.92 * v
        return 1.055 * (v ** (1.0 / 2.4)) - 0.055

    return (gamma_compress(r_lin), gamma_compress(g_lin), gamma_compress(b_lin))


# =============================================================================
# HTML Report Styling
# =============================================================================

REPORT_CSS = """
body {
    background-color: #1a1a2e;
    color: #e0e0e0;
    font-family: 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
    margin: 0;
    padding: 20px;
    line-height: 1.6;
}
.report-container {
    max-width: 960px;
    margin: 0 auto;
    background-color: #16213e;
    border-radius: 12px;
    padding: 40px;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
}
.report-header {
    text-align: center;
    border-bottom: 2px solid #0f3460;
    padding-bottom: 24px;
    margin-bottom: 32px;
}
.report-header h1 {
    color: #e94560;
    font-size: 28px;
    margin: 0 0 8px 0;
    font-weight: 600;
    letter-spacing: 0.5px;
}
.report-header .subtitle {
    color: #a0a0b8;
    font-size: 14px;
    margin: 4px 0;
}
.report-header .display-name {
    color: #00d2ff;
    font-size: 20px;
    margin: 12px 0 4px 0;
    font-weight: 500;
}
.section {
    margin-bottom: 36px;
}
.section h2 {
    color: #e94560;
    font-size: 20px;
    border-bottom: 1px solid #0f3460;
    padding-bottom: 8px;
    margin-bottom: 16px;
    font-weight: 500;
}
.section h3 {
    color: #00d2ff;
    font-size: 16px;
    margin: 16px 0 8px 0;
    font-weight: 500;
}
.summary-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
}
.summary-card {
    background-color: #1a1a2e;
    border: 1px solid #0f3460;
    border-radius: 8px;
    padding: 16px;
}
.summary-card .label {
    color: #a0a0b8;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-bottom: 4px;
}
.summary-card .value {
    color: #ffffff;
    font-size: 18px;
    font-weight: 500;
}
.metric-source {
    color: #7f8ca8;
    font-size: 10px;
    font-weight: 400;
    margin-top: 4px;
    overflow-wrap: anywhere;
}
.summary-card .value.grade-ref { color: #00e676; }
.summary-card .value.grade-pro { color: #00d2ff; }
.summary-card .value.grade-exc { color: #69f0ae; }
.summary-card .value.grade-good { color: #ffd740; }
.summary-card .value.grade-acc { color: #ff9100; }
.diagram-container {
    display: flex;
    justify-content: center;
    margin: 16px 0;
}
table.patch-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
}
table.patch-table th {
    background-color: #0f3460;
    color: #e0e0e0;
    padding: 10px 12px;
    text-align: left;
    font-weight: 500;
    text-transform: uppercase;
    font-size: 11px;
    letter-spacing: 0.5px;
}
table.patch-table td {
    padding: 8px 12px;
    border-bottom: 1px solid #1a1a2e;
    vertical-align: middle;
}
table.patch-table tr:nth-child(even) {
    background-color: rgba(15, 52, 96, 0.3);
}
table.patch-table tr:hover {
    background-color: rgba(15, 52, 96, 0.5);
}
.color-swatch {
    display: inline-block;
    width: 18px;
    height: 18px;
    border-radius: 3px;
    vertical-align: middle;
    margin-right: 6px;
    border: 1px solid rgba(255, 255, 255, 0.2);
}
.status-pass {
    color: #00e676;
    font-weight: 600;
}
.status-warn {
    color: #ffd740;
    font-weight: 600;
}
.status-fail {
    color: #ff5252;
    font-weight: 600;
}
.whitepoint-grid {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 12px;
}
.wp-card {
    background-color: #1a1a2e;
    border: 1px solid #0f3460;
    border-radius: 8px;
    padding: 14px;
    text-align: center;
}
.wp-card .wp-label {
    color: #a0a0b8;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-bottom: 6px;
}
.wp-card .wp-value {
    color: #ffffff;
    font-size: 15px;
    font-weight: 500;
}
.wp-card .wp-sub {
    color: #a0a0b8;
    font-size: 12px;
    margin-top: 2px;
}
.ddc-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
    margin-top: 8px;
}
.ddc-table th {
    background-color: #0f3460;
    color: #e0e0e0;
    padding: 8px 12px;
    text-align: left;
    font-weight: 500;
    font-size: 11px;
    text-transform: uppercase;
}
.ddc-table td {
    padding: 6px 12px;
    border-bottom: 1px solid #1a1a2e;
}
.footer {
    text-align: center;
    color: #555;
    font-size: 11px;
    margin-top: 32px;
    padding-top: 16px;
    border-top: 1px solid #0f3460;
}
"""


# =============================================================================
# SVG Diagram Generators
# =============================================================================


def _generate_cie_diagram_svg(
    panel_red: tuple[float, float],
    panel_green: tuple[float, float],
    panel_blue: tuple[float, float],
    panel_white: tuple[float, float],
) -> str:
    """
    Generate an inline SVG of the CIE 1931 chromaticity diagram.

    Shows the spectral locus, sRGB gamut triangle, panel gamut triangle,
    and D65 white point.

    Args:
        panel_red: Panel red primary (x, y)
        panel_green: Panel green primary (x, y)
        panel_blue: Panel blue primary (x, y)
        panel_white: Panel white point (x, y)

    Returns:
        SVG markup string
    """
    svg_w, svg_h = 400, 400
    # Mapping: CIE xy (0-0.8, 0-0.9) -> SVG coordinates
    margin = 40
    plot_w = svg_w - 2 * margin
    plot_h = svg_h - 2 * margin

    def xy_to_svg(x: float, y: float) -> tuple[float, float]:
        sx = margin + (x / 0.8) * plot_w
        sy = svg_h - margin - (y / 0.9) * plot_h
        return (sx, sy)

    lines: list[str] = []
    lines.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{svg_w}" height="{svg_h}" '
        f'viewBox="0 0 {svg_w} {svg_h}" '
        f'style="background-color:#111827;border-radius:8px;">'
    )

    # Background grid
    for i in range(9):
        gx = margin + (i / 8.0) * plot_w
        lines.append(
            f'<line x1="{gx:.1f}" y1="{margin}" x2="{gx:.1f}" '
            f'y2="{svg_h - margin}" stroke="#1f2937" stroke-width="0.5"/>'
        )
    for i in range(10):
        gy = margin + (i / 9.0) * plot_h
        lines.append(
            f'<line x1="{margin}" y1="{gy:.1f}" x2="{svg_w - margin}" '
            f'y2="{gy:.1f}" stroke="#1f2937" stroke-width="0.5"/>'
        )

    # Axis labels
    lines.append(
        f'<text x="{svg_w / 2}" y="{svg_h - 6}" '
        f'text-anchor="middle" fill="#6b7280" font-size="11" '
        f'font-family="sans-serif">x</text>'
    )
    lines.append(
        f'<text x="12" y="{svg_h / 2}" '
        f'text-anchor="middle" fill="#6b7280" font-size="11" '
        f'font-family="sans-serif" transform="rotate(-90,12,{svg_h / 2})">y</text>'
    )

    # Axis tick labels
    for i in range(9):
        val = i * 0.1
        sx, _ = xy_to_svg(val, 0)
        lines.append(
            f'<text x="{sx:.1f}" y="{svg_h - margin + 14}" '
            f'text-anchor="middle" fill="#4b5563" font-size="9" '
            f'font-family="sans-serif">{val:.1f}</text>'
        )
    for i in range(1, 10):
        val = i * 0.1
        _, sy = xy_to_svg(0, val)
        lines.append(
            f'<text x="{margin - 6}" y="{sy + 3:.1f}" '
            f'text-anchor="end" fill="#4b5563" font-size="9" '
            f'font-family="sans-serif">{val:.1f}</text>'
        )

    # Spectral locus (filled with gradient-like appearance)
    locus_points = []
    for x, y in SPECTRAL_LOCUS_XY:
        sx, sy = xy_to_svg(x, y)
        locus_points.append(f"{sx:.1f},{sy:.1f}")
    # Close the locus with the purple line
    locus_path = " ".join(locus_points)
    lines.append(f'<polygon points="{locus_path}" fill="rgba(40,50,70,0.5)" stroke="#4b5563" stroke-width="1.5"/>')

    # sRGB gamut triangle (red)
    sr = xy_to_svg(*SRGB_RED)
    sg = xy_to_svg(*SRGB_GREEN)
    sb = xy_to_svg(*SRGB_BLUE)
    lines.append(
        f'<polygon points="{sr[0]:.1f},{sr[1]:.1f} '
        f"{sg[0]:.1f},{sg[1]:.1f} "
        f'{sb[0]:.1f},{sb[1]:.1f}" '
        f'fill="none" stroke="#ef4444" stroke-width="2" '
        f'stroke-dasharray="6,3" opacity="0.9"/>'
    )

    # Panel gamut triangle (blue)
    pr = xy_to_svg(*panel_red)
    pg = xy_to_svg(*panel_green)
    pb = xy_to_svg(*panel_blue)
    lines.append(
        f'<polygon points="{pr[0]:.1f},{pr[1]:.1f} '
        f"{pg[0]:.1f},{pg[1]:.1f} "
        f'{pb[0]:.1f},{pb[1]:.1f}" '
        f'fill="rgba(59,130,246,0.1)" stroke="#3b82f6" stroke-width="2" '
        f'opacity="0.9"/>'
    )

    # D65 white point marker
    wp = xy_to_svg(*D65_WHITE)
    lines.append(f'<circle cx="{wp[0]:.1f}" cy="{wp[1]:.1f}" r="5" fill="none" stroke="#ffffff" stroke-width="2"/>')
    lines.append(f'<circle cx="{wp[0]:.1f}" cy="{wp[1]:.1f}" r="2" fill="#ffffff"/>')
    lines.append(
        f'<text x="{wp[0] + 10:.1f}" y="{wp[1] - 6:.1f}" '
        f'fill="#ffffff" font-size="10" font-family="sans-serif">D65</text>'
    )

    # Panel white point marker (if different from D65)
    pw = xy_to_svg(*panel_white)
    dist = math.sqrt((panel_white[0] - D65_WHITE[0]) ** 2 + (panel_white[1] - D65_WHITE[1]) ** 2)
    if dist > 0.003:
        lines.append(
            f'<circle cx="{pw[0]:.1f}" cy="{pw[1]:.1f}" r="4" fill="none" stroke="#00d2ff" stroke-width="1.5"/>'
        )
        lines.append(f'<circle cx="{pw[0]:.1f}" cy="{pw[1]:.1f}" r="1.5" fill="#00d2ff"/>')

    # Legend
    legend_y = margin + 8
    lines.append(
        f'<line x1="{svg_w - margin - 100}" y1="{legend_y}" '
        f'x2="{svg_w - margin - 80}" y2="{legend_y}" '
        f'stroke="#ef4444" stroke-width="2" stroke-dasharray="6,3"/>'
    )
    lines.append(
        f'<text x="{svg_w - margin - 76}" y="{legend_y + 4}" '
        f'fill="#ef4444" font-size="10" font-family="sans-serif">sRGB</text>'
    )
    legend_y += 18
    lines.append(
        f'<line x1="{svg_w - margin - 100}" y1="{legend_y}" '
        f'x2="{svg_w - margin - 80}" y2="{legend_y}" '
        f'stroke="#3b82f6" stroke-width="2"/>'
    )
    lines.append(
        f'<text x="{svg_w - margin - 76}" y="{legend_y + 4}" '
        f'fill="#3b82f6" font-size="10" font-family="sans-serif">Panel</text>'
    )
    legend_y += 18
    lines.append(f'<circle cx="{svg_w - margin - 90}" cy="{legend_y}" r="3" fill="#ffffff"/>')
    lines.append(
        f'<text x="{svg_w - margin - 76}" y="{legend_y + 4}" '
        f'fill="#ffffff" font-size="10" font-family="sans-serif">D65</text>'
    )

    # Title
    lines.append(
        f'<text x="{svg_w / 2}" y="{margin - 14}" '
        f'text-anchor="middle" fill="#9ca3af" font-size="12" '
        f'font-family="sans-serif" font-weight="500">'
        f"CIE 1931 Chromaticity Diagram</text>"
    )

    lines.append("</svg>")
    return "\n".join(lines)


def _generate_gamma_curves_svg(
    gamma_r: float,
    gamma_g: float,
    gamma_b: float,
    target_gamma: float = 2.2,
) -> str:
    """
    Generate an inline SVG showing per-channel gamma curves.

    Args:
        gamma_r: Red channel native gamma
        gamma_g: Green channel native gamma
        gamma_b: Blue channel native gamma
        target_gamma: Target gamma (default 2.2)

    Returns:
        SVG markup string
    """
    svg_w, svg_h = 400, 200
    margin_l, margin_r, margin_t, margin_b = 40, 20, 30, 30
    plot_w = svg_w - margin_l - margin_r
    plot_h = svg_h - margin_t - margin_b

    def val_to_svg(inp: float, out: float) -> tuple[float, float]:
        sx = margin_l + inp * plot_w
        sy = svg_h - margin_b - out * plot_h
        return (sx, sy)

    lines: list[str] = []
    lines.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{svg_w}" height="{svg_h}" '
        f'viewBox="0 0 {svg_w} {svg_h}" '
        f'style="background-color:#111827;border-radius:8px;">'
    )

    # Grid
    for i in range(11):
        t = i / 10.0
        sx, _ = val_to_svg(t, 0)
        _, sy = val_to_svg(0, t)
        lines.append(
            f'<line x1="{sx:.1f}" y1="{margin_t}" '
            f'x2="{sx:.1f}" y2="{svg_h - margin_b}" '
            f'stroke="#1f2937" stroke-width="0.5"/>'
        )
        lines.append(
            f'<line x1="{margin_l}" y1="{sy:.1f}" '
            f'x2="{svg_w - margin_r}" y2="{sy:.1f}" '
            f'stroke="#1f2937" stroke-width="0.5"/>'
        )

    # Axis labels
    lines.append(
        f'<text x="{margin_l + plot_w / 2}" y="{svg_h - 4}" '
        f'text-anchor="middle" fill="#6b7280" font-size="10" '
        f'font-family="sans-serif">Input</text>'
    )
    lines.append(
        f'<text x="10" y="{margin_t + plot_h / 2}" '
        f'text-anchor="middle" fill="#6b7280" font-size="10" '
        f'font-family="sans-serif" '
        f'transform="rotate(-90,10,{margin_t + plot_h / 2})">Output</text>'
    )

    # Tick labels
    for i in range(0, 11, 2):
        t = i / 10.0
        sx, _ = val_to_svg(t, 0)
        lines.append(
            f'<text x="{sx:.1f}" y="{svg_h - margin_b + 14}" '
            f'text-anchor="middle" fill="#4b5563" font-size="8" '
            f'font-family="sans-serif">{t:.1f}</text>'
        )
        _, sy = val_to_svg(0, t)
        lines.append(
            f'<text x="{margin_l - 4}" y="{sy + 3:.1f}" '
            f'text-anchor="end" fill="#4b5563" font-size="8" '
            f'font-family="sans-serif">{t:.1f}</text>'
        )

    # Generate curve paths
    num_points = 100

    def make_path(gamma: float, color: str, width: str = "1.5") -> str:
        points = []
        for i in range(num_points + 1):
            t = i / num_points
            out = t**gamma
            sx, sy = val_to_svg(t, out)
            points.append(f"{sx:.1f},{sy:.1f}")
        path_data = "M" + " L".join(points)
        return f'<path d="{path_data}" fill="none" stroke="{color}" stroke-width="{width}" opacity="0.9"/>'

    # Target gamma (gray reference)
    lines.append(make_path(target_gamma, "#6b7280", "1.5"))

    # Channel curves
    lines.append(make_path(gamma_r, "#ef4444", "1.5"))
    lines.append(make_path(gamma_g, "#22c55e", "1.5"))
    lines.append(make_path(gamma_b, "#3b82f6", "1.5"))

    # Legend
    legend_x = margin_l + 10
    legend_y = margin_t + 10

    legend_items = [
        (f"Target ({target_gamma:.1f})", "#6b7280"),
        (f"Red ({gamma_r:.4f})", "#ef4444"),
        (f"Green ({gamma_g:.4f})", "#22c55e"),
        (f"Blue ({gamma_b:.4f})", "#3b82f6"),
    ]
    for label, color in legend_items:
        lines.append(
            f'<line x1="{legend_x}" y1="{legend_y}" '
            f'x2="{legend_x + 16}" y2="{legend_y}" '
            f'stroke="{color}" stroke-width="2"/>'
        )
        lines.append(
            f'<text x="{legend_x + 20}" y="{legend_y + 4}" '
            f'fill="{color}" font-size="9" font-family="sans-serif">'
            f"{label}</text>"
        )
        legend_y += 14

    # Title
    lines.append(
        f'<text x="{svg_w / 2}" y="{margin_t - 10}" '
        f'text-anchor="middle" fill="#9ca3af" font-size="12" '
        f'font-family="sans-serif" font-weight="500">'
        f"Per-Channel Gamma Curves</text>"
    )

    lines.append("</svg>")
    return "\n".join(lines)


# =============================================================================
# HTML Section Builders
# =============================================================================


def _build_header(
    display_name: str,
    panel_info: str,
    report_date: str,
) -> str:
    """Build the report header section."""
    return f"""
<div class="report-header">
    <h1>Calibrate Pro Calibration Report</h1>
    <div class="display-name">{_html_escape(display_name)}</div>
    <div class="subtitle">{_html_escape(report_date)}</div>
    <div class="subtitle">{_html_escape(panel_info)}</div>
</div>
"""


def _build_cie_diagram_section(
    panel_red: tuple[float, float],
    panel_green: tuple[float, float],
    panel_blue: tuple[float, float],
    panel_white: tuple[float, float],
) -> str:
    """Build the CIE diagram section."""
    svg = _generate_cie_diagram_svg(panel_red, panel_green, panel_blue, panel_white)
    return f"""
<div class="section">
    <h2>CIE 1931 Chromaticity Diagram</h2>
    <div class="diagram-container">
        {svg}
    </div>
</div>
"""


def _grade_css_class(grade_str: str) -> str:
    """Map grade string to CSS class."""
    lower = grade_str.lower()
    if "reference" in lower:
        return "grade-ref"
    if "professional" in lower:
        return "grade-pro"
    if "excellent" in lower:
        return "grade-exc"
    if "good" in lower:
        return "grade-good"
    return "grade-acc"


def _build_summary_section(
    panel_name: str,
    panel_type: str,
    manufacturer: str,
    delta_e_avg: MetricValue,
    delta_e_max: MetricValue,
    grade: str,
    lut_method: str,
    ddc_changes: dict[str, Any],
    gamut_coverage: dict[str, MetricValue] | None = None,
    cam16_delta_e_avg: MetricValue | None = None,
    color_volume: dict[str, MetricValue] | None = None,
) -> str:
    """Build the calibration results summary section."""
    grade_class = _grade_css_class(grade)

    # Format LUT method
    method_display = {
        "dwm_lut": "DWM 3D LUT (system-wide)",
        "vcgt_from_3dlut": "VCGT from 3D LUT (1D approximation)",
        "vcgt_direct": "VCGT from panel characterization",
        "gamma_ramp": "Direct gamma ramp (Windows API)",
    }
    lut_display = method_display.get(lut_method, lut_method or "None")

    # DDC/CI changes summary
    ddc_html = ""
    if ddc_changes:
        ddc_status = ddc_changes.get("status", "No DDC/CI changes")
        ddc_items = []
        for key, val in ddc_changes.items():
            if key in ("status", "original_settings", "error"):
                continue
            if isinstance(val, (tuple, list)) and len(val) == 2:
                ddc_items.append(f"<tr><td>{_html_escape(key)}</td><td>{val[0]} &rarr; {val[1]}</td></tr>")
        if ddc_items:
            ddc_html = f"""
    <h3>DDC/CI Adjustments</h3>
    <p style="color:#a0a0b8;font-size:13px;">{_html_escape(ddc_status)}</p>
    <table class="ddc-table">
        <tr><th>Setting</th><th>Change</th></tr>
        {"".join(ddc_items)}
    </table>
"""
        else:
            ddc_html = (
                f'<h3>DDC/CI Adjustments</h3><p style="color:#a0a0b8;font-size:13px;">{_html_escape(ddc_status)}</p>'
            )

    return f"""
<div class="section">
    <h2>Calibration Results Summary</h2>
    <div class="summary-grid">
        <div class="summary-card">
            <div class="label">Panel</div>
            <div class="value">{_html_escape(panel_name)}</div>
        </div>
        <div class="summary-card">
            <div class="label">Panel Type</div>
            <div class="value">{_html_escape(panel_type)}</div>
        </div>
        <div class="summary-card">
            <div class="label">Manufacturer</div>
            <div class="value">{_html_escape(manufacturer)}</div>
        </div>
        <div class="summary-card">
            <div class="label">Average Delta E (CIEDE2000)</div>
            <div class="value">{_metric_html(delta_e_avg)}</div>
        </div>
        <div class="summary-card">
            <div class="label">Maximum Delta E</div>
            <div class="value">{_metric_html(delta_e_max)}</div>
        </div>
        <div class="summary-card">
            <div class="label">Quality Grade</div>
            <div class="value {grade_class}">{_html_escape(grade)}</div>
        </div>
        <div class="summary-card">
            <div class="label">CAM16-UCS Delta E</div>
            <div class="value">{_metric_html(cam16_delta_e_avg or _not_measured_metric("cam16_delta_e_avg"))}</div>
        </div>
        <div class="summary-card">
            <div class="label">LUT Application Method</div>
            <div class="value" style="font-size:14px;">{_html_escape(lut_display)}</div>
        </div>
    </div>
    {_build_gamut_coverage_html(gamut_coverage, color_volume)}
    {ddc_html}
</div>
"""


def _build_gamut_coverage_html(
    coverage: dict[str, MetricValue] | None,
    color_volume: dict[str, MetricValue] | None = None,
) -> str:
    """Build gamut coverage and color volume section HTML."""
    if not coverage:
        return ""

    srgb = coverage.get("srgb_pct", _not_measured_metric("gamut_coverage_srgb"))
    p3 = coverage.get("dci_p3_pct", _not_measured_metric("gamut_coverage_p3"))
    bt2020 = coverage.get("bt2020_pct", _not_measured_metric("gamut_coverage_bt2020"))

    def bar(metric: MetricValue, color: str) -> str:
        if metric.value is None:
            return '<div style="background:#0d1b2a;border-radius:4px;height:20px;width:100%;margin:4px 0;"></div>'
        pct = metric.value
        w = max(0, min(100, pct))
        return (
            f'<div style="background:#0d1b2a;border-radius:4px;height:20px;width:100%;margin:4px 0;">'
            f'<div style="background:{color};border-radius:4px;height:100%;width:{w}%;'
            f'min-width:2px;transition:width 0.3s;"></div></div>'
        )

    html = f"""
    <h3>Gamut Coverage (2D Area)</h3>
    <div style="display:grid;grid-template-columns:100px 1fr 60px;gap:6px;align-items:center;max-width:500px;">
        <span style="color:#a0a0b8;">sRGB</span>
        {bar(srgb, "#4cc9f0")}
        <span style="color:#e0e0e8;font-weight:bold;">{_metric_html(srgb, decimals=1)}</span>

        <span style="color:#a0a0b8;">DCI-P3</span>
        {bar(p3, "#f72585")}
        <span style="color:#e0e0e8;font-weight:bold;">{_metric_html(p3, decimals=1)}</span>

        <span style="color:#a0a0b8;">BT.2020</span>
        {bar(bt2020, "#7209b7")}
        <span style="color:#e0e0e8;font-weight:bold;">{_metric_html(bt2020, decimals=1)}</span>
    </div>
"""

    # 3D Color Volume section
    if color_volume:
        v_srgb = color_volume.get("srgb_pct", _not_measured_metric("color_volume_srgb", unit="percent"))
        v_p3 = color_volume.get("p3_pct", _not_measured_metric("color_volume_p3", unit="percent"))
        v_bt2020 = color_volume.get(
            "bt2020_pct",
            _not_measured_metric("color_volume_bt2020", unit="percent"),
        )

        html += f"""
    <h3 style="margin-top:16px;">Color Volume (3D)</h3>
    <p style="color:#6b7280;font-size:12px;margin:4px 0 8px;">
        Accounts for luminance-dependent gamut changes (OLED rolloff at high brightness).
    </p>
    <div style="display:grid;grid-template-columns:100px 1fr 60px;gap:6px;align-items:center;max-width:500px;">
        <span style="color:#a0a0b8;">sRGB</span>
        {bar(v_srgb, "#4cc9f0")}
        <span style="color:#e0e0e8;font-weight:bold;">{_metric_html(v_srgb, decimals=1)}</span>

        <span style="color:#a0a0b8;">DCI-P3</span>
        {bar(v_p3, "#f72585")}
        <span style="color:#e0e0e8;font-weight:bold;">{_metric_html(v_p3, decimals=1)}</span>

        <span style="color:#a0a0b8;">BT.2020</span>
        {bar(v_bt2020, "#7209b7")}
        <span style="color:#e0e0e8;font-weight:bold;">{_metric_html(v_bt2020, decimals=1)}</span>
    </div>
"""

        # Per-lightness gamut area chart (inline SVG)
    return html


def _srgb_to_hex(r: float, g: float, b: float) -> str:
    """Convert sRGB float (0-1) to hex color string."""
    ri = max(0, min(255, int(round(r * 255))))
    gi = max(0, min(255, int(round(g * 255))))
    bi = max(0, min(255, int(round(b * 255))))
    return f"#{ri:02x}{gi:02x}{bi:02x}"


def _build_patch_table_section(
    patches: list[dict[str, Any]],
) -> str:
    """Build the ColorChecker patch results table."""
    rows: list[str] = []

    for index, patch in enumerate(patches):
        name = patch["name"]
        raw_delta_e = patch.get("delta_e", _not_measured_metric(f"patch_{index}_delta_e", unit="dE2000"))
        delta_e = _metric_from_serialized(raw_delta_e, key=f"patches[{index}].delta_e")

        # Get reference sRGB
        ref_srgb = COLORCHECKER_SRGB.get(name, (0.5, 0.5, 0.5))

        # Compute predicted sRGB from displayed Lab
        displayed_lab = patch.get("displayed_lab", (50.0, 0.0, 0.0))
        pred_srgb = _lab_to_approx_srgb(displayed_lab)

        ref_hex = _srgb_to_hex(*ref_srgb)
        pred_hex = _srgb_to_hex(*pred_srgb)

        ref_str = f"{int(round(ref_srgb[0] * 255))}, {int(round(ref_srgb[1] * 255))}, {int(round(ref_srgb[2] * 255))}"
        pred_str = (
            f"{int(round(pred_srgb[0] * 255))}, {int(round(pred_srgb[1] * 255))}, {int(round(pred_srgb[2] * 255))}"
        )

        # Status
        if delta_e.value is None:
            status_class = ""
            status_text = "NOT MEASURED"
        elif delta_e.value < 1.0:
            status_class = "status-pass"
            status_text = "PASS"
        elif delta_e.value < 2.0:
            status_class = "status-warn"
            status_text = "WARN"
        else:
            status_class = "status-fail"
            status_text = "FAIL"

        rows.append(f"""
        <tr>
            <td>{_html_escape(name)}</td>
            <td>
                <span class="color-swatch" style="background-color:{ref_hex};"></span>
                {ref_str}
            </td>
            <td>
                <span class="color-swatch" style="background-color:{pred_hex};"></span>
                {pred_str}
            </td>
            <td>{_metric_html(delta_e)}</td>
            <td class="{status_class}">{status_text}</td>
        </tr>""")

    return f"""
<div class="section">
    <h2>ColorChecker Patch Results</h2>
    <table class="patch-table">
        <thead>
            <tr>
                <th>Patch Name</th>
                <th>Reference sRGB</th>
                <th>Predicted sRGB</th>
                <th>Delta E</th>
                <th>Status</th>
            </tr>
        </thead>
        <tbody>
            {"".join(rows)}
        </tbody>
    </table>
</div>
"""


def _build_gamma_section(
    gamma_r: float,
    gamma_g: float,
    gamma_b: float,
) -> str:
    """Build the gamma curves section."""
    svg = _generate_gamma_curves_svg(gamma_r, gamma_g, gamma_b)
    return f"""
<div class="section">
    <h2>Per-Channel Gamma Curves</h2>
    <div class="diagram-container">
        {svg}
    </div>
</div>
"""


def _build_whitepoint_section(
    native_wp: tuple[float, float],
    target_wp: tuple[float, float],
) -> str:
    """Build the white point information section."""
    native_cct = _xy_to_cct(native_wp[0], native_wp[1])
    target_cct = _xy_to_cct(target_wp[0], target_wp[1])

    return f"""
<div class="section">
    <h2>White Point Information</h2>
    <div class="whitepoint-grid">
        <div class="wp-card">
            <div class="wp-label">Native White Point</div>
            <div class="wp-value">x={native_wp[0]:.4f}, y={native_wp[1]:.4f}</div>
            <div class="wp-sub">{native_cct:.0f} K</div>
        </div>
        <div class="wp-card">
            <div class="wp-label">Target White Point</div>
            <div class="wp-value">x={target_wp[0]:.4f}, y={target_wp[1]:.4f}</div>
            <div class="wp-sub">{target_cct:.0f} K</div>
        </div>
        <div class="wp-card">
            <div class="wp-label">CCT Difference</div>
            <div class="wp-value">{abs(target_cct - native_cct):.0f} K</div>
            <div class="wp-sub">&Delta;x={abs(target_wp[0] - native_wp[0]):.4f}, &Delta;y={abs(target_wp[1] - native_wp[1]):.4f}</div>
        </div>
    </div>
</div>
"""


# =============================================================================
# HTML Escaping
# =============================================================================


def _html_escape(text: str) -> str:
    """Escape HTML special characters."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )


def _build_source_receipts_section(receipts: list[str]) -> str:
    if not receipts:
        return """
<div class="section">
    <h2>Evidence Sources</h2>
    <p>Not measured</p>
</div>
"""
    items = "".join(f"<li>{_html_escape(receipt)}</li>" for receipt in receipts)
    return f"""
<div class="section">
    <h2>Evidence Sources</h2>
    <ul>{items}</ul>
</div>
"""


# =============================================================================
# Main Report Generator
# =============================================================================


def generate_calibration_report(
    result: Any,
    panel: Any,
    verification: dict[str, Any],
    output_path: Any,
) -> Path:
    """
    Generate a self-contained HTML calibration report.

    The report includes CIE 1931 chromaticity diagram, calibration summary,
    ColorChecker patch results, per-channel gamma curves, and white point
    information. All diagrams are inline SVG with no external dependencies.

    Args:
        result: AutoCalibrationResult from auto_calibration.py.
            Expected attributes:
                - display_name (str)
                - panel_matched (str)
                - panel_type (str)
                - lut_application_method (str)
                - ddc_changes_made (dict)
        panel: PanelCharacterization from panels/database.py.
            Expected attributes:
                - manufacturer (str)
                - model_pattern (str)
                - panel_type (str)
                - native_primaries.red/green/blue/white (.x, .y)
                - gamma_red/green/blue (.gamma)
        verification: Evidence-bearing verification mapping with keys:
                - patches (list of dicts whose delta_e is a MetricValue)
                - delta_e_avg (MetricValue)
                - delta_e_max (MetricValue)
                - grade (str)
        output_path: Path to save the HTML file.

    Returns:
        Path to the generated HTML file.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Extract panel data
    primaries = panel.native_primaries
    panel_red = (primaries.red.x, primaries.red.y)
    panel_green = (primaries.green.x, primaries.green.y)
    panel_blue = (primaries.blue.x, primaries.blue.y)
    panel_white = (primaries.white.x, primaries.white.y)

    gamma_r = panel.gamma_red.gamma
    gamma_g = panel.gamma_green.gamma
    gamma_b = panel.gamma_blue.gamma

    # Extract result data
    display_name = getattr(result, "display_name", "Unknown Display")
    panel_matched = getattr(result, "panel_matched", "")
    panel_type = getattr(result, "panel_type", panel.panel_type)
    lut_method = getattr(result, "lut_application_method", "")
    ddc_changes = getattr(result, "ddc_changes_made", {})

    manufacturer = panel.manufacturer
    model_name = panel_matched or (manufacturer + " " + panel.model_pattern.split("|")[0])

    result_payload = build_report_payload(result)
    result_metrics = cast(Mapping[str, object], result_payload["metrics"])

    def result_metric(key: str, *fallback_keys: str) -> MetricValue:
        for candidate_key in (key, *fallback_keys):
            candidate = _metric_from_serialized(result_metrics[candidate_key], key=candidate_key)
            if candidate.value is not None:
                return candidate
        return _metric_from_serialized(result_metrics[key], key=key)

    def verification_metric(key: str, fallback: MetricValue) -> MetricValue:
        if key not in verification:
            return fallback
        return _metric_from_serialized(verification[key], key=key)

    # Verification data
    patches = verification.get("patches", [])
    if not isinstance(patches, list):
        raise TypeError("verification patches must be a list")
    delta_e_avg = verification_metric("delta_e_avg", result_metric("delta_e_avg", "delta_e"))
    delta_e_max = verification_metric("delta_e_max", result_metric("delta_e_max"))
    grade = verification.get("grade", "Not measured")

    # Report date
    report_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    panel_info = f"{manufacturer} | {panel_type} | {model_name}"

    # Build HTML sections
    header = _build_header(display_name, panel_info, report_date)
    cie_section = _build_cie_diagram_section(panel_red, panel_green, panel_blue, panel_white)
    raw_coverage = verification.get("gamut_coverage")
    if raw_coverage is not None and not isinstance(raw_coverage, Mapping):
        raise TypeError("gamut_coverage must be an evidence-bearing mapping")
    coverage_aliases = {
        "srgb_pct": "gamut_coverage_srgb",
        "dci_p3_pct": "gamut_coverage_p3",
        "bt2020_pct": "gamut_coverage_bt2020",
    }
    gamut_coverage: dict[str, MetricValue] = {}
    for nested_key, metric_key in coverage_aliases.items():
        fallback = result_metric(metric_key)
        if isinstance(raw_coverage, Mapping) and nested_key in raw_coverage:
            fallback = _metric_from_serialized(raw_coverage[nested_key], key=f"gamut_coverage.{nested_key}")
        gamut_coverage[nested_key] = fallback

    raw_color_volume = verification.get("color_volume")
    if raw_color_volume is not None and not isinstance(raw_color_volume, Mapping):
        raise TypeError("color_volume must be an evidence-bearing mapping")
    color_volume: dict[str, MetricValue] | None = None
    if isinstance(raw_color_volume, Mapping):
        color_volume = {}
        for nested_key in ("srgb_pct", "p3_pct", "bt2020_pct"):
            value = raw_color_volume.get(
                nested_key,
                _not_measured_metric(f"color_volume_{nested_key}", unit="percent"),
            )
            color_volume[nested_key] = _metric_from_serialized(value, key=f"color_volume.{nested_key}")
    cam16_de_avg = verification_metric(
        "cam16_delta_e_avg",
        result_metric("cam16_delta_e_avg"),
    )

    summary_section = _build_summary_section(
        model_name,
        panel_type,
        manufacturer,
        delta_e_avg,
        delta_e_max,
        grade,
        lut_method,
        ddc_changes,
        gamut_coverage=gamut_coverage,
        cam16_delta_e_avg=cam16_de_avg,
        color_volume=color_volume,
    )
    patch_section = _build_patch_table_section(patches)
    gamma_section = _build_gamma_section(gamma_r, gamma_g, gamma_b)
    wp_section = _build_whitepoint_section(panel_white, D65_WHITE)
    receipts = {
        metric.source for metric in [delta_e_avg, delta_e_max, cam16_de_avg, *gamut_coverage.values()] if metric.source
    }
    if color_volume:
        receipts.update(metric.source for metric in color_volume.values() if metric.source)
    for index, patch in enumerate(patches):
        if not isinstance(patch, Mapping):
            raise TypeError("verification patch entries must be mappings")
        patch_metric = _metric_from_serialized(
            patch.get("delta_e", _not_measured_metric(f"patch_{index}_delta_e", unit="dE2000")),
            key=f"patches[{index}].delta_e",
        )
        if patch_metric.source:
            receipts.add(patch_metric.source)
    receipt_section = _build_source_receipts_section(sorted(receipts))

    # Assemble full HTML
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Calibrate Pro - Calibration Report - {_html_escape(display_name)}</title>
    <style>
{REPORT_CSS}
    </style>
</head>
<body>
    <div class="report-container">
        {header}
        {cie_section}
        {summary_section}
        {patch_section}
        {gamma_section}
        {wp_section}
        {receipt_section}
        <div class="footer">
            Generated by Calibrate Pro &mdash; Build Universe &mdash; {_html_escape(report_date)}
        </div>
    </div>
</body>
</html>
"""

    output_path.write_text(html, encoding="utf-8")
    return output_path
