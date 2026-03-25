"""
Core Color Mathematics Module

Provides precise color space conversions, chromatic adaptation, and Delta E calculations
for professional display calibration.

All calculations follow ICC specifications and use high-precision floating point arithmetic.
"""

import numpy as np
from dataclasses import dataclass
from typing import Tuple, Union, Optional
import math

from quanta_color import spaces as _qc_spaces
from quanta_color import adaptation as _qc_adapt
from quanta_color import difference as _qc_diff
from quanta_color import gamut as _qc_gamut


def _illuminant_to_array(ill: 'Illuminant') -> np.ndarray:
    """Convert Calibrate Pro Illuminant to numpy array for quanta_color."""
    return np.array([ill.X, ill.Y, ill.Z])

# =============================================================================
# Standard Illuminants (CIE 1931 2-degree observer)
# =============================================================================

@dataclass(frozen=True)
class Illuminant:
    """Standard illuminant with XYZ tristimulus values (Y=1.0 normalized)."""
    name: str
    X: float
    Y: float
    Z: float
    cct: int  # Correlated Color Temperature in Kelvin

# D50 - ICC Profile Connection Space reference white
D50_WHITE = Illuminant("D50", 0.96422, 1.0, 0.82521, 5003)

# D65 - sRGB and most display standards reference white
D65_WHITE = Illuminant("D65", 0.95047, 1.0, 1.08883, 6504)

# D55 - Daylight, sometimes used for proofing
D55_WHITE = Illuminant("D55", 0.95682, 1.0, 0.92149, 5503)

# D75 - North sky daylight
D75_WHITE = Illuminant("D75", 0.94972, 1.0, 1.22638, 7504)

# Illuminant A - Incandescent/tungsten
A_WHITE = Illuminant("A", 1.09850, 1.0, 0.35585, 2856)

# =============================================================================
# Color Space Conversion Matrices
# =============================================================================

# sRGB to XYZ (D65) - IEC 61966-2-1
SRGB_TO_XYZ = np.array([
    [0.4124564, 0.3575761, 0.1804375],
    [0.2126729, 0.7151522, 0.0721750],
    [0.0193339, 0.1191920, 0.9503041]
], dtype=np.float64)

# XYZ (D65) to sRGB
XYZ_TO_SRGB = np.array([
    [ 3.2404542, -1.5371385, -0.4985314],
    [-0.9692660,  1.8760108,  0.0415560],
    [ 0.0556434, -0.2040259,  1.0572252]
], dtype=np.float64)

# Adobe RGB (1998) to XYZ (D65)
ADOBE_RGB_TO_XYZ = np.array([
    [0.5767309, 0.1855540, 0.1881852],
    [0.2973769, 0.6273491, 0.0752741],
    [0.0270343, 0.0706872, 0.9911085]
], dtype=np.float64)

# DCI-P3 (D65) to XYZ
DCI_P3_TO_XYZ = np.array([
    [0.4865709, 0.2656677, 0.1982173],
    [0.2289746, 0.6917385, 0.0792869],
    [0.0000000, 0.0451134, 1.0439444]
], dtype=np.float64)

# BT.2020 to XYZ (D65)
BT2020_TO_XYZ = np.array([
    [0.6369580, 0.1446169, 0.1688810],
    [0.2627002, 0.6779981, 0.0593017],
    [0.0000000, 0.0280727, 1.0609851]
], dtype=np.float64)

# =============================================================================
# Bradford Chromatic Adaptation
# =============================================================================

# Bradford transformation matrix
BRADFORD_MATRIX = np.array([
    [ 0.8951000,  0.2664000, -0.1614000],
    [-0.7502000,  1.7135000,  0.0367000],
    [ 0.0389000, -0.0685000,  1.0296000]
], dtype=np.float64)

BRADFORD_INVERSE = np.linalg.inv(BRADFORD_MATRIX)

def bradford_adapt(
    xyz: np.ndarray,
    source_white: Illuminant,
    dest_white: Illuminant
) -> np.ndarray:
    """
    Perform Bradford chromatic adaptation transform.

    Converts XYZ values from one illuminant to another using the Bradford
    cone-response-based chromatic adaptation transform.

    Args:
        xyz: XYZ values as (3,) array or (N, 3) array
        source_white: Source illuminant (e.g., D65_WHITE)
        dest_white: Destination illuminant (e.g., D50_WHITE)

    Returns:
        Adapted XYZ values
    """
    if source_white == dest_white:
        return xyz.copy()
    return _qc_adapt.adapt(np.asarray(xyz, dtype=np.float64), _illuminant_to_array(source_white), _illuminant_to_array(dest_white), method="bradford")

def get_adaptation_matrix(
    source_white: Illuminant,
    dest_white: Illuminant
) -> np.ndarray:
    """Get the 3x3 Bradford adaptation matrix for the given white points."""
    return _qc_adapt.get_adaptation_matrix(_illuminant_to_array(source_white), _illuminant_to_array(dest_white), method="bradford")

# =============================================================================
# XYZ <-> Lab Conversions
# =============================================================================

def xyz_to_lab(
    xyz: np.ndarray,
    illuminant: Illuminant = D50_WHITE
) -> np.ndarray:
    """
    Convert XYZ to CIELAB.

    Args:
        xyz: XYZ values as (3,) array or (N, 3) array
        illuminant: Reference white point (default D50 for ICC)

    Returns:
        Lab values as (3,) or (N, 3) array
    """
    return _qc_spaces.xyz_to_lab(np.asarray(xyz, dtype=np.float64), white=_illuminant_to_array(illuminant))

def lab_to_xyz(
    lab: np.ndarray,
    illuminant: Illuminant = D50_WHITE
) -> np.ndarray:
    """
    Convert CIELAB to XYZ.

    Args:
        lab: Lab values as (3,) array or (N, 3) array
        illuminant: Reference white point (default D50 for ICC)

    Returns:
        XYZ values as (3,) or (N, 3) array
    """
    return _qc_spaces.lab_to_xyz(np.asarray(lab, dtype=np.float64), white=_illuminant_to_array(illuminant))

# =============================================================================
# sRGB <-> XYZ Conversions
# =============================================================================

def srgb_gamma_expand(rgb: np.ndarray) -> np.ndarray:
    """
    Convert sRGB (gamma-compressed) to linear RGB.

    Follows IEC 61966-2-1 specification.
    """
    return _qc_spaces.srgb_to_linear(np.asarray(rgb, dtype=np.float64))

def srgb_gamma_compress(linear: np.ndarray) -> np.ndarray:
    """
    Convert linear RGB to sRGB (gamma-compressed).

    Follows IEC 61966-2-1 specification.
    """
    return _qc_spaces.linear_to_srgb(np.asarray(linear, dtype=np.float64))

def srgb_to_xyz(rgb: np.ndarray) -> np.ndarray:
    """
    Convert sRGB to XYZ (D65).

    Args:
        rgb: sRGB values in [0, 1] range as (3,) or (N, 3) array

    Returns:
        XYZ values (D65)
    """
    return _qc_spaces.srgb_to_xyz(np.asarray(rgb, dtype=np.float64))

def xyz_to_srgb(xyz: np.ndarray, clip: bool = True) -> np.ndarray:
    """
    Convert XYZ (D65) to sRGB.

    Args:
        xyz: XYZ values as (3,) or (N, 3) array
        clip: Whether to clip output to [0, 1] range

    Returns:
        sRGB values in [0, 1] range
    """
    return _qc_spaces.xyz_to_srgb(np.asarray(xyz, dtype=np.float64), clip=clip)

# =============================================================================
# Lab <-> sRGB Conversions (via XYZ)
# =============================================================================

def lab_to_srgb(
    lab: np.ndarray,
    illuminant: Illuminant = D50_WHITE,
    clip: bool = True
) -> np.ndarray:
    """
    Convert CIELAB to sRGB.

    Handles chromatic adaptation from Lab illuminant (typically D50) to D65.

    Args:
        lab: Lab values as (3,) or (N, 3) array
        illuminant: Lab reference white (default D50)
        clip: Whether to clip output to [0, 1]

    Returns:
        sRGB values in [0, 1] range
    """
    xyz = lab_to_xyz(lab, illuminant)

    # Adapt from Lab illuminant to D65 (sRGB)
    if illuminant != D65_WHITE:
        xyz = bradford_adapt(xyz, illuminant, D65_WHITE)

    return xyz_to_srgb(xyz, clip=clip)

