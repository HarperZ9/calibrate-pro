"""
Custom Widgets for Calibrate Pro GUI

Provides specialized visualization widgets for color calibration:
- CIE chromaticity diagram
- Gamma/EOTF curves
- Delta E bar charts
- Color swatches
"""

# =============================================================================
# CIE Diagram
# =============================================================================

from calibrate_pro.gui.widgets.cie_diagram import (
    GAMUTS,
    SPECTRAL_LOCUS,
    WHITE_POINTS,
    CIEDiagramWidget,
    MeasuredPoint,
)

# =============================================================================
# Color Swatches
# =============================================================================
from calibrate_pro.gui.widgets.color_swatch import (
    ColorGrid,
    ColorInfoPanel,
    ColorSwatch,
    ComparisonSwatch,
    delta_e_2000,
    rgb_to_lab,
    rgb_to_xyz,
    xyz_to_lab,
)

# =============================================================================
# Delta E Charts
# =============================================================================
from calibrate_pro.gui.widgets.delta_e_chart import (
    DeltaEBarChart,
    DeltaEMeasurement,
    DeltaEQuality,
    DeltaEStatsPanel,
    classify_delta_e,
    get_delta_e_color,
)

# =============================================================================
# Gamma Curves
# =============================================================================
from calibrate_pro.gui.widgets.gamma_curve import (
    CurveData,
    GammaCurveWidget,
    GammaInfoPanel,
    bt1886_eotf,
    l_star_eotf,
    power_law_eotf,
    srgb_eotf,
    srgb_oetf,
)

# =============================================================================
# Public API
# =============================================================================

__all__ = [
    # CIE Diagram
    "CIEDiagramWidget",
    "MeasuredPoint",
    "SPECTRAL_LOCUS",
    "WHITE_POINTS",
    "GAMUTS",
    # Gamma Curves
    "GammaCurveWidget",
    "GammaInfoPanel",
    "CurveData",
    "srgb_eotf",
    "srgb_oetf",
    "bt1886_eotf",
    "power_law_eotf",
    "l_star_eotf",
    # Delta E Charts
    "DeltaEBarChart",
    "DeltaEStatsPanel",
    "DeltaEMeasurement",
    "DeltaEQuality",
    "classify_delta_e",
    "get_delta_e_color",
    # Color Swatches
    "ColorSwatch",
    "ComparisonSwatch",
    "ColorInfoPanel",
    "ColorGrid",
    "rgb_to_xyz",
    "xyz_to_lab",
    "rgb_to_lab",
    "delta_e_2000",
]
