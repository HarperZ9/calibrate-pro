"""Lazy compatibility facade for the Calibrate Pro PySide6 GUI."""

from __future__ import annotations

from importlib import import_module
from typing import Any

from calibrate_pro.qt_runtime import configure_qt_api

configure_qt_api()

_EXPORTS: dict[str, tuple[str, str]] = {
    # Active shell.
    "CalibrateProWindow": ("calibrate_pro.gui.app", "CalibrateProWindow"),
    # Historical main-window API.
    "MainWindow": ("calibrate_pro.gui.main_window", "MainWindow"),
    "run_application": ("calibrate_pro.gui.main_window", "run_application"),
    # Theme and identity.
    "APP_NAME": ("calibrate_pro.gui.theme", "APP_NAME"),
    "APP_ORGANIZATION": ("calibrate_pro.gui.theme", "APP_ORGANIZATION"),
    "APP_VERSION": ("calibrate_pro.gui.theme", "APP_VERSION"),
    "COLORS": ("calibrate_pro.gui.theme", "COLORS"),
    "DARK_STYLESHEET": ("calibrate_pro.gui.theme", "DARK_STYLESHEET"),
    "IconFactory": ("calibrate_pro.gui.icons", "IconFactory"),
    # Calibration wizard.
    "CalibrationConfig": ("calibrate_pro.gui.calibration_wizard", "CalibrationConfig"),
    "CalibrationMode": ("calibrate_pro.gui.calibration_wizard", "CalibrationMode"),
    "CalibrationModeStep": ("calibrate_pro.gui.calibration_wizard", "CalibrationModeStep"),
    "CalibrationWizard": ("calibrate_pro.gui.calibration_wizard", "CalibrationWizard"),
    "DisplaySelectionStep": ("calibrate_pro.gui.calibration_wizard", "DisplaySelectionStep"),
    "GammaTarget": ("calibrate_pro.gui.calibration_wizard", "GammaTarget"),
    "GamutTarget": ("calibrate_pro.gui.calibration_wizard", "GamutTarget"),
    "MeasurementStep": ("calibrate_pro.gui.calibration_wizard", "MeasurementStep"),
    "ProfileGenerationStep": ("calibrate_pro.gui.calibration_wizard", "ProfileGenerationStep"),
    "TargetSettingsStep": ("calibrate_pro.gui.calibration_wizard", "TargetSettingsStep"),
    "VerificationStep": ("calibrate_pro.gui.calibration_wizard", "VerificationStep"),
    "WhitepointTarget": ("calibrate_pro.gui.calibration_wizard", "WhitepointTarget"),
    "WizardStep": ("calibrate_pro.gui.calibration_wizard", "WizardStep"),
    # Dialogs.
    "ConsentDialog": ("calibrate_pro.gui.dialogs", "ConsentDialog"),
    "SimulatedMeasurementWindow": ("calibrate_pro.gui.dialogs", "SimulatedMeasurementWindow"),
    # Display selection.
    "CalibrationStatus": ("calibrate_pro.gui.display_selector", "CalibrationStatus"),
    "DisplayInfo": ("calibrate_pro.gui.display_selector", "DisplayInfo"),
    "DisplayInfoPanel": ("calibrate_pro.gui.display_selector", "DisplayInfoPanel"),
    "DisplayLayoutPreview": ("calibrate_pro.gui.display_selector", "DisplayLayoutPreview"),
    "DisplayMonitorWidget": ("calibrate_pro.gui.display_selector", "DisplayMonitorWidget"),
    "DisplaySelector": ("calibrate_pro.gui.display_selector", "DisplaySelector"),
    "DisplayTechnology": ("calibrate_pro.gui.display_selector", "DisplayTechnology"),
    # Measurement view.
    "ColorPatchDisplay": ("calibrate_pro.gui.measurement_view", "ColorPatchDisplay"),
    "DeltaEDisplay": ("calibrate_pro.gui.measurement_view", "DeltaEDisplay"),
    "Measurement": ("calibrate_pro.gui.measurement_view", "Measurement"),
    "MeasurementHistoryTable": ("calibrate_pro.gui.measurement_view", "MeasurementHistoryTable"),
    "MeasurementView": ("calibrate_pro.gui.measurement_view", "MeasurementView"),
    "ValuesPanel": ("calibrate_pro.gui.measurement_view", "ValuesPanel"),
    # Test-pattern window.
    "PatternCanvas": ("calibrate_pro.gui.pattern_window", "PatternCanvas"),
    "PatternConfig": ("calibrate_pro.gui.pattern_window", "PatternConfig"),
    "PatternRenderer": ("calibrate_pro.gui.pattern_window", "PatternRenderer"),
    "PatternSequencer": ("calibrate_pro.gui.pattern_window", "PatternSequencer"),
    "PatternType": ("calibrate_pro.gui.pattern_window", "PatternType"),
    "PatternWindow": ("calibrate_pro.gui.pattern_window", "PatternWindow"),
    # LUT preview.
    "BeforeAfterView": ("calibrate_pro.gui.lut_preview", "BeforeAfterView"),
    "LUT3D": ("calibrate_pro.gui.lut_preview", "LUT3D"),
    "LUTCubeView": ("calibrate_pro.gui.lut_preview", "LUTCubeView"),
    "LUTPreviewWidget": ("calibrate_pro.gui.lut_preview", "LUTPreviewWidget"),
    "LUTSliceView": ("calibrate_pro.gui.lut_preview", "LUTSliceView"),
    # Reports.
    "CalibrationReport": ("calibrate_pro.gui.report_viewer", "CalibrationReport"),
    "ColorCheckerResult": ("calibrate_pro.gui.report_viewer", "ColorCheckerResult"),
    "GamutCoverage": ("calibrate_pro.gui.report_viewer", "GamutCoverage"),
    "GrayscaleResult": ("calibrate_pro.gui.report_viewer", "GrayscaleResult"),
    "ReportSummaryPanel": ("calibrate_pro.gui.report_viewer", "ReportSummaryPanel"),
    "ReportViewer": ("calibrate_pro.gui.report_viewer", "ReportViewer"),
    "SummaryCard": ("calibrate_pro.gui.report_viewer", "SummaryCard"),
    # Active pages.
    "CalibrationPage": ("calibrate_pro.gui.pages.calibration_page", "CalibrationPage"),
    "DashboardPage": ("calibrate_pro.gui.pages.dashboard_page", "DashboardPage"),
    "DDCControlPage": ("calibrate_pro.gui.pages.ddc_control_page", "DDCControlPage"),
    "ProfilesPage": ("calibrate_pro.gui.pages.profiles_page", "ProfilesPage"),
    "SettingsPage": ("calibrate_pro.gui.pages.settings_page", "SettingsPage"),
    "SoftwareColorControlPage": (
        "calibrate_pro.gui.pages.color_control_page",
        "SoftwareColorControlPage",
    ),
    "VCGTToolsPage": ("calibrate_pro.gui.pages.vcgt_tools_page", "VCGTToolsPage"),
    "VerificationPage": ("calibrate_pro.gui.pages.verification_page", "VerificationPage"),
    # Workers.
    "CalibrationWorker": ("calibrate_pro.gui.workers", "CalibrationWorker"),
    "ColorManagementStatus": ("calibrate_pro.gui.workers", "ColorManagementStatus"),
    # Visualization and color helpers.
    "CIEDiagramWidget": ("calibrate_pro.gui.widgets", "CIEDiagramWidget"),
    "ColorGrid": ("calibrate_pro.gui.widgets", "ColorGrid"),
    "ColorInfoPanel": ("calibrate_pro.gui.widgets", "ColorInfoPanel"),
    "ColorSwatch": ("calibrate_pro.gui.widgets", "ColorSwatch"),
    "ComparisonSwatch": ("calibrate_pro.gui.widgets", "ComparisonSwatch"),
    "CurveData": ("calibrate_pro.gui.widgets", "CurveData"),
    "DeltaEBarChart": ("calibrate_pro.gui.widgets", "DeltaEBarChart"),
    "DeltaEMeasurement": ("calibrate_pro.gui.widgets", "DeltaEMeasurement"),
    "DeltaEQuality": ("calibrate_pro.gui.widgets", "DeltaEQuality"),
    "DeltaEStatsPanel": ("calibrate_pro.gui.widgets", "DeltaEStatsPanel"),
    "GAMUTS": ("calibrate_pro.gui.widgets", "GAMUTS"),
    "GammaCurveWidget": ("calibrate_pro.gui.widgets", "GammaCurveWidget"),
    "GammaInfoPanel": ("calibrate_pro.gui.widgets", "GammaInfoPanel"),
    "MeasuredPoint": ("calibrate_pro.gui.widgets", "MeasuredPoint"),
    "SPECTRAL_LOCUS": ("calibrate_pro.gui.widgets", "SPECTRAL_LOCUS"),
    "WHITE_POINTS": ("calibrate_pro.gui.widgets", "WHITE_POINTS"),
    "bt1886_eotf": ("calibrate_pro.gui.widgets", "bt1886_eotf"),
    "classify_delta_e": ("calibrate_pro.gui.widgets", "classify_delta_e"),
    "delta_e_2000": ("calibrate_pro.gui.widgets", "delta_e_2000"),
    "get_delta_e_color": ("calibrate_pro.gui.widgets", "get_delta_e_color"),
    "l_star_eotf": ("calibrate_pro.gui.widgets", "l_star_eotf"),
    "power_law_eotf": ("calibrate_pro.gui.widgets", "power_law_eotf"),
    "rgb_to_lab": ("calibrate_pro.gui.widgets", "rgb_to_lab"),
    "rgb_to_xyz": ("calibrate_pro.gui.widgets", "rgb_to_xyz"),
    "srgb_eotf": ("calibrate_pro.gui.widgets", "srgb_eotf"),
    "srgb_oetf": ("calibrate_pro.gui.widgets", "srgb_oetf"),
    "xyz_to_lab": ("calibrate_pro.gui.widgets", "xyz_to_lab"),
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    """Resolve one compatibility export without importing the historical GUI graph."""
    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}", name=name) from None
    configure_qt_api()
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Expose lazy names to IDEs and interactive help."""
    return sorted({*globals(), *__all__})
