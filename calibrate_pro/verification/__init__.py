"""Verification and reporting, imported when a name is asked for.

This package holds the ColorChecker verifier, the grayscale verifier, the gamut
volume analysis, and the report writers. Touching the package used to import all
four, because every name was re-exported here with an import statement that ran
at package import. The gamut analysis imports scipy, and that costs half a
second. The application layer reaches this package for one dataclass, so every
terminal command paid the half second before it printed a line.

The table below is the surface this package has always had. Each name is paired
with the module it is read from, and that module is imported the first time
something asks for the name.

The module names are written in full on purpose. A packaging gate reads module
names out of module-level tables to work out what a frozen build can reach, and
bare submodule names would drop these four modules from the frozen closure.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

#: Every name this package exports, and where each one is read from.
_EXPORTS: dict[str, tuple[str, str]] = {
    "COLORCHECKER_CATEGORIES": ("calibrate_pro.verification.colorchecker", "COLORCHECKER_CATEGORIES"),
    "COLORCHECKER_CLASSIC_D50": ("calibrate_pro.verification.colorchecker", "COLORCHECKER_CLASSIC_D50"),
    "COLORCHECKER_CLASSIC_NAMES": ("calibrate_pro.verification.colorchecker", "COLORCHECKER_CLASSIC_NAMES"),
    "COLORCHECKER_CLASSIC_ORDER": ("calibrate_pro.verification.colorchecker", "COLORCHECKER_CLASSIC_ORDER"),
    "COLORSPACE_PRIMARIES": ("calibrate_pro.verification.gamut_volume", "COLORSPACE_PRIMARIES"),
    "CategoryAnalysis": ("calibrate_pro.verification.colorchecker", "CategoryAnalysis"),
    "ColorCheckerResult": ("calibrate_pro.verification.colorchecker", "ColorCheckerResult"),
    "ColorCheckerType": ("calibrate_pro.verification.colorchecker", "ColorCheckerType"),
    "ColorCheckerVerifier": ("calibrate_pro.verification.colorchecker", "ColorCheckerVerifier"),
    "ColorSpace": ("calibrate_pro.verification.gamut_volume", "ColorSpace"),
    "GammaType": ("calibrate_pro.verification.grayscale", "GammaType"),
    "GamutAnalysisResult": ("calibrate_pro.verification.gamut_volume", "GamutAnalysisResult"),
    "GamutAnalyzer": ("calibrate_pro.verification.gamut_volume", "GamutAnalyzer"),
    "GamutBoundary": ("calibrate_pro.verification.gamut_volume", "GamutBoundary"),
    "GamutCoverage": ("calibrate_pro.verification.gamut_volume", "GamutCoverage"),
    "GamutGrade": ("calibrate_pro.verification.gamut_volume", "GamutGrade"),
    "GamutPrimary": ("calibrate_pro.verification.gamut_volume", "GamutPrimary"),
    "GrayscaleGrade": ("calibrate_pro.verification.grayscale", "GrayscaleGrade"),
    "GrayscalePatch": ("calibrate_pro.verification.grayscale", "GrayscalePatch"),
    "GrayscaleRegionAnalysis": ("calibrate_pro.verification.grayscale", "GrayscaleRegionAnalysis"),
    "GrayscaleResult": ("calibrate_pro.verification.grayscale", "GrayscaleResult"),
    "GrayscaleVerifier": ("calibrate_pro.verification.grayscale", "GrayscaleVerifier"),
    "OutOfGamutAnalysis": ("calibrate_pro.verification.gamut_volume", "OutOfGamutAnalysis"),
    "PatchMeasurement": ("calibrate_pro.verification.colorchecker", "PatchMeasurement"),
    "REPORTLAB_AVAILABLE": ("calibrate_pro.verification.gamut_volume", "SCIPY_AVAILABLE"),
    "REPORT_COLORS": ("calibrate_pro.verification.reports", "REPORT_COLORS"),
    "ReportConfig": ("calibrate_pro.verification.reports", "ReportConfig"),
    "ReportFormat": ("calibrate_pro.verification.reports", "ReportFormat"),
    "ReportGenerator": ("calibrate_pro.verification.reports", "ReportGenerator"),
    "ReportMetadata": ("calibrate_pro.verification.reports", "ReportMetadata"),
    "ReportType": ("calibrate_pro.verification.reports", "ReportType"),
    "VerificationGrade": ("calibrate_pro.verification.colorchecker", "VerificationGrade"),
    "VerificationSummary": ("calibrate_pro.verification.reports", "VerificationSummary"),
    "calculate_delta_components": ("calibrate_pro.verification.colorchecker", "calculate_delta_components"),
    "calculate_gamma_at_level": ("calibrate_pro.verification.grayscale", "calculate_gamma_at_level"),
    "calculate_gamut_area_uv": ("calibrate_pro.verification.gamut_volume", "calculate_gamut_area_uv"),
    "calculate_gamut_area_xy": ("calibrate_pro.verification.gamut_volume", "calculate_gamut_area_xy"),
    "calculate_gamut_coverage": ("calibrate_pro.verification.gamut_volume", "calculate_gamut_coverage"),
    "calculate_gamut_exceeds": ("calibrate_pro.verification.gamut_volume", "calculate_gamut_exceeds"),
    "calculate_gamut_volume_lab": ("calibrate_pro.verification.gamut_volume", "calculate_gamut_volume_lab"),
    "calculate_gamut_volume_ratio": ("calibrate_pro.verification.gamut_volume", "calculate_gamut_volume_ratio"),
    "calculate_triangle_area": ("calibrate_pro.verification.gamut_volume", "calculate_triangle_area"),
    "calculate_triangle_intersection_area": (
        "calibrate_pro.verification.gamut_volume",
        "calculate_triangle_intersection_area",
    ),
    "cc_delta_e_2000": ("calibrate_pro.verification.colorchecker", "delta_e_2000"),
    "cc_grade_to_string": ("calibrate_pro.verification.colorchecker", "grade_to_string"),
    "cc_xyz_to_lab": ("calibrate_pro.verification.colorchecker", "xyz_to_lab"),
    "cct_to_uv": ("calibrate_pro.verification.grayscale", "cct_to_uv"),
    "create_cc_test_measurements": ("calibrate_pro.verification.colorchecker", "create_test_measurements"),
    "create_gs_test_measurements": ("calibrate_pro.verification.grayscale", "create_test_measurements"),
    "create_test_primaries": ("calibrate_pro.verification.gamut_volume", "create_test_primaries"),
    "create_verification_summary": ("calibrate_pro.verification.reports", "create_verification_summary"),
    "delta_e_1976": ("calibrate_pro.verification.colorchecker", "delta_e_1976"),
    "delta_e_2000": ("calibrate_pro.verification.colorchecker", "delta_e_2000"),
    "delta_uv": ("calibrate_pro.verification.grayscale", "delta_uv"),
    "gamma_bt1886": ("calibrate_pro.verification.grayscale", "gamma_bt1886"),
    "gamma_l_star": ("calibrate_pro.verification.grayscale", "gamma_l_star"),
    "gamma_power_law": ("calibrate_pro.verification.grayscale", "gamma_power_law"),
    "gamma_srgb": ("calibrate_pro.verification.grayscale", "gamma_srgb"),
    "generate_gamut_samples": ("calibrate_pro.verification.gamut_volume", "generate_gamut_samples"),
    "generate_grayscale_levels": ("calibrate_pro.verification.grayscale", "generate_grayscale_levels"),
    "generate_recommendations": ("calibrate_pro.verification.reports", "generate_recommendations"),
    "grade_from_coverage": ("calibrate_pro.verification.gamut_volume", "grade_from_coverage"),
    "grade_from_delta_e": ("calibrate_pro.verification.colorchecker", "grade_from_delta_e"),
    "grade_from_grayscale": ("calibrate_pro.verification.grayscale", "grade_from_grayscale"),
    "gs_delta_e_2000": ("calibrate_pro.verification.grayscale", "delta_e_2000"),
    "gs_grade_to_string": ("calibrate_pro.verification.grayscale", "grade_to_string"),
    "gs_xyz_to_lab": ("calibrate_pro.verification.grayscale", "xyz_to_lab"),
    "gv_grade_to_string": ("calibrate_pro.verification.gamut_volume", "grade_to_string"),
    "gv_xyz_to_lab": ("calibrate_pro.verification.gamut_volume", "xyz_to_lab"),
    "lab_to_lch": ("calibrate_pro.verification.colorchecker", "lab_to_lch"),
    "point_in_triangle": ("calibrate_pro.verification.gamut_volume", "point_in_triangle"),
    "print_cc_summary": ("calibrate_pro.verification.colorchecker", "print_verification_summary"),
    "print_gamut_summary": ("calibrate_pro.verification.gamut_volume", "print_gamut_summary"),
    "print_gs_summary": ("calibrate_pro.verification.grayscale", "print_grayscale_summary"),
    "rgb_to_xyz": ("calibrate_pro.verification.gamut_volume", "rgb_to_xyz"),
    "uv_to_xy": ("calibrate_pro.verification.gamut_volume", "uv_to_xy"),
    "xy_to_cct": ("calibrate_pro.verification.grayscale", "xy_to_cct"),
    "xy_to_uv": ("calibrate_pro.verification.gamut_volume", "xy_to_uv"),
    "xy_to_xyz": ("calibrate_pro.verification.gamut_volume", "xy_to_xyz"),
    "xyz_to_lab": ("calibrate_pro.verification.colorchecker", "xyz_to_lab"),
    "xyz_to_uv": ("calibrate_pro.verification.grayscale", "xyz_to_uv"),
    "xyz_to_xy": ("calibrate_pro.verification.grayscale", "xyz_to_xy"),
}

#: The exported surface, read off the table so the two cannot disagree.
__all__ = sorted([*_EXPORTS, "grade_to_string"])


def __getattr__(name: str) -> Any:
    """Read one exported name, importing the module it lives in to do it."""
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """What this package offers, answered without importing anything to say it."""
    return list(__all__)


def grade_to_string(grade: object) -> str:
    """Word one grade from any of the verifiers, as that verifier words it.

    Each verifier has its own grade type. This reads whichever one it was handed,
    so a caller holding a grade does not have to know which verifier made it.
    """
    from calibrate_pro.verification import colorchecker, gamut_volume, grayscale

    if isinstance(grade, colorchecker.VerificationGrade):
        return colorchecker.grade_to_string(grade)
    if isinstance(grade, grayscale.GrayscaleGrade):
        return grayscale.grade_to_string(grade)
    if isinstance(grade, gamut_volume.GamutGrade):
        return gamut_volume.grade_to_string(grade)
    return str(grade)
