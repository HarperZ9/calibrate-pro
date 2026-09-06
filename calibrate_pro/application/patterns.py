"""What a test pattern is, before anything paints one.

A test pattern is the oldest tool in this trade and the only one that needs no
instrument. An operator sets a display's brightness by finding the lowest bar
they can still separate from black, and sets its contrast by finding the point
where the steps below white stop merging. Both are judgements a person makes
with their own eyes, and both are worth making because the panel controls they
set sit upstream of every table this build can load.

So the value here is the exactness of the code sent, not the look of the
surface. Everything in this module is integers and rectangles. A pattern is a
ground colour and a set of regions, each region an exact 8-bit triple over an
area with integer edges. Nothing is antialiased, nothing is interpolated, and
no text is drawn, because a glyph's edge pixels are code values nobody asked
for and an operator reading a near-black step cannot tell one from the bar.

Regions are declared as fractions of the surface and rounded to pixels one edge
at a time. Two regions sharing an edge round it to the same pixel, so a set of
bars tiles the surface with no seam and no overlap. A region that rounds below
one pixel is refused rather than dropped, because a pattern whose bars vanished
is not the pattern the operator asked for.

Every pattern paints its ground first, over the whole surface. That is why
``place`` returns the ground as its own region rather than trusting a layout to
cover the surface: a pixel a layout forgot would show whatever the window held
before, and an operator judging black would be judging a stale frame.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

#: How many values one channel of an 8-bit signal can take.
LEVELS = 256

#: The largest value a channel can carry, which is what full white drives.
MAXIMUM_LEVEL = LEVELS - 1


class PatternError(ValueError):
    """A pattern that cannot be laid out as asked on the surface it was given."""


def _exact_int(value: object, name: str) -> int:
    """Take an integer and refuse anything that only behaves like one."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise PatternError(f"{name} must be an exact integer")
    return value


@dataclass(frozen=True)
class Swatch:
    """One exact 8-bit colour, which is what a region sends to the display."""

    red: int
    green: int
    blue: int

    def __post_init__(self) -> None:
        for name in ("red", "green", "blue"):
            value = _exact_int(getattr(self, name), name)
            if value < 0 or value > MAXIMUM_LEVEL:
                raise PatternError(f"{name} must fall within 0 and {MAXIMUM_LEVEL}")

    @classmethod
    def grey(cls, level: int) -> Swatch:
        """The neutral swatch at one code value, driven equally on all three."""
        return cls(level, level, level)

    @property
    def values(self) -> tuple[int, int, int]:
        return (self.red, self.green, self.blue)

    @property
    def signal(self) -> tuple[float, float, float]:
        """The same colour as the 0 to 1 triple a patch window takes.

        This is the seam between a pattern and a measurement. A swatch shown to
        an operator and a patch shown to an instrument carry the same numbers,
        so a pattern's colour can be measured without being restated.
        """
        return (
            self.red / MAXIMUM_LEVEL,
            self.green / MAXIMUM_LEVEL,
            self.blue / MAXIMUM_LEVEL,
        )

    @property
    def line(self) -> str:
        return f"{self.red}, {self.green}, {self.blue}"


BLACK = Swatch.grey(0)
WHITE = Swatch.grey(MAXIMUM_LEVEL)


@dataclass(frozen=True)
class PlacedRegion:
    """One rectangle of one colour, in the surface's own pixels."""

    x: int
    y: int
    width: int
    height: int
    swatch: Swatch

    def __post_init__(self) -> None:
        for name in ("x", "y"):
            if _exact_int(getattr(self, name), name) < 0:
                raise PatternError(f"{name} must not be negative")
        for name in ("width", "height"):
            if _exact_int(getattr(self, name), name) < 1:
                raise PatternError(
                    f"{name} rounded to {getattr(self, name)} pixels, and a region "
                    f"thinner than a pixel is not the pattern that was asked for"
                )

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height


