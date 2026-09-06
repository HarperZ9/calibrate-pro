"""What the session adds around a measurement run.

The measurement core reads patches and the verification core grades a chart.
Neither owns a colorimeter, a window, or a session, so the properties that make
a run safe to offer an operator live in the service: the ports are opened in an
order the operator can live with and closed however the run ends, a run that
stopped is reported as a refusal rather than a defect, and the record a run
produced stays attached to the display it was taken on.

The ports here are arithmetic and the patch presenter is a stand-in placed in
``sys.modules``, so no USB device is opened and Qt is never imported. Nothing
here establishes that a colorimeter reads a display correctly. What it does
establish is that a run which failed leaves no device held open, and that a
figure reported as measured came from a reading rather than from a model.
"""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from calibrate_pro.application import service as service_module
from calibrate_pro.application.assets import AssetGenerator
from calibrate_pro.application.composition import _runner as build_runner
from calibrate_pro.application.composition import load_fake_display
from calibrate_pro.application.contracts import CharacterizationKind
from calibrate_pro.application.detection import DisplayDetector, ReadOnlyCapabilityProbe
from calibrate_pro.application.generation import _measurement_for
from calibrate_pro.application.instruments import InstrumentUnavailable
from calibrate_pro.application.journal import DiagnosticJournal
from calibrate_pro.application.measurement import MeasurementRefused
from calibrate_pro.application.outcomes import ActionFailure
from calibrate_pro.application.refusals import (
    MEASUREMENT_REFUSED,
    NO_DETECTION,
    NO_MEASUREMENT,
    NO_SEALED_PLAN,
)
from calibrate_pro.application.runner import ACTION_NOT_AVAILABLE
from calibrate_pro.application.selection import adopt
from calibrate_pro.application.service import FunctionalRecoveryService
from calibrate_pro.application.session import CalibrationMethod, SessionState
from calibrate_pro.panels.database import get_database
from calibrate_pro.sensorless.neuralux import SensorlessEngine
from calibrate_pro.verification.provenance import EvidenceKind
from tests.fake_acceptance_support import refused, succeeded
from tests.measurement_support import NARROW_PRIMARIES, SrgbDisplay, SyntheticDisplay

#: The bundled synthetic display, which is the only one this session enumerates.
DISPLAY_ID = "FAKE-ACCEPTANCE-DISPLAY"

#: The one target the reference chart describes.
PRESET = "calibration.preset.srgb_web"

#: A real preset the chart does not describe.
UNCOVERED_PRESET = "calibration.preset.dci_p3"

#: The module the service imports inside ``_open_patches``. Tests replace this
#: entry rather than an attribute on it, so PySide6 is never loaded here.
PRESENTER = "calibrate_pro.adapters.qt_patch_presenter"

#: Enough ramp steps to describe a tone response, few enough to run fast.
STEPS = 5

#: What a qualified display reads back, standing for the real gamma table check.
QUALIFIED = "The display's gamma table read within 0 codes of identity."


class PatchWindowUnavailable(RuntimeError):
    """The stand-in's refusal, raised where the real presenter raises its own."""


@dataclass
class Ports:
    """Both ports of one session, and what the session did with them.

    The order list is the point of the class. A port lifetime cannot be read off
    a return value, so every open and close appends here and the tests assert
    against the sequence.
    """

    display: SyntheticDisplay
    order: list[str] = field(default_factory=list)
    settles: list[float] = field(default_factory=list)
    #: Reason the instrument cannot be opened, or None if it opens.
    instrument_unavailable: str | None = None
    #: Reason the window cannot be placed, or None if it opens.
    window_unavailable: str | None = None
    #: Raised by the window instead of showing a patch, standing for a fault
    #: the measurement core does not classify.
    show_raises: Exception | None = None


class Instrument:
    """The open colorimeter, reading the synthetic display behind it."""

    def __init__(self, ports: Ports) -> None:
        self._ports = ports

    def identity(self) -> str:
        return self._ports.display.identity()

    def read(self) -> object:
        return self._ports.display.read()

    def close(self) -> None:
        self._ports.order.append("close instrument")


class Window:
    """The patch window, painting onto the synthetic display."""

    def __init__(self, ports: Ports) -> None:
        self._ports = ports

    def show(self, rgb: tuple[float, float, float]) -> None:
        if self._ports.show_raises is not None:
            raise self._ports.show_raises
        self._ports.display.show(rgb)

    def describe(self) -> str:
        return self._ports.display.describe()

    def settle(self, seconds: float) -> None:
        self._ports.settles.append(seconds)

    def close(self) -> None:
        self._ports.order.append("close window")


