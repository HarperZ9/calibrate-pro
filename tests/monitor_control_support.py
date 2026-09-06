"""A display that answers on DDC/CI, and misbehaves the ways real ones do.

The lane under test is judged entirely by what a panel reads at after a write,
so a fake that reported success from its own calls would prove nothing. This
one holds the state a panel holds: a value and a reported maximum per control,
moved only by writes it decides to act on.

Four ways to misbehave are offered, because all four are ordinary hardware
rather than defects. ``ignore`` takes a write and holds the old value, which is
what a panel does for a control it advertises and does not drive. ``clamp``
lands on a value of its own choosing. ``refuse_read`` and ``refuse_write`` raise
the way a driver does when DDC/CI is switched off in the panel's own menu or the
bus is busy. Both refusals take an ``after`` count, so a control can answer the
staging read and fail the read taken after the write, which is the case that
separates a result read back from the panel from one assembled out of calls.

The maxima differ per control on purpose. A panel reporting 100 for brightness
and 255 for a channel gain is the common case, and a fake with one uniform
range would let a range check pass while comparing against the wrong number.
"""

from __future__ import annotations

from pathlib import Path

from calibrate_pro.application.composition import _engine_and_generator, _runner, load_fake_display
from calibrate_pro.application.detection import DisplayDetector, ReadOnlyCapabilityProbe
from calibrate_pro.application.journal import DiagnosticJournal
from calibrate_pro.application.monitor_controls import (
    BLUE_BLACK_LEVEL,
    BLUE_GAIN,
    BRIGHTNESS,
    CONTRAST,
    GREEN_BLACK_LEVEL,
    GREEN_GAIN,
    RED_BLACK_LEVEL,
    RED_GAIN,
    RESTORE_FACTORY_DEFAULTS,
    MonitorControlPort,
    MonitorControlUnavailable,
)
from calibrate_pro.application.service import FunctionalRecoveryService
from calibrate_pro.application.session import SessionState
from calibrate_pro.panels.database import get_database
from tests.session_support import ENUMERATOR_NAME

#: The synthetic panel the session adopts, named here so a test can read the
#: display id without running a detection pass first.
DISPLAY_ID = "FAKE-ACCEPTANCE-DISPLAY"

#: What the fake port calls itself, so a test reading printed output can tell
#: the control channel's own name from the display's.
INSTRUMENT = "fake monitor control channel"

#: What each control reads at before a test moves it.
DEFAULT_VALUES: dict[int, int] = {
    BRIGHTNESS: 75,
    CONTRAST: 50,
    RED_GAIN: 128,
    GREEN_GAIN: 128,
    BLUE_GAIN: 128,
    RED_BLACK_LEVEL: 32,
    GREEN_BLACK_LEVEL: 32,
    BLUE_BLACK_LEVEL: 32,
}

#: What each control reports as its ceiling. A panel decides this, and the two
#: scales here are the two a real panel usually reports.
DEFAULT_MAXIMA: dict[int, int] = {
    BRIGHTNESS: 100,
    CONTRAST: 100,
    RED_GAIN: 255,
    GREEN_GAIN: 255,
    BLUE_GAIN: 255,
    RED_BLACK_LEVEL: 255,
    GREEN_BLACK_LEVEL: 255,
    BLUE_BLACK_LEVEL: 255,
}


