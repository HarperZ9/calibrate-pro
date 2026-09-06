"""What a session remembers about the system's colour profile store.

One reading, and whichever write was performed against it. The reading is what
every profile action is judged from: whether the selected bundle is installed,
whether this display is using it, and whether there is anything of this
product's on the display to take back off. None of those can be answered from
the bundle on disk, because the store is where the answer lives.

A reading is kept only while the display it was taken for is still selected.
The installed list is machine wide and would survive a display change, but the
associated list and the default are not, and a record that kept half of itself
valid would offer an operator an activation judged against another monitor.

Nothing here writes. This is what the session has read, and the procedure that
changes the store lives in
:mod:`calibrate_pro.application.system_profile_transactions`.
"""

from __future__ import annotations

from dataclasses import dataclass

from calibrate_pro.application.system_profile_results import (
    ProfileActivation,
    ProfileInstallation,
    ProfileRemoval,
    ProfileRestoration,
)
from calibrate_pro.application.system_profiles import SystemProfileReading

#: What a completed profile write can be. Held as one field rather than four
#: because a surface reports the last thing that happened, and a session that
#: kept an install beside a later removal would have two answers to that.
ProfileOutcome = ProfileActivation | ProfileInstallation | ProfileRemoval | ProfileRestoration


@dataclass
class SystemProfileSession:
    """The colour profile store as this session has seen it."""

    #: Whether a system profile port was wired into this composition. It says
    #: nothing about whether the store answered, which is what the reading
    #: says. Both are required before a profile write is offered.
    route: bool = False
    reading: SystemProfileReading | None = None
    applied: ProfileOutcome | None = None

    def __post_init__(self) -> None:
        if type(self.route) is not bool:
            raise TypeError("route must be an exact boolean")

    @property
    def installed(self) -> tuple[str, ...]:
        """Every profile the machine holds, or nothing when the store is unread."""
        return self.reading.installed if self.reading is not None else ()

    @property
    def ours(self) -> tuple[str, ...]:
        """The profiles this product put on the selected display."""
        return self.reading.ours if self.reading is not None else ()

    def holds(self, name: str) -> bool:
        """Whether the machine has this exact profile registered."""
        return self.reading is not None and self.reading.holds(name)

    def is_default(self, name: str) -> bool:
        """Whether the selected display hands this profile to colour-managed software."""
        return self.reading is not None and self.reading.is_default(name)

    def record_reading(self, reading: SystemProfileReading) -> None:
        """Take a reading as what this session knows about the store."""
        if type(reading) is not SystemProfileReading:
            raise TypeError("reading must be a SystemProfileReading")
        self.reading = reading
        self.applied = None

    def record_write(self, outcome: ProfileOutcome) -> None:
        """Take the result of a write, and keep the reading it ended with.

        The write already read the store afterwards, so that reading is the
        current one. Dropping it would leave a surface unable to say whether
        the profile is now in effect until somebody read again, having just
        performed the operation that settled it.
        """
        if not isinstance(outcome, ProfileActivation | ProfileInstallation | ProfileRemoval | ProfileRestoration):
            raise TypeError("outcome must be the result of a profile write")
        self.applied = outcome
        self.reading = outcome.after

    def clear(self) -> None:
        """Forget the store entirely, keeping only whether a port was wired."""
        self.reading = None
        self.applied = None

    def retain_for(self, display_id: str | None) -> None:
        """Keep a reading only while the display it was taken for is still selected."""
        if self.reading is None:
            self.clear()
            return
        if display_id is None or self.reading.display_id != display_id:
            self.clear()


__all__ = ["ProfileOutcome", "SystemProfileSession"]
