"""The arithmetic a test pattern is, before anything paints one.

A pattern is judged by eye, so almost nothing about the finished thing can be
asserted here. What can be asserted is everything in front of the window. A
pattern is a set of exact integers over rectangles with integer edges, and
every defect worth catching in this lane is arithmetic: a bar that rounds away,
a seam between two bars that should share an edge, a rectangle laid past the
edge of the surface, a ground that does not cover what a layout forgot.

The seam is the one worth stating. Two regions sharing a fractional edge have
to round that edge to the same pixel, or a set of bars covering a band leaves a
one-pixel line of whatever was underneath. An operator judging near-black steps
on a PLUGE would read that line as the display and would be reading this
program.
"""

from __future__ import annotations

import pytest

from calibrate_pro.application.patterns import (
    BLACK,
    MAXIMUM_LEVEL,
    WHITE,
    Pattern,
    PatternError,
    PlacedRegion,
    Region,
    Swatch,
    columns,
    fixed,
    grid,
)

#: A surface wide enough that a rounding difference of one pixel is visible in
#: the arithmetic, and odd enough that nothing divides into it evenly.
ODD_SURFACE = (1367, 769)


def make_pattern(layout, **overrides) -> Pattern:
    """One pattern around a layout, with everything else out of the way."""
    fields = {
        "pattern_id": "under-test",
        "name": "Pattern under test",
        "decision": "Nothing; this pattern exists to be laid out.",
        "look_for": "Nothing.",
        "ground": BLACK,
        "minimum_width": 320,
        "minimum_height": 240,
        "exact_pixels": False,
        "layout": layout,
    }
    fields.update(overrides)
    return Pattern(**fields)


class TestSwatch:
    """One exact 8-bit colour, and the values it refuses to be."""

    @pytest.mark.parametrize("channel", ["red", "green", "blue"])
    @pytest.mark.parametrize("value", [-1, 256, 1000])
    def test_a_channel_outside_the_signal_is_refused(self, channel: str, value: int) -> None:
        """A code value no cable carries is not quietly clamped into one."""
        with pytest.raises(PatternError, match=channel):
            Swatch(**{"red": 0, "green": 0, "blue": 0, channel: value})

    def test_a_boolean_is_not_an_integer_here(self) -> None:
        """True is 1 to Python and is not a code value anybody typed."""
        with pytest.raises(PatternError, match="exact integer"):
            Swatch(True, 0, 0)

    def test_a_float_that_happens_to_be_whole_is_still_refused(self) -> None:
        """128.0 is a computed number, and a code value is one that was chosen."""
        with pytest.raises(PatternError, match="exact integer"):
            Swatch(128.0, 0, 0)  # type: ignore[arg-type]

    def test_the_ends_of_the_signal_map_to_the_ends_of_the_patch_scale(self) -> None:
        """The seam to the measurement side, where a swatch becomes a patch.

        A pattern and a patch have to carry the same colour or a pattern shown
        to an operator and a patch shown to an instrument are different
        stimuli. Both ends are exact rather than near, so full white measures
        as full white rather than as 0.9999.
        """
        assert BLACK.signal == (0.0, 0.0, 0.0)
        assert WHITE.signal == (1.0, 1.0, 1.0)

    def test_a_grey_drives_all_three_channels_to_the_same_value(self) -> None:
        assert Swatch.grey(37).values == (37, 37, 37)


class TestRegionPlacement:
    """Fractions to pixels, one edge at a time."""

    def test_two_regions_sharing_an_edge_land_on_the_same_pixel(self) -> None:
        """The seam test. A shared fraction rounds once, so the bars meet.

        Rounded independently as width times fraction, a right edge and the
        left edge beside it are the same expression and land on the same
        pixel. Rounding a width instead would drift, and a band of eight bars
        would end one to three pixels short of where it was declared.
        """
        width, height = ODD_SURFACE
        left = Region(0.0, 0.0, 1 / 3, 1.0, BLACK).place(width, height)
        right = Region(1 / 3, 0.0, 1.0, 1.0, WHITE).place(width, height)

        assert left.right == right.x

    def test_a_region_that_rounds_away_is_refused_rather_than_dropped(self) -> None:
        """A bar too thin to draw is a pattern that is not what was asked for."""
        with pytest.raises(PatternError, match="thinner than a pixel"):
            Region(0.0, 0.0, 0.001, 1.0, WHITE).place(320, 240)

    def test_a_region_enclosing_no_area_is_refused(self) -> None:
        with pytest.raises(PatternError, match="encloses none"):
            Region(0.5, 0.0, 0.5, 1.0, WHITE)

    @pytest.mark.parametrize("edge", ["left", "top", "right", "bottom"])
    def test_an_edge_outside_the_surface_is_refused(self, edge: str) -> None:
        fields = {"left": 0.0, "top": 0.0, "right": 1.0, "bottom": 1.0, "swatch": WHITE}
        fields[edge] = 1.5
        with pytest.raises(PatternError, match=edge):
            Region(**fields)  # type: ignore[arg-type]