class Source:
    """Where the session gets its instrument, or the reason it gets none."""

    def __init__(self, ports: Ports) -> None:
        self._ports = ports

    def describe(self) -> str:
        return "a synthetic instrument"

    def present(self) -> bool:
        return True

    def open(self) -> Instrument:
        if self._ports.instrument_unavailable is not None:
            raise InstrumentUnavailable(self._ports.instrument_unavailable)
        self._ports.order.append("open instrument")
        return Instrument(self._ports)


def install_presenter(monkeypatch: pytest.MonkeyPatch, ports: Ports) -> None:
    """Answer the service's in-body import with a window made of arithmetic."""

    def open_patch_window(*, device_name: str, fraction: float) -> Window:
        if ports.window_unavailable is not None:
            raise PatchWindowUnavailable(ports.window_unavailable)
        ports.order.append(f"open window on {device_name} at {fraction}")
        return Window(ports)

    module = types.ModuleType(PRESENTER)
    module.PatchWindowUnavailable = PatchWindowUnavailable  # type: ignore[attr-defined]
    module.open_patch_window = open_patch_window  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, PRESENTER, module)


def build_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    display: SyntheticDisplay | None = None,
    correction: str | Exception = QUALIFIED,
    instrument_unavailable: str | None = None,
    window_unavailable: str | None = None,
    show_raises: Exception | None = None,
) -> tuple[FunctionalRecoveryService, Ports]:
    """Wire a session that can measure, over ports made of arithmetic.

    The correction check is replaced rather than run. The real one reads the
    video card gamma table for a display this process does not own, and its own
    behaviour is held in ``tests/test_correction_state.py``. What matters here
    is which side of it the ports are opened on.
    """
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    ports = Ports(
        display=display if display is not None else SrgbDisplay(primaries=NARROW_PRIMARIES, white_luminance=120.0),
        instrument_unavailable=instrument_unavailable,
        window_unavailable=window_unavailable,
        show_raises=show_raises,
    )
    install_presenter(monkeypatch, ports)

    def qualify(display_id: str) -> str:
        if isinstance(correction, Exception):
            raise correction
        ports.order.append(f"qualify {display_id}")
        return correction

    monkeypatch.setattr(service_module, "qualify_uncorrected", qualify)
    database = get_database()
    engine = SensorlessEngine(database)
    state = SessionState(measurement_route=True)
    detector = DisplayDetector(
        enumerator=lambda: (load_fake_display(),),
        capability_probe=ReadOnlyCapabilityProbe(
            sensor=lambda _display: True,
            absent_reason="no instrument is wired under test",
        ),
        database=database,
        enumerator_name="tests.test_measurement_service:fake-display",
    )
    service = FunctionalRecoveryService(
        state=state,
        runner=build_runner(state, DiagnosticJournal()),
        detector=detector,
        generator=AssetGenerator(engine, database),
        engine=engine,
        instruments=Source(ports),
    )
    return service, ports


def reach_measurement(service: FunctionalRecoveryService) -> None:
    """Drive the session to the point where a measurement is offered."""
    succeeded(service.detect())
    succeeded(service.select_display(DISPLAY_ID))
    succeeded(service.select_method(CalibrationMethod.MEASURED))


def reach_verification(service: FunctionalRecoveryService, preset: str = PRESET) -> None:
    """Drive the session to the point where a measured verification is offered.

    A verification reports on a calibration, so the gate offers it only over a
    sealed plan the operator confirmed. Reaching it is therefore the whole
    measured route, which is what makes this the end-to-end drive.
    """
    reach_measurement(service)
    succeeded(service.measure(steps=STEPS))
    succeeded(service.set_target(preset))
    succeeded(service.generate())
    succeeded(service.preview())
    succeeded(service.confirm_plan(accepted=True))


# The measurement run --------------------------------------------------------


def test_a_run_reads_the_display_and_reports_what_the_instrument_saw(tmp_path, monkeypatch) -> None:
    service, ports = build_session(tmp_path, monkeypatch)
    reach_measurement(service)

    summary = succeeded(service.measure(steps=STEPS))

    assert summary.display_id == DISPLAY_ID
    assert summary.instrument == ports.display.identity_string
    assert ports.display.reads > 0
    assert ports.display.reads == len(ports.display.shown), "every patch shown was read once"
    assert summary.characterization.white_luminance == pytest.approx(120.0, abs=0.5)


