"""The chart's signals have to be what its reference Labs become in sRGB.

A ColorChecker entry is a pair: the Lab the patch measures, and the sRGB signal
that drives a display to it. Grading a display means sending the signal and
comparing the reading against the Lab, so the two halves have to be derived from
each other. If they are not, the difference read back is the distance between
two charts, and a display reproducing sRGB exactly is reported as inaccurate.

That is not hypothetical. Three copies of this chart shipped in this package
with ten signals that did not correspond to their Labs, most of them the greys,
and a synthetic display reproducing sRGB exactly graded at 2.27 dE2000 average
and 10.59 maximum against them.

So this module re-derives all twenty-four signals from the Labs, through the
transform written out here rather than through the package's own colour code,
and checks that the shipped table is what falls out. Then it checks that every
other table in the package is the same chart. A test that fixed the numbers once
would not have caught the drift; a test that re-derives them catches it whenever
either half moves.
"""

from __future__ import annotations

import numpy as np
import pytest

from calibrate_pro.calibration import native_loop
from calibrate_pro.core.colorchecker import (
    COLORCHECKER_ORDER,
    COLORCHECKER_PATCHES,
    COLORCHECKER_REF_LAB,
    COLORCHECKER_SRGB,
    OUTSIDE_SRGB,
    SIGNAL_DECIMALS,
    patch_named,
)
from calibrate_pro.sensorless import neuralux
from calibrate_pro.verification import colorchecker as verification_colorchecker
from calibrate_pro.verification import measured_verify, patch_sets, report_generator

# The constants below are the published ones, written out here so this module
# derives the chart independently of the code that produced it.

#: ICC D50, the white the chart's Labs are quoted under.
D50_XYZ = np.array([0.96422, 1.0, 0.82521])

#: CIE D65, the white sRGB is defined against.
D65_XYZ = np.array([0.95047, 1.0, 1.08883])

#: The Bradford cone response matrix, from CIECAM's chromatic adaptation work.
BRADFORD = np.array(
    [
        [0.8951, 0.2664, -0.1614],
        [-0.7502, 1.7135, 0.0367],
        [0.0389, -0.0685, 1.0296],
    ]
)

#: Linear sRGB to XYZ under D65, from IEC 61966-2-1.
SRGB_TO_XYZ = np.array(
    [
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ]
)

#: The CIE Lab kappa and epsilon, as the standard's rational numbers.
KAPPA = 24389 / 27
EPSILON = 216 / 24389


def lab_to_xyz(lab: tuple[float, float, float], white: np.ndarray) -> np.ndarray:
    """CIE Lab to XYZ, by the definition in CIE 15."""
    lightness, a_star, b_star = lab
    f_y = (lightness + 16.0) / 116.0
    f_x = f_y + a_star / 500.0
    f_z = f_y - b_star / 200.0
    x_r = f_x**3 if f_x**3 > EPSILON else (116.0 * f_x - 16.0) / KAPPA
    y_r = ((lightness + 16.0) / 116.0) ** 3 if lightness > KAPPA * EPSILON else lightness / KAPPA
    z_r = f_z**3 if f_z**3 > EPSILON else (116.0 * f_z - 16.0) / KAPPA
    return np.array([x_r, y_r, z_r]) * white


def adapt(xyz: np.ndarray, source: np.ndarray, destination: np.ndarray) -> np.ndarray:
    """Bradford chromatic adaptation between two white points."""
    source_cone = BRADFORD @ source
    destination_cone = BRADFORD @ destination
    scale = np.diag(destination_cone / source_cone)
    return np.linalg.inv(BRADFORD) @ scale @ BRADFORD @ xyz


def encode(linear: float) -> float:
    """The sRGB transfer function, from IEC 61966-2-1."""
    if linear <= 0.0031308:
        return 12.92 * linear
    return 1.055 * linear ** (1.0 / 2.4) - 0.055


def derive(lab: tuple[float, float, float]) -> tuple[tuple[float, float, float], bool]:
    """Return the sRGB signal for one Lab, and whether the gamut held it."""
    xyz_d65 = adapt(lab_to_xyz(lab, D50_XYZ), D50_XYZ, D65_XYZ)
    linear = np.linalg.inv(SRGB_TO_XYZ) @ xyz_d65
    within = bool(np.all(linear >= -1e-9) and np.all(linear <= 1.0 + 1e-9))
    clipped = np.clip(linear, 0.0, 1.0)
    signal = tuple(round(encode(float(channel)), SIGNAL_DECIMALS) for channel in clipped)
    return signal, within  # type: ignore[return-value]


#: How far a stored signal may sit from the re-derivation. The signals are
#: quoted to three decimals, so half a unit in the last place is the whole of
#: the allowance; anything larger is a table that was not derived.
TOLERANCE = 0.5 * 10.0**-SIGNAL_DECIMALS


def as_lab_map(pairs) -> dict[str, tuple[float, float, float]]:
    return {name: tuple(lab) for name, lab in pairs}


def as_signal_map(pairs) -> dict[str, tuple[float, float, float]]:
    return {name: tuple(round(float(channel), 6) for channel in signal) for name, signal in pairs}


CANONICAL_LAB = as_lab_map((patch.name, patch.lab_d50) for patch in COLORCHECKER_PATCHES)
CANONICAL_SIGNAL = as_signal_map((patch.name, patch.srgb) for patch in COLORCHECKER_PATCHES)


# What the chart is ---------------------------------------------------------


