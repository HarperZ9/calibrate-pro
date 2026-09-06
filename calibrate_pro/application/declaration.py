"""What a display says about itself, turned into something the engine builds from.

A display carries a descriptor, and most descriptors name the primaries and the
transfer the manufacturer intended for that model. Reading those is what lets
this build produce a real correction for a display no panel record matches, and
it is the difference between a wide-gamut monitor left showing oversaturated
sRGB content and one clamped to the gamut the content was authored for.

What this is not is a measurement. The numbers describe a model as its maker
wrote them down, so a unit that drifted, a monitor sitting in a vivid picture
mode, and a descriptor copied across a product line each produce a display that
does not match its own declaration. Every artifact built from this carries
``EvidenceKind.ESTIMATED`` for that reason, and the label the session holds says
``EDID_DECLARED`` rather than ``MEASURED`` so a reader can tell the two apart
without opening the manifest.

The record is derived from the generic sRGB record rather than assembled from
defaults. That matters because :class:`PanelCapabilities` defaults claim HDR,
wide gamut, ten bits and a million to one, and a descriptor says none of those
things. Starting from the generic record means the only fields that change are
the ones the descriptor actually covered, and every remaining field carries the
same conservative value the ``--generic`` path already uses.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from calibrate_pro.application.contracts import CharacterizationKind
from calibrate_pro.application.contracts import PanelCharacterization as DeclaredContract
from calibrate_pro.application.detection import EDID_PROVENANCE_PREFIX
from calibrate_pro.application.measurement import (
    MAXIMUM_GAMMA,
    MINIMUM_GAMMA,
    MINIMUM_GAMUT_AREA,
    WIDE_GAMUT_RED_X,
)
from calibrate_pro.panels.panel_types import (
    ChromaticityCoord,
    GammaCurve,
    PanelCharacterization,
    PanelPrimaries,
)

#: How many characters of a descriptor label name the manufacturer. The first
#: three are the PnP vendor code and the four after them are the product code,
#: which is the same shape the registry keys displays under.
_VENDOR_CODE_LENGTH = 3

#: What the panel record's notes say, so a bundle built from a declaration
#: carries the caveat in the record itself and not only in the label.
DECLARATION_NOTE = (
    "Primaries and gamma as the display declared them in its descriptor. "
    "These describe the model the manufacturer shipped, not a reading of this unit."
)


class DeclarationRefused(Exception):
    """Raised when a declaration cannot be turned into a usable record."""


@dataclass(frozen=True)
class DeclaredCharacterization:
    """One display as it describes itself, with the record built from it.

    This is the sensorless counterpart to
    :class:`~calibrate_pro.application.measurement.MeasuredCharacterization`.
    Both pair a panel record with the evidence behind it, and both exist so a
    caller cannot hand the generator a label without the thing that earns it.
    """

    panel: PanelCharacterization
    provenance: str
    red_xy: tuple[float, float]
    green_xy: tuple[float, float]
    blue_xy: tuple[float, float]
    white_xy: tuple[float, float]
    gamma: float

    @property
    def summary(self) -> str:
        """One line naming the source and the gamut it declared."""
        corners = " ".join(
            f"{name} {x:.4f},{y:.4f}"
            for name, (x, y) in (
                ("R", self.red_xy),
                ("G", self.green_xy),
                ("B", self.blue_xy),
                ("W", self.white_xy),
            )
        )
        return f"{self.provenance}: {corners}, gamma {self.gamma:.2f}"


def declared_label(provenance: str) -> tuple[str, str]:
    """Split a declaration's provenance into the vendor and the product it names.

    The provenance is written in one place and read here, so the shape is fixed:
    the ``edid:`` prefix, the vendor code and product code run together the way
    the platform keys them, then optionally a space and the name the display
    reported. Nothing else is encoded in it, and in particular no serial, so a
    record built from this names a product and never a unit.
    """
    text = provenance.strip()
    if not text.startswith(EDID_PROVENANCE_PREFIX):
        raise DeclarationRefused(f"a declared provenance must start with {EDID_PROVENANCE_PREFIX!r}")
    label = text[len(EDID_PROVENANCE_PREFIX) :].strip()
    if not label:
        raise DeclarationRefused("a declared provenance must name the display that declared it")
    stem, _, product = label.partition(" ")
    vendor = stem[:_VENDOR_CODE_LENGTH]
    model = product.strip() or stem[_VENDOR_CODE_LENGTH:] or stem
    return vendor, model


def _coordinate(pair: tuple[str, str] | None, field_name: str) -> tuple[float, float]:
    if pair is None:
        raise DeclarationRefused(f"the declaration carried no {field_name} chromaticity")
    try:
        x, y = (float(component) for component in pair)
    except (TypeError, ValueError) as exc:
        raise DeclarationRefused(f"the declared {field_name} chromaticity was not a pair of numbers") from exc
    if not (math.isfinite(x) and math.isfinite(y)):
        raise DeclarationRefused(f"the declared {field_name} chromaticity was not finite")
    return x, y


def _triangle_area(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    return abs((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])) / 2.0


def declared_from(base: PanelCharacterization, characterization: DeclaredContract) -> DeclaredCharacterization:
    """Build the record a declaration describes, refusing one that describes nothing.

    Detection already refuses a descriptor whose primaries collapse or whose
    gamma is absent, so an offer that came from this build arrives valid. The
    checks are repeated because this is a public seam: a caller assembling a
    characterization by hand reaches the same generator, and a degenerate gamut
    accepted here would produce a correction matrix that maps colours onto a
    line rather than a refusal an operator can read.

    The correction matrix the base record may carry is dropped. It corrects one
    model's record toward that model's measured behaviour, and these primaries
    came from a different display, so keeping it would apply a correction for an
    error this panel does not have.
    """
    if type(characterization) is not DeclaredContract:
        raise TypeError("characterization must be an application PanelCharacterization")
    if characterization.kind is not CharacterizationKind.EDID_DECLARED:
        raise DeclarationRefused("only an EDID_DECLARED characterization describes a declaration")

    red = _coordinate(characterization.red_xy, "red")
    green = _coordinate(characterization.green_xy, "green")
    blue = _coordinate(characterization.blue_xy, "blue")
    white = _coordinate(characterization.white_xy, "white")
    area = _triangle_area(red, green, blue)
    if area < MINIMUM_GAMUT_AREA:
        raise DeclarationRefused(f"the declared primaries enclose {area:.4f}, too little to be three separate colours")

    raw_gamma = characterization.nominal_gamma
    try:
        gamma = float(raw_gamma) if raw_gamma is not None else float("nan")
    except (TypeError, ValueError) as exc:
        raise DeclarationRefused("the declared gamma was not a number") from exc
    if not math.isfinite(gamma) or not MINIMUM_GAMMA <= gamma <= MAXIMUM_GAMMA:
        raise DeclarationRefused(f"the declared gamma is {raw_gamma}, outside the band a display responds in")

    vendor, model = declared_label(characterization.provenance)
    # ``panel_type`` is not replaced. The descriptor says nothing about panel
    # technology, and the engine applies its OLED near-black compensation off
    # that field, so naming OLED here would bend a curve for a display that may
    # well be an LCD.
    panel = replace(
        base,
        manufacturer=vendor,
        model_pattern=model,
        display_name=model,
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(*red),
            green=ChromaticityCoord(*green),
            blue=ChromaticityCoord(*blue),
            white=ChromaticityCoord(*white),
        ),
        # One curve per channel rather than one instance under three names.
        # ``GammaCurve`` is a mutable dataclass, so a shared object would make a
        # correction written to one channel land on the other two, and a
        # descriptor carries one gamma for all three rather than a claim that
        # the channels track each other.
        gamma_red=GammaCurve(gamma=gamma),
        gamma_green=GammaCurve(gamma=gamma),
        gamma_blue=GammaCurve(gamma=gamma),
        capabilities=replace(base.capabilities, wide_gamut=red[0] > WIDE_GAMUT_RED_X),
        color_correction_matrix=None,
        notes=DECLARATION_NOTE,
    )
    return DeclaredCharacterization(
        panel=panel,
        provenance=characterization.provenance,
        red_xy=red,
        green_xy=green,
        blue_xy=blue,
        white_xy=white,
        gamma=gamma,
    )


__all__ = [
    "DECLARATION_NOTE",
    "DeclarationRefused",
    "DeclaredCharacterization",
    "declared_from",
    "declared_label",
]