def srgb_to_lab(
    rgb: np.ndarray,
    illuminant: Illuminant = D50_WHITE
) -> np.ndarray:
    """
    Convert sRGB to CIELAB.

    Handles chromatic adaptation from D65 to Lab illuminant (typically D50).

    Args:
        rgb: sRGB values in [0, 1] range
        illuminant: Lab reference white (default D50)

    Returns:
        Lab values
    """
    xyz = srgb_to_xyz(rgb)

    # Adapt from D65 to Lab illuminant
    if illuminant != D65_WHITE:
        xyz = bradford_adapt(xyz, D65_WHITE, illuminant)

    return xyz_to_lab(xyz, illuminant)

# =============================================================================
# CIEDE2000 Delta E Calculation
# =============================================================================

def delta_e_2000(
    lab1: np.ndarray,
    lab2: np.ndarray,
    kL: float = 1.0,
    kC: float = 1.0,
    kH: float = 1.0
) -> Union[float, np.ndarray]:
    """
    Calculate CIEDE2000 color difference.

    This is the most perceptually uniform color difference formula,
    preferred for display calibration verification.

    Args:
        lab1: First Lab color(s) as (3,) or (N, 3) array
        lab2: Second Lab color(s) as (3,) or (N, 3) array
        kL: Lightness weighting factor (default 1.0)
        kC: Chroma weighting factor (default 1.0)
        kH: Hue weighting factor (default 1.0)

    Returns:
        Delta E value(s)
    """
    lab1 = np.asarray(lab1, dtype=np.float64)
    lab2 = np.asarray(lab2, dtype=np.float64)
    single = lab1.ndim == 1
    if single:
        lab1 = lab1.reshape(1, 3)
        lab2 = lab2.reshape(1, 3)
    result = _qc_diff.delta_e_2000(lab1, lab2, kL=kL, kC=kC, kH=kH)
    return float(result[0]) if single else result

# =============================================================================
# Gamma and Transfer Functions
# =============================================================================

def gamma_encode(linear: np.ndarray, gamma: float = 2.2) -> np.ndarray:
    """Apply power-law gamma encoding."""
    linear = np.asarray(linear, dtype=np.float64)
    return np.power(np.clip(linear, 0.0, None), 1.0 / gamma)

def gamma_decode(encoded: np.ndarray, gamma: float = 2.2) -> np.ndarray:
    """Apply power-law gamma decoding (linearization)."""
    encoded = np.asarray(encoded, dtype=np.float64)
    return np.power(np.clip(encoded, 0.0, 1.0), gamma)

def bt1886_eotf(signal: np.ndarray, gamma: float = 2.4, Lw: float = 100.0, Lb: float = 0.0) -> np.ndarray:
    """
    BT.1886 Electro-Optical Transfer Function.

    Used for broadcast and professional video displays.

    Args:
        signal: Normalized signal [0, 1]
        gamma: Display gamma (default 2.4)
        Lw: Peak white luminance in cd/m2
        Lb: Black level luminance in cd/m2

    Returns:
        Display luminance in cd/m2
    """
    signal = np.asarray(signal, dtype=np.float64)
    a = (Lw ** (1.0 / gamma) - Lb ** (1.0 / gamma)) ** gamma
    b = Lb ** (1.0 / gamma) / (Lw ** (1.0 / gamma) - Lb ** (1.0 / gamma))
    return a * np.power(np.maximum(signal + b, 0.0), gamma)

def bt1886_eotf_inv(luminance: np.ndarray, gamma: float = 2.4, Lw: float = 100.0, Lb: float = 0.0) -> np.ndarray:
    """Inverse BT.1886 EOTF (luminance to signal)."""
    luminance = np.asarray(luminance, dtype=np.float64)
    a = (Lw ** (1.0 / gamma) - Lb ** (1.0 / gamma)) ** gamma
    b = Lb ** (1.0 / gamma) / (Lw ** (1.0 / gamma) - Lb ** (1.0 / gamma))
    return np.power(luminance / a, 1.0 / gamma) - b

# =============================================================================
# Chromaticity Conversions
# =============================================================================

def xyz_to_xyY(xyz: np.ndarray) -> np.ndarray:
    """
    Convert XYZ to CIE xyY chromaticity.

    Args:
        xyz: XYZ values as (3,) or (N, 3) array

    Returns:
        xyY values where x, y are chromaticity coordinates and Y is luminance
    """
    return _qc_spaces.xyz_to_xyY(np.asarray(xyz, dtype=np.float64))

def xyY_to_xyz(xyY: np.ndarray) -> np.ndarray:
    """
    Convert CIE xyY to XYZ.

    Args:
        xyY: xyY values as (3,) or (N, 3) array

    Returns:
        XYZ values
    """
    return _qc_spaces.xyY_to_xyz(np.asarray(xyY, dtype=np.float64))

# =============================================================================
# CCT (Correlated Color Temperature) Calculations
# =============================================================================

def xy_to_cct(x: float, y: float) -> float:
    """
    Calculate Correlated Color Temperature from CIE xy chromaticity.

    Uses McCamy's approximation, accurate for 2000K to 12000K.

    Args:
        x, y: CIE 1931 chromaticity coordinates

    Returns:
        CCT in Kelvin
    """
    return _qc_adapt.xy_to_cct_mccamy(x, y)

def cct_to_xy(cct: float) -> Tuple[float, float]:
    """
    Calculate CIE xy chromaticity from CCT (Planckian locus).

    Uses CIE formulas for daylight illuminants.

    Args:
        cct: Correlated Color Temperature in Kelvin

    Returns:
        (x, y) chromaticity coordinates
    """
    return _qc_adapt.cct_to_xy(cct)

# =============================================================================
# Gamut Utilities
# =============================================================================

def is_in_gamut(rgb: np.ndarray, tolerance: float = 0.0) -> Union[bool, np.ndarray]:
    """
    Check if RGB values are within gamut [0, 1].

    Args:
        rgb: RGB values as (3,) or (N, 3) array
        tolerance: Allow small out-of-gamut values

    Returns:
        Boolean or array of booleans
    """
    return _qc_gamut.is_in_gamut(np.asarray(rgb, dtype=np.float64), tolerance=tolerance)

def gamut_clip(rgb: np.ndarray) -> np.ndarray:
    """Simple RGB clipping to [0, 1] range."""
    return _qc_gamut.clip(np.asarray(rgb, dtype=np.float64))

def gamut_compress(
    rgb: np.ndarray,
    threshold: float = 0.8,
    limit: float = 1.0
) -> np.ndarray:
    """
    Soft gamut compression using a power curve.

    Compresses out-of-gamut values smoothly rather than hard clipping.
    """
    rgb = np.asarray(rgb, dtype=np.float64)

    # Compress values above threshold
    above = rgb > threshold
    if np.any(above):
        x = (rgb[above] - threshold) / (limit - threshold)
        # Soft knee compression
        compressed = threshold + (limit - threshold) * (1.0 - np.exp(-x))
        result = rgb.copy()
        result[above] = compressed
        return np.clip(result, 0.0, 1.0)

    return np.clip(rgb, 0.0, 1.0)

# =============================================================================
# Matrix Utilities
# =============================================================================

