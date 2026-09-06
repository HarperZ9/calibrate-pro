"""Changing one axis of a target while the other two stay where they are.

The manifest declares four axis actions, ``calibration.target.gamut``,
``.whitepoint``, ``.custom_cct`` and ``.gamma``. Each edits one part of the
target a session holds. A session holds one target id, so an edit reads as:
take the target that is held, replace one of its three parts, name the result.

Naming the result is where the care is. A composed id and a preset id carrying
the same three choices produce the same correction, so leaving both spellings
reachable would put two names for one target into the record. The preset name
wins. It is the one the shipped bundles are digest-sealed against and the one
every surface already has a label for.

Reading a target back into its parts is the other half. A control offering D55
has to show D55 while the session holds it, and the session holds a label
rather than a slug, so the label tables are inverted here.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from calibrate_pro.application.target_selection import (
    GAMUT_SLUGS,
    PRESET_TARGETS,
    TONE_SLUGS,
    WHITE_SLUGS,
    TargetSelectionError,
    compose_target_id,
    custom_cct_slug,
    resolve_part,
    resolve_target,
)

#: The three parts of a target, named as an operator-facing surface names them
#: and as a refusal spells them. The order is the order a composed id spells.
GAMUT_AXIS = "gamut"
WHITE_AXIS = "white point"
TONE_AXIS = "tone response"

AXES = (GAMUT_AXIS, WHITE_AXIS, TONE_AXIS)

#: What the two axes an operator did not name take while they name the third.
#: A target needs three parts and an edit supplies one, so the other two come
#: from somewhere. These are the parts of ``calibration.preset.srgb_web``,
#: which is also the one target the prediction path models. Every surface
#: prints the whole target after an edit, so what an operator ends up holding
#: is stated back to them rather than left to be assumed.
DEFAULT_TARGET_SLUGS = ("srgb", "d65", "g2.2")

_AXIS_INDEX: Mapping[str, int] = MappingProxyType({axis: index for index, axis in enumerate(AXES)})

#: Label to slug, per axis. Derived from the forward tables rather than typed
#: again, so a slug renamed in one direction cannot mean something else read
#: back. Every forward table is injective, which is what makes this well
#: defined: ``srgb`` and ``rec709`` share primaries and are separate labels.
_GAMUT_BY_LABEL: Mapping[str, str] = MappingProxyType({label: slug for slug, label in GAMUT_SLUGS.items()})
_TONE_BY_LABEL: Mapping[str, str] = MappingProxyType({label: slug for slug, label in TONE_SLUGS.items()})
_WHITE_BY_LABEL: Mapping[str, str] = MappingProxyType({label: slug for slug, label in WHITE_SLUGS.items()})


def white_point_slug(label: str) -> str:
    """Read a white-point label back into the slug that names it.

    A colour temperature is labelled for its own number and has no entry in
    the illuminant table, so it is read back through the same bound check that
    let it be chosen. A label outside both is refused rather than guessed at.
    """
    slug = _WHITE_BY_LABEL.get(label)
    if slug is not None:
        return slug
    if label.endswith("K") and label[:-1].isdigit():
        return custom_cct_slug(int(label[:-1]))
    raise TargetSelectionError(
        f"No white point is labelled {label!r}. This build carries {', '.join(sorted(_WHITE_BY_LABEL))}, "
        "and a colour temperature written as 6300K."
    )


def target_slugs(target_id: str) -> tuple[str, str, str]:
    """The three parts of a target, in the order a composed id spells them."""
    target = resolve_target(target_id)
    return (
        resolve_part(_GAMUT_BY_LABEL, target.gamut_label, GAMUT_AXIS),
        white_point_slug(target.white_label),
        resolve_part(_TONE_BY_LABEL, target.tone_label, TONE_AXIS),
    )


def canonical_target_id(gamut_slug: str, white_slug: str, tone_slug: str) -> str:
    """Name one target, preferring the preset that already names it.

    The HDR flag is checked rather than assumed. Every composed target is SDR,
    so collapsing one onto a preset that carries the same three labels and the
    HDR flag would hand back a target with a fourth part the operator did not
    ask for. No shipped preset sets the flag today, and this is the guard that
    keeps that from becoming load-bearing the day one does.
    """
    target_id = compose_target_id(gamut_slug, white_slug, tone_slug)
    composed = resolve_target(target_id)
    parts = (composed.gamut_label, composed.white_label, composed.tone_label)
    for preset_id, preset in PRESET_TARGETS.items():
        if preset[:3] == parts and not preset[3]:
            return preset_id
    return target_id


def with_axis(target_id: str | None, axis: str, slug: str) -> str:
    """The target that differs from the held one in one axis only.

    ``None`` is a session that holds no target yet. The two axes the operator
    did not name take :data:`DEFAULT_TARGET_SLUGS` there, because a target
    with one part is not a target this build can generate against.
    """
    index = _AXIS_INDEX.get(axis)
    if index is None:
        raise TargetSelectionError(f"A target has no {axis!r} axis. It has {', '.join(AXES)}.")
    slugs = list(DEFAULT_TARGET_SLUGS if target_id is None else target_slugs(target_id))
    slugs[index] = slug
    return canonical_target_id(*slugs)


__all__ = [
    "AXES",
    "DEFAULT_TARGET_SLUGS",
    "GAMUT_AXIS",
    "TONE_AXIS",
    "WHITE_AXIS",
    "canonical_target_id",
    "target_slugs",
    "white_point_slug",
    "with_axis",
]
