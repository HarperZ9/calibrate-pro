"""Where a session is assembled, and the only place a composition is chosen.

Three compositions exist and none can turn into another. The calibration
composition wires a Windows display adapter and is what the product runs when
the operator means to change a display. The diagnostic composition wires the
same read-only detection and holds no adapter, and nothing a caller passes in
can hand one to a session built for reading. The fake-acceptance composition
wires a recording adapter and a bundled synthetic display, so its apply path
proves ordering and gating while touching nothing.

The mode is a value a caller reads, not a switch a caller sets. Each builder
constructs its own collaborators, which is what keeps the paths from sharing a
seam an adapter could be injected through.

Only the calibration builder imports an adapter, and it imports one inside the
function body. A module-level import would pull the writer into every process
that loads this module, including the diagnostic path whose whole claim is
that it never loaded one.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from enum import Enum
from importlib import resources
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from calibrate_pro.application.actions import ActionRegistry
from calibrate_pro.application.assets import AssetGenerator
from calibrate_pro.application.calibration import CalibrationApplyService
from calibrate_pro.application.detection import (
    DeniedCapabilityProbe,
    DisplayDetector,
    read_hdr_states,
    windows_read_only_probe,
)
from calibrate_pro.application.diagnostics import windows_folder_opener
from calibrate_pro.application.fake_acceptance import FakeAcceptanceService, RecordingFakeAdapter
from calibrate_pro.application.instruments import (
    NoInstrumentSource,
    UsbInstrumentSource,
    usb_instrument_present,
)
from calibrate_pro.application.journal import DiagnosticBundleManager, DiagnosticJournal
from calibrate_pro.application.outcomes import ActionBoundary
from calibrate_pro.application.runner import IssuedCorrelationId, SessionActionRunner
from calibrate_pro.application.service import FunctionalRecoveryService
from calibrate_pro.application.session import SessionState
from calibrate_pro.panels.database import PanelDatabase, get_database
from calibrate_pro.panels.detection import DisplayInfo
from calibrate_pro.sensorless.neuralux import SensorlessEngine

#: The bundled synthetic display the fake composition reads. It is the only
#: display source that composition has, so the proof cannot drift onto a real
#: machine by having an enumerator handed to it.
FAKE_DISPLAY_RESOURCE = "fake-acceptance-display.json"

#: Where the fake composition keeps its journal, relative to the output root it
#: was given. Deriving it rather than accepting it is what keeps every file the
#: composition writes inside the root the caller named.
FAKE_JOURNAL_DIRNAME = "diagnostics"

_FAKE_PROBE_REASON = "the fake-acceptance composition probes no hardware"
_FAKE_INSTRUMENT_REASON = "the fake-acceptance composition opens no instrument"


class CompositionMode(str, Enum):
    """Which session was built, reported rather than selected."""

    CALIBRATION = "calibration"
    PRODUCTION = "production"
    FAKE_ACCEPTANCE = "fake_acceptance"


def load_fake_display() -> DisplayInfo:
    """Read the bundled synthetic display, refusing any other source."""
    package_files = cast(Any, resources.files("calibrate_pro"))
    payload = package_files.joinpath("resources", FAKE_DISPLAY_RESOURCE).read_bytes()
    document = json.loads(payload.decode("utf-8"))
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise ValueError("fake display resource must declare schema_version 1")
    display = document.get("display")
    if not isinstance(display, dict):
        raise ValueError("fake display resource must carry one display object")
    return DisplayInfo(**display)


def prepare_fake_output_root(output_root: Path | str) -> Path:
    """Resolve an empty output root the fake composition may write inside.

    An existing directory must be empty. Writing into a directory that already
    holds files would let a proof read back an artifact it did not create, so
    the refusal comes before anything is built rather than after.
    """
    root = Path(output_root).expanduser().resolve()
    if root.exists():
        if not root.is_dir():
            raise ValueError("fake-acceptance output root must be a directory")
        if any(root.iterdir()):
            raise ValueError("fake-acceptance output root must be empty")
    else:
        root.mkdir(parents=True)
    return root


def contained_path(root: Path, *parts: str) -> Path:
    """Build a path under `root`, refusing anything that escapes it."""
    candidate = root.joinpath(*parts).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("fake-acceptance paths must stay inside the output root")
    return candidate


def _runner(state: SessionState, journal: DiagnosticJournal) -> SessionActionRunner:
    """Wire the one path an action takes from a service to the journal."""
    registry = ActionRegistry.load_default()
    correlation_ids = IssuedCorrelationId(_correlation_id)
    boundary = ActionBoundary(correlation_ids, journal, registry)
    return SessionActionRunner(state, registry, boundary, correlation_ids)


def _correlation_id() -> str:
    return uuid4().hex


def _bundles(journal: DiagnosticJournal) -> DiagnosticBundleManager:
    """Give the session the one manager that reads the journal it writes.

    Both are built from the same instance, so a bundle can only ever hold
    records this session put there. A platform with no way to open a folder
    gets no opener, and the folder action refuses instead of pretending.
    """
    return DiagnosticBundleManager(journal, folder_opener=windows_folder_opener())


def _engine_and_generator(database: PanelDatabase) -> tuple[SensorlessEngine, AssetGenerator]:
    """Share one engine between generation and prediction.

    The generator renders assets from the engine and the service predicts
    accuracy from it. Handing both the same instance is what makes a predicted
    number describe the bundle the operator holds.
    """
    engine = SensorlessEngine(database)
    return engine, AssetGenerator(engine, database)


def build_calibration_service() -> CalibrationApplyService:
    """Build the session that can change the display it detected.

    The adapter is imported here rather than at module scope. Importing it at
    module scope would load the platform writer into any process that reads
    this module, and the diagnostic session's guarantee is that no such module
    was ever loaded in its process.

    ``actuation_route`` is set by this builder alone, and it is one half of the
    apply qualification. The other half is what the probe found on the
    selected display. A session built here still refuses to apply to a
    display that reported no writable route.

    The monitor control source is wired here and nowhere else, and so is the
    DDC/CI capability check. That check costs a device session per display,
    which is why the read-only probe does not carry it by default: it opens
    the display and reads one control, because a panel can enumerate on the
    bus, advertise brightness in its capability string, and then refuse to
    answer for it.

    Wiring the source widens nothing on its own. It says a port exists, and
    the reading a session takes says whether a display answered. A control is
    offered only when both are true.

    The system profile source is wired on the same terms. It is what puts a
    published bundle into Windows colour management, which is the step that
    makes a finished calibration take effect for colour-managed software, and
    it stays out of the read-only session for the same reason the control
    source does.
    """
    from calibrate_pro.adapters.monitor_control_source import (
        WindowsMonitorControlSource,
        ddc_control_present,
    )
    from calibrate_pro.adapters.system_profile_source import WindowsSystemProfileSource
    from calibrate_pro.adapters.windows_display_state import (
        DefaultWindowsDisplayPorts,
        WindowsDisplayStateAdapter,
    )

    state = SessionState(actuation_route=True, measurement_route=True)
    journal = DiagnosticJournal()
    database = get_database()
    engine, generator = _engine_and_generator(database)
    detector = DisplayDetector(
        capability_probe=windows_read_only_probe(sensor=usb_instrument_present, ddc=ddc_control_present),
        hdr_reader=read_hdr_states,
        database=database,
    )
    return CalibrationApplyService(
        adapter=WindowsDisplayStateAdapter(DefaultWindowsDisplayPorts()),
        state=state,
        runner=_runner(state, journal),
        bundles=_bundles(journal),
        detector=detector,
        generator=generator,
        engine=engine,
        instruments=UsbInstrumentSource(),
        monitor_controls=WindowsMonitorControlSource(),
        system_profiles=WindowsSystemProfileSource(),
    )


def build_production_service() -> FunctionalRecoveryService:
    """Build the read-only session, which changes neither the signal nor the display.

    No monitor control source is wired, so the DDC/CI lane reports that this
    session was built without a port. That is the same refusal the calibration
    session gives for a display that did not answer, and it is stated by the
    composition rather than inferred from a failure.
    """
    state = SessionState(measurement_route=True)
    journal = DiagnosticJournal()
    database = get_database()
    engine, generator = _engine_and_generator(database)
    detector = DisplayDetector(
        capability_probe=windows_read_only_probe(sensor=usb_instrument_present),
        hdr_reader=read_hdr_states,
        database=database,
    )
    return FunctionalRecoveryService(
        state=state,
        runner=_runner(state, journal),
        bundles=_bundles(journal),
        detector=detector,
        generator=generator,
        engine=engine,
        instruments=UsbInstrumentSource(),
    )


def build_default_service() -> FunctionalRecoveryService:
    """Build the composition this machine can honestly offer.

    A calibration session is built where a display write route can exist at
    all. Elsewhere the read-only session is the correct answer rather than a
    leftover: there is no route for an adapter to take, so a control offered
    for applying would stand for something that could not happen.

    Which one was built is still not the whole apply qualification. A
    calibration session refuses a display whose probe found no writable
    route, so this choice widens nothing on its own.
    """
    if os.name != "nt":
        return build_production_service()
    return build_calibration_service()


def build_fake_acceptance_service(output_root: Path) -> FakeAcceptanceService:
    """Build the proof session, which writes only inside `output_root`."""
    root = prepare_fake_output_root(output_root)
    display = load_fake_display()
    state = SessionState(fake_acceptance=True)
    journal = DiagnosticJournal(contained_path(root, FAKE_JOURNAL_DIRNAME))
    database = get_database()
    engine, generator = _engine_and_generator(database)

    def enumerate_fake_displays() -> Sequence[DisplayInfo]:
        return (display,)

    detector = DisplayDetector(
        enumerator=enumerate_fake_displays,
        capability_probe=DeniedCapabilityProbe(_FAKE_PROBE_REASON),
        database=database,
        enumerator_name=f"composition.fake_acceptance:{FAKE_DISPLAY_RESOURCE}",
    )
    return FakeAcceptanceService(
        adapter=RecordingFakeAdapter(),
        state=state,
        runner=_runner(state, journal),
        bundles=_bundles(journal),
        detector=detector,
        generator=generator,
        engine=engine,
        instruments=NoInstrumentSource(_FAKE_INSTRUMENT_REASON),
    )


__all__ = [
    "FAKE_DISPLAY_RESOURCE",
    "FAKE_JOURNAL_DIRNAME",
    "CompositionMode",
    "build_calibration_service",
    "build_default_service",
    "build_fake_acceptance_service",
    "build_production_service",
    "contained_path",
    "load_fake_display",
    "prepare_fake_output_root",
]
