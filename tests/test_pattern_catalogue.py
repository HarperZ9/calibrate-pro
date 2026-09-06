"""The patterns this build offers, and what each one has to be to be offered.

A catalogue of patterns is easy to pad and hard to keep honest. Every entry
here has to name a decision an operator makes while looking at it, has to lay
out on the sizes a display actually is, and has to carry the exact values its
description claims. Those are the three ways an entry goes wrong: it becomes a
coloured screen with no purpose, it works at 1920 by 1080 and refuses at 3840
by 2160, or its code values drift from the words beside it.

The crosshatch is checked hardest because it is the one pattern whose whole
claim is pixel structure. A line drawn two pixels wide would still look like a
grid, and an operator reading a doubled line concludes their display is
resampling when the doubling happened here.
"""

from __future__ import annotations

import pytest

from calibrate_pro.application.pattern_catalogue import (
    BAR_LEVEL,
    CATALOGUE,
    CROSSHATCH_SPACING,
    MINIMUM_HEIGHT,
    MINIMUM_WIDTH,
    PATTERN_IDS,
    PLUGE_LEVELS,
    RAMP_STEPS,
    WHITE_CLIP_LEVELS,
    pattern_named,
)
from calibrate_pro.application.patterns import MAXIMUM_LEVEL, Pattern, PatternError, Swatch
from calibrate_pro.core.colorchecker import COLORCHECKER_PATCHES

#: Sizes a panel this product is pointed at actually reports, plus the smallest
#: surface the catalogue offers anything on. A pattern that lays out on one and
#: refuses on another is a pattern that works on the machine it was written on.
SURFACES = [
    (MINIMUM_WIDTH, MINIMUM_HEIGHT),
    (1280, 1024),
    (1920, 1080),
    (2560, 1440),
    (3440, 1440),
    (3840, 2160),
    (1367, 769),
]


def placed_ids() -> list[str]:
    return [pattern.pattern_id for pattern in CATALOGUE]


class TestTheCatalogueItself:
    """What has to be true of every entry, whatever it draws."""

    def test_every_pattern_has_a_distinct_id_and_the_index_agrees(self) -> None:
        """Two entries sharing an id would make one of them unreachable by name."""
        assert len(set(placed_ids())) == len(CATALOGUE)
        assert tuple(placed_ids()) == PATTERN_IDS

    @pytest.mark.parametrize("pattern", CATALOGUE, ids=placed_ids())
    def test_every_pattern_names_the_decision_it_is_for(self, pattern: Pattern) -> None:
        """A pattern nobody knows how to read is a coloured screen.

        Both sentences travel to every surface that offers the pattern, so an
        entry with a blank one ships a screen with no instructions attached to
        it. The length floor is there because a word is not a sentence.
        """
        assert len(pattern.decision.split()) >= 5
        assert len(pattern.look_for.split()) >= 8
        assert pattern.name.strip()

    @pytest.mark.parametrize("pattern", CATALOGUE, ids=placed_ids())
    @pytest.mark.parametrize("surface", SURFACES, ids=[f"{w}x{h}" for w, h in SURFACES])
    def test_every_pattern_lays_out_on_every_surface_a_panel_reports(
        self, pattern: Pattern, surface: tuple[int, int]
    ) -> None:
        """The whole catalogue, on the sizes displays are, with no seam anywhere.

        Regions are checked against the surface rather than against each other,
        because a layout that reached past the edge would be clipped by the
        window and an operator would see a truncated pattern with nothing
        saying so.
        """
        width, height = surface

        placed = pattern.place(width, height)

        assert placed[0].width == width and placed[0].height == height
        for region in placed:
            assert region.x >= 0 and region.y >= 0
            assert region.right <= width and region.bottom <= height

    def test_asking_for_a_pattern_this_build_does_not_carry_lists_the_ones_it_does(self) -> None:
        """A refusal an operator can act on names what to type instead."""
        with pytest.raises(PatternError) as refused:
            pattern_named("gradient-sweep")

        message = str(refused.value)
        assert "gradient-sweep" in message
        for pattern_id in PATTERN_IDS:
            assert pattern_id in message

    @pytest.mark.parametrize("pattern_id", PATTERN_IDS)
    def test_every_id_the_index_offers_resolves_to_a_pattern(self, pattern_id: str) -> None:
        assert pattern_named(pattern_id).pattern_id == pattern_id