@dataclass(frozen=True)
class Region:
    """One rectangle of one colour, as a fraction of whatever surface it lands on.

    Edges are held as fractions rather than pixels so a pattern describes itself
    once and lands correctly on any panel. Each edge rounds independently, which
    is what makes two regions sharing an edge land on the same pixel.
    """

    left: float
    top: float
    right: float
    bottom: float
    swatch: Swatch

    def __post_init__(self) -> None:
        for name in ("left", "top", "right", "bottom"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise PatternError(f"{name} must be a number")
            if value < 0.0 or value > 1.0:
                raise PatternError(f"{name} must fall within 0 and 1 of the surface")
        if self.left >= self.right or self.top >= self.bottom:
            raise PatternError("a region must enclose an area, and this one encloses none")

    def place(self, width: int, height: int) -> PlacedRegion:
        x = round(self.left * width)
        y = round(self.top * height)
        return PlacedRegion(
            x=x,
            y=y,
            width=round(self.right * width) - x,
            height=round(self.bottom * height) - y,
            swatch=self.swatch,
        )


#: How a pattern turns a surface size into the regions painted over its ground.
Layout = Callable[[int, int], tuple[PlacedRegion, ...]]


@dataclass(frozen=True)
class Pattern:
    """One pattern, and the decision an operator makes while looking at it.

    ``decision`` and ``look_for`` are carried because a pattern nobody knows how
    to read is a coloured screen. Every surface that offers one of these prints
    both, so the operator is told what they are setting and what to watch while
    they set it.
    """

    pattern_id: str
    name: str
    decision: str
    look_for: str
    ground: Swatch
    minimum_width: int
    minimum_height: int
    exact_pixels: bool
    layout: Layout

    def place(self, width: int, height: int) -> tuple[PlacedRegion, ...]:
        """Lay the pattern out on a surface, ground first.

        The ground is returned as the first region rather than assumed, so a
        surface painting these in order covers every pixel it was given before
        it paints anything on top.
        """
        _exact_int(width, "width")
        _exact_int(height, "height")
        if width < self.minimum_width or height < self.minimum_height:
            raise PatternError(
                f"{self.name} needs a surface of at least {self.minimum_width} by "
                f"{self.minimum_height} pixels, and this one is {width} by {height}"
            )
        try:
            features = self.layout(width, height)
        except PatternError as refused:
            raise PatternError(f"{self.name} does not fit {width} by {height}: {refused}") from refused
        for region in features:
            if region.right > width or region.bottom > height:
                raise PatternError(f"{self.name} laid out a region past the edge of a {width} by {height} surface")
        return (PlacedRegion(0, 0, width, height, self.ground), *features)


def fixed(regions: Sequence[Region]) -> Layout:
    """A layout whose regions are the same fractions on every surface."""
    held = tuple(regions)

    def place(width: int, height: int) -> tuple[PlacedRegion, ...]:
        return tuple(region.place(width, height) for region in held)

    return place


def columns(
    swatches: Sequence[Swatch],
    *,
    left: float = 0.0,
    top: float = 0.0,
    right: float = 1.0,
    bottom: float = 1.0,
) -> tuple[Region, ...]:
    """Equal-width columns filling a band, sharing every interior edge."""
    if not swatches:
        raise PatternError("a band of no columns paints nothing")
    span = right - left
    count = len(swatches)
    return tuple(
        Region(
            left=left + span * index / count,
            top=top,
            right=left + span * (index + 1) / count,
            bottom=bottom,
            swatch=swatch,
        )
        for index, swatch in enumerate(swatches)
    )


def grid(
    swatches: Sequence[Swatch],
    *,
    across: int,
    left: float = 0.0,
    top: float = 0.0,
    right: float = 1.0,
    bottom: float = 1.0,
) -> tuple[Region, ...]:
    """Swatches laid row by row into a rectangle, sharing every interior edge."""
    if not swatches:
        raise PatternError("a grid of no swatches paints nothing")
    if across < 1 or len(swatches) % across:
        raise PatternError(f"{len(swatches)} swatches do not fill rows of {across}")
    down = len(swatches) // across
    width = right - left
    height = bottom - top
    regions: list[Region] = []
    for index, swatch in enumerate(swatches):
        column, row = index % across, index // across
        regions.append(
            Region(
                left=left + width * column / across,
                top=top + height * row / down,
                right=left + width * (column + 1) / across,
                bottom=top + height * (row + 1) / down,
                swatch=swatch,
            )
        )
    return tuple(regions)


__all__ = [
    "BLACK",
    "LEVELS",
    "MAXIMUM_LEVEL",
    "WHITE",
    "Layout",
    "Pattern",
    "PatternError",
    "PlacedRegion",
    "Region",
    "Swatch",
    "columns",
    "fixed",
    "grid",
]