def test_the_instrument_opens_first_and_closes_last(tmp_path, monkeypatch) -> None:
    """The order an operator waits through, and the order a device is released in."""
    service, ports = build_session(tmp_path, monkeypatch)
    reach_measurement(service)

    succeeded(service.measure(steps=STEPS))

    assert ports.order == [
        f"qualify {DISPLAY_ID}",
        "open instrument",
        f"open window on {DISPLAY_ID} at 1.0",
        "close window",
        "close instrument",
    ]


def test_the_window_is_opened_on_the_display_being_measured(tmp_path, monkeypatch) -> None:
    """The instrument reports light and says nothing about where it came from."""
    service, ports = build_session(tmp_path, monkeypatch)
    reach_measurement(service)

    succeeded(service.measure(steps=STEPS, window_fraction=0.5))

    assert f"open window on {DISPLAY_ID} at 0.5" in ports.order


def test_every_patch_is_given_the_settle_the_service_asks_for(tmp_path, monkeypatch) -> None:
    """A patch read before the panel reached it is a reading of the patch before it."""
    service, ports = build_session(tmp_path, monkeypatch)
    reach_measurement(service)

    succeeded(service.measure(steps=STEPS))

    assert len(ports.settles) == len(ports.display.shown)
    assert set(ports.settles) == {service_module.SETTLE_SECONDS}


def test_a_colorimeter_that_is_not_there_refuses_before_anything_covers_the_screen(tmp_path, monkeypatch) -> None:
    service, ports = build_session(
        tmp_path,
        monkeypatch,
        instrument_unavailable="no supported colorimeter answered on USB",
    )
    reach_measurement(service)

    error = refused(service.measure(steps=STEPS))

    assert error.code == MEASUREMENT_REFUSED
    assert error.retryable is True
    assert "no supported colorimeter answered on USB" in error.summary
    assert ports.order == [f"qualify {DISPLAY_ID}"], "a window never opened is a screen never blacked out"


def test_a_window_that_cannot_be_placed_releases_the_instrument(tmp_path, monkeypatch) -> None:
    """A refusal that left a device session open would fail the next run too."""
    service, ports = build_session(
        tmp_path,
        monkeypatch,
        window_unavailable="no screen matched the display being measured",
    )
    reach_measurement(service)

    error = refused(service.measure(steps=STEPS))

    assert error.code == MEASUREMENT_REFUSED
    assert "no screen matched" in error.summary
    assert ports.order == [f"qualify {DISPLAY_ID}", "open instrument", "close instrument"]


def test_a_reading_that_failed_partway_through_closes_both_ports(tmp_path, monkeypatch) -> None:
    display = SrgbDisplay(primaries=NARROW_PRIMARIES, white_luminance=120.0, fails_at=3)
    service, ports = build_session(tmp_path, monkeypatch, display=display)
    reach_measurement(service)

    error = refused(service.measure(steps=STEPS))

    assert error.code == MEASUREMENT_REFUSED
    assert error.retryable is True
    assert ports.order[-2:] == ["close window", "close instrument"]


def test_a_fault_the_run_does_not_classify_still_closes_both_ports(tmp_path, monkeypatch) -> None:
    """The false-success control on the two finally blocks.

    Every other closing test drives a failure the measurement core raises as a
    refusal, which the service catches on its way out. This one raises something
    the service does not catch, so the ports are closed only if the finally
    blocks are doing it rather than the except clause.
    """
    service, ports = build_session(tmp_path, monkeypatch, show_raises=ZeroDivisionError("a fault nobody planned for"))
    reach_measurement(service)

    error = refused(service.measure(steps=STEPS))

    assert error.code == "UNEXPECTED_ACTION_FAILURE", "an unclassified fault is not reported as a stopped run"
    assert ports.order[-2:] == ["close window", "close instrument"]


def test_a_display_loading_a_correction_refuses_before_either_port_is_opened(tmp_path, monkeypatch) -> None:
    """A run against a corrected display would measure the correction with the panel."""
    service, ports = build_session(
        tmp_path,
        monkeypatch,
        correction=MeasurementRefused("the display is loading a gamma table 3705 codes from identity"),
    )
    reach_measurement(service)

    error = refused(service.measure(steps=STEPS))

    assert error.code == MEASUREMENT_REFUSED
    assert "3705 codes from identity" in error.summary
    assert ports.order == []