def primaries_to_xyz_matrix(
    red_xy: Tuple[float, float],
    green_xy: Tuple[float, float],
    blue_xy: Tuple[float, float],
    white_xy: Tuple[float, float]
) -> np.ndarray:
    """
    Calculate RGB to XYZ matrix from primary chromaticities.

    Args:
        red_xy: Red primary (x, y) chromaticity
        green_xy: Green primary (x, y) chromaticity
        blue_xy: Blue primary (x, y) chromaticity
        white_xy: White point (x, y) chromaticity

    Returns:
        3x3 RGB to XYZ matrix
    """
    # Convert xy to XYZ (assuming Y=1)
    def xy_to_XYZ(x, y):
        return np.array([x/y, 1.0, (1-x-y)/y])

    R = xy_to_XYZ(*red_xy)
    G = xy_to_XYZ(*green_xy)
    B = xy_to_XYZ(*blue_xy)
    W = xy_to_XYZ(*white_xy)

    # Create primaries matrix
    M = np.column_stack([R, G, B])

    # Solve for scaling factors
    S = np.linalg.solve(M, W)

    # Scale columns
    return M * S

def xyz_to_rgb_matrix(rgb_to_xyz: np.ndarray) -> np.ndarray:
    """Calculate XYZ to RGB matrix (inverse of RGB to XYZ)."""
    return np.linalg.inv(rgb_to_xyz)


# =============================================================================
# Oklab / Oklch — Perceptually Uniform Color Space (Björn Ottosson)
# =============================================================================

def linear_srgb_to_oklab(rgb: np.ndarray) -> np.ndarray:
    """
    Convert linear sRGB to Oklab.

    Oklab is more perceptually uniform than CIELAB, especially in blue/purple
    hues. Preferred for gamut mapping and color interpolation.

    Args:
        rgb: Linear sRGB as (3,) or (N, 3)
    Returns:
        Oklab [L, a, b] where L in [0,1]
    """
    return _qc_spaces.linear_srgb_to_oklab(np.asarray(rgb, dtype=np.float64))


def oklab_to_linear_srgb(lab: np.ndarray) -> np.ndarray:
    """
    Convert Oklab to linear sRGB.

    Args:
        lab: Oklab [L, a, b] as (3,) or (N, 3)
    Returns:
        Linear sRGB
    """
    return _qc_spaces.oklab_to_linear_srgb(np.asarray(lab, dtype=np.float64))


def oklab_to_oklch(lab: np.ndarray) -> np.ndarray:
    """Convert Oklab to Oklch (cylindrical: L, C, h in degrees)."""
    return _qc_spaces.oklab_to_oklch(np.asarray(lab, dtype=np.float64))


def oklch_to_oklab(lch: np.ndarray) -> np.ndarray:
    """Convert Oklch to Oklab."""
    return _qc_spaces.oklch_to_oklab(np.asarray(lch, dtype=np.float64))


# =============================================================================
# JzAzBz / JzCzhz — HDR Perceptual Color Space
# =============================================================================

# JzAzBz constants
_JZ_B = 1.15
_JZ_G = 0.66
_JZ_D = -0.56
_JZ_D0 = 1.6295499532821566e-11

# PQ constants for JzAzBz (operates on absolute luminance)
_PQ_M1 = 2610.0 / 16384.0
_PQ_M2 = 2523.0 / 4096.0 * 128.0
_PQ_C1 = 3424.0 / 4096.0
_PQ_C2 = 2413.0 / 4096.0 * 32.0
_PQ_C3 = 2392.0 / 4096.0 * 32.0


def _pq_encode(x: np.ndarray) -> np.ndarray:
    """PQ perceptual quantizer encode (for JzAzBz)."""
    xp = np.maximum(x / 10000.0, 0.0)
    num = _PQ_C1 + _PQ_C2 * np.power(xp, _PQ_M1)
    den = 1.0 + _PQ_C3 * np.power(xp, _PQ_M1)
    return np.power(num / den, _PQ_M2)


def _pq_decode(x: np.ndarray) -> np.ndarray:
    """PQ perceptual quantizer decode (for JzAzBz)."""
    xp = np.power(np.maximum(x, 0.0), 1.0 / _PQ_M2)
    num = np.maximum(xp - _PQ_C1, 0.0)
    den = _PQ_C2 - _PQ_C3 * xp
    den = np.where(np.abs(den) < 1e-30, 1e-30, den)
    return 10000.0 * np.power(np.maximum(num / den, 0.0), 1.0 / _PQ_M1)


def xyz_abs_to_jzazbz(xyz: np.ndarray) -> np.ndarray:
    """
    Convert absolute XYZ (cd/m²) to JzAzBz.

    JzAzBz is perceptually uniform across the full HDR luminance range,
    making it essential for HDR display calibration.

    Args:
        xyz: Absolute XYZ in cd/m² as (3,) or (N, 3)
    Returns:
        JzAzBz as (3,) or (N, 3)
    """
    xyz = np.asarray(xyz, dtype=np.float64)
    single = xyz.ndim == 1
    if single:
        xyz = xyz.reshape(1, 3)

    x, y, z = xyz[:, 0], xyz[:, 1], xyz[:, 2]

    xp = _JZ_B * x - (_JZ_B - 1.0) * z
    yp = _JZ_G * y - (_JZ_G - 1.0) * x

    lp = 0.41478972 * xp + 0.579999 * yp + 0.0146480 * z
    mp = -0.2015100 * xp + 1.120649 * yp + 0.0531008 * z
    sp = -0.0166008 * xp + 0.264800 * yp + 0.6684799 * z

    l = _pq_encode(lp)
    m = _pq_encode(mp)
    s = _pq_encode(sp)

    iz = 0.5 * (l + m)
    az = 3.524000 * l - 4.066708 * m + 0.542708 * s
    bz = 0.199076 * l + 1.096799 * m - 1.295875 * s

    jz = ((1.0 + _JZ_D) * iz) / (1.0 + _JZ_D * iz) - _JZ_D0

    result = np.column_stack([jz, az, bz])
    return result[0] if single else result


def jzazbz_to_xyz_abs(jzazbz: np.ndarray) -> np.ndarray:
    """
    Convert JzAzBz to absolute XYZ (cd/m²).

    Args:
        jzazbz: JzAzBz as (3,) or (N, 3)
    Returns:
        Absolute XYZ in cd/m²
    """
    jzazbz = np.asarray(jzazbz, dtype=np.float64)
    single = jzazbz.ndim == 1
    if single:
        jzazbz = jzazbz.reshape(1, 3)

    jz, az, bz = jzazbz[:, 0], jzazbz[:, 1], jzazbz[:, 2]

    jz_adj = jz + _JZ_D0
    iz = jz_adj / (1.0 + _JZ_D - _JZ_D * jz_adj)

    l = iz + 0.1386050432715393 * az + 0.05804731615611886 * bz
    m = iz - 0.1386050432715393 * az - 0.05804731615611886 * bz
    s = iz - 0.09601924202631895 * az - 0.8118918960560388 * bz

    lp = _pq_decode(l)
    mp = _pq_decode(m)
    sp = _pq_decode(s)

    xp =  1.9242264357876067 * lp - 1.0047923125953657 * mp + 0.037651404030618 * sp
    yp =  0.35031676209499907 * lp + 0.7264811939316552 * mp - 0.06538442294808501 * sp
    z  = -0.09098281098284752 * lp - 0.3127282905230739 * mp + 1.5227665613052603 * sp

    x = (xp + (_JZ_B - 1.0) * z) / _JZ_B
    y = (yp + (_JZ_G - 1.0) * x) / _JZ_G

    result = np.column_stack([x, y, z])
    return result[0] if single else result


def jzazbz_to_jzczhz(jzazbz: np.ndarray) -> np.ndarray:
    """Convert JzAzBz to cylindrical JzCzhz (Jz, Chroma, hue degrees)."""
    jzazbz = np.asarray(jzazbz, dtype=np.float64)
    single = jzazbz.ndim == 1
    if single:
        jzazbz = jzazbz.reshape(1, 3)

    Jz = jzazbz[:, 0]
    Cz = np.sqrt(jzazbz[:, 1]**2 + jzazbz[:, 2]**2)
    hz = np.degrees(np.arctan2(jzazbz[:, 2], jzazbz[:, 1])) % 360.0

    result = np.column_stack([Jz, Cz, hz])
    return result[0] if single else result


