"""What a session remembers about one display's own controls.

A reading, the values staged against it, and the transaction that wrote them
are held together because none of the three means anything on its own. A staged
brightness with no reading behind it is a number with no range to check it
against. A transaction carried past the display it was taken on describes a
panel that is no longer selected.

Staging is checked here rather than at the surface that offers it. The range a
control accepts comes from the display, not from this build, so the only place
a staged value can be judged is beside the reading that reported the range. A
value staged for a code the display did not answer is refused for the same
reason: there is nothing to check it against, and a write to it would be a
request this session cannot report the result of.

Nothing here writes. This is the record of what a session has read and what it
means to ask for, and the procedure that changes a display lives in
:mod:`calibrate_pro.application.control_transactions`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from calibrate_pro.application.control_results import ControlTransaction
from calibrate_pro.application.monitor_controls import (
    MonitorControlError,
    MonitorReading,
    label_for,
    validate_code,
)


@dataclass
class MonitorControlSession:
    """One display's controls as this session has seen them."""

    #: Whether a monitor control port was wired into this composition. It says
    #: nothing about whether a display answered, which is what the reading
    #: says. Both are required before a control is offered, for the same
    #: reason the measurement route and the sensor capability are both
    #: required before a run is offered.
    route: bool = False
    reading: MonitorReading | None = None
    staged: dict[int, int] = field(default_factory=dict)
    applied: ControlTransaction | None = None

    def __post_init__(self) -> None:
        if type(self.route) is not bool:
            raise TypeError("route must be an exact boolean")

    @property
    def supported_codes(self) -> frozenset[int]:
        """The codes the display answered, which are the ones it may be asked to change."""
        return self.reading.codes if self.reading is not None else frozenset()

    @property
    def staged_codes(self) -> frozenset[int]:
        """The codes an apply would write if it ran now."""
        return frozenset(self.staged)

    @property
    def pending(self) -> bool:
        """Whether anything is staged, which is what an apply control is offered for."""
        return bool(self.staged)

    def record_reading(self, reading: MonitorReading) -> None:
        """Take a reading as what this session knows about the display.

        Staged values are dropped. They were checked against the ranges the
        previous reading reported, and a display that has been re-read may have
        changed underneath them, either because this session wrote to it or
        because somebody used the panel's own menu.
        """
        if type(reading) is not MonitorReading:
            raise TypeError("reading must be a MonitorReading")
        self.reading = reading
        self.staged = {}
        self.applied = None

    def stage(self, code: int, value: int) -> None:
        """Stage one value against the reading, refusing what the display cannot take."""
        validate_code(code, "code")
        if isinstance(value, bool) or not isinstance(value, int):
            raise MonitorControlError(f"the value staged for {label_for(code)} must be an exact integer")
        if self.reading is None:
            raise MonitorControlError("a control cannot be staged before the display has been read")
        control = self.reading.control(code)
        if control is None:
            raise MonitorControlError(f"{label_for(code)} was not answered by this display")
        if value < 0 or value > control.maximum:
            raise MonitorControlError(
                f"{control.label} accepts 0 through {control.maximum}, and {value} was staged for it"
            )
        self.staged[code] = value

    def unstage(self, code: int) -> None:
        """Drop one staged value, leaving the rest of the set staged."""
        validate_code(code, "code")
        self.staged.pop(code, None)

    def record_apply(self, transaction: ControlTransaction) -> None:
        """Take the result of a write, dropping the staging it consumed.

        The reading goes too. Every value in it was read before the write, so
        keeping it would leave a surface staging against numbers the display
        has moved away from. The next read is what this session knows next.
        """
        if type(transaction) is not ControlTransaction:
            raise TypeError("transaction must be a ControlTransaction")
        self.applied = transaction
        self.staged = {}
        self.reading = None

    def clear(self) -> None:
        """Forget the display entirely, keeping only whether a port was wired."""
        self.reading = None
        self.staged = {}
        self.applied = None

    def retain_for(self, display_id: str | None) -> None:
        """Keep a reading only while the display it was taken on is still selected.

        A reading describes one unit's controls. Carrying it across a display
        change would offer an operator a brightness value read off another
        monitor, and stage a write against a range that monitor reported.
        """
        if self.reading is None:
            self.clear()
            return
        if display_id is None or self.reading.display_id != display_id:
            self.clear()


__all__ = ["MonitorControlSession"]