def test_the_sentence_that_qualified_the_run_travels_with_it(tmp_path, monkeypatch) -> None:
    """A measurement is reproducible only beside the state it was taken in."""
    sentence = f"{QUALIFIED} Nothing here reads the DWM LUT."
    service, _ports = build_session(tmp_path, monkeypatch, correction=sentence)
    reach_measurement(service)

    summary = succeeded(service.measure(steps=STEPS))

    assert summary.correction_state == sentence


def test_a_run_records_the_characterization_against_the_display_it_measured(tmp_path, monkeypatch) -> None:
    service, _ports = build_session(tmp_path, monkeypatch)
    reach_measurement(service)

    succeeded(service.measure(steps=STEPS))

    state = service._state
    assert state.characterization_kind is CharacterizationKind.MEASURED
    assert state.measured_display_id == DISPLAY_ID
    assert state.measurement_matches_selection is True


def test_a_run_breaks_the_seal_the_session_was_holding(tmp_path, monkeypatch) -> None:
    """A bundle generated before this run described the panel record, not the unit."""
    service, _ports = build_session(tmp_path, monkeypatch)
    reach_verification(service)
    assert service._state.sealed_plan_sha256 is not None

    service._measure(steps=STEPS, window_fraction=1.0, progress=None)

    assert service._sealed_plan is None
    assert service._state.sealed_plan_sha256 is None


def test_measuring_is_refused_while_a_bundle_is_sealed(tmp_path, monkeypatch) -> None:
    """The gate in front of the run the previous test drives directly.

    A run taken while a seal is held would drop a bundle the operator is
    standing in front of, so the offer is withdrawn rather than the seal being
    broken underneath them.
    """
    service, ports = build_session(tmp_path, monkeypatch)
    reach_verification(service)
    ports.order.clear()

    error = refused(service.measure(steps=STEPS))

    assert error.code == ACTION_NOT_AVAILABLE
    assert ports.order == []


def test_progress_is_reported_while_the_run_is_running(tmp_path, monkeypatch) -> None:
    """A run an operator cannot watch is a run they will interrupt."""
    service, _ports = build_session(tmp_path, monkeypatch)
    reach_measurement(service)
    seen: list[tuple[str, float]] = []

    succeeded(service.measure(steps=STEPS, progress=lambda label, fraction: seen.append((label, fraction))))

    assert seen, "the run reported nothing while it ran"
    assert all(label for label, _fraction in seen), "a progress step with no label says nothing"
    assert all(0.0 <= fraction <= 1.0 for _label, fraction in seen)


def test_measuring_with_no_display_selected_is_refused(tmp_path, monkeypatch) -> None:
    """The gate hides this, so the refusal underneath it is asserted directly."""
    service, ports = build_session(tmp_path, monkeypatch)

    with pytest.raises(ActionFailure) as refusal:
        service._measure(steps=STEPS, window_fraction=1.0, progress=None)

    assert refusal.value.code == NO_DETECTION
    assert ports.order == []


# The measured verification --------------------------------------------------


def test_a_measured_verification_grades_the_display_it_read(tmp_path, monkeypatch) -> None:
    service, ports = build_session(tmp_path, monkeypatch)
    reach_verification(service)
    ports.order.clear()

    result = succeeded(service.verify_measured())

    assert result.evidence is EvidenceKind.MEASURED
    assert result.average_delta_e.value is not None
    assert result.average_delta_e.evidence is EvidenceKind.MEASURED
    assert result.average_delta_e.source == ports.display.identity_string
    assert result.patch_count == 24
    assert service._state.verification_evidence is EvidenceKind.MEASURED


def test_a_verification_opens_and_closes_the_ports_the_same_way_a_run_does(tmp_path, monkeypatch) -> None:
    service, ports = build_session(tmp_path, monkeypatch)
    reach_verification(service)
    ports.order.clear()

    succeeded(service.verify_measured(window_fraction=0.25))

    assert ports.order == [
        "open instrument",
        f"open window on {DISPLAY_ID} at 0.25",
        "close window",
        "close instrument",
    ]