def jzczhz_to_jzazbz(jzczhz: np.ndarray) -> np.ndarray:
    """Convert cylindrical JzCzhz to JzAzBz."""
    jzczhz = np.asarray(jzczhz, dtype=np.float64)
    single = jzczhz.ndim == 1
    if single:
        jzczhz = jzczhz.reshape(1, 3)

    h_rad = np.radians(jzczhz[:, 2])
    az = jzczhz[:, 1] * np.cos(h_rad)
    bz = jzczhz[:, 1] * np.sin(h_rad)

    result = np.column_stack([jzczhz[:, 0], az, bz])
    return result[0] if single else result


# =============================================================================
# ICtCp — Dolby HDR Perceptual Space
# =============================================================================

def xyz_abs_to_ictcp(xyz: np.ndarray) -> np.ndarray:
    """
    Convert absolute XYZ (cd/m²) to ICtCp (Dolby).

    ICtCp separates intensity from chrominance more cleanly than
    JzAzBz and is the native space for Dolby Vision processing.

    Args:
        xyz: Absolute XYZ in cd/m² as (3,) or (N, 3)
    Returns:
        ICtCp as (3,) or (N, 3)
    """
    xyz = np.asarray(xyz, dtype=np.float64)
    single = xyz.ndim == 1
    if single:
        xyz = xyz.reshape(1, 3)

    x, y, z = xyz[:, 0], xyz[:, 1], xyz[:, 2]

    # XYZ to LMS
    L =  0.3592 * x + 0.6976 * y - 0.0358 * z
    M = -0.1922 * x + 1.1004 * y + 0.0755 * z
    S =  0.0070 * x + 0.0749 * y + 0.8434 * z

    # PQ encode (normalize to 10000 nits)
    Lp = _pq_st2084_oetf(L / 10000.0)
    Mp = _pq_st2084_oetf(M / 10000.0)
    Sp = _pq_st2084_oetf(S / 10000.0)

    # LMS' to ICtCp
    I  = 0.5 * Lp + 0.5 * Mp
    Ct = 1.613769531 * Lp - 3.323486328 * Mp + 1.709716797 * Sp
    Cp = 4.378173828 * Lp - 4.245605469 * Mp - 0.132568359 * Sp

    result = np.column_stack([I, Ct, Cp])
    return result[0] if single else result


def ictcp_to_xyz_abs(ictcp: np.ndarray) -> np.ndarray:
    """
    Convert ICtCp to absolute XYZ (cd/m²).

    Args:
        ictcp: ICtCp as (3,) or (N, 3)
    Returns:
        Absolute XYZ in cd/m²
    """
    ictcp = np.asarray(ictcp, dtype=np.float64)
    single = ictcp.ndim == 1
    if single:
        ictcp = ictcp.reshape(1, 3)

    I, Ct, Cp = ictcp[:, 0], ictcp[:, 1], ictcp[:, 2]

    # ICtCp to LMS'
    Lp = I + 0.00860904 * Ct + 0.11103 * Cp
    Mp = I - 0.00860904 * Ct - 0.11103 * Cp
    Sp = I + 0.56003 * Ct - 0.32068 * Cp

    # PQ decode
    L = _pq_st2084_eotf(Lp) * 10000.0
    M = _pq_st2084_eotf(Mp) * 10000.0
    S = _pq_st2084_eotf(Sp) * 10000.0

    # LMS to XYZ
    x =  2.0702 * L - 1.3265 * M + 0.2067 * S
    y =  0.3650 * L + 0.6806 * M - 0.0453 * S
    z = -0.0496 * L - 0.0494 * M + 1.1880 * S

    result = np.column_stack([x, y, z])
    return result[0] if single else result


# =============================================================================
# PQ (ST.2084) and HLG (BT.2100) Transfer Functions
# =============================================================================

def _pq_st2084_oetf(v: np.ndarray) -> np.ndarray:
    """PQ OETF: linear [0,1] normalized to 10000 nits → PQ signal [0,1]."""
    v = np.asarray(v, dtype=np.float64)
    v = np.maximum(v, 0.0)
    ym1 = np.power(v, _PQ_M1)
    return np.power((_PQ_C1 + _PQ_C2 * ym1) / (1.0 + _PQ_C3 * ym1), _PQ_M2)


def _pq_st2084_eotf(v: np.ndarray) -> np.ndarray:
    """PQ EOTF: PQ signal [0,1] → linear [0,1] normalized to 10000 nits."""
    v = np.asarray(v, dtype=np.float64)
    vp = np.power(np.maximum(v, 0.0), 1.0 / _PQ_M2)
    num = np.maximum(vp - _PQ_C1, 0.0)
    den = _PQ_C2 - _PQ_C3 * vp
    return np.power(np.maximum(num / den, 0.0), 1.0 / _PQ_M1)


def pq_eotf(v: np.ndarray, peak_luminance: float = 10000.0) -> np.ndarray:
    """
    PQ EOTF: Decode PQ signal to absolute luminance (cd/m²).

    Args:
        v: PQ-encoded signal [0, 1]
        peak_luminance: Reference peak (default 10000 cd/m²)
    Returns:
        Luminance in cd/m²
    """
    return _pq_st2084_eotf(np.asarray(v, dtype=np.float64)) * peak_luminance


def pq_oetf(v: np.ndarray, peak_luminance: float = 10000.0) -> np.ndarray:
    """
    PQ OETF: Encode absolute luminance to PQ signal.

    Args:
        v: Luminance in cd/m²
        peak_luminance: Reference peak (default 10000 cd/m²)
    Returns:
        PQ signal [0, 1]
    """
    v = np.asarray(v, dtype=np.float64)
    return _pq_st2084_oetf(np.clip(v / peak_luminance, 0.0, 1.0))


_HLG_A = 0.17883277
_HLG_B = 0.28466892
_HLG_C = 0.55991073


def hlg_oetf(v: np.ndarray) -> np.ndarray:
    """HLG OETF: linear scene light [0,1] → HLG signal [0,1]."""
    v = np.asarray(v, dtype=np.float64)
    result = np.zeros_like(v)
    lo = v <= 1.0 / 12.0
    result[lo] = np.sqrt(3.0 * v[lo])
    result[~lo] = _HLG_A * np.log(12.0 * v[~lo] - _HLG_B) + _HLG_C
    return result


def hlg_eotf(v: np.ndarray) -> np.ndarray:
    """HLG EOTF: HLG signal [0,1] → linear scene light [0,1]."""
    v = np.asarray(v, dtype=np.float64)
    result = np.zeros_like(v)
    lo = v <= 0.5
    result[lo] = (v[lo] ** 2) / 3.0
    result[~lo] = (np.exp((v[~lo] - _HLG_C) / _HLG_A) + _HLG_B) / 12.0
    return result


def hlg_ootf_rgb(
    rgb: np.ndarray,
    peak_luminance: float = 1000.0,
    gamma: float = 1.2
) -> np.ndarray:
    """
    HLG OOTF: scene-referred linear → display-referred linear.

    Args:
        rgb: Scene light RGB [0,1] as (3,) or (N, 3)
        peak_luminance: Display peak in cd/m²
        gamma: System gamma (typically 1.2)
    Returns:
        Display light RGB in cd/m²
    """
    rgb = np.asarray(rgb, dtype=np.float64)
    single = rgb.ndim == 1
    if single:
        rgb = rgb.reshape(1, 3)

    Ys = 0.2627 * rgb[:, 0] + 0.6780 * rgb[:, 1] + 0.0593 * rgb[:, 2]
    scale = np.power(np.maximum(Ys, 1e-10), gamma - 1.0) * peak_luminance

    result = rgb * scale[:, np.newaxis]
    return result[0] if single else result


# =============================================================================
# ACES Color Spaces
# =============================================================================

# ACES 2065-1 (AP0) ↔ XYZ
ACES2065_1_TO_XYZ = np.array([
    [0.9525523959, 0.0000000000, 0.0000936786],
    [0.3439664498, 0.7281660966, -0.0721325464],
    [0.0000000000, 0.0000000000, 1.0088251844]
], dtype=np.float64)

