"""Display intent: one target description for SDR, HDR and any panel.

A `DisplayIntent` says what the user wants: white point, white and black
luminance, transfer function, gamut with a coverage goal, and tolerances per
patch class. A `PanelCapability` says what a panel can do, measured or declared.
`resolve_intent` clips the intent into an `AchievableTarget` and reports every
clip, so the loop chases what the panel can reach and the report says what it
gave up. Nothing here touches hardware.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from calibrate_pro.calibration.closed_loop import gamut
from calibrate_pro.verification.provenance import EvidenceKind

D65_XY = (0.3127, 0.3290)

#: Primary chromaticities by gamut name. BT.709 and BT.2020 values are from
#: Rec. ITU-R BT.709-6 and BT.2020-2. Display P3 uses the DCI-P3 primaries
#: with a D65 white.
GAMUTS: dict[str, gamut.Triangle] = {
    "srgb": ((0.640, 0.330), (0.300, 0.600), (0.150, 0.060)),
    "display_p3": ((0.680, 0.320), (0.265, 0.690), (0.150, 0.060)),
    "bt2020": ((0.708, 0.292), (0.170, 0.797), (0.131, 0.046)),
}

SDR_EOTFS = ("srgb", "gamma", "bt1886")
HDR_EOTFS = ("pq", "hlg")

#: Share of measured peak kept in reserve, so white balance has gain room.
PEAK_HEADROOM = 0.02

#: HDR Reference White, Rec. ITU-R BT.2100-3 Note 10a.
HDR_REFERENCE_WHITE = 203.0


@dataclass(frozen=True)
class Tolerances:
    """Pass bounds per patch class. ITP bounds apply to HDR intents."""

    white_de2000: float = 1.0
    gray_de2000: float = 2.0
    color_de2000: float = 3.0
    white_de_itp: float = 5.0
    gray_de_itp: float = 8.0
    color_de_itp: float = 10.0
    luminance_relative: float = 0.03

    def __post_init__(self) -> None:
        for name, value in self.__dict__.items():
            if not isinstance(value, float) or not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"tolerance {name} must be a positive finite float")


@dataclass(frozen=True)
class DisplayIntent:
    """What the user asks the display to be, before any panel is considered."""

    name: str
    white_luminance: float
    eotf: str = "gamma"
    gamma: float = 2.2
    white_xy: tuple[float, float] = D65_XY
    black_luminance: float = 0.0
    gamut: str = "srgb"
    min_gamut_coverage: float = 0.95
    tolerances: Tolerances = field(default_factory=Tolerances)
    #: Reserved for a per-viewer observer adjustment. Only the CIE 1931 2
    #: degree observer is implemented.
    observer: str = "cie1931_2deg"

    def __post_init__(self) -> None:
        if self.eotf not in SDR_EOTFS + HDR_EOTFS:
            raise ValueError(f"unknown EOTF {self.eotf!r}")
        if self.gamut not in GAMUTS:
            raise ValueError(f"unknown gamut {self.gamut!r}")
        if not 0.0 < self.white_luminance <= 10_000.0:
            raise ValueError("white_luminance must be within (0, 10000] cd/m2")
        if not 0.0 <= self.black_luminance < self.white_luminance:
            raise ValueError("black_luminance must be non-negative and below white")
        if not 0.0 < self.min_gamut_coverage <= 1.0:
            raise ValueError("min_gamut_coverage must be within (0, 1]")
        if self.observer != "cie1931_2deg":
            raise ValueError("only the cie1931_2deg observer is implemented")

    @property
    def is_hdr(self) -> bool:
        return self.eotf in HDR_EOTFS


@dataclass(frozen=True)
class PanelCapability:
    """What one panel can do, with the evidence kind of the numbers."""

    peak_luminance: float
    contrast_ratio: float
    primaries_xy: gamut.Triangle
    native_white_xy: tuple[float, float]
    evidence: EvidenceKind
    source: str


@dataclass(frozen=True)
class Clip:
    """One place the intent was changed to fit the panel."""

    field: str
    requested: float
    achievable: float
    unit: str
    reason: str
    evidence: EvidenceKind


@dataclass(frozen=True)
class AchievableTarget:
    """The target the loop chases, and every clip that produced it."""

    intent: DisplayIntent
    white_xy: tuple[float, float]
    white_luminance: float
    black_luminance: float
    gamut_coverage: float | None
    hlg_system_gamma: float | None
    clips: tuple[Clip, ...]


def hlg_system_gamma(peak: float) -> float:
    """System gamma for an HLG display, Rec. ITU-R BT.2100-3 Note 5f."""
    return 1.2 + 0.42 * math.log10(peak / 1000.0)


def _clip_luminance(intent: DisplayIntent, cap: PanelCapability) -> tuple[float, list[Clip]]:
    ceiling = cap.peak_luminance * (1.0 - PEAK_HEADROOM)
    if intent.white_luminance <= ceiling:
        return intent.white_luminance, []
    reason = "intent white is above the panel's peak less gain headroom"
    clip = Clip("white_luminance", intent.white_luminance, ceiling, "cd/m2", reason, cap.evidence)
    return ceiling, [clip]


def _clip_black(intent: DisplayIntent, white: float, cap: PanelCapability) -> tuple[float, list[Clip]]:
    floor = white / cap.contrast_ratio
    if intent.black_luminance == 0.0:
        return floor, []
    if intent.black_luminance >= floor:
        return intent.black_luminance, []
    reason = "panel black at this white is above the requested black"
    return floor, [Clip("black_luminance", intent.black_luminance, floor, "cd/m2", reason, cap.evidence)]


def _clip_white_point(intent: DisplayIntent, cap: PanelCapability) -> tuple[tuple[float, float], list[Clip]]:
    if gamut.contains(cap.primaries_xy, intent.white_xy):
        return intent.white_xy, []
    reason = "requested white lies outside the panel primaries"
    distance = math.dist(intent.white_xy, cap.native_white_xy)
    return cap.native_white_xy, [Clip("white_xy_distance", 0.0, distance, "xy", reason, cap.evidence)]


def resolve_intent(intent: DisplayIntent, cap: PanelCapability | None) -> AchievableTarget:
    """Clip an intent to a panel. With no capability, the intent is unclipped."""
    if cap is None:
        hlg = hlg_system_gamma(intent.white_luminance) if intent.eotf == "hlg" else None
        black = intent.black_luminance
        return AchievableTarget(intent, intent.white_xy, intent.white_luminance, black, None, hlg, ())
    white, clips = _clip_luminance(intent, cap)
    black, black_clips = _clip_black(intent, white, cap)
    white_xy, wp_clips = _clip_white_point(intent, cap)
    clips += black_clips + wp_clips
    share = gamut.coverage(cap.primaries_xy, GAMUTS[intent.gamut])
    if share < intent.min_gamut_coverage:
        reason = f"panel covers {share:.3f} of {intent.gamut} in u'v' area"
        clips.append(Clip("gamut_coverage", intent.min_gamut_coverage, share, "ratio", reason, cap.evidence))
    if intent.is_hdr and white < HDR_REFERENCE_WHITE:
        reason = "panel peak is below HDR Reference White (BT.2100-3 Note 10a)"
        clips.append(Clip("hdr_reference_white", HDR_REFERENCE_WHITE, white, "cd/m2", reason, cap.evidence))
    hlg = hlg_system_gamma(white) if intent.eotf == "hlg" else None
    return AchievableTarget(intent, white_xy, white, black, share, hlg, tuple(clips))


__all__ = [
    "D65_XY",
    "GAMUTS",
    "HDR_REFERENCE_WHITE",
    "AchievableTarget",
    "Clip",
    "DisplayIntent",
    "PanelCapability",
    "Tolerances",
    "hlg_system_gamma",
    "resolve_intent",
]
