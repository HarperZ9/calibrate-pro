"""Showing a test pattern from a terminal, and listing the ones this build has.

A pattern is the one thing in this product an operator judges with their own
eyes rather than reads off a report, so the terminal's job here is to say what
the pattern is for before it covers the screen and what could not be
established about it afterwards. Both sentences come from the pattern and the
surface rather than from this module, which is what keeps the terminal and the
window telling an operator the same thing.

Listing costs no session. It reads the catalogue, which is a table of exact
values with no machine in it, so ``patterns`` answers on a laptop with no
display attached and no toolkit installed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from calibrate_pro.application.pattern_surface import PatternPresentation
    from calibrate_pro.application.service import FunctionalRecoveryService

#: How a pattern is dismissed, said once here and once by the window itself.
DISMISS_HINT = "Press Escape to close the pattern."


def patterns(service: FunctionalRecoveryService, args: Any) -> int:
    """List every pattern this build carries and the decision each one is for."""
    del service, args
    from calibrate_pro.application.pattern_catalogue import CATALOGUE

    for pattern in CATALOGUE:
        print(f"{pattern.pattern_id:<12s} {pattern.name}")
        print(f"             {pattern.decision}")
    print("")
    print(f"{len(CATALOGUE)} patterns. Run 'show-pattern NAME' to put one on the selected display.")
    return 0


def _print_pattern_header(pattern_id: str) -> None:
    """Say what the pattern decides and what to watch, before it is on screen.

    Printed before the window opens rather than after it closes, because the
    window covers the terminal it was launched from and an operator reading
    this afterwards has already made the judgement it describes.
    """
    from calibrate_pro.application.pattern_catalogue import pattern_named
    from calibrate_pro.application.patterns import PatternError
    from calibrate_pro.commands.session import CommandError

    try:
        pattern = pattern_named(pattern_id)
    except PatternError as refused:
        raise CommandError(str(refused)) from refused
    print(pattern.name)
    print(f"  decides    {pattern.decision}")
    print(f"  look for   {pattern.look_for}")
    print("")
    print(DISMISS_HINT)
    print("")


def _print_presentation(presentation: PatternPresentation) -> None:
    """Report the surface the pattern was shown on, and what it could not settle."""
    print(presentation.qualification.summary)
    print(f"Ended because {presentation.ended}.")
    for limit in presentation.limits:
        print("")
        print(limit)


def show_pattern(service: FunctionalRecoveryService, args: Any) -> int:
    """Hold one pattern on the selected display until the operator dismisses it."""
    from calibrate_pro.commands.session import value

    _print_pattern_header(args.pattern)
    value(service.detect())
    display_id = getattr(args, "display", None)
    if display_id:
        value(service.select_display(display_id))
    _print_presentation(value(service.show_test_pattern(args.pattern)))
    return 0


__all__ = ["DISMISS_HINT", "patterns", "show_pattern"]