XYZ_TO_ACES2065_1 = np.array([
    [ 1.0498110175, 0.0000000000, -0.0000974845],
    [-0.4959030231, 1.3733130458,  0.0982400361],
    [ 0.0000000000, 0.0000000000,  0.9912520182]
], dtype=np.float64)

# ACEScg (AP1) ↔ XYZ
ACESCG_TO_XYZ = np.array([
    [0.6624541811, 0.1340042065, 0.1561876870],
    [0.2722287168, 0.6740817658, 0.0536895174],
    [-0.0055746495, 0.0040607335, 1.0103391003]
], dtype=np.float64)

XYZ_TO_ACESCG = np.array([
    [ 1.6410233797, -0.3248032942, -0.2364246952],
    [-0.6636628587,  1.6153315917,  0.0167563477],
    [ 0.0117218943, -0.0082844420,  0.9883948585]
], dtype=np.float64)

# ACEScg ↔ linear sRGB
ACESCG_TO_SRGB_LINEAR = np.array([
    [ 1.7050509879, -0.6217921206, -0.0832588234],
    [-0.1302564175,  1.1408047365, -0.0105482626],
    [-0.0240033568, -0.1289689761,  1.1529723252]
], dtype=np.float64)

SRGB_LINEAR_TO_ACESCG = np.array([
    [0.6131178520, 0.3395231462, 0.0473590018],
    [0.0701918649, 0.9163553837, 0.0134527514],
    [0.0205798908, 0.1096578085, 0.8697623008]
], dtype=np.float64)


def acescg_to_xyz(rgb: np.ndarray) -> np.ndarray:
    """Convert ACEScg (AP1 linear) to XYZ."""
    rgb = np.asarray(rgb, dtype=np.float64)
    if rgb.ndim == 1:
        return ACESCG_TO_XYZ @ rgb
    return (ACESCG_TO_XYZ @ rgb.T).T


def xyz_to_acescg(xyz: np.ndarray) -> np.ndarray:
    """Convert XYZ to ACEScg (AP1 linear)."""
    xyz = np.asarray(xyz, dtype=np.float64)
    if xyz.ndim == 1:
        return XYZ_TO_ACESCG @ xyz
    return (XYZ_TO_ACESCG @ xyz.T).T


def acescc_encode(linear: np.ndarray) -> np.ndarray:
    """ACEScc log encoding (from ACEScg linear values)."""
    linear = np.asarray(linear, dtype=np.float64)
    result = np.zeros_like(linear)

    neg = linear <= 0.0
    lo = (~neg) & (linear < 2.0**-15)
    hi = ~neg & ~lo

    result[neg] = -0.3584474886  # (log2(2^-16) + 9.72) / 17.52
    result[lo] = (np.log2(2.0**-16 + linear[lo] * 0.5) + 9.72) / 17.52
    result[hi] = (np.log2(linear[hi]) + 9.72) / 17.52

    return result


def acescc_decode(encoded: np.ndarray) -> np.ndarray:
    """ACEScc log decoding (to ACEScg linear values)."""
    encoded = np.asarray(encoded, dtype=np.float64)
    result = np.zeros_like(encoded)

    lo = encoded < (9.72 - 15.0) / 17.52
    hi = encoded >= (np.log2(65504.0) + 9.72) / 17.52
    mid = ~lo & ~hi

    result[lo] = (np.power(2.0, encoded[lo] * 17.52 - 9.72) - 2.0**-16) * 2.0
    result[mid] = np.power(2.0, encoded[mid] * 17.52 - 9.72)
    result[hi] = 65504.0

    return result


_ACESCCT_CUT = 0.0078125  # 2^-7


def acescct_encode(linear: np.ndarray) -> np.ndarray:
    """ACEScct log encoding (ACEScc with toe for better shadow handling)."""
    linear = np.asarray(linear, dtype=np.float64)
    result = np.zeros_like(linear)

    lo = linear <= _ACESCCT_CUT
    hi = ~lo

    result[lo] = 10.5402377416545 * linear[lo] + 0.0729055341958355
    result[hi] = (np.log2(linear[hi]) + 9.72) / 17.52

    return result


def acescct_decode(encoded: np.ndarray) -> np.ndarray:
    """ACEScct log decoding."""
    encoded = np.asarray(encoded, dtype=np.float64)
    result = np.zeros_like(encoded)

    lo = encoded <= 0.155251141552511
    hi = ~lo

    result[lo] = (encoded[lo] - 0.0729055341958355) / 10.5402377416545
    result[hi] = np.power(2.0, encoded[hi] * 17.52 - 9.72)

    return result


# =============================================================================
# Display P3 / Rec.2020 with Proper Transfer Functions
# =============================================================================

# Display P3 ↔ XYZ matrices (already defined at top as DCI_P3_TO_XYZ)
DISPLAY_P3_TO_XYZ = DCI_P3_TO_XYZ  # Same primaries, D65 white, sRGB EOTF
XYZ_TO_DISPLAY_P3 = np.linalg.inv(DISPLAY_P3_TO_XYZ)


def display_p3_to_xyz(rgb: np.ndarray) -> np.ndarray:
    """Convert Display P3 (sRGB EOTF) to XYZ (D65)."""
    rgb = np.asarray(rgb, dtype=np.float64)
    linear = srgb_gamma_expand(rgb)
    if linear.ndim == 1:
        return DISPLAY_P3_TO_XYZ @ linear
    return (DISPLAY_P3_TO_XYZ @ linear.T).T


def xyz_to_display_p3(xyz: np.ndarray, clip: bool = True) -> np.ndarray:
    """Convert XYZ (D65) to Display P3."""
    xyz = np.asarray(xyz, dtype=np.float64)
    if xyz.ndim == 1:
        linear = XYZ_TO_DISPLAY_P3 @ xyz
    else:
        linear = (XYZ_TO_DISPLAY_P3 @ xyz.T).T
    if clip:
        linear = np.clip(linear, 0.0, None)
    return srgb_gamma_compress(linear)


# Rec.2020 transfer function constants
_REC2020_ALPHA = 1.09929682680944
_REC2020_BETA = 0.018053968510807


def rec2020_oetf(v: np.ndarray) -> np.ndarray:
    """Rec.2020 OETF (non-linear encoding)."""
    v = np.asarray(v, dtype=np.float64)
    result = np.zeros_like(v)
    lo = v < _REC2020_BETA
    result[lo] = 4.5 * v[lo]
    result[~lo] = _REC2020_ALPHA * np.power(v[~lo], 0.45) - (_REC2020_ALPHA - 1.0)
    return result


def rec2020_eotf(v: np.ndarray) -> np.ndarray:
    """Rec.2020 EOTF (non-linear decoding)."""
    v = np.asarray(v, dtype=np.float64)
    result = np.zeros_like(v)
    lo = v < 4.5 * _REC2020_BETA
    result[lo] = v[lo] / 4.5
    result[~lo] = np.power((v[~lo] + _REC2020_ALPHA - 1.0) / _REC2020_ALPHA, 1.0 / 0.45)
    return result


def rec2020_to_xyz(rgb: np.ndarray) -> np.ndarray:
    """Convert Rec.2020 (non-linear) to XYZ (D65)."""
    rgb = np.asarray(rgb, dtype=np.float64)
    linear = rec2020_eotf(rgb)
    if linear.ndim == 1:
        return BT2020_TO_XYZ @ linear
    return (BT2020_TO_XYZ @ linear.T).T


def xyz_to_rec2020(xyz: np.ndarray, clip: bool = True) -> np.ndarray:
    """Convert XYZ (D65) to Rec.2020 (non-linear)."""
    xyz = np.asarray(xyz, dtype=np.float64)
    XYZ_TO_BT2020 = np.linalg.inv(BT2020_TO_XYZ)
    if xyz.ndim == 1:
        linear = XYZ_TO_BT2020 @ xyz
    else:
        linear = (XYZ_TO_BT2020 @ xyz.T).T
    if clip:
        linear = np.clip(linear, 0.0, None)
    return rec2020_oetf(linear)


# =============================================================================
# CIE Luv
# =============================================================================

_CIE_EPSILON = 216.0 / 24389.0
_CIE_KAPPA = 24389.0 / 27.0


