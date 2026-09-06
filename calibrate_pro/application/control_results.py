"""What a display answered after it was asked to change one of its own controls.

These results are separated from the contract they belong to because they carry
the one judgement this lane makes: whether the display did what it was asked.
That judgement is computed from a read taken after the write, never from the
write call's return value, and every property here is written so a reader can
see which of the two it came from.

A display can answer a write with success and then hold its old value, or land
on a value of its own choosing between the two. So a write reports three
numbers, not one: what the control read before, what it was asked for, and what
it reads now. ``accepted`` compares the last against the middle one.

Nothing here says a screen changed brightness. It says a control now reads at a
value, which is the display's own account of its state.
"""

from __future__ import annotations

from dataclasses import dataclass

from calibrate_pro.application.monitor_controls import (
    MonitorControlError,
    MonitorReading,
    label_for,
    validate_code,
)


@dataclass(frozen=True)
class StagedControl:
    """One value held for a later write, beside what the control reads now.

    Staging changes nothing on the display. This is the record of a request,
    and it carries the reading it was checked against so a surface can show the
    operator both numbers rather than replacing the display's own value with
    one this session made up.
    """

    code: int
    label: str
    current: int
    requested: int
    maximum: int

    def __post_init__(self) -> None:
        validate_code(self.code, "code")
        if type(self.label) is not str or not self.label.strip():
            raise MonitorControlError("label must be a nonblank exact string")
        for name in ("current", "requested", "maximum"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise MonitorControlError(f"{name} must be an exact integer")
        if self.maximum < 1:
            raise MonitorControlError("a control reporting a maximum below 1 drives nothing")
        for name in ("current", "requested"):
            value = getattr(self, name)
            if value < 0 or value > self.maximum:
                raise MonitorControlError(f"{name} must fall within 0 and the reported maximum")

    @property
    def changes(self) -> bool:
        """Whether writing this would ask the display for a different value."""
        return self.requested != self.current

    @property
    def line(self) -> str:
        if not self.changes:
            return f"{self.label}: staged at {self.requested}, which is what it reads now"
        return f"{self.label}: reads {self.current}, staged at {self.requested}"


@dataclass(frozen=True)
class ControlWrite:
    """One code the display was asked to change, and what it answered afterwards."""

    code: int
    label: str
    before: int
    requested: int
    after: int

    def __post_init__(self) -> None:
        validate_code(self.code, "code")
        if type(self.label) is not str or not self.label.strip():
            raise MonitorControlError("label must be a nonblank exact string")
        for name in ("before", "requested", "after"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise MonitorControlError(f"{name} must be an exact integer")
            if value < 0:
                raise MonitorControlError(f"{name} must not be negative")

    @property
    def accepted(self) -> bool:
        """Whether the display now reads at the value it was asked for."""
        return self.after == self.requested

    @property
    def moved(self) -> bool:
        """Whether the display reads at a different value than before the write."""
        return self.after != self.before

    @property
    def line(self) -> str:
        if self.accepted:
            return f"{self.label}: {self.before} to {self.after}"
        if self.moved:
            return f"{self.label}: asked for {self.requested}, reads {self.after}"
        return f"{self.label}: asked for {self.requested}, still reads {self.after}"


@dataclass(frozen=True)
class ControlTransaction:
    """Every write one apply attempted, and what the display did with each."""

    display_id: str
    writes: tuple[ControlWrite, ...]
    restored: tuple[int, ...]
    failure: str | None

    def __post_init__(self) -> None:
        if type(self.display_id) is not str or not self.display_id.strip():
            raise MonitorControlError("display_id must be a nonblank exact string")
        if type(self.writes) is not tuple or type(self.restored) is not tuple:
            raise MonitorControlError("writes and restored must be exact tuples")
        if self.failure is not None and (type(self.failure) is not str or not self.failure.strip()):
            raise MonitorControlError("failure must be a nonblank exact string or None")

    @property
    def accepted(self) -> bool:
        """Whether every code reads at the value it was asked for and nothing failed."""
        return self.failure is None and all(write.accepted for write in self.writes)

    @property
    def rejected(self) -> tuple[ControlWrite, ...]:
        """The writes whose read-back disagreed with what was asked for."""
        return tuple(write for write in self.writes if not write.accepted)

    @property
    def summary(self) -> str:
        """One line an operator can act on, including when the set failed partway.

        A set that was refused midway carries no writes, because the codes that
        went out were put back. Reporting only that leaves out the two things
        worth knowing: which control refused, and whether the rollback landed.
        Both are named here, so a display left partly changed says so.
        """
        parts: list[str] = []
        if self.writes:
            written = "; ".join(write.line for write in self.writes)
            parts.append(f"{self.display_id} read back {written}.")
            if self.rejected:
                parts.append(f"{len(self.rejected)} of {len(self.writes)} did not take the value asked for.")
        else:
            parts.append(f"No control was written on {self.display_id}.")
        if self.restored:
            names = ", ".join(label_for(code) for code in self.restored)
            parts.append(f"{names} put back to the value read before the write.")
        if self.failure is not None:
            parts.append(f"The write stopped: {self.failure}")
        return " ".join(parts)


@dataclass(frozen=True)
class ControlRestore:
    """What the readable controls said before and after a factory restore.

    A display is asked to restore itself and answers nothing. So this reports
    the two readings and names the controls that moved between them. It does
    not say the display is at its factory values, because only the display
    knows that and it was not asked.
    """

    display_id: str
    before: MonitorReading
    after: MonitorReading

    @property
    def moved(self) -> tuple[str, ...]:
        names = []
        for control in self.after.controls:
            previous = self.before.control(control.code)
            if previous is not None and previous.current != control.current:
                names.append(f"{control.label} {previous.current} to {control.current}")
        return tuple(names)

    @property
    def summary(self) -> str:
        if not self.moved:
            return (
                f"{self.display_id} was asked to restore its factory settings "
                f"and every control this build reads came back at the value it held."
            )
        return f"{self.display_id} restored its factory settings. " + "; ".join(self.moved) + "."


__all__ = [
    "ControlRestore",
    "ControlTransaction",
    "ControlWrite",
    "StagedControl",
]
