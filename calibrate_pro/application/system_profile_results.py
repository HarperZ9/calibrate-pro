"""What a profile write turned out to have done, read back from the store.

Every result here carries the reading taken before the write and the reading
taken after it, and every judgement it reports is computed from the second one.
None of them is computed from whether a native call returned success. Windows
will report a profile registered and leave a display's default untouched, and
will accept an association for a profile that is not installed, so a result that
trusted the return value would tell an operator their calibration is in effect
on evidence that never showed it.

An install is two operations and can half succeed. When registration lands and
association does not, nothing is rolled back: unregistering would delete the
file this session just wrote, on a path shared with the display vendor's own
profiles, to undo a step that may have failed for a reason the next attempt
would clear. The result reports both halves separately and refuses to call
itself accepted, which leaves the operator holding a true description of the
machine instead of a tidy one.
"""

from __future__ import annotations

from dataclasses import dataclass

from calibrate_pro.application.system_profiles import SystemProfileError, SystemProfileReading


def _exact_name(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise SystemProfileError(f"{field_name} must be a nonblank exact string")
    return value


def _readings(before: object, after: object) -> None:
    for field_name, value in (("before", before), ("after", after)):
        if not isinstance(value, SystemProfileReading):
            raise SystemProfileError(f"{field_name} must be a reading taken from the profile store")


def _same_display(before: SystemProfileReading, after: SystemProfileReading, display_id: str) -> None:
    if before.display_id != display_id or after.display_id != display_id:
        raise SystemProfileError("both readings must have been taken for the display the write named")


@dataclass(frozen=True)
class ProfileInstallation:
    """A bundle registered on the machine and attached to one display.

    ``registered`` and ``associated`` are read off the store afterwards rather
    than reported by the calls that asked for them, so a half-completed install
    is visible as the half it completed. When one half raised, ``refusal``
    carries what the colour management API said about it, which is the part a
    read-back cannot recover.
    """

    display_id: str
    name: str
    before: SystemProfileReading
    after: SystemProfileReading
    refusal: str | None = None

    def __post_init__(self) -> None:
        _exact_name(self.display_id, "display_id")
        _exact_name(self.name, "name")
        _readings(self.before, self.after)
        _same_display(self.before, self.after, self.display_id)
        if self.refusal is not None:
            _exact_name(self.refusal, "refusal")

    @property
    def registered(self) -> bool:
        """Whether the machine now holds a profile file under this name."""
        return self.after.holds(self.name)

    @property
    def associated(self) -> bool:
        """Whether this display's own profile list now names it."""
        return self.after.associates(self.name)

    @property
    def replaced(self) -> bool:
        """Whether this name was already installed before the write.

        An operator who installs the same bundle twice is not doing anything
        wrong, and saying so is more useful than reporting an install that
        changed nothing as though it had.
        """
        return self.before.holds(self.name)

    @property
    def accepted(self) -> bool:
        return self.registered and self.associated

    @property
    def summary(self) -> str:
        said = f" Windows said: {self.refusal}" if self.refusal else ""
        if self.accepted:
            already = " It was already installed, so the file was left as it stood." if self.replaced else ""
            return f"{self.name} is installed and associated with {self.display_id}.{already}{said}"
        if self.registered:
            return (
                f"{self.name} is installed on this machine but {self.display_id} does not list it. "
                f"Nothing was rolled back, so the file is still there to associate.{said}"
            )
        if self.associated:
            return (
                f"{self.display_id} lists {self.name} but the machine holds no file under that name. "
                f"Colour-managed software reading it will get nothing.{said}"
            )
        return f"{self.name} is not installed on this machine and {self.display_id} does not list it.{said}"


@dataclass(frozen=True)
class ProfileActivation:
    """A display's default profile set, and what the display reports afterwards."""

    display_id: str
    name: str
    before: SystemProfileReading
    after: SystemProfileReading

    def __post_init__(self) -> None:
        _exact_name(self.display_id, "display_id")
        _exact_name(self.name, "name")
        _readings(self.before, self.after)
        _same_display(self.before, self.after, self.display_id)

    @property
    def accepted(self) -> bool:
        return self.after.is_default(self.name)

    @property
    def moved(self) -> bool:
        """Whether the default this display reports is not the one it reported before."""
        return self.before.default != self.after.default

    @property
    def summary(self) -> str:
        if self.accepted:
            if not self.moved:
                return f"{self.display_id} was already using {self.name}, and still is."
            return f"{self.display_id} now uses {self.name}. It was using {self.before.default or 'no profile'}."
        reported = self.after.default or "no profile"
        return f"{self.display_id} reports {reported} as its default, not {self.name}."


@dataclass(frozen=True)
class ProfileRemoval:
    """A profile detached from a display and unregistered from the machine.

    Detaching comes first. Unregistering an associated profile leaves the
    display naming a file that is gone, which Windows reports as a default the
    store does not hold, and which an operator meets as colour management that
    silently stopped working.
    """

    display_id: str
    name: str
    before: SystemProfileReading
    after: SystemProfileReading
    refusal: str | None = None

    def __post_init__(self) -> None:
        _exact_name(self.display_id, "display_id")
        _exact_name(self.name, "name")
        _readings(self.before, self.after)
        _same_display(self.before, self.after, self.display_id)
        if self.refusal is not None:
            _exact_name(self.refusal, "refusal")

    @property
    def detached(self) -> bool:
        return not self.after.associates(self.name)

    @property
    def unregistered(self) -> bool:
        return not self.after.holds(self.name)

    @property
    def accepted(self) -> bool:
        return self.detached and self.unregistered

    @property
    def summary(self) -> str:
        said = f" Windows said: {self.refusal}" if self.refusal else ""
        if self.accepted:
            fell_back = self.after.default or "no profile"
            return f"{self.name} is gone, and {self.display_id} now uses {fell_back}.{said}"
        if self.detached:
            return f"{self.display_id} no longer lists {self.name}, but the machine still holds the file.{said}"
        return f"{self.display_id} still lists {self.name}.{said}"


@dataclass(frozen=True)
class ProfileRestoration:
    """Every profile this product attached to a display, taken back off it.

    What the display falls back to is Windows' decision rather than this
    build's, so the result reports the default read afterwards instead of
    naming a profile it intended to restore.
    """

    display_id: str
    removed: tuple[str, ...]
    before: SystemProfileReading
    after: SystemProfileReading

    def __post_init__(self) -> None:
        _exact_name(self.display_id, "display_id")
        if type(self.removed) is not tuple:
            raise SystemProfileError("removed must be an exact tuple")
        for name in self.removed:
            _exact_name(name, "removed entry")
        _readings(self.before, self.after)
        _same_display(self.before, self.after, self.display_id)

    @property
    def remaining(self) -> tuple[str, ...]:
        """The names this restore asked to detach that the display still lists."""
        return tuple(name for name in self.removed if self.after.associates(name))

    @property
    def accepted(self) -> bool:
        return not self.remaining

    @property
    def summary(self) -> str:
        fell_back = self.after.default or "no profile"
        if not self.removed:
            return f"{self.display_id} lists no profile from this product. It uses {fell_back}."
        if self.accepted:
            listed = ", ".join(self.removed)
            return f"{self.display_id} no longer lists {listed}. It now uses {fell_back}."
        return f"{self.display_id} still lists {', '.join(self.remaining)}, and uses {fell_back}."


__all__ = [
    "ProfileActivation",
    "ProfileInstallation",
    "ProfileRemoval",
    "ProfileRestoration",
]
