"""
Verification and Reporting Module - Calibrate Pro

Provides comprehensive verification and report generation:
- ColorChecker verification (24/140-patch)
- Grayscale ramp verification (21-step)
- Gamut volume and coverage analysis
- Professional PDF/HTML/JSON report generation

Usage:
    from calibrate_pro.verification import (
        # ColorChecker
        ColorCheckerVerifier, ColorCheckerResult, PatchMeasurement,
        VerificationGrade, ColorCheckerType,
        # Grayscale
        GrayscaleVerifier, GrayscaleResult, GrayscalePatch,
        GrayscaleGrade, GammaType,
        # Gamut
        GamutAnalyzer, GamutAnalysisResult, GamutCoverage,
        GamutGrade, ColorSpace,
        # Reports
        ReportGenerator, ReportConfig, ReportFormat,
        ReportMetadata, VerificationSummary,
        create_verification_summary,
    )

    # Verify ColorChecker
    verifier = ColorCheckerVerifier()
    result = verifier.verify(measured_lab_values)

    # Generate report
    summary = create_verification_summary(colorchecker=result)
    generator = ReportGenerator()
    generator.generate(summary, metadata)
"""

# =============================================================================
# ColorChecker Verification
# =============================================================================

from calibrate_pro.verification.colorchecker import (
    COLORCHECKER_CATEGORIES,
    # Reference data
    COLORCHECKER_CLASSIC_D50,
    COLORCHECKER_CLASSIC_NAMES,
    COLORCHECKER_CLASSIC_ORDER,
    CategoryAnalysis,
    ColorCheckerResult,
    ColorCheckerType,
    # Main classes
    ColorCheckerVerifier,
    PatchMeasurement,
    # Enums
    VerificationGrade,
    calculate_delta_components,
    # Functions
    delta_e_1976,
    grade_from_delta_e,
    lab_to_lch,
)
from calibrate_pro.verification.colorchecker import (
    # Test utilities
    create_test_measurements as create_cc_test_measurements,
)
from calibrate_pro.verification.colorchecker import (
    delta_e_2000 as cc_delta_e_2000,
)
from calibrate_pro.verification.colorchecker import (
    grade_to_string as cc_grade_to_string,
)
from calibrate_pro.verification.colorchecker import (
    print_verification_summary as print_cc_summary,
)
from calibrate_pro.verification.colorchecker import (
    xyz_to_lab as cc_xyz_to_lab,
)

# =============================================================================
# Gamut Volume Analysis
# =============================================================================
from calibrate_pro.verification.gamut_volume import (
    # Reference data
    COLORSPACE_PRIMARIES,
    ColorSpace,
    GamutAnalysisResult,
    # Main classes
    GamutAnalyzer,
    GamutBoundary,
    GamutCoverage,
    # Enums
    GamutGrade,
    GamutPrimary,
    OutOfGamutAnalysis,
    calculate_gamut_area_uv,
    calculate_gamut_area_xy,
    calculate_gamut_coverage,
    calculate_gamut_exceeds,
    calculate_gamut_volume_lab,
    calculate_gamut_volume_ratio,
    # Geometry functions
    calculate_triangle_area,
    calculate_triangle_intersection_area,
    # Test utilities
    create_test_primaries,
    # Volume functions
    generate_gamut_samples,
    # Grade functions
    grade_from_coverage,
    point_in_triangle,
    print_gamut_summary,
    rgb_to_xyz,
    uv_to_xy,
    # Conversion functions
    xy_to_uv,
    xy_to_xyz,
)
from calibrate_pro.verification.gamut_volume import (
    grade_to_string as gv_grade_to_string,
)
from calibrate_pro.verification.gamut_volume import (
    xyz_to_lab as gv_xyz_to_lab,
)

# =============================================================================
# Grayscale Verification
# =============================================================================
from calibrate_pro.verification.grayscale import (
    GammaType,
    # Enums
    GrayscaleGrade,
    GrayscalePatch,
    GrayscaleRegionAnalysis,
    GrayscaleResult,
    # Main classes
    GrayscaleVerifier,
    calculate_gamma_at_level,
    cct_to_uv,
    delta_uv,
    gamma_bt1886,
    gamma_l_star,
    # EOTF functions
    gamma_power_law,
    gamma_srgb,
    # Test utilities
    generate_grayscale_levels,
    # Grade functions
    grade_from_grayscale,
    # CCT functions
    xy_to_cct,
    xyz_to_uv,
    xyz_to_xy,
)
from calibrate_pro.verification.grayscale import (
    create_test_measurements as create_gs_test_measurements,
)
from calibrate_pro.verification.grayscale import (
    delta_e_2000 as gs_delta_e_2000,
)
from calibrate_pro.verification.grayscale import (
    grade_to_string as gs_grade_to_string,
)
from calibrate_pro.verification.grayscale import (
    print_grayscale_summary as print_gs_summary,
)
from calibrate_pro.verification.grayscale import (
    # Conversion
    xyz_to_lab as gs_xyz_to_lab,
)