def xyz_to_luv(
    xyz: np.ndarray,
    illuminant: Illuminant = D65_WHITE
) -> np.ndarray:
    """
    Convert XYZ to CIE L*u*v*.

    Luv is better than Lab for additive color mixing and saturation
    comparisons. Used in TV/display engineering.

    Args:
        xyz: XYZ as (3,) or (N, 3)
        illuminant: Reference white
    Returns:
        Luv as (3,) or (N, 3)
    """
    xyz = np.asarray(xyz, dtype=np.float64)
    single = xyz.ndim == 1
    if single:
        xyz = xyz.reshape(1, 3)

    ref = np.array([illuminant.X, illuminant.Y, illuminant.Z])

    yr = xyz[:, 1] / ref[1]
    L = np.where(yr > _CIE_EPSILON, 116.0 * np.cbrt(yr) - 16.0, _CIE_KAPPA * yr)

    def uv_prime(vals):
        denom = vals[:, 0] + 15.0 * vals[:, 1] + 3.0 * vals[:, 2]
        denom = np.where(denom == 0, 1.0, denom)
        u = 4.0 * vals[:, 0] / denom
        v = 9.0 * vals[:, 1] / denom
        return u, v

    u_p, v_p = uv_prime(xyz)
    un_p, vn_p = uv_prime(ref.reshape(1, 3))

    u = 13.0 * L * (u_p - un_p[0])
    v = 13.0 * L * (v_p - vn_p[0])

    result = np.column_stack([L, u, v])
    return result[0] if single else result


def luv_to_xyz(
    luv: np.ndarray,
    illuminant: Illuminant = D65_WHITE
) -> np.ndarray:
    """Convert CIE L*u*v* to XYZ."""
    luv = np.asarray(luv, dtype=np.float64)
    single = luv.ndim == 1
    if single:
        luv = luv.reshape(1, 3)

    ref = np.array([illuminant.X, illuminant.Y, illuminant.Z])
    ref_denom = ref[0] + 15.0 * ref[1] + 3.0 * ref[2]
    un_p = 4.0 * ref[0] / ref_denom
    vn_p = 9.0 * ref[1] / ref_denom

    L, u_star, v_star = luv[:, 0], luv[:, 1], luv[:, 2]

    u_p = np.where(L != 0, u_star / (13.0 * L) + un_p, 0.0)
    v_p = np.where(L != 0, v_star / (13.0 * L) + vn_p, 0.0)

    Y = np.where(
        L > _CIE_KAPPA * _CIE_EPSILON,
        np.power((L + 16.0) / 116.0, 3.0),
        L / _CIE_KAPPA
    ) * ref[1]

    X = np.where(v_p != 0, Y * 9.0 * u_p / (4.0 * v_p), 0.0)
    Z = np.where(v_p != 0, Y * (12.0 - 3.0 * u_p - 20.0 * v_p) / (4.0 * v_p), 0.0)

    result = np.column_stack([X, Y, Z])
    return result[0] if single else result


# =============================================================================
# HSL / HSV / HWB
# =============================================================================

def srgb_to_hsl(rgb: np.ndarray) -> np.ndarray:
    """Convert sRGB [0,1] to HSL (H in degrees, S and L in [0,1])."""
    rgb = np.asarray(rgb, dtype=np.float64)
    r, g, b = rgb[0], rgb[1], rgb[2]
    mx = max(r, g, b)
    mn = min(r, g, b)
    l = (mx + mn) / 2.0

    if mx == mn:
        return np.array([0.0, 0.0, l])

    d = mx - mn
    s = d / (2.0 - mx - mn) if l > 0.5 else d / (mx + mn)

    if mx == r:
        h = ((g - b) / d + (6.0 if g < b else 0.0)) * 60.0
    elif mx == g:
        h = ((b - r) / d + 2.0) * 60.0
    else:
        h = ((r - g) / d + 4.0) * 60.0

    return np.array([h, s, l])


def hsl_to_srgb(hsl: np.ndarray) -> np.ndarray:
    """Convert HSL to sRGB [0,1]."""
    hsl = np.asarray(hsl, dtype=np.float64)
    h, s, l = hsl[0], hsl[1], hsl[2]

    if s == 0.0:
        return np.array([l, l, l])

    q = l * (1.0 + s) if l < 0.5 else l + s - l * s
    p = 2.0 * l - q

    def hue2rgb(p, q, t):
        if t < 0: t += 1
        if t > 1: t -= 1
        if t < 1/6: return p + (q - p) * 6 * t
        if t < 1/2: return q
        if t < 2/3: return p + (q - p) * (2/3 - t) * 6
        return p

    r = hue2rgb(p, q, h / 360.0 + 1/3)
    g = hue2rgb(p, q, h / 360.0)
    b = hue2rgb(p, q, h / 360.0 - 1/3)

    return np.array([r, g, b])


def srgb_to_hsv(rgb: np.ndarray) -> np.ndarray:
    """Convert sRGB [0,1] to HSV (H degrees, S and V in [0,1])."""
    rgb = np.asarray(rgb, dtype=np.float64)
    r, g, b = rgb[0], rgb[1], rgb[2]
    mx = max(r, g, b)
    mn = min(r, g, b)
    d = mx - mn

    v = mx
    s = 0.0 if mx == 0.0 else d / mx

    if mx == mn:
        h = 0.0
    elif mx == r:
        h = ((g - b) / d + (6.0 if g < b else 0.0)) * 60.0
    elif mx == g:
        h = ((b - r) / d + 2.0) * 60.0
    else:
        h = ((r - g) / d + 4.0) * 60.0

    return np.array([h, s, v])


def hsv_to_srgb(hsv: np.ndarray) -> np.ndarray:
    """Convert HSV to sRGB [0,1]."""
    hsv = np.asarray(hsv, dtype=np.float64)
    h, s, v = hsv[0], hsv[1], hsv[2]

    if s == 0.0:
        return np.array([v, v, v])

    h_sec = h / 60.0
    i = int(h_sec) % 6
    f = h_sec - int(h_sec)
    p = v * (1.0 - s)
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))

    if i == 0: return np.array([v, t, p])
    if i == 1: return np.array([q, v, p])
    if i == 2: return np.array([p, v, t])
    if i == 3: return np.array([p, q, v])
    if i == 4: return np.array([t, p, v])
    return np.array([v, p, q])


def srgb_to_hwb(rgb: np.ndarray) -> np.ndarray:
    """Convert sRGB [0,1] to HWB (Hue, Whiteness, Blackness)."""
    hsv = srgb_to_hsv(rgb)
    w = (1.0 - hsv[1]) * hsv[2]
    b = 1.0 - hsv[2]
    return np.array([hsv[0], w, b])


def hwb_to_srgb(hwb: np.ndarray) -> np.ndarray:
    """Convert HWB to sRGB [0,1]."""
    hwb = np.asarray(hwb, dtype=np.float64)
    h, w, b = hwb[0], hwb[1], hwb[2]

    if w + b > 1.0:
        s = w + b
        w /= s
        b /= s

    v = 1.0 - b
    s = 0.0 if v == 0.0 else 1.0 - w / v
    return hsv_to_srgb(np.array([h, s, v]))


# =============================================================================
# CAM16 Color Appearance Model
# =============================================================================

# CAT16 forward matrix (XYZ to sharpened RGB)
_CAT16 = np.array([
    [ 0.401288,  0.650173, -0.051461],
    [-0.250268,  1.204414,  0.045854],
    [-0.002079,  0.048952,  0.953127]
], dtype=np.float64)

_CAT16_INV = np.linalg.inv(_CAT16)

# Surround parameters: (c, Nc, F)
CAM16_SURROUND_AVERAGE = (0.69, 1.0, 1.0)
CAM16_SURROUND_DIM = (0.59, 0.9, 0.9)
CAM16_SURROUND_DARK = (0.525, 0.8, 0.8)


@dataclass
class CAM16Env:
    """Pre-computed CAM16 viewing condition parameters."""
    c: float
    Nc: float
    F_L: float
    n: float
    Nbb: float
    z: float
    Aw: float
    D_RGB: np.ndarray


