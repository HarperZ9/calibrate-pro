"""Gamut coverage between two primary triangles, in CIE 1976 u'v'.

Coverage is the share of the target triangle that the panel triangle also
contains. It is computed in u'v' because equal areas there are closer to equal
perceived colour differences than in CIE 1931 xy. Both are 2D chromaticity
measures; neither says anything about luminance, so a panel can cover a gamut
at its peak and not near black.
"""

from __future__ import annotations

Point = tuple[float, float]
Triangle = tuple[Point, Point, Point]


def xy_to_uv(point: Point) -> Point:
    """Convert CIE 1931 xy to CIE 1976 u'v'."""
    x, y = point
    denominator = -2.0 * x + 12.0 * y + 3.0
    if denominator <= 0.0:
        raise ValueError(f"chromaticity {point} has no u'v' image")
    return (4.0 * x / denominator, 9.0 * y / denominator)


def polygon_area(points: list[Point]) -> float:
    """Return the unsigned area of a simple polygon by the shoelace formula."""
    total = 0.0
    for index, (x0, y0) in enumerate(points):
        x1, y1 = points[(index + 1) % len(points)]
        total += x0 * y1 - x1 * y0
    return abs(total) / 2.0


def _orientation(triangle: Triangle) -> float:
    (ax, ay), (bx, by), (cx, cy) = triangle
    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)


def _inside(point: Point, start: Point, end: Point, sign: float) -> bool:
    cross = (end[0] - start[0]) * (point[1] - start[1]) - (end[1] - start[1]) * (point[0] - start[0])
    return cross * sign >= -1e-15


def _crossing(p0: Point, p1: Point, start: Point, end: Point) -> Point:
    dx_edge, dy_edge = end[0] - start[0], end[1] - start[1]
    dx_seg, dy_seg = p1[0] - p0[0], p1[1] - p0[1]
    denominator = dx_edge * dy_seg - dy_edge * dx_seg
    if denominator == 0.0:
        return p1
    t = (dx_edge * (start[1] - p0[1]) - dy_edge * (start[0] - p0[0])) / denominator
    return (p0[0] + t * dx_seg, p0[1] + t * dy_seg)


def clip_polygon(subject: list[Point], clip: Triangle) -> list[Point]:
    """Clip a polygon by a convex triangle (Sutherland-Hodgman)."""
    sign = 1.0 if _orientation(clip) >= 0.0 else -1.0
    output = list(subject)
    for index in range(3):
        start, end = clip[index], clip[(index + 1) % 3]
        source, output = output, []
        for position, current in enumerate(source):
            previous = source[position - 1]
            if _inside(current, start, end, sign):
                if not _inside(previous, start, end, sign):
                    output.append(_crossing(previous, current, start, end))
                output.append(current)
            elif _inside(previous, start, end, sign):
                output.append(_crossing(previous, current, start, end))
        if not output:
            return []
    return output


def coverage(panel_xy: Triangle, target_xy: Triangle) -> float:
    """Return the share of the target gamut the panel covers, in u'v' area."""
    panel = tuple(xy_to_uv(p) for p in panel_xy)
    target = [xy_to_uv(p) for p in target_xy]
    target_area = polygon_area(target)
    if target_area <= 0.0:
        raise ValueError("target gamut has no area")
    shared = clip_polygon(target, (panel[0], panel[1], panel[2]))
    return min(1.0, polygon_area(shared) / target_area) if len(shared) >= 3 else 0.0


def contains(triangle_xy: Triangle, point_xy: Point, margin: float = 0.0) -> bool:
    """Answer whether a chromaticity lies inside a primary triangle."""
    sign = 1.0 if _orientation(triangle_xy) >= 0.0 else -1.0
    for index in range(3):
        start, end = triangle_xy[index], triangle_xy[(index + 1) % 3]
        cross = (end[0] - start[0]) * (point_xy[1] - start[1]) - (end[1] - start[1]) * (point_xy[0] - start[0])
        if cross * sign < -margin:
            return False
    return True


__all__ = ["clip_polygon", "contains", "coverage", "polygon_area", "xy_to_uv"]
