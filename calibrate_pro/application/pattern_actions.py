"""The session action that puts a test pattern on the selected display.

This is the only lane in the product that produces nothing. No file is written,
no panel control moves, no evidence is recorded, and the session stage does not
advance. What it produces is a surface an operator looks at, and a decision they
make with their own eyes about the two panel controls that sit upstream of
everything else this build can do.

That is why it is worth shipping rather than leaving to a browser page. The
value of a test pattern is the exactness of the code values it sends, and a page
in a browser is composited, colour managed, and scaled before it reaches the
panel. This lane refuses instead: a surface that cannot carry the pattern says
so with nothing painted, and a pattern that needs a one-pixel line is not
offered at all on a scaled display.

The port opened here is closed here, on every path, for the same reason the
control lane closes its own. A window left open on top of everything else with
no way to dismiss it is worse than a refusal.

Nothing in this module decides whether the action is offered. The manifest and
the resolver do that, and the method routes through the runner for it.
"""

from __future__ import annotations

from calibrate_pro.application.outcomes import ActionOutcome
from calibrate_pro.application.pattern_catalogue import pattern_named
from calibrate_pro.application.pattern_surface import (
    PatternPresentation,
    PatternSurfaceError,
    PatternSurfaceSource,
    PatternSurfaceUnavailable,
    show_pattern,
)
from calibrate_pro.application.patterns import PatternError
from calibrate_pro.application.refusals import (
    no_display_selected,
    no_such_pattern,
    pattern_surface_refused,
)
from calibrate_pro.application.runner import SessionActionRunner
from calibrate_pro.application.session import SessionState


class PatternActions:
    """Showing one test pattern on the display this session selected."""

    _state: SessionState
    _patterns: PatternSurfaceSource
    _runner: SessionActionRunner

    def show_test_pattern(self, pattern_id: str) -> ActionOutcome[PatternPresentation]:
        """Open a surface on the selected display and hold one pattern on it.

        The call returns when the operator dismisses the surface, because a
        pattern is judged while it is on screen and a result reported before
        then would describe a window nobody had looked at yet. What comes back
        names the pattern, what the surface established about itself, and how
        the operator ended it.
        """
        return self._runner.run("patterns.open", lambda: self._show_test_pattern(pattern_id))

    def _show_test_pattern(self, pattern_id: str) -> PatternPresentation:
        display_id = self._state.selected_display_id
        if display_id is None:
            raise no_display_selected()
        try:
            pattern = pattern_named(pattern_id)
        except PatternError as exc:
            raise no_such_pattern(str(exc)) from exc
        try:
            port = self._patterns.open(display_id)
        except PatternSurfaceUnavailable as exc:
            raise pattern_surface_refused(str(exc)) from exc
        try:
            return show_pattern(port, display_id, pattern)
        except (PatternError, PatternSurfaceError, PatternSurfaceUnavailable) as exc:
            raise pattern_surface_refused(str(exc)) from exc
        finally:
            port.close()


__all__ = ["PatternActions"]
