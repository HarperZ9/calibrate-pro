"""
Professional GUI - Calibrate Pro PyQt6 Interface

Comprehensive display calibration interface featuring:
- Dark theme optimized for calibration environment
- Step-by-step calibration wizard
- Multi-monitor support with visual layout
- Real-time measurement display
- Fullscreen test patterns
- CIE chromaticity diagrams
- Gamma curve visualization
- Delta E charts and statistics
- 3D LUT preview and comparison
- Professional verification reports

Usage:
    from calibrate_pro.gui import (
        # Main application
        run_application, MainWindow,
        # Wizard
        CalibrationWizard, CalibrationConfig,
        # Display selection
        DisplaySelector, DisplayInfo,
        # Patterns
        PatternWindow, PatternConfig, PatternType,
        # Visualization
        CIEDiagramWidget, GammaCurveWidget, DeltaEBarChart,
        # LUT preview
        LUTPreviewWidget, LUT3D,
        # Reports
        ReportViewer, CalibrationReport,
    )

    # Run the application
    run_application()
"""

# Main Application

# Calibration Wizard
from calibrate_pro.gui.calibration_wizard import (
    CalibrationConfig,
    CalibrationMode,
    CalibrationModeStep,
    CalibrationWizard,
    DisplaySelectionStep,
    GammaTarget,
    GamutTarget,
    MeasurementStep,
    ProfileGenerationStep,
    TargetSettingsStep,
    VerificationStep,
    WhitepointTarget,
    WizardStep,
)
from calibrate_pro.gui.dialogs import ConsentDialog, SimulatedMeasurementWindow

# Display Selection
from calibrate_pro.gui.display_selector import (
    CalibrationStatus,
    DisplayInfo,
    DisplayInfoPanel,
    DisplayLayoutPreview,
    DisplayMonitorWidget,
    DisplaySelector,
    DisplayTechnology,
)
from calibrate_pro.gui.icons import IconFactory

# LUT Preview
from calibrate_pro.gui.lut_preview import (
    LUT3D,
    BeforeAfterView,
    LUTCubeView,
    LUTPreviewWidget,
    LUTSliceView,
)
from calibrate_pro.gui.main_window import MainWindow, run_application

# Measurement View
from calibrate_pro.gui.measurement_view import (
    ColorPatchDisplay,
    DeltaEDisplay,
    Measurement,
    MeasurementHistoryTable,
    MeasurementView,
    ValuesPanel,
)
from calibrate_pro.gui.pages.calibration_page import CalibrationPage
from calibrate_pro.gui.pages.color_control_page import SoftwareColorControlPage
from calibrate_pro.gui.pages.dashboard_page import DashboardPage
from calibrate_pro.gui.pages.ddc_control_page import DDCControlPage
from calibrate_pro.gui.pages.profiles_page import ProfilesPage
from calibrate_pro.gui.pages.settings_page import SettingsPage
from calibrate_pro.gui.pages.vcgt_tools_page import VCGTToolsPage
from calibrate_pro.gui.pages.verification_page import VerificationPage

# Pattern Window
from calibrate_pro.gui.pattern_window import (
    PatternCanvas,
    PatternConfig,
    PatternRenderer,
    PatternSequencer,
    PatternType,
    PatternWindow,
)

# Report Viewer
from calibrate_pro.gui.report_viewer import (
    CalibrationReport,
    ColorCheckerResult,
    GamutCoverage,
    GrayscaleResult,
    ReportSummaryPanel,
    ReportViewer,
    SummaryCard,
)
from calibrate_pro.gui.theme import APP_NAME, APP_ORGANIZATION, APP_VERSION, COLORS, DARK_STYLESHEET

# Visualization Widgets
from calibrate_pro.gui.widgets import (
    GAMUTS,
    SPECTRAL_LOCUS,
    WHITE_POINTS,
    # CIE Diagram
    CIEDiagramWidget,
    ColorGrid,
    ColorInfoPanel,
    # Color Swatches
    ColorSwatch,
    ComparisonSwatch,
    CurveData,
    # Delta E Charts
    DeltaEBarChart,
    DeltaEMeasurement,
    DeltaEQuality,
    DeltaEStatsPanel,
    # Gamma Curves
    GammaCurveWidget,
    GammaInfoPanel,
    MeasuredPoint,
    bt1886_eotf,
    classify_delta_e,
    delta_e_2000,
    get_delta_e_color,
    l_star_eotf,
    power_law_eotf,
    rgb_to_lab,
    rgb_to_xyz,
    srgb_eotf,
    srgb_oetf,
    xyz_to_lab,
)
from calibrate_pro.gui.workers import CalibrationWorker, ColorManagementStatus

# Public API

__all__ = [
    # Main Application
    "MainWindow",
    "run_application",
    "APP_NAME",
    "APP_VERSION",
    "APP_ORGANIZATION",
    "COLORS",
    "DARK_STYLESHEET",
    "IconFactory",
    "ColorManagementStatus",
    "ConsentDialog",
    "CalibrationWorker",
    "SimulatedMeasurementWindow",
    "DashboardPage",
    "CalibrationPage",
    "VerificationPage",
    "ProfilesPage",
    "VCGTToolsPage",
    "SoftwareColorControlPage",
    "DDCControlPage",
    "SettingsPage",
    # Calibration Wizard
    "CalibrationWizard",
    "CalibrationConfig",
    "CalibrationMode",
    "WhitepointTarget",
    "GammaTarget",
    "GamutTarget",
    "WizardStep",
    "DisplaySelectionStep",
    "TargetSettingsStep",
    "CalibrationModeStep",
    "MeasurementStep",
    "ProfileGenerationStep",
    "VerificationStep",
    # Display Selection
    "DisplaySelector",
    "DisplayLayoutPreview",
    "DisplayMonitorWidget",
    "DisplayInfoPanel",
    "DisplayInfo",
    "DisplayTechnology",
    "CalibrationStatus",
    # Pattern Window
    "PatternWindow",
    "PatternCanvas",
    "PatternRenderer",
    "PatternSequencer",
    "PatternType",
    "PatternConfig",
    # Measurement View
    "MeasurementView",
    "Measurement",
    "ColorPatchDisplay",
    "DeltaEDisplay",
    "ValuesPanel",
    "MeasurementHistoryTable",
    # LUT Preview
    "LUTPreviewWidget",
    "LUTCubeView",
    "LUTSliceView",
    "BeforeAfterView",
    "LUT3D",
    # Report Viewer
    "ReportViewer",
    "ReportSummaryPanel",
    "SummaryCard",
    "CalibrationReport",
    "GrayscaleResult",
    "ColorCheckerResult",
    "GamutCoverage",
    # CIE Diagram Widget
    "CIEDiagramWidget",
    "MeasuredPoint",
    "SPECTRAL_LOCUS",
    "WHITE_POINTS",
    "GAMUTS",
    # Gamma Curve Widget
    "GammaCurveWidget",
    "GammaInfoPanel",
    "CurveData",
    "srgb_eotf",
    "srgb_oetf",
    "bt1886_eotf",
    "power_law_eotf",
    "l_star_eotf",
    # Delta E Chart Widget
    "DeltaEBarChart",
    "DeltaEStatsPanel",
    "DeltaEMeasurement",
    "DeltaEQuality",
    "classify_delta_e",
    "get_delta_e_color",
    # Color Swatch Widgets
    "ColorSwatch",
    "ComparisonSwatch",
    "ColorInfoPanel",
    "ColorGrid",
    "rgb_to_xyz",
    "xyz_to_lab",
    "rgb_to_lab",
    "delta_e_2000",
]