class FakePanel:
    """One display's control channel, holding the state the panel holds.

    Opens and closes are counted rather than enforced, so a test can say the
    lane released the handle on the path where the transaction raised. Windows
    hands out a physical monitor handle and expects it back, and a lane that
    leaks one leaves the next run unable to open the display at all.
    """

    def __init__(
        self,
        *,
        values: dict[int, int] | None = None,
        maxima: dict[int, int] | None = None,
    ) -> None:
        self.values = dict(DEFAULT_VALUES)
        self.values.update(values or {})
        self.maxima = dict(DEFAULT_MAXIMA)
        self.maxima.update(maxima or {})
        #: Every call made through the port, in order, so a test can say what
        #: the lane did and not only what the panel ended up holding.
        self.calls: list[tuple[int, ...]] = []
        self.opens = 0
        self.closes = 0
        self._ignored: set[int] = set()
        self._clamped: dict[int, int] = {}
        self._read_refusals: dict[int, tuple[str, int]] = {}
        self._write_refusals: dict[int, tuple[str, int]] = {}
        self._factory: dict[int, int] | None = None
        self._seen_reads: dict[int, int] = {}
        self._seen_writes: dict[int, int] = {}

    # -- arranging ----------------------------------------------------------

    def ignore(self, code: int) -> None:
        """Take a write on this control and go on holding the old value.

        This is the false-success control. A panel advertising a control it
        does not drive answers the write exactly as one that drove it, and a
        result taken from the call cannot tell the two apart.
        """
        self._ignored.add(code)

    def clamp(self, code: int, ceiling: int) -> None:
        """Act on a write, but never past a limit the panel keeps to itself."""
        self._clamped[code] = ceiling

    def refuse_read(self, code: int, message: str, *, after: int = 0) -> None:
        """Raise on reads of this control, once it has answered `after` of them."""
        self._read_refusals[code] = (message, after)

    def refuse_write(self, code: int, message: str, *, after: int = 0) -> None:
        """Raise on writes to this control, once it has taken `after` of them."""
        self._write_refusals[code] = (message, after)

    def restores_to(self, **controls: int) -> None:
        """Make the factory restore move the named controls, as a panel would.

        Left unset, the restore code is accepted and nothing moves, which is
        what a panel that implements none of it does.
        """
        self._factory = {code: value for code, value in _by_name(controls).items()}

    # -- the port -----------------------------------------------------------

    def identity(self) -> str:
        return INSTRUMENT

    def read(self, code: int) -> tuple[int, int]:
        self.calls.append(("read", code))
        seen = self._seen_reads.get(code, 0)
        self._seen_reads[code] = seen + 1
        refusal = self._read_refusals.get(code)
        if refusal is not None and seen >= refusal[1]:
            raise RuntimeError(refusal[0])
        if code not in self.values:
            raise RuntimeError(f"0x{code:02X} is not supported by this display")
        return self.values[code], self.maxima[code]

    def write(self, code: int, value: int) -> None:
        self.calls.append(("write", code, value))
        seen = self._seen_writes.get(code, 0)
        self._seen_writes[code] = seen + 1
        refusal = self._write_refusals.get(code)
        if refusal is not None and seen >= refusal[1]:
            raise RuntimeError(refusal[0])
        if code == RESTORE_FACTORY_DEFAULTS:
            self.values.update(self._factory or {})
            return
        if code in self._ignored:
            return
        ceiling = self._clamped.get(code)
        self.values[code] = min(value, ceiling) if ceiling is not None else value

    def close(self) -> None:
        self.closes += 1

    # -- reading the record -------------------------------------------------

    def writes(self) -> list[tuple[int, ...]]:
        """Every write the lane attempted, in the order it attempted them."""
        return [call for call in self.calls if call[0] == "write"]

    def written_codes(self) -> list[int]:
        """The codes written, in order, for a test about ordering or rollback."""
        return [int(call[1]) for call in self.writes()]


def _by_name(controls: dict[str, int]) -> dict[int, int]:
    """Turn keyword control names into the codes the protocol uses."""
    codes = {
        "brightness": BRIGHTNESS,
        "contrast": CONTRAST,
        "red_gain": RED_GAIN,
        "green_gain": GREEN_GAIN,
        "blue_gain": BLUE_GAIN,
        "red_black_level": RED_BLACK_LEVEL,
        "green_black_level": GREEN_BLACK_LEVEL,
        "blue_black_level": BLUE_BLACK_LEVEL,
    }
    return {codes[name]: value for name, value in controls.items()}


class FakePanelSource:
    """Where the session gets the fake panel, and how it answers without one."""

    def __init__(self, panel: FakePanel | None = None, *, reason: str = "no fake panel was wired") -> None:
        self._panel = panel
        self._reason = reason

    def describe(self) -> str:
        return INSTRUMENT if self._panel is not None else self._reason

    def present(self) -> bool:
        return self._panel is not None

    def open(self, display_id: str) -> MonitorControlPort:
        del display_id
        if self._panel is None:
            raise MonitorControlUnavailable(self._reason)
        self._panel.opens += 1
        return self._panel


def build_monitor_service(
    root: Path,
    panel: FakePanel | None = None,
    *,
    ddc: bool = True,
) -> FunctionalRecoveryService:
    """The session a terminal drives, with the control channel wired to a fake.

    Two things separate this from the read-only session the other command tests
    use. A source is passed, which is what sets the route the resolver reads,
    and the capability probe answers for DDC/CI, which is the other half of the
    same gate. Passing ``ddc=False`` leaves the route in place and the probe
    closed, which is the machine whose panel has DDC/CI switched off in its own
    menu.
    """
    display = load_fake_display()
    state = SessionState()
    journal = DiagnosticJournal(root / "diagnostics")
    database = get_database()
    engine, generator = _engine_and_generator(database)
    detector = DisplayDetector(
        enumerator=lambda: (display,),
        capability_probe=ReadOnlyCapabilityProbe(ddc=lambda _display: ddc),
        database=database,
        enumerator_name=ENUMERATOR_NAME,
    )
    return FunctionalRecoveryService(
        state=state,
        runner=_runner(state, journal),
        detector=detector,
        generator=generator,
        engine=engine,
        monitor_controls=FakePanelSource(panel),
    )


__all__ = [
    "DEFAULT_MAXIMA",
    "DEFAULT_VALUES",
    "DISPLAY_ID",
    "INSTRUMENT",
    "FakePanel",
    "FakePanelSource",
    "build_monitor_service",
]