# =============================================================================
# Report Generation
# =============================================================================
from calibrate_pro.verification.reports import (
    # Color definitions
    REPORT_COLORS,
    # ReportLab availability flag
    REPORTLAB_AVAILABLE,
    ReportConfig,
    # Enums
    ReportFormat,
    # Main classes
    ReportGenerator,
    ReportMetadata,
    ReportType,
    VerificationSummary,
    create_verification_summary,
    # Utility functions
    generate_recommendations,
)

# =============================================================================
# Convenience aliases
# =============================================================================

# Common Delta E function
delta_e_2000 = cc_delta_e_2000

# Common xyz_to_lab function
xyz_to_lab = cc_xyz_to_lab


# Common grade_to_string (returns verification grade string)
def grade_to_string(grade) -> str:
    """Convert any verification grade to string."""
    if isinstance(grade, VerificationGrade):
        return cc_grade_to_string(grade)
    elif isinstance(grade, GrayscaleGrade):
        return gs_grade_to_string(grade)
    elif isinstance(grade, GamutGrade):
        return gv_grade_to_string(grade)
    else:
        return str(grade)


# =============================================================================
# Public API
# =============================================================================

__all__ = [
    # -------------------------------------------------------------------------
    # ColorChecker Verification
    # -------------------------------------------------------------------------
    "ColorCheckerVerifier",
    "ColorCheckerResult",
    "PatchMeasurement",
    "CategoryAnalysis",
    "VerificationGrade",
    "ColorCheckerType",
    "COLORCHECKER_CLASSIC_D50",
    "COLORCHECKER_CLASSIC_ORDER",
    "COLORCHECKER_CLASSIC_NAMES",
    "COLORCHECKER_CATEGORIES",
    "delta_e_1976",
    "cc_delta_e_2000",
    "calculate_delta_components",
    "grade_from_delta_e",
    "cc_grade_to_string",
    "lab_to_lch",
    "cc_xyz_to_lab",
    "create_cc_test_measurements",
    "print_cc_summary",
    # -------------------------------------------------------------------------
    # Grayscale Verification
    # -------------------------------------------------------------------------
    "GrayscaleVerifier",
    "GrayscaleResult",
    "GrayscalePatch",
    "GrayscaleRegionAnalysis",
    "GrayscaleGrade",
    "GammaType",
    "gamma_power_law",
    "gamma_srgb",
    "gamma_bt1886",
    "gamma_l_star",
    "calculate_gamma_at_level",
    "xy_to_cct",
    "cct_to_uv",
    "xyz_to_xy",
    "xyz_to_uv",
    "delta_uv",
    "grade_from_grayscale",
    "gs_grade_to_string",
    "gs_xyz_to_lab",
    "gs_delta_e_2000",
    "generate_grayscale_levels",
    "create_gs_test_measurements",
    "print_gs_summary",
    # -------------------------------------------------------------------------
    # Gamut Volume Analysis
    # -------------------------------------------------------------------------
    "GamutAnalyzer",
    "GamutAnalysisResult",
    "GamutCoverage",
    "GamutBoundary",
    "GamutPrimary",
    "OutOfGamutAnalysis",
    "GamutGrade",
    "ColorSpace",
    "COLORSPACE_PRIMARIES",
    "xy_to_uv",
    "uv_to_xy",
    "xy_to_xyz",
    "gv_xyz_to_lab",
    "rgb_to_xyz",
    "calculate_triangle_area",
    "calculate_gamut_area_xy",
    "calculate_gamut_area_uv",
    "point_in_triangle",
    "calculate_triangle_intersection_area",
    "calculate_gamut_coverage",
    "calculate_gamut_exceeds",
    "generate_gamut_samples",
    "calculate_gamut_volume_lab",
    "calculate_gamut_volume_ratio",
    "grade_from_coverage",
    "gv_grade_to_string",
    "create_test_primaries",
    "print_gamut_summary",
    # -------------------------------------------------------------------------
    # Report Generation
    # -------------------------------------------------------------------------
    "ReportGenerator",
    "VerificationSummary",
    "ReportMetadata",
    "ReportConfig",
    "ReportFormat",
    "ReportType",
    "REPORT_COLORS",
    "generate_recommendations",
    "create_verification_summary",
    "REPORTLAB_AVAILABLE",
    # -------------------------------------------------------------------------
    # Common/Convenience
    # -------------------------------------------------------------------------
    "delta_e_2000",
    "xyz_to_lab",
    "grade_to_string",
]
