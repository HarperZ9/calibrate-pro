"""A colour profile store that answers, with no machine underneath it.

The lane that installs a published bundle is judged entirely by what the store
says afterwards, so a fake that reported success from its own calls would prove
nothing about the code being tested. This one holds the state Windows holds: one
list of registered profiles for the machine, a list of associated profiles per
display, and one default per display. Every call moves that state, and every
result the tests read is built by the production code out of a second reading.

Two ways to make it misbehave are offered on purpose. ``refuse`` makes one
operation raise, which is what an unelevated account meets. ``ignore`` makes one
operation return without doing anything, which is what Windows does more often
than an operator expects, and which is the case that separates a result read
back from the store from a result assembled out of return values.

The rules it enforces are the ones the real store enforces. A default may only
name a profile the display already lists, and an association is accepted for a
profile the machine does not hold. Both of those shape the order the transaction
layer has to call things in, so both are modelled rather than assumed.
"""

from __future__ import annotations

from pathlib import Path

from calibrate_pro.application.composition import _engine_and_generator, _runner, load_fake_display
from calibrate_pro.application.detection import DisplayDetector, ReadOnlyCapabilityProbe
from calibrate_pro.application.journal import DiagnosticJournal
from calibrate_pro.application.service import FunctionalRecoveryService
from calibrate_pro.application.session import SessionState
from calibrate_pro.application.system_profiles import (
    SystemProfilePort,
    SystemProfileReading,
    SystemProfileUnavailable,
)
from calibrate_pro.panels.database import get_database
from tests.session_support import ENUMERATOR_NAME

#: The synthetic panel the session adopts, named here so a test can write the
#: store's contents before the session has run a detection pass.
DISPLAY_ID = "FAKE-ACCEPTANCE-DISPLAY"

#: A second display, for the tests that hold one display's profiles apart from
#: another's. Nothing enumerates it; only the store knows about it.
OTHER_DISPLAY_ID = "FAKE-ACCEPTANCE-DISPLAY-2"

#: What the fake port calls itself. A reading carries it, so a test reading the
#: printed output can tell the instrument line from the display line.
INSTRUMENT = "fake colour profile store"

#: A profile with a panel vendor's name on it. Every removal and restore is
#: tested against a display carrying this, because leaving it alone is the
#: bound the whole lane is written to keep.
VENDOR_PROFILE = "AW3423DW vendor.icm"


class FakeProfileStore:
    """The machine's profile store and the handle onto it, in one object.

    A handle in this lane is opened per operation and closed however the
    operation ends, so keeping the state on the handle would throw it away
    between the two readings a result is built from. Opens and closes are
    counted instead, which is what lets a test say the lane released the port
    on the path where the operation raised.
    """

    def __init__(
        self,
        *,
        installed: tuple[str, ...] = (),
        associated: tuple[str, ...] = (),
        default: str | None = None,
        display_id: str = DISPLAY_ID,
    ) -> None:
        self.installed: list[str] = list(installed)
        self.associated: dict[str, list[str]] = {display_id: list(associated)}
        self.default: dict[str, str | None] = {display_id: default}
        self.payloads: dict[str, bytes] = {}
        #: Every call made through the port, in order, so a test can say what
        #: the lane did and not only what the store ended up holding.
        self.calls: list[tuple[str, ...]] = []
        self.opens = 0
        self.closes = 0
        self._refused: dict[str, str] = {}
        self._ignored: set[str] = set()

    # -- arranging ----------------------------------------------------------

    def refuse(self, operation: str, message: str) -> None:
        """Make one operation raise, the way an unelevated account meets it."""
        self._refused[operation] = message

    def ignore(self, operation: str) -> None:
        """Make one operation return without doing anything.

        This is the false-success control. A result built from return values
        cannot tell this apart from an operation that took, and a result built
        from a second reading of the store can.
        """
        self._ignored.add(operation)

    def attach(self, name: str, *, display_id: str = DISPLAY_ID, default: bool = False) -> None:
        """Put a profile on a display without going through the lane."""
        self.associated.setdefault(display_id, []).append(name)
        if default:
            self.default[display_id] = name

    # -- the port -----------------------------------------------------------

    def identity(self) -> str:
        return INSTRUMENT

    def read(self, display_id: str) -> SystemProfileReading:
        self.calls.append(("read", display_id))
        self._check("read")
        return SystemProfileReading(
            display_id=display_id,
            instrument=INSTRUMENT,
            installed=tuple(self.installed),
            associated=tuple(self.associated.get(display_id, ())),
            default=self.default.get(display_id),
        )

    def install(self, name: str, payload: bytes) -> None:
        self.calls.append(("install", name))
        if self._skipped("install"):
            return
        if not self._holds(name):
            self.installed.append(name)
        self.payloads[name] = payload

    def associate(self, name: str, display_id: str) -> None:
        """Attach a profile to a display, holding or not holding the file.

        Windows accepts this for a profile the machine does not have, which is
        how a display ends up naming a default nothing can open. Refusing it
        here would hide the case the reading is written to report.
        """
        self.calls.append(("associate", name, display_id))
        if self._skipped("associate"):
            return
        attached = self.associated.setdefault(display_id, [])
        if not any(held.casefold() == name.casefold() for held in attached):
            attached.append(name)

    def make_default(self, name: str, display_id: str) -> None:
        """Name one of the display's own profiles as the one it hands out.

        A profile the display does not list is refused, as Windows refuses it.
        That is what makes the association step in an activation load-bearing
        rather than a courtesy.
        """
        self.calls.append(("make_default", name, display_id))
        if self._skipped("make_default"):
            return
        attached = self.associated.get(display_id, [])
        if not any(held.casefold() == name.casefold() for held in attached):
            raise RuntimeError(f"{display_id} does not list {name}")
        self.default[display_id] = name

    def disassociate(self, name: str, display_id: str) -> None:
        """Take a profile off a display, and let the display fall back.

        Windows chooses the fallback rather than being told it, so the choice
        is made here and read back by the result instead of being named by the
        code under test.
        """
        self.calls.append(("disassociate", name, display_id))
        if self._skipped("disassociate"):
            return
        attached = self.associated.get(display_id, [])
        self.associated[display_id] = [held for held in attached if held.casefold() != name.casefold()]
        current = self.default.get(display_id)
        if current is not None and current.casefold() == name.casefold():
            remaining = self.associated[display_id]
            self.default[display_id] = remaining[0] if remaining else None

    def uninstall(self, name: str) -> None:
        """Unregister a profile from the machine, leaving associations alone.

        The lane detaches before it unregisters, so an association surviving
        here is a defect this fake will show rather than tidy away.
        """
        self.calls.append(("uninstall", name))
        if self._skipped("uninstall"):
            return
        self.installed = [held for held in self.installed if held.casefold() != name.casefold()]
        self.payloads.pop(name, None)

    def close(self) -> None:
        self.closes += 1

    # -- internals ----------------------------------------------------------

    def _holds(self, name: str) -> bool:
        return any(held.casefold() == name.casefold() for held in self.installed)

    def _check(self, operation: str) -> None:
        message = self._refused.get(operation)
        if message is not None:
            raise RuntimeError(message)

    def _skipped(self, operation: str) -> bool:
        self._check(operation)
        return operation in self._ignored

    def named(self, operation: str) -> list[tuple[str, ...]]:
        """Every recorded call to one operation, for a test counting writes."""
        return [call for call in self.calls if call[0] == operation]


