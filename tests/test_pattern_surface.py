"""What a surface has to establish before a pattern shown on it means anything.

Putting a pattern on screen claims a set of exact code values reached the
panel, and on a modern desktop that claim is not free. Two facts are readable
from inside the process and one is not, and the whole point of this layer is
that the third is reported as unestablished rather than assumed away.

Two refusals are checked with nothing painted, because both are cases where the
operator would otherwise look at a surface and draw a conclusion from it. A
crosshatch on a scaled display shows this program's resampling and reads as the
display's. A pattern laid out on a window too small for its bars shows a
judgement that cannot be made at that size.
"""

from __future__ import annotations

import pytest

from calibrate_pro.application.pattern_catalogue import pattern_named
from calibrate_pro.application.pattern_surface import (
    NO_SURFACE_REASON,
    NoPatternSurfaceSource,
    PatternSurfaceError,
    PatternSurfaceUnavailable,
    SurfaceQualification,
    qualify,
    show_pattern,
)
from tests.pattern_surface_support import DISMISSED, SURFACE, FakeSurface

DISPLAY = "FAKE-DISPLAY-1"


def qualification(**overrides) -> SurfaceQualification:
    fields = {
        "display_id": DISPLAY,
        "surface": SURFACE,
        "device_pixels": (1920, 1080),
        "pixel_ratio": 1.0,
    }
    fields.update(overrides)
    return SurfaceQualification(**fields)


class TestWhatASurfaceReportsAboutItself:
    """The two facts a process can read, and the values it refuses to read."""

    @pytest.mark.parametrize("field", ["display_id", "surface"])
    @pytest.mark.parametrize("value", ["", "   "])
    def test_a_blank_name_is_refused(self, field: str, value: str) -> None:
        """A report naming an empty display is a report about nothing."""
        with pytest.raises(PatternSurfaceError, match=field):
            qualification(**{field: value})

    @pytest.mark.parametrize("pixels", [(0, 1080), (1920, 0), (-1, 1080)])
    def test_a_window_with_no_area_is_refused(self, pixels: tuple[int, int]) -> None:
        with pytest.raises(PatternSurfaceError, match="which no window has"):
            qualification(device_pixels=pixels)

    def test_a_boolean_dimension_is_not_a_pixel_count(self) -> None:
        with pytest.raises(PatternSurfaceError, match="which no window has"):
            qualification(device_pixels=(True, 1080))

    @pytest.mark.parametrize("ratio", [0.0, -1.0])
    def test_a_ratio_at_or_below_zero_has_no_geometry(self, ratio: float) -> None:
        with pytest.raises(PatternSurfaceError, match="pixel ratio"):
            qualification(pixel_ratio=ratio)

    def test_a_ratio_that_is_not_a_number_is_refused(self) -> None:
        with pytest.raises(PatternSurfaceError, match="must be a number"):
            qualification(pixel_ratio="1.0")

    def test_an_unscaled_surface_is_the_one_that_reaches_the_panel_intact(self) -> None:
        assert qualification(pixel_ratio=1.0).one_to_one
        assert not qualification(pixel_ratio=1.25).one_to_one

    def test_the_summary_names_the_display_the_size_and_the_scaling(self) -> None:
        """One sentence, carrying every fact the surface actually established."""
        summary = qualification(pixel_ratio=1.5).summary

        assert DISPLAY in summary
        assert "1920 by 1080" in summary
        assert "scaled at 1.5" in summary


class TestWhatASurfaceCannotEstablish:
    """The honest null, which travels with every pattern rather than once."""

    def test_colour_management_is_reported_as_unestablished_on_every_pattern(self) -> None:
        """No process can read whether the desktop is transforming its output.

        Reporting it as absent would be the same defect as reporting a control
        value from a write call's return: an answer nobody got. So it is named
        every time, beside the values, rather than left out.
        """
        limits = qualification().unestablished

        assert any("colour transform" in limit and "not established" in limit for limit in limits)

    def test_the_qualification_a_port_produces_never_carries_a_colour_answer(self) -> None:
        """The check on the field itself: nothing reading a port fills it in."""
        surface = FakeSurface()

        assert qualify(surface, DISPLAY).colour_management is None

    def test_an_unscaled_surface_reports_the_one_limit_and_no_more(self) -> None:
        assert len(qualification(pixel_ratio=1.0).unestablished) == 1

    def test_a_scaled_surface_says_so_beside_the_values_it_is_showing(self) -> None:
        """The operator is about to turn a knob on the strength of what they see."""
        limits = qualification(pixel_ratio=1.25).unestablished

        assert len(limits) == 2
        assert "resampled" in limits[1]
        assert "1.25" in limits[1]


