"""Driving the two pattern commands from a terminal.

A pattern window covers the terminal it was launched from, so the order things
are printed in is not cosmetic here. What the pattern decides has to be on
screen before the window opens or the operator reads it after they have already
made the judgement it describes, and the way out of a frameless fullscreen
window has to be said before the window is the only thing visible.

Listing is the other half, and it is the half that runs anywhere. The catalogue
is a table of exact values with no machine in it, so ``patterns`` answers on a
laptop with no display attached and no window toolkit installed.
"""

from __future__ import annotations

from pathlib import Path

from calibrate_pro.application.pattern_catalogue import CATALOGUE, PATTERN_IDS
from calibrate_pro.commands import session as commands
from calibrate_pro.commands.session_patterns import DISMISS_HINT
from tests.monitor_control_support import DISPLAY_ID
from tests.pattern_surface_support import DISMISSED, SURFACE, FakeSurface, FakeSurfaceSource, build_pattern_service
from tests.session_support import lines, run


def position(text: str, fragment: str) -> int:
    """Where a fragment starts, or a failure naming what was printed instead."""
    at = text.find(fragment)
    assert at >= 0, f"{fragment!r} was never printed:\n{text}"
    return at


class TestListingWhatThisBuildCarries:
    """``patterns``, which reads a table and touches nothing."""

    def test_every_pattern_is_listed_with_the_decision_it_is_for(self, tmp_path: Path) -> None:
        code, printed = run("patterns", build_pattern_service(tmp_path, FakeSurfaceSource(FakeSurface())))

        assert code == 0
        for pattern in CATALOGUE:
            assert pattern.pattern_id in printed
            assert pattern.name in printed
            assert pattern.decision in printed

    def test_the_listing_says_how_to_show_one(self, tmp_path: Path) -> None:
        """A list of names with no verb beside them is a list nobody can use."""
        _, printed = run("patterns", build_pattern_service(tmp_path, FakeSurfaceSource(FakeSurface())))

        assert "show-pattern" in lines(printed)[-1]
        assert str(len(CATALOGUE)) in lines(printed)[-1]

    def test_listing_answers_on_a_machine_with_no_surface_wired(self, tmp_path: Path) -> None:
        """The laptop with no window toolkit still gets the catalogue.

        This is why listing takes no session and reads no state. A build that
        could not say what patterns it carries until it had a display would be
        unable to answer the question an operator asks first.
        """
        code, printed = run("patterns", build_pattern_service(tmp_path))

        assert code == 0
        for pattern_id in PATTERN_IDS:
            assert pattern_id in printed


class TestShowingOne:
    """``show-pattern NAME``, which opens a window and waits on a person."""

    def test_what_the_pattern_decides_is_printed_before_the_window_opens(self, tmp_path: Path) -> None:
        """The ordering assertion, which is the reason the header exists.

        Both sentences and the way out are ahead of anything the surface said
        about itself, because everything printed after that point is behind a
        fullscreen window until the operator has already dismissed it.
        """
        pattern = CATALOGUE[0]
        service = build_pattern_service(tmp_path, FakeSurfaceSource(FakeSurface()))

        code, printed = run("show-pattern", service, pattern=pattern.pattern_id)

        assert code == 0
        assert position(printed, pattern.decision) < position(printed, SURFACE)
        assert position(printed, pattern.look_for) < position(printed, SURFACE)
        assert position(printed, DISMISS_HINT) < position(printed, SURFACE)

    def test_the_surface_and_the_way_it_ended_are_reported_afterwards(self, tmp_path: Path) -> None:
        service = build_pattern_service(tmp_path, FakeSurfaceSource(FakeSurface()))

        _, printed = run("show-pattern", service, pattern="pluge")

        assert "1920 by 1080" in printed
        assert DISMISSED in printed

    def test_what_the_surface_could_not_establish_is_printed_with_the_result(self, tmp_path: Path) -> None:
        """The honest null reaches the terminal, not only the return value.

        No process can read whether the desktop is transforming its output, and
        an operator about to turn a knob on the strength of what they just saw
        is the person who needs to know that.
        """
        service = build_pattern_service(tmp_path, FakeSurfaceSource(FakeSurface(pixel_ratio=1.25)))

        _, printed = run("show-pattern", service, pattern="pluge")

        assert "colour transform" in printed
        assert "resampled" in printed

    def test_the_window_opens_on_the_display_the_terminal_named(self, tmp_path: Path) -> None:
        source = FakeSurfaceSource(FakeSurface())
        service = build_pattern_service(tmp_path, source)

        code, _ = run("show-pattern", service, pattern="white", display=DISPLAY_ID)

        assert code == 0
        assert source.opened == [DISPLAY_ID]

    def test_a_name_this_build_does_not_carry_is_refused_before_anything_opens(self, tmp_path: Path) -> None:
        """The header resolves the name, so a typo costs no window and no wait."""
        source = FakeSurfaceSource(FakeSurface())
        service = build_pattern_service(tmp_path, source)

        code, printed = run("show-pattern", service, pattern="gradient-sweep")

        assert code == commands.REFUSED
        assert "gradient-sweep" in printed
        assert source.opened == []

    def test_a_refusal_after_the_header_still_leaves_the_header_printed(self, tmp_path: Path) -> None:
        """The crosshatch on a scaled display, refused with the reason on screen.

        The header is already out when the surface reports its ratio, so the
        operator reads what they were about to judge beside the reason they
        cannot judge it here. Printing the header afterwards instead would put
        both behind a window that never opened.
        """
        service = build_pattern_service(tmp_path, FakeSurfaceSource(FakeSurface(pixel_ratio=1.5)))

        code, printed = run("show-pattern", service, pattern="crosshatch")

        assert code == commands.REFUSED
        assert DISMISS_HINT in printed
        assert "100% scaling" in printed

    def test_a_session_with_no_surface_wired_is_declined_by_name(self, tmp_path: Path) -> None:
        code, printed = run("show-pattern", build_pattern_service(tmp_path), pattern="pluge")

        assert code == commands.REFUSED
        assert "pattern surface" in printed
