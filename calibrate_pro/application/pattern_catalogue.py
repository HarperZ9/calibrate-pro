"""The patterns this build offers, and what each one is for.

Every entry here earns its place by naming a decision an operator makes while
looking at it. A pattern that only demonstrates that the program can fill a
screen is a screensaver, so there is no gradient sweep, no colour wheel, and no
moving test card. What is here is the set a display is actually set up with:
the two panel controls that sit upstream of everything, the tone response those
controls land on, the channel drive behind a colour cast, and the reference
chart the rest of this package grades against.

Two choices in here are worth stating. The ColorChecker swatches come from
``calibrate_pro.core.colorchecker`` rather than from a table typed in beside
them, because this package has already had five copies of that chart drift
apart from each other and one of them is enough. And the crosshatch is defined
in the surface's own pixels rather than in fractions, because its whole purpose
is to show a line one pixel wide: an operator seeing that line blurred, doubled,
or grey is looking at a display or a compositor that is resampling the signal,
and every exact value in every other pattern here is landing softened too.
"""

from __future__ import annotations

from calibrate_pro.application.patterns import (
    BLACK,
    MAXIMUM_LEVEL,
    WHITE,
    Layout,
    Pattern,
    PatternError,
    PlacedRegion,
    Region,
    Swatch,
    columns,
    fixed,
    grid,
)
from calibrate_pro.core.colorchecker import COLORCHECKER_PATCHES

#: The smallest surface any pattern here is offered on. Below this the bars in
#: a PLUGE are a few pixels wide and the judgement they exist for cannot be
#: made, so the pattern is refused rather than drawn too small to read.
MINIMUM_WIDTH = 320
MINIMUM_HEIGHT = 240

#: How far apart the crosshatch lines run, in the surface's own pixels.
CROSSHATCH_SPACING = 64

#: The code values a PLUGE offers above black. An operator raises the display's
#: brightness until the lowest of these separates from the ground, and stops
#: before the ground itself lifts.
PLUGE_LEVELS = (1, 2, 3, 4, 6, 8, 12, 16)

#: The steps below white a contrast control is set against. All six have to
#: stay distinct from each other and from full white.
WHITE_CLIP_LEVELS = (230, 235, 240, 245, 250, MAXIMUM_LEVEL)

#: Twenty-one steps from black to white, which is the sampling a tone response
#: is normally read at.
RAMP_STEPS = 21

#: What a 75% colour bar drives each channel to.
BAR_LEVEL = 191


def _ramp_levels(steps: int) -> tuple[int, ...]:
    return tuple(round(index * MAXIMUM_LEVEL / (steps - 1)) for index in range(steps))


def _greys(levels: tuple[int, ...]) -> tuple[Swatch, ...]:
    return tuple(Swatch.grey(level) for level in levels)


def _chart_swatches() -> tuple[Swatch, ...]:
    """The reference chart, quantized to the signal a display can be sent."""
    return tuple(
        Swatch(*(round(component * MAXIMUM_LEVEL) for component in patch.srgb)) for patch in COLORCHECKER_PATCHES
    )


def _crosshatch(width: int, height: int) -> tuple[PlacedRegion, ...]:
    """One-pixel lines on a fixed pixel pitch, with the surface edge drawn.

    The border is drawn last and separately so it lands on the final row and
    column whatever the surface size is. A grid that stopped short of the edge
    would leave the operator unable to tell a panel overscanning its input from
    one showing the signal whole.
    """
    lines = [PlacedRegion(x, 0, 1, height, WHITE) for x in range(0, width, CROSSHATCH_SPACING)]
    lines.append(PlacedRegion(width - 1, 0, 1, height, WHITE))
    lines.extend(PlacedRegion(0, y, width, 1, WHITE) for y in range(0, height, CROSSHATCH_SPACING))
    lines.append(PlacedRegion(0, height - 1, width, 1, WHITE))
    return tuple(lines)


def _pattern(
    pattern_id: str,
    name: str,
    decision: str,
    look_for: str,
    ground: Swatch,
    layout: Layout,
    *,
    exact_pixels: bool = False,
) -> Pattern:
    return Pattern(
        pattern_id=pattern_id,
        name=name,
        decision=decision,
        look_for=look_for,
        ground=ground,
        minimum_width=MINIMUM_WIDTH,
        minimum_height=MINIMUM_HEIGHT,
        exact_pixels=exact_pixels,
        layout=layout,
    )