def cam16_environment(
    white_xyz: np.ndarray = None,
    La: float = 64.0,
    Yb: float = 20.0,
    surround: tuple = CAM16_SURROUND_AVERAGE
) -> CAM16Env:
    """
    Pre-compute CAM16 viewing condition parameters.

    Args:
        white_xyz: Reference white XYZ (default D65, Y=100)
        La: Adapting luminance in cd/m² (default 64, ~200 lux office)
        Yb: Background luminance as absolute Y (default 20)
        surround: (c, Nc, F) tuple
    Returns:
        CAM16Env with pre-computed values
    """
    if white_xyz is None:
        white_xyz = np.array([95.047, 100.0, 108.883])
    white_xyz = np.asarray(white_xyz, dtype=np.float64)

    c, Nc, F = surround
    Yw = white_xyz[1]

    # Degree of adaptation
    D = F * (1.0 - (1.0 / 3.6) * math.exp((-La - 42.0) / 92.0))
    D = max(0.0, min(1.0, D))

    # Adapted white
    rgb_w = _CAT16 @ white_xyz
    D_RGB = np.array([
        D * (Yw / rgb_w[0]) + 1.0 - D,
        D * (Yw / rgb_w[1]) + 1.0 - D,
        D * (Yw / rgb_w[2]) + 1.0 - D
    ])

    # Factors
    n = Yb / Yw
    Nbb = 0.725 * (1.0 / n) ** 0.2
    z = 1.48 + math.sqrt(n)

    # Luminance adaptation factor
    k = 1.0 / (5.0 * La + 1.0)
    k4 = k ** 4
    F_L = k4 * La + 0.1 * (1.0 - k4) ** 2 * (5.0 * La) ** (1.0 / 3.0)

    # Achromatic response of white
    rgb_cw = D_RGB * rgb_w
    rgb_aw = _cam16_post_adapt(rgb_cw, F_L)
    Aw = (2.0 * rgb_aw[0] + rgb_aw[1] + rgb_aw[2] / 20.0 - 0.305) * Nbb

    return CAM16Env(c=c, Nc=Nc, F_L=F_L, n=n, Nbb=Nbb, z=z, Aw=Aw, D_RGB=D_RGB)


def _cam16_post_adapt(rgb: np.ndarray, F_L: float) -> np.ndarray:
    """CAM16 post-adaptation nonlinear compression."""
    sign = np.sign(rgb)
    fl_abs = F_L * np.abs(rgb) / 100.0
    fl_pow = np.power(fl_abs, 0.42)
    return sign * 400.0 * fl_pow / (fl_pow + 27.13) + 0.1


def _cam16_post_adapt_inv(rgb_a: np.ndarray, F_L: float) -> np.ndarray:
    """Inverse CAM16 post-adaptation."""
    t = rgb_a - 0.1
    sign = np.sign(t)
    abs_t = np.abs(t)
    # Avoid division by zero
    denom = np.maximum(400.0 - abs_t, 1e-10)
    return sign * 100.0 / F_L * np.power(27.13 * abs_t / denom, 1.0 / 0.42)


def xyz_to_cam16(
    xyz: np.ndarray,
    env: CAM16Env
) -> dict:
    """
    Convert XYZ to CAM16 appearance correlates.

    Returns dict with keys: J (lightness), C (chroma), h (hue angle),
    Q (brightness), M (colorfulness), s (saturation), a, b.

    Args:
        xyz: XYZ as (3,) array
        env: Pre-computed CAM16 environment
    Returns:
        Dict of appearance correlates
    """
    xyz = np.asarray(xyz, dtype=np.float64)

    # Chromatic adaptation
    rgb = _CAT16 @ xyz
    rgb_c = env.D_RGB * rgb

    # Post-adaptation
    rgb_a = _cam16_post_adapt(rgb_c, env.F_L)

    # Opponent dimensions
    a = rgb_a[0] - 12.0 * rgb_a[1] / 11.0 + rgb_a[2] / 11.0
    b = (rgb_a[0] + rgb_a[1] - 2.0 * rgb_a[2]) / 9.0

    # Hue
    h = math.degrees(math.atan2(b, a)) % 360.0

    # Eccentricity
    h_rad = math.radians(h)
    et = 0.25 * (math.cos(h_rad + 2.0) + 3.8)

    # Achromatic response
    A = (2.0 * rgb_a[0] + rgb_a[1] + rgb_a[2] / 20.0 - 0.305) * env.Nbb

    # Lightness
    J = 100.0 * (A / env.Aw) ** (env.c * env.z)

    # Brightness
    Q = (4.0 / env.c) * math.sqrt(J / 100.0) * (env.Aw + 4.0) * env.F_L ** 0.25

    # Chroma
    t_val = (50000.0 / 13.0 * env.Nc * env.Nbb * et * math.sqrt(a**2 + b**2)) / \
            (rgb_a[0] + rgb_a[1] + 21.0 * rgb_a[2] / 20.0 + 1e-10)
    C = t_val ** 0.9 * math.sqrt(J / 100.0) * (1.64 - 0.29 ** env.n) ** 0.73

    # Colorfulness & saturation
    M = C * env.F_L ** 0.25
    s_val = 100.0 * math.sqrt(M / max(Q, 1e-10))

    return {"J": J, "C": C, "h": h, "Q": Q, "M": M, "s": s_val, "a": a, "b": b}


def cam16_to_xyz(
    J: float,
    C: float,
    h: float,
    env: CAM16Env
) -> np.ndarray:
    """
    Convert CAM16 (J, C, h) back to XYZ.

    Args:
        J: Lightness [0, 100]
        C: Chroma
        h: Hue angle in degrees
        env: Pre-computed CAM16 environment
    Returns:
        XYZ as (3,) array
    """
    if J <= 0:
        return np.array([0.0, 0.0, 0.0])

    h_rad = math.radians(h)
    et = 0.25 * (math.cos(h_rad + 2.0) + 3.8)

    A = env.Aw * (J / 100.0) ** (1.0 / (env.c * env.z))

    t = (C / (math.sqrt(J / 100.0) * (1.64 - 0.29 ** env.n) ** 0.73 + 1e-10)) ** (1.0 / 0.9)

    p1 = 50000.0 / 13.0 * env.Nc * env.Nbb * et
    p2 = A / env.Nbb + 0.305

    sin_h = math.sin(h_rad)
    cos_h = math.cos(h_rad)

    denom = 23.0 * p1 + 11.0 * t * cos_h + 108.0 * t * sin_h
    if abs(denom) < 1e-10:
        denom = 1e-10
    gamma = 23.0 * (p2 - 0.305) * t / denom
    a = gamma * cos_h
    b = gamma * sin_h

    rgb_a = np.array([
        460.0 * p2 / 1403.0 + 451.0 * a / 1403.0 + 288.0 * b / 1403.0,
        460.0 * p2 / 1403.0 - 891.0 * a / 1403.0 - 261.0 * b / 1403.0,
        460.0 * p2 / 1403.0 - 220.0 * a / 1403.0 - 6300.0 * b / 1403.0
    ])

    rgb_c = _cam16_post_adapt_inv(rgb_a, env.F_L)
    rgb = rgb_c / env.D_RGB

    return _CAT16_INV @ rgb


# CAM16-UCS constants
_CAM16_UCS_C1 = 0.007
_CAM16_UCS_C2 = 0.0228


def cam16_to_ucs(J: float, M: float, h: float) -> np.ndarray:
    """
    Convert CAM16 (J, M, h) to CAM16-UCS coordinates (J', a', b').

    CAM16-UCS is the most perceptually uniform space available —
    Euclidean distance in this space corresponds to perceived color difference.
    """
    Jp = (1.0 + 100.0 * _CAM16_UCS_C1) * J / (1.0 + _CAM16_UCS_C1 * J)
    Mp = (1.0 / _CAM16_UCS_C2) * math.log(1.0 + _CAM16_UCS_C2 * M)
    h_rad = math.radians(h)
    ap = Mp * math.cos(h_rad)
    bp = Mp * math.sin(h_rad)
    return np.array([Jp, ap, bp])


