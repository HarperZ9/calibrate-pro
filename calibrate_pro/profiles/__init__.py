"""
ICC Profile System - Professional Profile Generation and Management

Provides comprehensive ICC profile capabilities:
- ICC v4.4 profile generation with full tag support
- Video Card Gamma Table (VCGT) handling
- Windows HDR MHC2 tag support
- System profile installation and management

Usage:
    from calibrate_pro.profiles import (
        # Profile creation
        ICCProfile, create_calibration_profile,
        # VCGT
        VCGTTable, GammaRampController,
        # HDR
        MHC2Tag, create_hdr_profile_with_mhc2,
        # Installation
        install_profile, associate_profile_with_display,
        quick_calibrate_display
    )
"""

# =============================================================================
# ICC v4.4 Profile Generation
# =============================================================================

from calibrate_pro.profiles.icc_v4 import (
    CLUT,
    # Constants
    ICC_MAGIC,
    ICC_VERSION_4_4,
    ColorSpace,
    CurveData,
    DateTimeNumber,
    # Main profile class
    ICCProfile,
    MeasurementData,
    MultiLocalizedString,
    ParametricCurve,
    Platform,
    # Enums
    ProfileClass,
    RenderingIntent,
    TagSignature,
    # Data structures
    XYZNumber,
    # Helper functions
    create_calibration_profile,
    create_lut_profile,
)

# =============================================================================
# Windows HDR MHC2 Tag
# =============================================================================
from calibrate_pro.profiles.mhc2 import (
    DEFAULT_MAX_LUMINANCE,
    DEFAULT_MIN_LUMINANCE,
    DEFAULT_SDR_WHITE_LEVEL,
    # Constants
    MHC2_TAG_SIGNATURE,
    MHC2_VERSION_1,
    MHC2_VERSION_2,
    SDR_WHITE_MAX,
    SDR_WHITE_MIN,
    # Data structures
    MHC2ColorMatrix,
    MHC2Tag,
    MHC2ToneCurve,
    WindowsHDRSettings,
    calculate_hdr_headroom,
    create_hdr_profile_with_mhc2,
    # Profile integration
    extract_mhc2_from_profile,
    # MHC2 ICC profile generation (Phase 2.1)
    generate_mhc2_profile,
    # Helpers
    get_recommended_sdr_white,
    install_mhc2_profile,
)

# =============================================================================
# Profile Installation and Management
# =============================================================================
from calibrate_pro.profiles.profile_installer import (
    ColorProfileType,
    # Display enumeration
    DisplayDevice,
    MonitorInfo,
    ProfileAssociation,
    # Backup and restore
    ProfileBackup,
    # Constants
    ProfileScope,
    # Profile association
    associate_profile_with_display,
    backup_profiles,
    disassociate_profile_from_display,
    enumerate_displays,
    get_associated_profiles,
    get_display_calibration_status,
    get_display_profile,
    get_monitor_info,
    # Profile installation
    get_profile_directory,
    install_profile,
    list_installed_profiles,
    # VCGT loading
    load_profile_vcgt,
    # Convenience functions
    quick_calibrate_display,
    reset_display_gamma,
    restore_profiles,
    uninstall_profile,
)

# =============================================================================
# Video Card Gamma Table (VCGT)
# =============================================================================
from calibrate_pro.profiles.vcgt import (
    GAMMA_RAMP_SIZE,
    VCGT_SIZE_EXTENDED,
    VCGT_SIZE_MAXIMUM,
    # Constants
    VCGT_SIZE_STANDARD,
    # Gamma ramp controller
    GammaRampController,
    # Main VCGT class
    VCGTTable,
    embed_vcgt_in_profile,
    # Profile VCGT extraction
    extract_vcgt_from_profile,
    # Calibration helpers
    generate_correction_vcgt,
    generate_rgb_correction_vcgt,
    generate_whitepoint_vcgt,
)

# =============================================================================
# Public API
# =============================================================================

__all__ = [
    # -------------------------------------------------------------------------
    # ICC v4.4 Profile
    # -------------------------------------------------------------------------
    # Constants
    "ICC_MAGIC",
    "ICC_VERSION_4_4",
    # Enums
    "ProfileClass",
    "ColorSpace",
    "Platform",
    "RenderingIntent",
    "TagSignature",
    # Data structures
    "XYZNumber",
    "DateTimeNumber",
    "MultiLocalizedString",
    "ParametricCurve",
    "CurveData",
    "MeasurementData",
    "CLUT",
    # Profile class
    "ICCProfile",
    # Helpers
    "create_calibration_profile",
    "create_lut_profile",
    # -------------------------------------------------------------------------
    # VCGT
    # -------------------------------------------------------------------------
    # Constants
    "VCGT_SIZE_STANDARD",
    "VCGT_SIZE_EXTENDED",
    "VCGT_SIZE_MAXIMUM",
    "GAMMA_RAMP_SIZE",
    # Classes
    "VCGTTable",
    "GammaRampController",
    # Functions
    "extract_vcgt_from_profile",
    "embed_vcgt_in_profile",
    "generate_correction_vcgt",
    "generate_rgb_correction_vcgt",
    "generate_whitepoint_vcgt",
    # -------------------------------------------------------------------------
    # MHC2 (Windows HDR)
    # -------------------------------------------------------------------------
    # Constants
    "MHC2_TAG_SIGNATURE",
    "MHC2_VERSION_1",
    "MHC2_VERSION_2",
    "DEFAULT_SDR_WHITE_LEVEL",
    "DEFAULT_MIN_LUMINANCE",
    "DEFAULT_MAX_LUMINANCE",
    "SDR_WHITE_MIN",
    "SDR_WHITE_MAX",
    # Data structures
    "MHC2ColorMatrix",
    "MHC2ToneCurve",
    "MHC2Tag",
    "WindowsHDRSettings",
    # Functions
    "extract_mhc2_from_profile",
    "create_hdr_profile_with_mhc2",
    "generate_mhc2_profile",
    "install_mhc2_profile",
    "get_recommended_sdr_white",
    "calculate_hdr_headroom",
    # -------------------------------------------------------------------------
    # Profile Installation
    # -------------------------------------------------------------------------
    # Enums
    "ProfileScope",
    "ProfileAssociation",
    "ColorProfileType",
    # Display info
    "DisplayDevice",
    "MonitorInfo",
    "enumerate_displays",
    "get_monitor_info",
    # Installation
    "get_profile_directory",
    "install_profile",
    "uninstall_profile",
    "list_installed_profiles",
    # Association
    "associate_profile_with_display",
    "disassociate_profile_from_display",
    "get_display_profile",
    "get_associated_profiles",
    # Backup/Restore
    "ProfileBackup",
    "backup_profiles",
    "restore_profiles",
    # VCGT loading
    "load_profile_vcgt",
    "reset_display_gamma",
    # Convenience
    "quick_calibrate_display",
    "get_display_calibration_status",
]