CATALOGUE: tuple[Pattern, ...] = (
    _pattern(
        "black",
        "Black field",
        "Whether the room and the panel let you judge black at all.",
        "Backlight bleed at the corners, clouding across the middle, and how much "
        "of what you see is the room rather than the display.",
        BLACK,
        fixed(()),
    ),
    _pattern(
        "white",
        "White field",
        "Whether the panel is uniform enough for a single-point reading to speak for it.",
        "A corner or edge dimmer than the centre, a colour cast that moves across "
        "the screen, and dust or marks that a later measurement would read as panel error.",
        WHITE,
        fixed(()),
    ),
    _pattern(
        "grey",
        "Mid grey field",
        "Whether the display carries a colour cast at the level most content sits at.",
        "Any tint in a field that should be neutral. This is the level the channel "
        "gains are set against, so a cast here is the one worth correcting.",
        Swatch.grey(128),
        fixed(()),
    ),
    _pattern(
        "pluge",
        "PLUGE",
        "Where to set the display's brightness control.",
        "Raise brightness until the lowest bar you can see separates from the ground, "
        "then stop. If the ground itself has lifted off black, brightness is too high.",
        BLACK,
        fixed(
            columns(_greys(PLUGE_LEVELS), left=0.05, top=0.35, right=0.75, bottom=0.65)
            + (Region(0.82, 0.35, 0.95, 0.65, WHITE),)
        ),
    ),
    _pattern(
        "white-clip",
        "White clipping",
        "Where to set the display's contrast control.",
        "Lower contrast until every step is distinct from its neighbours and from "
        "full white. Steps that have merged are levels the display can no longer separate.",
        Swatch.grey(128),
        fixed(columns(_greys(WHITE_CLIP_LEVELS), left=0.1, top=0.35, right=0.9, bottom=0.65)),
    ),
    _pattern(
        "grey-ramp",
        "Grey ramp",
        "Whether the tone response is smooth and whether the ends are intact.",
        "Steps of even width but uneven brightness, a step that repeats its "
        "neighbour, and banding inside a step. The two ends say whether black and white clip.",
        BLACK,
        fixed(columns(_greys(_ramp_levels(RAMP_STEPS)))),
    ),
    _pattern(
        "primaries",
        "Primaries and neutrals",
        "Whether each channel drives on its own and whether the mixtures land neutral.",
        "A primary that looks dull or shifted in hue, a secondary that leans toward "
        "one of the primaries mixed into it, and a tint in the white or the grey.",
        BLACK,
        fixed(
            grid(
                (
                    Swatch(MAXIMUM_LEVEL, 0, 0),
                    Swatch(0, MAXIMUM_LEVEL, 0),
                    Swatch(0, 0, MAXIMUM_LEVEL),
                    WHITE,
                    Swatch(0, MAXIMUM_LEVEL, MAXIMUM_LEVEL),
                    Swatch(MAXIMUM_LEVEL, 0, MAXIMUM_LEVEL),
                    Swatch(MAXIMUM_LEVEL, MAXIMUM_LEVEL, 0),
                    Swatch.grey(128),
                ),
                across=4,
            )
        ),
    ),
    _pattern(
        "colour-bars",
        "Colour bars at 75%",
        "Whether the display reproduces saturated colour in the order it was sent.",
        "Bars out of order or out of hue, and any bar that has gone flat against "
        "its neighbour. These are the seven combinations of full-on and full-off, driven at 75%.",
        BLACK,
        fixed(
            columns(
                (
                    Swatch(BAR_LEVEL, BAR_LEVEL, BAR_LEVEL),
                    Swatch(BAR_LEVEL, BAR_LEVEL, 0),
                    Swatch(0, BAR_LEVEL, BAR_LEVEL),
                    Swatch(0, BAR_LEVEL, 0),
                    Swatch(BAR_LEVEL, 0, BAR_LEVEL),
                    Swatch(BAR_LEVEL, 0, 0),
                    Swatch(0, 0, BAR_LEVEL),
                )
            )
        ),
    ),
    _pattern(
        "colorchecker",
        "ColorChecker chart",
        "How the display looks on the chart this build grades it against.",
        "The skin tones in the top row and the grey scale along the bottom. Cyan "
        "lies outside sRGB, so no display driven in sRGB reaches it and the difference is the chart's.",
        BLACK,
        fixed(grid(_chart_swatches(), across=6, left=0.08, top=0.14, right=0.92, bottom=0.86)),
    ),
    _pattern(
        "crosshatch",
        "Crosshatch",
        "Whether the signal reaches the panel one pixel to one pixel.",
        "Lines that are blurred, doubled, uneven in width, or grey rather than white. "
        "Any of those means something is resampling the image, and every exact value in "
        "these patterns is landing softened.",
        BLACK,
        _crosshatch,
        exact_pixels=True,
    ),
)

#: The ids a surface offers, in the order the catalogue lists them.
PATTERN_IDS: tuple[str, ...] = tuple(pattern.pattern_id for pattern in CATALOGUE)


def pattern_named(pattern_id: str) -> Pattern:
    """Return one pattern by id, refusing an id the catalogue does not carry."""
    for pattern in CATALOGUE:
        if pattern.pattern_id == pattern_id:
            return pattern
    offered = ", ".join(PATTERN_IDS)
    raise PatternError(f"there is no pattern named {pattern_id!r}. The patterns offered are: {offered}.")


__all__ = [
    "BAR_LEVEL",
    "CATALOGUE",
    "CROSSHATCH_SPACING",
    "MINIMUM_HEIGHT",
    "MINIMUM_WIDTH",
    "PATTERN_IDS",
    "PLUGE_LEVELS",
    "RAMP_STEPS",
    "WHITE_CLIP_LEVELS",
    "pattern_named",
]