def cam16_ucs_delta_e(ucs1: np.ndarray, ucs2: np.ndarray) -> float:
    """Euclidean distance in CAM16-UCS (perceptual color difference)."""
    d = np.asarray(ucs1) - np.asarray(ucs2)
    return float(np.sqrt(np.sum(d ** 2)))


# =============================================================================
# Gamut Boundary Descriptor
# =============================================================================

def compute_gamut_boundary(
    gamut_xyz_to_rgb: np.ndarray,
    lightness_steps: int = 101,
    hue_steps: int = 360,
    illuminant: Illuminant = D65_WHITE
) -> np.ndarray:
    """
    Compute the maximum chroma at each (lightness, hue) for a color gamut.

    Uses binary search in LCH space to find where RGB clips to [0,1].
    Returns a 2D array of shape (lightness_steps, hue_steps) containing
    the max achievable chroma.

    Args:
        gamut_xyz_to_rgb: 3x3 XYZ→RGB matrix for the target gamut
        lightness_steps: Number of L* steps (0-100)
        hue_steps: Number of hue steps (0-360°)
        illuminant: Reference illuminant for Lab
    Returns:
        2D array [L_idx, h_idx] of max chroma values
    """
    ref = np.array([illuminant.X, illuminant.Y, illuminant.Z])
    boundary = np.zeros((lightness_steps, hue_steps), dtype=np.float64)

    for l_idx in range(lightness_steps):
        L = l_idx * 100.0 / (lightness_steps - 1)

        for h_idx in range(hue_steps):
            h_deg = h_idx * 360.0 / hue_steps
            h_rad = math.radians(h_deg)
            cos_h = math.cos(h_rad)
            sin_h = math.sin(h_rad)

            low, high = 0.0, 200.0
            for _ in range(30):  # binary search iterations
                mid = (low + high) / 2.0
                a = mid * cos_h
                b = mid * sin_h

                # LCH → Lab → XYZ
                fy = (L + 16.0) / 116.0
                fx = a / 500.0 + fy
                fz = fy - b / 200.0

                delta = 6.0 / 29.0
                delta_cu = delta ** 3

                xr = fx ** 3 if fx ** 3 > delta_cu else (fx - 4.0 / 29.0) * 3 * delta ** 2
                yr = fy ** 3 if fy ** 3 > delta_cu else (fy - 4.0 / 29.0) * 3 * delta ** 2
                zr = fz ** 3 if fz ** 3 > delta_cu else (fz - 4.0 / 29.0) * 3 * delta ** 2

                xyz_val = np.array([xr * ref[0], yr * ref[1], zr * ref[2]])
                rgb_val = gamut_xyz_to_rgb @ xyz_val

                if np.all(rgb_val >= -0.001) and np.all(rgb_val <= 1.001):
                    low = mid
                else:
                    high = mid

            boundary[l_idx, h_idx] = low

    return boundary


def get_max_chroma(
    boundary: np.ndarray,
    L: float,
    h_deg: float
) -> float:
    """
    Look up maximum chroma from a pre-computed gamut boundary.

    Args:
        boundary: 2D array from compute_gamut_boundary
        L: Lightness [0, 100]
        h_deg: Hue angle in degrees
    Returns:
        Maximum achievable chroma
    """
    l_steps, h_steps = boundary.shape
    L = max(0.0, min(100.0, L))
    h_deg = h_deg % 360.0

    l_idx = L / 100.0 * (l_steps - 1)
    h_idx = h_deg / 360.0 * h_steps

    l0 = int(l_idx)
    l1 = min(l0 + 1, l_steps - 1)
    lt = l_idx - l0

    h0 = int(h_idx) % h_steps
    h1 = (h0 + 1) % h_steps
    ht = h_idx - int(h_idx)

    # Bilinear interpolation
    c00 = boundary[l0, h0]
    c01 = boundary[l0, h1]
    c10 = boundary[l1, h0]
    c11 = boundary[l1, h1]

    c0 = c00 * (1 - ht) + c01 * ht
    c1 = c10 * (1 - ht) + c11 * ht

    return c0 * (1 - lt) + c1 * lt


# =============================================================================
# BT.2390 EETF (Electrical-Electrical Transfer Function)
# =============================================================================

def bt2390_eetf(
    pq_signal: np.ndarray,
    source_peak_nits: float = 10000.0,
    target_peak_nits: float = 1000.0,
    target_black_nits: float = 0.0
) -> np.ndarray:
    """
    BT.2390 EETF — maps HDR PQ signals from a source peak luminance to a
    target display peak luminance using a hermite spline in the PQ domain.

    This is the standard tone-mapping method specified in ITU-R BT.2390 for
    professional HDR workflows. It preserves content below the knee point
    and applies a smooth roll-off above it.

    Args:
        pq_signal: PQ-encoded signal values in [0, 1], any shape.
        source_peak_nits: Source content peak luminance in cd/m² (default 10000).
        target_peak_nits: Target display peak luminance in cd/m² (default 1000).
        target_black_nits: Target display black level in cd/m² (default 0).

    Returns:
        Tone-mapped PQ signal values, same shape as input.
    """
    pq_signal = np.asarray(pq_signal, dtype=np.float64)

    # Step 1: Convert source and target peaks to PQ values
    E_source = float(pq_oetf(np.array([source_peak_nits]))[0])
    E_target = float(pq_oetf(np.array([target_peak_nits]))[0])

    # If target >= source, no tone mapping needed
    if E_target >= E_source:
        return pq_signal.copy()

    # Step 2: Calculate knee point
    KS = 1.5 * E_target - 0.5
    # Clamp KS to valid range
    KS = max(KS, 0.0)

    # Step 3: Apply hermite spline above knee point
    E1 = pq_signal
    E2 = np.copy(E1)

    # Mask for values at or above the knee point (and below source)
    above_knee = E1 >= KS
    if np.any(above_knee):
        E1_above = E1[above_knee]
        denom = E_source - KS
        if denom > 0:
            t = (E1_above - KS) / denom
            # Hermite spline: H(t) = (2t^3 - 3t^2 + 1)*KS
            #                       + (t^3 - 2t^2 + t)*(E_source - KS)
            #                       + (-2t^3 + 3t^2)*E_target
            t2 = t * t
            t3 = t2 * t
            E2[above_knee] = (
                (2.0 * t3 - 3.0 * t2 + 1.0) * KS
                + (t3 - 2.0 * t2 + t) * (E_source - KS)
                + (-2.0 * t3 + 3.0 * t2) * E_target
            )

    # Step 4: Apply black level lift if target_black_nits > 0
    if target_black_nits > 0.0:
        E_black = float(pq_oetf(np.array([target_black_nits]))[0])
        E2 = E2 + E_black * (1.0 - E2)

    return np.clip(E2, 0.0, 1.0)


def gamut_map_chroma_compress(
    lab: np.ndarray,
    boundary: np.ndarray,
    method: str = "compress"
) -> np.ndarray:
    """
    Map an out-of-gamut Lab color into gamut by reducing chroma.

    Args:
        lab: Lab as (3,) array
        boundary: Pre-computed gamut boundary
        method: "clip" (hard), "compress" (soft exponential), or
                "preserve_lightness" (linear scale)
    Returns:
        Gamut-mapped Lab as (3,)
    """
    lab = np.asarray(lab, dtype=np.float64)
    L, a, b = lab[0], lab[1], lab[2]
    C = math.sqrt(a**2 + b**2)
    h = math.degrees(math.atan2(b, a)) % 360.0

    max_C = get_max_chroma(boundary, L, h)

    if C <= max_C:
        return lab.copy()

    if method == "clip":
        new_C = max_C
    elif method == "compress":
        # Soft exponential compression
        new_C = max_C * (1.0 - math.exp(-C / max_C)) / (1.0 - math.exp(-1.0))
    else:  # preserve_lightness
        new_C = max_C

    h_rad = math.radians(h)
    return np.array([L, new_C * math.cos(h_rad), new_C * math.sin(h_rad)])
