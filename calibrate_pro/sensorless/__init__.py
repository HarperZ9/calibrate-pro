"""
Calibrate Pro - Sensorless Calibration Module

Sensorless Calibration Engine for achieving Delta E < 1.0 calibration
without hardware colorimeters.

This module provides:
- Sensorless panel-database calibration
- Test pattern generation
- Visual matching algorithms for user-guided calibration
"""

# =============================================================================
# Sensorless Calibration Engine
# =============================================================================
# =============================================================================
# Auto-Calibration Engine (Zero-Input Calibration)
# =============================================================================
from .auto_calibration import (
    # Main Classes
    AutoCalibrationEngine,
    AutoCalibrationResult,
    # Enums
    CalibrationRisk,
    CalibrationStep,
    CalibrationTarget,
    # Data Classes
    UserConsent,
    auto_calibrate_all,
    generate_consent_warning,
    # Functions
    one_click_calibrate,
)
from .neuralux import (
    COLORCHECKER_CLASSIC,
    ColorPatch,
    NeuralUXEngine,  # Backwards compatibility alias
    SensorlessEngine,
    calibrate_display,
    get_colorchecker_reference,
    verify_display,
)

# =============================================================================
# Pattern Generator
# =============================================================================
from .pattern_generator import (
    # Data Classes
    PatternConfig,
    # Main Classes
    PatternGenerator,
    # Enums
    PatternType,
    TestPattern,
    # Functions
    create_pattern_generator,
)

# =============================================================================
# Visual Matcher
# =============================================================================
from .visual_matcher import (
    AdjustmentType,
    CalibrationAdjustment,
    GrayscaleBalancer,
    # Enums
    MatchingMethod,
    # Data Classes
    MatchResult,
    # Main Classes
    VisualMatcher,
    WhitepointMatcher,
    # Functions
    create_visual_matcher,
)

# =============================================================================
# Module Info
# =============================================================================

__all__ = [
    # Sensorless Calibration Engine
    "SensorlessEngine",
    "NeuralUXEngine",  # Backwards compatibility alias
    "ColorPatch",
    "COLORCHECKER_CLASSIC",
    "get_colorchecker_reference",
    "calibrate_display",
    "verify_display",

    # Pattern Generator
    "PatternType",
    "PatternConfig",
    "TestPattern",
    "PatternGenerator",
    "create_pattern_generator",

    # Visual Matcher
    "MatchingMethod",
    "AdjustmentType",
    "MatchResult",
    "CalibrationAdjustment",
    "VisualMatcher",
    "GrayscaleBalancer",
    "WhitepointMatcher",
    "create_visual_matcher",

    # Auto-Calibration (Zero-Input)
    "CalibrationRisk",
    "CalibrationStep",
    "UserConsent",
    "CalibrationTarget",
    "AutoCalibrationResult",
    "AutoCalibrationEngine",
    "one_click_calibrate",
    "auto_calibrate_all",
    "generate_consent_warning",
]

__version__ = "1.0.0"
