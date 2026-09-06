"""Gamut coverage that answers containment rather than size.

The question a calibration target has to answer is whether a panel can
reproduce a colour space, and the size of its gamut does not answer it. Adobe
RGB and DCI-P3 enclose almost the same area of the chromaticity diagram while
reaching different corners of it: Adobe RGB red sits at x=0.640 and DCI-P3 red
at x=0.680. Comparing areas reports 99.4% and reads as a panel ready for P3
work. Intersecting the two triangles reports 87.8%, and the missing eighth is
the deep red an operator would grade in.

So every function here intersects. The geometry comes from
:mod:`calibrate_pro.verification.gamut_volume`, which already carries a
Sutherland-Hodgman clipper the verification reports use, rather than a second
implementation that could drift from it.
"""

from __future__ import annotations

from dataclasses import dataclass

from calibrate_pro.verification.gamut_volume import (
    calculate_triangle_area,
    calculate_triangle_intersection_area,
    xy_to_uv,
)

# Below this, a display primary is close enough to the target primary that the
# difference is smaller than the agreement between two colorimeters. u'v' is
# used rather than xy because a fixed distance in u'v' means roughly the same
# visual difference across the diagram, so one number can bound the whole
# triangle.
DEFAULT_TOLERANCE_UV = 0.002

_CORNERS = ("red", "green", "blue")


@dataclass(frozen=True)
class GamutContainment:
    """Whether a display reaches a target gamut, and where it falls short."""

    coverage_percent: float
    """Share of the target triangle the display triangle overlaps, 0 to 100."""

    covers: bool
    """True when every target primary lies inside the display triangle."""

    deficits: tuple[str, ...]
    """Target corners the display cannot reach, named ``red``/``green``/``blue``."""

    worst_deficit_uv: float
    """u'v' distance from the furthest unreachable target corner to the display."""

    def describe(self) -> str:
        """One line naming the shortfall, for a refusal an operator reads."""
        if self.covers:
            return f"covers {self.coverage_percent:.1f}% of the target"
        corners = ", ".join(self.deficits)
        return (
            f"reaches {self.coverage_percent:.1f}% of the target; "
            f"{corners} out of reach by {self.worst_deficit_uv:.4f} u'v'"
        )


def _corner(primaries: object, name: str) -> tuple[float, float]:
    """Read one chromaticity off either primaries type this package carries.

    :class:`~calibrate_pro.targets.gamut.ColorPrimaries` holds each corner as
    an ``(x, y)`` tuple and
    :class:`~calibrate_pro.panels.panel_types.PanelPrimaries` holds a
    ``ChromaticityCoord``. They describe the same thing under the same three
    names, and the display side of every comparison in this module is a panel
    record, so reading only the tuple form made the question this module exists
    to answer the one it could not be asked.
    """
    corner = getattr(primaries, name, None)
    if corner is None:
        raise TypeError(f"primaries must name a {name} chromaticity, and {type(primaries).__name__} does not")
    as_tuple = getattr(corner, "as_tuple", None)
    if callable(as_tuple):
        corner = as_tuple()
    x, y = corner
    return (float(x), float(y))


def _triangle(primaries: object) -> list[tuple[float, float]]:
    """Read R, G, B chromaticities off either primaries type.

    Wound counter-clockwise before it is returned. The clipper treats its
    second argument as a counter-clockwise boundary and reports an empty
    intersection for a clockwise one, which would surface as a display that
    covers nothing rather than as the malformed input it is.
    """
    corners = [_corner(primaries, name) for name in _CORNERS]
    (r_x, r_y), (g_x, g_y), (b_x, b_y) = corners
    cross = (g_x - r_x) * (b_y - g_y) - (g_y - r_y) * (b_x - g_x)
    if cross < 0:
        corners.reverse()
    return corners


def _point_to_segment_uv(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    """Shortest u'v' distance from a point to a line segment."""
    p_u, p_v = xy_to_uv(*point)
    s_u, s_v = xy_to_uv(*start)
    e_u, e_v = xy_to_uv(*end)
    d_u, d_v = e_u - s_u, e_v - s_v
    span = d_u * d_u + d_v * d_v
    if span <= 0.0:
        return float(((p_u - s_u) ** 2 + (p_v - s_v) ** 2) ** 0.5)
    t = ((p_u - s_u) * d_u + (p_v - s_v) * d_v) / span
    t = max(0.0, min(1.0, t))
    near_u, near_v = s_u + t * d_u, s_v + t * d_v
    return float(((p_u - near_u) ** 2 + (p_v - near_v) ** 2) ** 0.5)


def _distance_outside_uv(point: tuple[float, float], triangle: list[tuple[float, float]]) -> float:
    """How far a chromaticity sits outside a triangle, in u'v'. Zero if inside."""
    inside = True
    for index in range(3):
        a_x, a_y = triangle[index]
        b_x, b_y = triangle[(index + 1) % 3]
        side = (b_x - a_x) * (point[1] - a_y) - (b_y - a_y) * (point[0] - a_x)
        if side < 0:
            inside = False
            break
    if inside:
        return 0.0
    return min(_point_to_segment_uv(point, triangle[i], triangle[(i + 1) % 3]) for i in range(3))


def chromaticity_coverage(display_primaries: object, reference_primaries: object) -> float:
    """Share of a reference gamut a display reaches, as a percentage.

    Computed as the intersection of the two chromaticity triangles over the
    area of the reference triangle, so it cannot exceed 100 and a wider panel
    that misses a corner is reported short rather than complete.
    """
    display = _triangle(display_primaries)
    reference = _triangle(reference_primaries)
    reference_area = calculate_triangle_area(*reference)
    if reference_area <= 0:
        return 0.0
    overlap = calculate_triangle_intersection_area(display, reference)
    return min(100.0, (overlap / reference_area) * 100.0)


def gamut_containment(
    display_primaries: object,
    reference_primaries: object,
    tolerance_uv: float = DEFAULT_TOLERANCE_UV,
) -> GamutContainment:
    """Report whether a display encloses a target gamut, and by how much it misses."""
    display = _triangle(display_primaries)

    deficits: list[str] = []
    worst = 0.0
    # Read each reference corner by the name it is being reported under, not
    # off the wound triangle. _triangle reverses a clockwise input so the
    # clipper and the inside test read a counter-clockwise boundary, and a
    # reversed list zipped against ("red", "green", "blue") reports the blue
    # shortfall as a red one. The name travels into a hashed manifest, so it
    # has to come from the same place the chromaticity does.
    for name in _CORNERS:
        distance = _distance_outside_uv(_corner(reference_primaries, name), display)
        if distance > tolerance_uv:
            deficits.append(name)
            worst = max(worst, distance)

    return GamutContainment(
        coverage_percent=chromaticity_coverage(display_primaries, reference_primaries),
        covers=not deficits,
        deficits=tuple(deficits),
        worst_deficit_uv=worst,
    )