class FakeProfileSource:
    """Where the session gets the fake store, and how it answers without one."""

    def __init__(self, store: FakeProfileStore | None = None, *, reason: str = "no fake store was wired") -> None:
        self._store = store
        self._reason = reason

    def describe(self) -> str:
        return INSTRUMENT if self._store is not None else self._reason

    def present(self) -> bool:
        return self._store is not None

    def open(self) -> SystemProfilePort:
        if self._store is None:
            raise SystemProfileUnavailable(self._reason)
        self._store.opens += 1
        return self._store


def build_profile_service(
    root: Path,
    store: FakeProfileStore | None = None,
    *,
    profile_write: bool = True,
) -> FunctionalRecoveryService:
    """The session a terminal drives, with the profile store wired to a fake.

    Two things separate this from the read-only session the other command tests
    use. A source is passed, which is what sets the route the resolver reads,
    and the capability probe answers for the colour directory, which is the
    other half of the same gate. Passing ``profile_write=False`` leaves the
    route in place and the probe closed, which is the machine that has a store
    this build cannot write into.
    """
    display = load_fake_display()
    state = SessionState()
    journal = DiagnosticJournal(root / "diagnostics")
    database = get_database()
    engine, generator = _engine_and_generator(database)
    detector = DisplayDetector(
        enumerator=lambda: (display,),
        capability_probe=ReadOnlyCapabilityProbe(profile_write=lambda _display: profile_write),
        database=database,
        enumerator_name=ENUMERATOR_NAME,
    )
    return FunctionalRecoveryService(
        state=state,
        runner=_runner(state, journal),
        detector=detector,
        generator=generator,
        engine=engine,
        system_profiles=FakeProfileSource(store),
    )


def publish_bundle(root: Path, name: str = "bundle") -> Path:
    """Write one calibration bundle, and hand back the directory holding it.

    Published by the read-only session rather than the one under test. Nothing
    about generating a bundle needs a profile store, and a test that arranged
    its subject with its subject would prove less than it appears to.
    """
    from tests.session_support import build_cli_service, run

    directory = root / name
    code, _ = run("generate-profiles", build_cli_service(root / f"publish-{name}"), output=str(directory))
    assert code == 0, "the publishing run these tests depend on was refused"
    return directory


def install_bundle(root: Path, store: FakeProfileStore, *, activate: bool = False) -> tuple[Path, str]:
    """Publish a bundle, put it in the store through the command line, and name it.

    The name a bundle installs under is derived from its manifest digest, which
    changes with the bundle. Reading it off the line the install printed keeps
    the tests from computing a name the product might derive differently.
    """
    from tests.session_support import field, run

    bundle = publish_bundle(root)
    code, text = run(
        "install-profile",
        build_profile_service(root / "install", store),
        bundle=str(bundle),
        confirm=True,
        activate=activate,
    )
    assert code == 0, f"the install these tests depend on was refused:\n{text}"
    return bundle, field(text, "installs as")


__all__ = [
    "DISPLAY_ID",
    "INSTRUMENT",
    "OTHER_DISPLAY_ID",
    "VENDOR_PROFILE",
    "FakeProfileSource",
    "FakeProfileStore",
    "build_profile_service",
    "install_bundle",
    "publish_bundle",
]