class TestPuttingAPatternOnASurface:
    """What is painted, what is refused, and what is left to the caller."""

    def test_a_pattern_is_presented_once_and_then_waited_on(self) -> None:
        """Two paints would be a flash an operator judging black would notice."""
        surface = FakeSurface()

        presentation = show_pattern(surface, DISPLAY, pattern_named("pluge"))

        assert len(surface.presented) == 1
        assert surface.waits == 1
        assert presentation.regions == len(surface.regions)
        assert presentation.ended == DISMISSED

    def test_the_call_returns_only_after_the_operator_ended_it(self) -> None:
        """A result reported before then describes a window nobody looked at.

        The fake reports how it ended, and that string is carried through
        rather than replaced, so a surface that closed for a reason other than
        a keypress says which reason on the way out.
        """
        surface = FakeSurface(ended="the window was closed")

        presentation = show_pattern(surface, DISPLAY, pattern_named("black"))

        assert presentation.ended == "the window was closed"
        assert "the window was closed" in presentation.summary

    def test_the_presentation_carries_the_pattern_s_own_words(self) -> None:
        pattern = pattern_named("white-clip")

        presentation = show_pattern(FakeSurface(), DISPLAY, pattern)

        assert presentation.pattern_id == pattern.pattern_id
        assert presentation.decision == pattern.decision
        assert presentation.look_for == pattern.look_for
        assert presentation.limits == presentation.qualification.unestablished

    def test_a_pixel_exact_pattern_is_refused_on_a_scaled_surface_with_nothing_painted(self) -> None:
        """The refusal that keeps this program's resampling off the operator's verdict."""
        surface = FakeSurface(pixel_ratio=1.5)

        with pytest.raises(PatternSurfaceError, match="one pixel wide"):
            show_pattern(surface, DISPLAY, pattern_named("crosshatch"))

        assert surface.presented == []
        assert surface.waits == 0

    def test_the_scaling_refusal_says_what_to_change(self) -> None:
        """A refusal an operator cannot act on is a dead end with a reason attached."""
        with pytest.raises(PatternSurfaceError, match="100% scaling"):
            show_pattern(FakeSurface(pixel_ratio=2.0), DISPLAY, pattern_named("crosshatch"))

    def test_every_other_pattern_still_shows_on_a_scaled_surface(self) -> None:
        """Fractions survive scaling, so only the pixel-exact one is withheld."""
        surface = FakeSurface(pixel_ratio=1.5)

        presentation = show_pattern(surface, DISPLAY, pattern_named("grey-ramp"))

        assert len(surface.presented) == 1
        assert not presentation.qualification.one_to_one

    def test_a_surface_too_small_for_the_pattern_is_refused_before_it_paints(self) -> None:
        """A judgement that cannot be made at that size is not offered at it."""
        surface = FakeSurface(device_pixels=(300, 200))

        with pytest.raises(Exception, match="needs a surface of at least"):
            show_pattern(surface, DISPLAY, pattern_named("pluge"))

        assert surface.presented == []

    def test_showing_a_pattern_does_not_close_the_surface_it_was_handed(self) -> None:
        """The caller owns the window's lifetime, and closes it on every path.

        Closing here would leave the action layer with nothing to close and a
        second close to make safe. Keeping the two apart is what lets the
        action close the port in a finally, which is the only thing standing
        between a refusal and a fullscreen window with no way out.
        """
        surface = FakeSurface()

        show_pattern(surface, DISPLAY, pattern_named("white"))

        assert surface.closes == 0


class TestASessionWithNoSurfaceWired:
    """The default, which proves nothing about the machine and says so."""

    def test_it_reports_no_surface_and_opens_nothing(self) -> None:
        source = NoPatternSurfaceSource()

        assert not source.present()
        assert source.describe() == NO_SURFACE_REASON
        with pytest.raises(PatternSurfaceUnavailable, match=NO_SURFACE_REASON):
            source.open(DISPLAY)

    def test_a_reason_of_its_own_is_the_one_reported(self) -> None:
        """The composition names what it found, and that reaches the operator."""
        source = NoPatternSurfaceSource("this build has no window toolkit installed")

        assert source.describe() == "this build has no window toolkit installed"

    @pytest.mark.parametrize("reason", ["", "   "])
    def test_a_blank_reason_is_refused_rather_than_shipped_empty(self, reason: str) -> None:
        with pytest.raises(TypeError, match="nonblank"):
            NoPatternSurfaceSource(reason)