def test_the_chart_is_twenty_four_named_patches_in_order() -> None:
    assert len(COLORCHECKER_PATCHES) == 24
    assert len(COLORCHECKER_ORDER) == 24
    assert len(set(COLORCHECKER_ORDER)) == 24
    assert COLORCHECKER_ORDER[0] == "Dark Skin"
    assert COLORCHECKER_ORDER[-1] == "Black"
    assert tuple(COLORCHECKER_REF_LAB) == COLORCHECKER_ORDER
    assert tuple(name for name, *_ in COLORCHECKER_SRGB) == COLORCHECKER_ORDER


def test_every_signal_is_what_its_own_reference_lab_becomes_in_srgb() -> None:
    """The pair, re-derived. This is the assertion the shipped chart failed."""
    for patch in COLORCHECKER_PATCHES:
        expected, _ = derive(patch.lab_d50)
        for channel, (stored, derived) in enumerate(zip(patch.srgb, expected, strict=True)):
            assert abs(stored - derived) <= TOLERANCE, (
                f"{patch.name} channel {channel}: table says {stored}, its Lab derives {derived}"
            )


def test_the_patches_marked_outside_srgb_are_the_ones_the_derivation_clipped() -> None:
    clipped = {patch.name for patch in COLORCHECKER_PATCHES if not derive(patch.lab_d50)[1]}
    assert clipped == OUTSIDE_SRGB
    assert clipped == {"Cyan"}, "a change here changes what a measured average is taken over"


def test_the_neutral_ramp_is_not_grey_in_srgb() -> None:
    """The signature of the defect this chart replaced.

    A printed grey is not exactly neutral, and the chart quotes it against a
    different white than the signal drives. So a derived neutral has unequal
    channels, tilted the way its own b* is tilted: the five darker greys measure
    slightly blue and carry more blue than red, and White measures slightly
    yellow and carries less. The tables that shipped had equal channels on all
    six, which is what put 10.59 dE2000 on Black.
    """
    for name in ("White", "Neutral 8", "Neutral 6.5", "Neutral 5", "Neutral 3.5", "Black"):
        red, _, blue = patch_named(name).srgb
        b_star = COLORCHECKER_REF_LAB[name][2]
        assert red != blue, f"{name} is grey in the signal, so it was not derived"
        assert (blue > red) == (b_star < 0), (
            f"{name} has b* {b_star} but its signal tilts the other way: red {red}, blue {blue}"
        )


def test_black_is_the_patch_the_old_tables_got_most_wrong() -> None:
    """A named regression, because this one patch cost 10.59 dE2000."""
    assert patch_named("Black").srgb == (0.191, 0.194, 0.199)
    assert patch_named("Black").lab_d50 == (20.461, -0.079, -0.973)


def test_asking_for_a_patch_the_chart_does_not_carry_is_refused() -> None:
    with pytest.raises(KeyError):
        patch_named("Dark Sky")


# What the gate would catch -------------------------------------------------


def test_a_signal_that_stopped_matching_its_reference_fails_this_derivation() -> None:
    """The false-success control.

    Without it, a re-derivation that silently agreed with anything would pass on
    a broken chart and read as proof. These are the values the package shipped.
    """
    for name, shipped in (
        ("Black", (0.085, 0.085, 0.085)),
        ("Neutral 3.5", (0.258, 0.258, 0.258)),
        ("Red", (0.752, 0.197, 0.178)),
        ("Cyan", (0.121, 0.544, 0.659)),
    ):
        derived, _ = derive(COLORCHECKER_REF_LAB[name])
        assert any(abs(a - b) > TOLERANCE for a, b in zip(shipped, derived, strict=True)), (
            f"{name}: the derivation accepted a signal that does not correspond to its Lab"
        )


# One chart, everywhere -----------------------------------------------------


def test_the_calibration_loop_grades_against_the_canonical_chart() -> None:
    assert as_lab_map(native_loop.COLORCHECKER_REF_LAB.items()) == CANONICAL_LAB
    assert as_signal_map((name, (r, g, b)) for name, r, g, b in native_loop.COLORCHECKER_SRGB) == CANONICAL_SIGNAL


def test_the_sensorless_engine_grades_against_the_canonical_chart() -> None:
    assert as_lab_map((p.name, p.lab_d50) for p in neuralux.COLORCHECKER_CLASSIC) == CANONICAL_LAB
    assert as_signal_map((p.name, p.srgb) for p in neuralux.COLORCHECKER_CLASSIC) == CANONICAL_SIGNAL


def test_the_measured_verify_workflow_grades_against_the_canonical_chart() -> None:
    assert as_lab_map(measured_verify.COLORCHECKER_REFERENCE_LAB_D50.items()) == CANONICAL_LAB
    assert as_signal_map(measured_verify.COLORCHECKER_SRGB_PATCHES) == CANONICAL_SIGNAL


def test_the_patch_sets_registry_carries_the_canonical_chart() -> None:
    assert as_lab_map(patch_sets.COLORCHECKER_CLASSIC_LAB_D50.items()) == CANONICAL_LAB
    assert as_signal_map((p.name, (p.r, p.g, p.b)) for p in patch_sets.COLORCHECKER_CLASSIC) == CANONICAL_SIGNAL


def test_the_report_generator_draws_the_canonical_chart() -> None:
    assert as_signal_map(report_generator.COLORCHECKER_SRGB.items()) == CANONICAL_SIGNAL


def test_the_verification_module_keys_the_canonical_chart_by_id() -> None:
    """Same chart, identified by id rather than by display name."""
    names = verification_colorchecker.COLORCHECKER_CLASSIC_NAMES
    assert as_lab_map((names[key], lab) for key, lab in verification_colorchecker.COLORCHECKER_CLASSIC_D50.items()) == (
        CANONICAL_LAB
    )
    assert [names[key] for key in verification_colorchecker.COLORCHECKER_CLASSIC_ORDER] == list(COLORCHECKER_ORDER)