class TestTheValuesEachPatternSends:
    """The code values, against the words printed beside them."""

    def test_the_pluge_offers_the_lowest_steps_above_black_on_black(self) -> None:
        """Brightness is set by finding the lowest bar that separates from the ground."""
        pattern = pattern_named("pluge")
        placed = pattern.place(1920, 1080)

        assert placed[0].swatch == Swatch.grey(0)
        levels = {region.swatch.red for region in placed[1:] if region.swatch.values == (region.swatch.red,) * 3}
        assert set(PLUGE_LEVELS) <= levels
        assert min(PLUGE_LEVELS) == 1
        assert MAXIMUM_LEVEL in levels, "a PLUGE carries a white reference beside the low bars"

    def test_the_white_clip_steps_run_up_to_full_white_and_stay_distinct(self) -> None:
        """Contrast is set by finding where the steps below white stop merging."""
        assert WHITE_CLIP_LEVELS[-1] == MAXIMUM_LEVEL
        assert len(set(WHITE_CLIP_LEVELS)) == len(WHITE_CLIP_LEVELS)
        assert list(WHITE_CLIP_LEVELS) == sorted(WHITE_CLIP_LEVELS)

    def test_the_ramp_runs_end_to_end_at_even_spacing(self) -> None:
        """Both ends are present, so the ramp says whether black and white clip."""
        placed = pattern_named("grey-ramp").place(1920, 1080)
        levels = [region.swatch.red for region in placed[1:]]

        assert len(levels) == RAMP_STEPS
        assert levels[0] == 0
        assert levels[-1] == MAXIMUM_LEVEL
        assert levels == sorted(levels)

    def test_the_colour_bars_drive_every_channel_to_the_same_level(self) -> None:
        """Seven combinations of full-on and full-off, at one drive level."""
        placed = pattern_named("colour-bars").place(1920, 1080)
        bars = [region.swatch for region in placed[1:]]

        assert len(bars) == 7
        for bar in bars:
            assert set(bar.values) <= {0, BAR_LEVEL}
        assert len({bar.values for bar in bars}) == 7

    def test_the_chart_is_the_one_the_rest_of_this_package_grades_against(self) -> None:
        """One copy of the reference chart, quantized where it is drawn.

        This package has had the ColorChecker typed in more than once and the
        copies drifted. Reading it from the reference means a correction to the
        chart reaches the pattern an operator looks at in the same commit.
        """
        placed = pattern_named("colorchecker").place(1920, 1080)
        drawn = [region.swatch.values for region in placed[1:]]

        assert len(drawn) == len(COLORCHECKER_PATCHES)
        expected = [
            tuple(round(component * MAXIMUM_LEVEL) for component in patch.srgb) for patch in COLORCHECKER_PATCHES
        ]
        assert drawn == expected


class TestTheCrosshatch:
    """The one pattern whose whole claim is that a pixel is a pixel."""

    def test_it_is_the_only_pattern_asking_for_exact_pixels(self) -> None:
        """Everything else is fractions, so everything else survives scaling."""
        exact = [pattern.pattern_id for pattern in CATALOGUE if pattern.exact_pixels]

        assert exact == ["crosshatch"]

    @pytest.mark.parametrize("surface", SURFACES, ids=[f"{w}x{h}" for w, h in SURFACES])
    def test_every_line_is_exactly_one_pixel_across(self, surface: tuple[int, int]) -> None:
        """A doubled line reads as the display resampling, and would be this program."""
        width, height = surface

        lines = pattern_named("crosshatch").place(width, height)[1:]

        for line in lines:
            vertical = line.width == 1 and line.height == height
            horizontal = line.height == 1 and line.width == width
            assert vertical or horizontal, f"{line} is neither a one-pixel row nor a one-pixel column"

    @pytest.mark.parametrize("surface", SURFACES, ids=[f"{w}x{h}" for w, h in SURFACES])
    def test_the_last_row_and_column_are_drawn_whatever_the_surface_size(self, surface: tuple[int, int]) -> None:
        """Without the border an overscanning panel looks the same as one that is not.

        The grid runs on a fixed pitch, so on most sizes it stops short of the
        edge. The final row and column are added separately for that reason,
        and an operator missing them cannot tell a display showing the signal
        whole from one cropping it.
        """
        width, height = surface

        lines = pattern_named("crosshatch").place(width, height)[1:]

        columns_at = {line.x for line in lines if line.width == 1}
        rows_at = {line.y for line in lines if line.height == 1}
        assert {0, width - 1} <= columns_at
        assert {0, height - 1} <= rows_at

    def test_the_lines_run_on_the_pitch_the_module_declares(self) -> None:
        """The spacing is a stated number, not whatever the loop happened to do."""
        width, height = 1920, 1080

        lines = pattern_named("crosshatch").place(width, height)[1:]

        columns_at = sorted({line.x for line in lines if line.width == 1})
        on_pitch = [x for x in columns_at if x != width - 1]
        assert on_pitch == list(range(0, width, CROSSHATCH_SPACING))