class TestColumns:
    """A band of equal columns, which is what most of the catalogue is."""

    def test_a_band_of_columns_tiles_with_no_seam_and_no_overlap(self) -> None:
        """Every interior edge is shared, so the band is covered exactly once."""
        width, height = ODD_SURFACE
        placed = [region.place(width, height) for region in columns(tuple(Swatch.grey(level) for level in range(8)))]

        assert placed[0].x == 0
        assert placed[-1].right == width
        for earlier, later in zip(placed, placed[1:], strict=False):
            assert earlier.right == later.x

    def test_a_band_inset_from_the_surface_starts_and_ends_where_it_says(self) -> None:
        width, height = ODD_SURFACE
        placed = [
            region.place(width, height)
            for region in columns((BLACK, WHITE), left=0.05, top=0.35, right=0.75, bottom=0.65)
        ]

        assert placed[0].x == round(0.05 * width)
        assert placed[-1].right == round(0.75 * width)
        assert placed[0].y == round(0.35 * height)
        assert placed[0].bottom == round(0.65 * height)

    def test_a_band_of_no_columns_is_refused(self) -> None:
        with pytest.raises(PatternError, match="paints nothing"):
            columns(())


class TestGrid:
    """Swatches laid row by row, which is what a chart is."""

    def test_a_grid_tiles_both_directions_with_shared_edges(self) -> None:
        width, height = ODD_SURFACE
        placed = [region.place(width, height) for region in grid((BLACK,) * 6, across=3)]

        assert placed[0].right == placed[1].x
        assert placed[1].right == placed[2].x
        assert placed[2].right == width
        assert placed[0].bottom == placed[3].y
        assert placed[3].bottom == height

    def test_a_swatch_count_that_does_not_fill_its_rows_is_refused(self) -> None:
        """A chart with a ragged last row is not the chart it was declared as."""
        with pytest.raises(PatternError, match="do not fill rows"):
            grid((BLACK,) * 7, across=3)

    def test_a_grid_of_no_swatches_is_refused(self) -> None:
        with pytest.raises(PatternError, match="paints nothing"):
            grid((), across=3)


class TestPatternPlacement:
    """What a pattern hands a surface, and what it refuses to hand one."""

    def test_the_ground_is_the_first_region_and_covers_the_whole_surface(self) -> None:
        """A pixel a layout forgot shows the ground, not the last frame.

        This is why the ground is returned rather than assumed. A surface
        painting these in order writes every pixel it was given before it
        writes anything on top, so an operator judging black is judging black
        rather than whatever the window held a moment earlier.
        """
        pattern = make_pattern(fixed(columns((WHITE,), left=0.4, top=0.4, right=0.6, bottom=0.6)), ground=BLACK)

        placed = pattern.place(*ODD_SURFACE)

        assert placed[0] == PlacedRegion(0, 0, ODD_SURFACE[0], ODD_SURFACE[1], BLACK)
        assert len(placed) == 2

    def test_a_surface_below_the_minimum_is_refused_by_name(self) -> None:
        """Bars a few pixels wide cannot carry the judgement they exist for."""
        pattern = make_pattern(fixed(()))

        with pytest.raises(PatternError, match="Pattern under test needs a surface"):
            pattern.place(319, 240)

    def test_a_layout_reaching_past_the_edge_is_refused(self) -> None:
        """The check on the layout, for a region built in pixels rather than fractions."""
        pattern = make_pattern(lambda width, height: (PlacedRegion(0, 0, width + 1, height, WHITE),))

        with pytest.raises(PatternError, match="past the edge"):
            pattern.place(*ODD_SURFACE)

    def test_a_refusal_from_inside_a_layout_names_the_pattern_and_the_surface(self) -> None:
        """The message an operator reads says which pattern and which size."""
        pattern = make_pattern(fixed((Region(0.0, 0.0, 0.0005, 1.0, WHITE),)))

        with pytest.raises(PatternError, match=r"Pattern under test does not fit 400 by 300"):
            pattern.place(400, 300)

    @pytest.mark.parametrize("size", [(1366.0, 768), (1366, True)])
    def test_a_surface_size_that_is_not_an_exact_integer_is_refused(self, size: tuple) -> None:
        """A window reports pixels, and a number that is nearly one is a bug upstream."""
        pattern = make_pattern(fixed(()))

        with pytest.raises(PatternError, match="exact integer"):
            pattern.place(*size)

    def test_full_white_is_the_top_of_the_signal(self) -> None:
        """A field of white drives every channel to the maximum a cable carries."""
        assert WHITE.values == (MAXIMUM_LEVEL,) * 3
