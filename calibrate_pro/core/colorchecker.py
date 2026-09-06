"""The reference chart every verification in this package compares against.

The chart is the twenty-four patch ColorChecker Classic. Each entry carries two
things: the Lab the patch measures under D50, which is X-Rite's published
number for the physical chart, and the sRGB signal that drives a display to it.

The signal is not an independent measurement. It is what the Lab becomes when
it is taken through the sRGB specification backwards: Lab under D50 to XYZ under
D50, Bradford-adapted to the D65 white sRGB is defined against, through the
inverse sRGB primaries matrix to linear RGB, and encoded with the piecewise
transfer function from IEC 61966-2-1. Deriving it is what makes the pair
meaningful. A signal that came from somewhere else would grade a display against
the difference between two charts rather than against the error in its
calibration, and the display would be reported as wrong for reproducing exactly
what it was sent.

This package held five copies of the pair. Three of them had drifted on the same
ten patches, most of them the greys an operator looks at first, and a display
reproducing sRGB exactly graded at 2.27 dE2000 average and 10.59 maximum against
them. Against this table the same display grades at 0.05 average and 0.13
maximum, which is the rounding in three-decimal signals rather than an error the
chart introduces. Give that display a pure 2.2 power law instead of the sRGB
curve and it grades at 0.55 and 1.15, and the difference is the curve, not the
chart. The copies are gone and ``tests/test_colorchecker_reference.py``
re-derives every signal here from its own Lab, so the pair cannot drift apart
again without a test saying so.

One patch of the twenty-four lies outside the sRGB gamut. Cyan wants a negative
red component, so its signal is the clipped one and no display driven in sRGB
can reach its reference. The difference that leaves is a property of the chart
rather than of the calibration, which is why the patch is named here and why
what consumes this table has to decide what to do about it rather than folding
2.8 dE2000 of unreachable colour into an accuracy figure.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class ColorCheckerPatch:
    """One chart patch, and whether a display driven in sRGB can reach it."""

    name: str
    #: X-Rite's published Lab for the physical patch, under D50.
    lab_d50: tuple[float, float, float]
    #: The sRGB signal derived from that Lab, clipped into range if it had to be.
    srgb: tuple[float, float, float]
    #: False when the derivation clipped, meaning the signal below is the
    #: closest sRGB can come rather than the colour the reference names.
    within_srgb: bool = True


COLORCHECKER_PATCHES: tuple[ColorCheckerPatch, ...] = (
    ColorCheckerPatch("Dark Skin", (37.986, 13.555, 14.059), (0.453, 0.317, 0.264)),
    ColorCheckerPatch("Light Skin", (65.711, 18.130, 17.810), (0.779, 0.577, 0.505)),
    ColorCheckerPatch("Blue Sky", (49.927, -4.880, -21.925), (0.355, 0.480, 0.611)),
    ColorCheckerPatch("Foliage", (43.139, -13.095, 21.905), (0.352, 0.422, 0.253)),
    ColorCheckerPatch("Blue Flower", (55.112, 8.844, -25.399), (0.508, 0.502, 0.691)),
    ColorCheckerPatch("Bluish Green", (70.719, -33.397, -0.199), (0.362, 0.745, 0.675)),
    ColorCheckerPatch("Orange", (62.661, 36.067, 57.096), (0.879, 0.485, 0.183)),
    ColorCheckerPatch("Purplish Blue", (40.020, 10.410, -45.964), (0.266, 0.358, 0.667)),
    ColorCheckerPatch("Moderate Red", (51.124, 48.239, 16.248), (0.778, 0.321, 0.381)),
    ColorCheckerPatch("Purple", (30.325, 22.976, -21.587), (0.367, 0.227, 0.414)),
    ColorCheckerPatch("Yellow Green", (72.532, -23.709, 57.255), (0.623, 0.741, 0.246)),
    ColorCheckerPatch("Orange Yellow", (71.941, 19.363, 67.857), (0.904, 0.634, 0.154)),
    ColorCheckerPatch("Blue", (28.778, 14.179, -50.297), (0.139, 0.248, 0.577)),
    ColorCheckerPatch("Green", (55.261, -38.342, 31.370), (0.262, 0.584, 0.291)),
    ColorCheckerPatch("Red", (42.101, 53.378, 28.190), (0.705, 0.191, 0.223)),
    ColorCheckerPatch("Yellow", (81.733, 4.039, 79.819), (0.934, 0.778, 0.077)),
    ColorCheckerPatch("Magenta", (51.935, 49.986, -14.574), (0.757, 0.329, 0.590)),
    # Wants a red component of -0.037 in linear sRGB. Clipped to zero, which
    # leaves 2.8 dE2000 no display driven in sRGB can close.
    ColorCheckerPatch("Cyan", (51.038, -28.631, -28.638), (0.000, 0.534, 0.665), within_srgb=False),
    ColorCheckerPatch("White", (96.539, -0.425, 1.186), (0.961, 0.962, 0.952)),
    ColorCheckerPatch("Neutral 8", (81.257, -0.638, -0.335), (0.786, 0.793, 0.794)),
    ColorCheckerPatch("Neutral 6.5", (66.766, -0.734, -0.504), (0.630, 0.639, 0.640)),
    ColorCheckerPatch("Neutral 5", (50.867, -0.153, -0.270), (0.473, 0.475, 0.477)),
    ColorCheckerPatch("Neutral 3.5", (35.656, -0.421, -1.231), (0.323, 0.330, 0.336)),
    ColorCheckerPatch("Black", (20.461, -0.079, -0.973), (0.191, 0.194, 0.199)),
)

#: How many decimal places the signals above are quoted to. A signal rounded
#: here costs an ideal display up to 0.14 dE2000, which is the floor the
#: reference test allows and well under what a panel contributes.
SIGNAL_DECIMALS = 3

#: Named rather than counted, so a consumer excluding them from an aggregate
#: says which patch it excluded instead of reporting a smaller total.
OUTSIDE_SRGB: frozenset[str] = frozenset(patch.name for patch in COLORCHECKER_PATCHES if not patch.within_srgb)

#: The order the chart is walked in, left to right and top to bottom.
COLORCHECKER_ORDER: tuple[str, ...] = tuple(patch.name for patch in COLORCHECKER_PATCHES)

#: Lab under D50, keyed by patch name.
COLORCHECKER_REF_LAB: Mapping[str, tuple[float, float, float]] = MappingProxyType(
    {patch.name: patch.lab_d50 for patch in COLORCHECKER_PATCHES}
)

#: Name and signal flattened, in chart order, for a loop that shows patches.
COLORCHECKER_SRGB: tuple[tuple[str, float, float, float], ...] = tuple(
    (patch.name, patch.srgb[0], patch.srgb[1], patch.srgb[2]) for patch in COLORCHECKER_PATCHES
)


def patch_named(name: str) -> ColorCheckerPatch:
    """Return one patch by name, refusing a name the chart does not carry."""
    for patch in COLORCHECKER_PATCHES:
        if patch.name == name:
            return patch
    raise KeyError(f"the ColorChecker chart has no patch named {name!r}")


__all__ = [
    "COLORCHECKER_ORDER",
    "COLORCHECKER_PATCHES",
    "COLORCHECKER_REF_LAB",
    "COLORCHECKER_SRGB",
    "OUTSIDE_SRGB",
    "SIGNAL_DECIMALS",
    "ColorCheckerPatch",
    "patch_named",
]