def test_a_verification_does_not_qualify_the_display_correction(tmp_path, monkeypatch) -> None:
    """The difference between grading a calibration and building one.

    A characterization run refuses a corrected display, because it would measure
    the correction together with the panel. A verification is pointed at
    whatever correction is loaded, since that correction is the thing being
    checked, so the same refusal here would make a calibrated display
    ungradeable.
    """
    service, ports = build_session(tmp_path, monkeypatch)
    reach_verification(service)
    monkeypatch.setattr(
        service_module,
        "qualify_uncorrected",
        lambda display_id: pytest.fail(f"a verification qualified {display_id}"),
    )
    ports.order.clear()

    result = succeeded(service.verify_measured())

    assert result.evidence is EvidenceKind.MEASURED
    assert "open instrument" in ports.order


def test_a_target_the_chart_does_not_describe_answers_without_opening_the_ports(tmp_path, monkeypatch) -> None:
    """The chart describes one target, and a run cannot report a figure for another."""
    service, ports = build_session(tmp_path, monkeypatch)
    reach_verification(service, preset=UNCOVERED_PRESET)
    ports.order.clear()

    result = succeeded(service.verify_measured())

    assert result.evidence is EvidenceKind.NOT_MEASURED
    assert result.average_delta_e.value is None
    assert result.limitation is not None
    assert ports.order == [], "the answer cost no dark calibration and blacked out no screen"


def test_a_verification_that_stopped_is_a_retryable_refusal(tmp_path, monkeypatch) -> None:
    service, ports = build_session(tmp_path, monkeypatch)
    reach_verification(service)
    ports.instrument_unavailable = "the colorimeter was unplugged between runs"
    ports.order.clear()

    error = refused(service.verify_measured())

    assert error.code == MEASUREMENT_REFUSED
    assert error.retryable is True
    assert error.category == "measurement"
    assert "unplugged between runs" in error.summary


def test_a_verification_with_no_target_is_refused(tmp_path, monkeypatch) -> None:
    service, ports = build_session(tmp_path, monkeypatch)

    with pytest.raises(ActionFailure) as refusal:
        service._verify_measured(window_fraction=1.0, progress=None)

    assert refusal.value.code == NO_SEALED_PLAN
    assert ports.order == []


def test_a_verification_with_no_display_is_refused(tmp_path, monkeypatch) -> None:
    service, ports = build_session(tmp_path, monkeypatch)
    service._state.selected_preset_id = PRESET

    with pytest.raises(ActionFailure) as refusal:
        service._verify_measured(window_fraction=1.0, progress=None)

    assert refusal.value.code == NO_DETECTION
    assert ports.order == []


# What a run belongs to ------------------------------------------------------


def test_a_bundle_cannot_be_built_from_a_run_of_another_display(tmp_path, monkeypatch) -> None:
    """The measured method refuses rather than falling back to the panel record."""
    service, _ports = build_session(tmp_path, monkeypatch)
    reach_measurement(service)
    succeeded(service.measure(steps=STEPS))
    state = service._state
    state.measured_display_id = "A-DISPLAY-THIS-SESSION-NEVER-ENUMERATED"

    with pytest.raises(ActionFailure) as refusal:
        _measurement_for(state, CalibrationMethod.MEASURED)

    assert refusal.value.code == NO_MEASUREMENT


def test_the_sensorless_method_builds_from_no_run_even_while_one_is_held(tmp_path, monkeypatch) -> None:
    """Choosing sensorless after measuring produces a sensorless bundle."""
    service, _ports = build_session(tmp_path, monkeypatch)
    reach_measurement(service)
    succeeded(service.measure(steps=STEPS))

    assert _measurement_for(service._state, CalibrationMethod.SENSORLESS) is None


def test_a_run_is_dropped_when_the_display_it_was_taken_on_leaves_the_selection(tmp_path, monkeypatch) -> None:
    """A record kept across a display change would label another monitor's light.

    Deselecting is how that happens on a session holding one display: detection
    runs again and the monitor the run was taken on is no longer there.
    """
    service, _ports = build_session(tmp_path, monkeypatch)
    reach_measurement(service)
    succeeded(service.measure(steps=STEPS))
    state = service._state

    adopt(state, None)

    assert state.measured_characterization is None
    assert state.measured_display_id is None
    assert state.characterization_kind is None


def test_reselecting_the_same_display_keeps_the_run_and_its_kind(tmp_path, monkeypatch) -> None:
    """Adopting a display resets the kind, so the run has to restore it."""
    service, _ports = build_session(tmp_path, monkeypatch)
    reach_measurement(service)
    succeeded(service.measure(steps=STEPS))
    state = service._state

    adopt(state, DISPLAY_ID)

    assert state.measured_display_id == DISPLAY_ID
    assert state.characterization_kind is CharacterizationKind.MEASURED
