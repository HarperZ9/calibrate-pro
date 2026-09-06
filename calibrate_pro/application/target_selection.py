"""Which calibration target an operator can select, and what each one means.

Until 2.0.0 a session could pick one of four presets. The four action ids
``calibration.target.gamut``, ``.whitepoint``, ``.custom_cct`` and ``.gamma``
were declared in the manifest and resolved enabled, and nothing bound them, so
the reference catalogue listed gamuts and white points that could not be asked
for. This module is what makes them askable.

A target is three independent choices plus an HDR flag. A preset is a name for
one combination of them, and a composed target names the combination directly::

    calibration.target.custom/<gamut>/<white>/<tone>

``/`` separates the parts because it cannot reach a filename: an
:class:`~calibrate_pro.application.assets.AssetRequest` builds every output
name from its own ``basename``, never from the target id, and a ``/`` would be
refused by ``basename`` validation if it ever did.

Every entry below is one this build applies end to end. That is the whole
constraint on what may be listed. A gamut reaches the cube as primaries, a
white point reaches the cube, the profile and the gamma table as a
chromaticity, and a tone response reaches all three as a curve. Nothing here
is a name the interface offers and the arithmetic ignores, because a target
that does not reach the correction is a declared value wearing the appearance
of a computed one, and this package refuses to ship that.

Two names the gamut catalogue carries are deliberately absent. ``DCI-P3
Theater`` holds the same primaries as ``DCI-P3`` and differs only by its white
point and tone response, which are now separate axes, so offering it here
would promise two things this axis does not carry. HDR transfer functions are
absent for the reason ``calibration.target.hdr`` is declared closed: PQ and HLG
answer in absolute luminance, and normalising either into an SDR signal would
describe an HDR curve while applying an SDR one.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TypeVar

from calibrate_pro.calibration.targets import D50, D63_DCI, D65
from calibrate_pro.core.tone_response import L_STAR, SRGB, ToneResponse, power_law
from calibrate_pro.targets.whitepoint import ILLUMINANT_XY, cct_to_xy

#: Prefix of a composed target id. A preset id is not built from this.
CUSTOM_TARGET_PREFIX = "calibration.target.custom"

#: Where a custom colour temperature may land. Below 4000 K the resolver would
#: leave the daylight locus for the Planckian one, which is a different white
#: for the same number, and above 10000 K no display target asks for it. The
#: bound is on the choice rather than on the arithmetic, which is defined out
#: to 25000 K.
CUSTOM_CCT_MIN_K = 4000
CUSTOM_CCT_MAX_K = 10000


class TargetSelectionError(ValueError):
    """A target id names something this build does not carry."""


#: Preset id to (gamut, white point, tone response, HDR). The labels are what
#: the manifest and the apply plan report, so they are the operator-facing
#: spelling rather than a slug.
PRESET_TARGETS: Mapping[str, tuple[str, str, str, bool]] = MappingProxyType(
    {
        "calibration.preset.srgb_web": ("sRGB", "D65", "2.2", False),
        "calibration.preset.rec709": ("Rec.709", "D65", "BT.1886", False),
        "calibration.preset.dci_p3": ("DCI-P3", "D65", "2.4", False),
        "calibration.preset.photography": ("sRGB", "D50", "2.2", False),
    }
)

#: Gamut label to the mode :meth:`SensorlessEngine.create_3d_lut` takes.
#: ``sRGB`` and ``Rec.709`` share primaries exactly and share the engine's
#: dedicated sRGB path; they are listed separately because a bundle labelled
#: for broadcast and a bundle labelled for the web are not the same document.
GAMUT_MODES: Mapping[str, str] = MappingProxyType(
    {
        "Native": "native",
        "sRGB": "sRGB",
        "Rec.709": "sRGB",
        "DCI-P3": "DCI-P3",
        "Display P3": "Display P3",
        "Adobe RGB": "Adobe RGB",
        "BT.2020": "BT.2020",
        "ProPhoto RGB": "ProPhoto RGB",
        "ACEScg": "ACEScg",
        "NTSC 1953": "NTSC 1953",
        "PAL/SECAM": "PAL/SECAM",
    }
)

#: White-point label to the chromaticity the correction drives to. D65, D50
#: and D63 keep the constants the shipped presets were sealed against; the
#: rest come from the illuminant table. The two sources agree to four decimal
#: places, which is an order of magnitude inside the tolerance the target
#: catalogue asks for, and using the sealed constants keeps every preset
#: bundle byte-identical across this change.
TARGET_WHITES: Mapping[str, tuple[float, float]] = MappingProxyType(
    {
        "D65": D65,
        "D50": D50,
        "D63": D63_DCI,
        "D55": ILLUMINANT_XY["D55"],
        "D60": ILLUMINANT_XY["D60"],
        "D75": ILLUMINANT_XY["D75"],
        "D93": ILLUMINANT_XY["D93"],
    }
)

#: Tone-response label to the curve applied. ``BT.1886`` is spelled as a 2.4
#: power law rather than as the BT.1886 kind because BT.1886 at a zero black
#: level is exactly that power law, and the power-law path reaches it in one
#: call to :func:`numpy.power` where the curve path takes two.
TONE_RESPONSES: Mapping[str, ToneResponse] = MappingProxyType(
    {
        "1.8": power_law(1.8),
        "2.0": power_law(2.0),
        "2.2": power_law(2.2),
        "2.4": power_law(2.4),
        "2.6": power_law(2.6),
        "BT.1886": power_law(2.4, label="BT.1886"),
        "sRGB": ToneResponse(label="sRGB", kind=SRGB),
        "L*": ToneResponse(label="L*", kind=L_STAR),
    }
)

#: Tone-response label to the power-law exponent. For a curve this is the
#: exponent that comes closest, reported and never applied.
TONE_RESPONSE_EXPONENTS: Mapping[str, float] = MappingProxyType(
    {label: tone.nominal_exponent for label, tone in TONE_RESPONSES.items()}
)

#: Slug to label, per axis. Written out rather than derived from the labels so
#: that renaming a label cannot silently change what a stored target id means.
GAMUT_SLUGS: Mapping[str, str] = MappingProxyType(
    {
        "native": "Native",
        "srgb": "sRGB",
        "rec709": "Rec.709",
        "dci-p3": "DCI-P3",
        "display-p3": "Display P3",
        "adobe-rgb": "Adobe RGB",
        "bt2020": "BT.2020",
        "prophoto-rgb": "ProPhoto RGB",
        "acescg": "ACEScg",
        "ntsc1953": "NTSC 1953",
        "pal-secam": "PAL/SECAM",
    }
)

WHITE_SLUGS: Mapping[str, str] = MappingProxyType(
    {"d50": "D50", "d55": "D55", "d60": "D60", "d63": "D63", "d65": "D65", "d75": "D75", "d93": "D93"}
)

TONE_SLUGS: Mapping[str, str] = MappingProxyType(
    {
        "g1.8": "1.8",
        "g2.0": "2.0",
        "g2.2": "2.2",
        "g2.4": "2.4",
        "g2.6": "2.6",
        "bt1886": "BT.1886",
        "srgb": "sRGB",
        "lstar": "L*",
    }
)

_Resolved = TypeVar("_Resolved")


def resolve_part(known: Mapping[str, _Resolved], label: str, part: str) -> _Resolved:
    """Translate one part of a declared target, refusing a label nothing maps.

    A default here is how a target stops reaching the correction. The white
    point defaulted to D65, so a D50 request produced a D65 correction while
    the plan line, the manifest and the bundle all still said D50. Every
    surface reported the target and only the arithmetic disagreed, which is
    the one failure this package cannot ship: a declared value presented as a
    property of a computed artifact.

    Refusing instead means a target added to the catalogue without a
    translation fails at generation rather than producing a bundle labelled
    for one target and corrected for another.
    """
    resolved = known.get(label)
    if resolved is None:
        raise TargetSelectionError(
            f"This build cannot generate for a {part} of {label!r}. It carries {', '.join(sorted(known))}."
        )
    return resolved


@dataclass(frozen=True)
class CalibrationTarget:
    """One target, in both the words a reader sees and the units a generator takes.

    Built in one place so the cube, the gamma table and the profile are aimed
    by the same values. Splitting the translation is how a bundle came to hold
    a D50 manifest beside a D65 correction.
    """

    target_id: str
    gamut_label: str
    white_label: str
    tone_label: str
    hdr: bool
    gamut_mode: str
    white: tuple[float, float]
    tone: ToneResponse

    @property
    def label(self) -> str:
        """The three choices in one string, as a profile description shows them."""
        return f"{self.gamut_label} {self.white_label} {self.tone_label}"

    @property
    def exponent(self) -> float:
        """The power law applied, or for a curve the one that comes closest."""
        return self.tone.nominal_exponent

    @property
    def engine_tone(self) -> ToneResponse | None:
        """The curve to hand a generator, or ``None`` when the exponent says it all.

        A power law goes through as its exponent. Both routes reach the same
        numbers, and the exponent route is the one every shipped preset bundle
        is digest-sealed against.
        """
        return None if self.tone.is_power_law else self.tone


def compose_target_id(gamut_slug: str, white_slug: str, tone_slug: str) -> str:
    """Build the id for one composed target, refusing a slug no axis carries."""
    for slug, known, axis in (
        (gamut_slug, GAMUT_SLUGS, "gamut"),
        (tone_slug, TONE_SLUGS, "tone response"),
    ):
        if slug not in known:
            raise TargetSelectionError(
                f"This build carries no {axis} named {slug!r}. It carries {', '.join(sorted(known))}."
            )
    _white_label(white_slug)
    return f"{CUSTOM_TARGET_PREFIX}/{gamut_slug}/{white_slug}/{tone_slug}"


def custom_cct_slug(kelvin: int) -> str:
    """Name a colour temperature that is not a standard illuminant."""
    if not isinstance(kelvin, int) or isinstance(kelvin, bool):
        raise TargetSelectionError("a custom colour temperature must be a whole number of kelvin")
    if not CUSTOM_CCT_MIN_K <= kelvin <= CUSTOM_CCT_MAX_K:
        raise TargetSelectionError(
            f"{kelvin} K is outside the {CUSTOM_CCT_MIN_K}-{CUSTOM_CCT_MAX_K} K range this build calibrates to."
        )
    return f"cct{kelvin}"


def _white_label(slug: str) -> str:
    """Read a white-point slug, whether it names an illuminant or a temperature.

    A temperature keeps its own label. For the daylight series the two agree
    closely: the locus reproduces D50, D55, D60, D65, D75 and D93 to within
    0.0002 in xy, well inside the 0.003 the catalogue asks for, so calling
    6500 K D65 would be a naming choice rather than a wrong number.

    D63 is the case that makes the separation load-bearing. It is the DCI
    projector white at 0.3140, 0.3510, it is not a daylight illuminant, and
    6300 K on the locus lands 0.0185 away in y. An operator asking for a
    temperature and one asking for the DCI white are asking for two different
    whites, and a bundle that answered either with the other would declare a
    target its cube does not drive to.
    """
    if slug in WHITE_SLUGS:
        return WHITE_SLUGS[slug]
    if slug.startswith("cct"):
        digits = slug[3:]
        if digits.isdigit():
            kelvin = int(digits)
            if CUSTOM_CCT_MIN_K <= kelvin <= CUSTOM_CCT_MAX_K:
                return f"{kelvin}K"
    raise TargetSelectionError(
        f"This build carries no white point named {slug!r}. It carries "
        f"{', '.join(sorted(WHITE_SLUGS))}, and cct4000 through cct10000."
    )


def _white_xy(label: str) -> tuple[float, float]:
    if label in TARGET_WHITES:
        return TARGET_WHITES[label]
    return cct_to_xy(float(label[:-1]))


def is_custom_target_id(value: object) -> bool:
    """Whether a value is a composed target id this build can resolve."""
    if not isinstance(value, str) or not value.startswith(CUSTOM_TARGET_PREFIX + "/"):
        return False
    try:
        resolve_target(value)
    except TargetSelectionError:
        return False
    return True


def is_target_id(value: object) -> bool:
    """Whether a value names a target, preset or composed."""
    return value in PRESET_TARGETS or is_custom_target_id(value)


def resolve_target(target_id: str) -> CalibrationTarget:
    """Translate a target id into the units every generator takes.

    Accepts a preset id or a composed one. Both come back as the same value,
    so no caller downstream has to know which kind it was handed.
    """
    if not isinstance(target_id, str):
        raise TargetSelectionError(f"a target id must be a string, not {type(target_id).__name__}")
    preset = PRESET_TARGETS.get(target_id)
    if preset is not None:
        gamut_label, white_label, tone_label, hdr = preset
    else:
        gamut_label, white_label, tone_label, hdr = _parse_custom(target_id)
    return CalibrationTarget(
        target_id=target_id,
        gamut_label=gamut_label,
        white_label=white_label,
        tone_label=tone_label,
        hdr=hdr,
        gamut_mode=resolve_part(GAMUT_MODES, gamut_label, "gamut"),
        white=_white_xy(white_label),
        tone=resolve_part(TONE_RESPONSES, tone_label, "tone response"),
    )


def _parse_custom(target_id: str) -> tuple[str, str, str, bool]:
    prefix, _, rest = target_id.partition("/")
    if prefix != CUSTOM_TARGET_PREFIX:
        raise TargetSelectionError(f"unknown calibration target: {target_id!r}")
    parts = rest.split("/")
    if len(parts) != 3 or not all(parts):
        raise TargetSelectionError(
            f"a composed target is {CUSTOM_TARGET_PREFIX}/<gamut>/<white point>/<tone response>, not {target_id!r}"
        )
    gamut_slug, white_slug, tone_slug = parts
    if gamut_slug not in GAMUT_SLUGS:
        raise TargetSelectionError(
            f"This build carries no gamut named {gamut_slug!r}. It carries {', '.join(sorted(GAMUT_SLUGS))}."
        )
    if tone_slug not in TONE_SLUGS:
        raise TargetSelectionError(
            f"This build carries no tone response named {tone_slug!r}. It carries {', '.join(sorted(TONE_SLUGS))}."
        )
    return (GAMUT_SLUGS[gamut_slug], _white_label(white_slug), TONE_SLUGS[tone_slug], False)


def selectable_gamuts() -> tuple[tuple[str, str], ...]:
    """Every gamut an operator may choose, as (slug, label), in catalogue order."""
    return tuple(GAMUT_SLUGS.items())


def selectable_white_points() -> tuple[tuple[str, str], ...]:
    """Every named white point an operator may choose, as (slug, label)."""
    return tuple(WHITE_SLUGS.items())


def selectable_tone_responses() -> tuple[tuple[str, str], ...]:
    """Every tone response an operator may choose, as (slug, label)."""
    return tuple(TONE_SLUGS.items())


__all__ = [
    "CUSTOM_CCT_MAX_K",
    "CUSTOM_CCT_MIN_K",
    "CUSTOM_TARGET_PREFIX",
    "CalibrationTarget",
    "GAMUT_MODES",
    "GAMUT_SLUGS",
    "PRESET_TARGETS",
    "TARGET_WHITES",
    "TONE_RESPONSES",
    "TONE_RESPONSE_EXPONENTS",
    "TONE_SLUGS",
    "TargetSelectionError",
    "WHITE_SLUGS",
    "compose_target_id",
    "custom_cct_slug",
    "is_custom_target_id",
    "is_target_id",
    "resolve_part",
    "resolve_target",
    "selectable_gamuts",
    "selectable_tone_responses",
    "selectable_white_points",
]
