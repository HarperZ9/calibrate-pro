"""Expected patch values and colour differences against an achievable target.

SDR differences are CIEDE2000 in CIELAB whose reference white is the target
white, so a luminance miss on white shows up as an L* error. HDR differences
use Delta E ITP from Rec. ITU-R BT.2124-0, where 1 is a just noticeable
difference under the most sensitive adaptation.
"""

from __future__ import annotations

import numpy as np

from calibrate_pro.calibration.closed_loop.intent import GAMUTS, AchievableTarget
from calibrate_pro.core.color_math import (
    Illuminant,
    bt1886_eotf,
    delta_e_2000,
    primaries_to_xyz_matrix,
    srgb_gamma_expand,
    xyz_abs_to_ictcp,
    xyz_to_lab,
)

RGB = tuple[float, float, float]


def xy_to_xyz(xy: tuple[float, float], luminance: float) -> np.ndarray:
    """Return absolute XYZ for a chromaticity at a luminance."""
    x, y = xy
    return np.array([x / y * luminance, luminance, (1.0 - x - y) / y * luminance])


def xyz_to_xy(xyz: np.ndarray) -> tuple[float, float]:
    total = float(np.sum(xyz))
    if total <= 0.0:
        raise ValueError("XYZ with no light has no chromaticity")
    return (float(xyz[0]) / total, float(xyz[1]) / total)


def target_white_xyz(target: AchievableTarget) -> np.ndarray:
    return xy_to_xyz(target.white_xy, target.white_luminance)


def _normalized_eotf(target: AchievableTarget, signal: np.ndarray) -> np.ndarray:
    """Per-channel display light relative to target white, for SDR EOTFs."""
    intent = target.intent
    if intent.eotf == "srgb":
        return np.asarray(srgb_gamma_expand(signal), dtype=np.float64)
    if intent.eotf == "gamma":
        return np.power(np.clip(signal, 0.0, 1.0), intent.gamma)
    if intent.eotf == "bt1886":
        light = bt1886_eotf(signal, intent.gamma, target.white_luminance, target.black_luminance)
        return np.asarray(light, dtype=np.float64) / target.white_luminance
    raise NotImplementedError(f"expected-value model for {intent.eotf!r} is not built in this slice")


def target_patch_xyz(target: AchievableTarget, rgb: RGB) -> np.ndarray:
    """Return the absolute XYZ the target asks for at one signal triplet."""
    primaries = GAMUTS[target.intent.gamut]
    matrix = primaries_to_xyz_matrix(primaries[0], primaries[1], primaries[2], target.white_xy)
    light = _normalized_eotf(target, np.asarray(rgb, dtype=np.float64))
    return np.asarray(matrix @ light, dtype=np.float64) * target.white_luminance


def target_patch_xy(target: AchievableTarget, rgb: RGB) -> tuple[float, float]:
    return xyz_to_xy(target_patch_xyz(target, rgb))


def _reference_white(target: AchievableTarget) -> Illuminant:
    white = target_white_xyz(target) / target.white_luminance
    return Illuminant("target", float(white[0]), 1.0, float(white[2]), 0)


def delta_e_relative(target: AchievableTarget, measured: np.ndarray, expected: np.ndarray) -> float:
    """CIEDE2000 between two absolute XYZ values, relative to target white."""
    scale = target.white_luminance
    white = _reference_white(target)
    lab_measured = xyz_to_lab(np.asarray(measured, dtype=np.float64) / scale, white)
    lab_expected = xyz_to_lab(np.asarray(expected, dtype=np.float64) / scale, white)
    return float(delta_e_2000(lab_measured, lab_expected))


def delta_e_itp(measured: np.ndarray, expected: np.ndarray) -> float:
    """Delta E ITP between two absolute XYZ values, Rec. ITU-R BT.2124-0."""
    first = xyz_abs_to_ictcp(np.asarray(measured, dtype=np.float64))
    second = xyz_abs_to_ictcp(np.asarray(expected, dtype=np.float64))
    di = float(first[0] - second[0])
    dt = 0.5 * float(first[1] - second[1])
    dp = float(first[2] - second[2])
    return 720.0 * float(np.sqrt(di * di + dt * dt + dp * dp))


def luminance_error(target: AchievableTarget, measured: np.ndarray) -> float:
    """Relative luminance miss of a white reading against target white."""
    return abs(float(measured[1]) - target.white_luminance) / target.white_luminance


__all__ = [
    "delta_e_itp",
    "delta_e_relative",
    "luminance_error",
    "target_patch_xy",
    "target_patch_xyz",
    "target_white_xyz",
    "xy_to_xyz",
    "xyz_to_xy",
]
