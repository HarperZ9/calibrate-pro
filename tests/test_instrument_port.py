"""The seam where an instrument reading enters the application.

`calibrate_pro.application.instruments` is the only place in this product where
a number a device produced can enter, and everything downstream reads a
MEASURED evidence kind off it. These tests hold that boundary. They cover what
the port admits, what it refuses, and what a session reports when no
colorimeter answered.

No test here opens a USB device. Enumeration runs against a stand-in module
placed in `sys.modules`, so the backend a shipped build would import is never
loaded, and `calibrate_pro.hardware` stays out of this process.

None of this establishes that a colorimeter measured a display correctly. What
it establishes is that a malformed driver answer never becomes a reading, and
that a session which found no instrument never reports itself qualified to
measure.
"""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass
from pathlib import Path

import pytest

from calibrate_pro.application.assets import AssetGenerator
from calibrate_pro.application.composition import _runner as build_runner
from calibrate_pro.application.composition import load_fake_display
from calibrate_pro.application.detection import (
    CapabilityUnavailable,
    DisplayDetector,
    ReadOnlyCapabilityProbe,
)
from calibrate_pro.application.instruments import (
    MAXIMUM_TRISTIMULUS,
    NO_DEVICE_REASON,
    NO_PORT_REASON,
    ConnectedInstrument,
    InstrumentError,
    InstrumentPort,
    InstrumentReading,
    InstrumentUnavailable,
    NoInstrumentSource,
    UsbInstrumentSource,
    available_instruments,
    usb_instrument_present,
)
from calibrate_pro.application.journal import DiagnosticJournal
from calibrate_pro.application.service import FunctionalRecoveryService
from calibrate_pro.application.session import SessionState
from calibrate_pro.panels.database import get_database
from calibrate_pro.panels.detection import DisplayInfo
from calibrate_pro.sensorless.neuralux import SensorlessEngine
from tests.fake_acceptance_support import succeeded

#: The module path the port imports inside its function bodies. Tests replace
#: this entry rather than the attribute, so the real backend is never imported.
BACKEND = "calibrate_pro.hardware.native_backend"

#: What the probe reports for a capability this file wired no check for.
ABSENT_REASON = "the test wired no check for this capability"


@dataclass
class FakeMeasurement:
    """What a driver hands back, shaped like `ColorMeasurement`."""

    X: float = 21.26
    Y: float = 100.0
    Z: float = 11.81
    integration_time: float = 1.5


#: Stands for "the test named no measurement". A plain None default would make
#: a driver that answers nothing indistinguishable from a driver left unset,
#: which is the exact case the false-success control has to be able to build.
UNSET = object()


class FakeDriver:
    """A connected device stand-in that counts what was asked of it."""

    def __init__(self, measurement: object = UNSET) -> None:
        self.measurement = FakeMeasurement() if measurement is UNSET else measurement
        self.disconnects = 0

    def measure_spot(self) -> object:
        return self.measurement

    def disconnect(self) -> bool:
        self.disconnects += 1
        return True


class StubSource:
    """A source that answers from what a test handed it."""

    def __init__(self, identity: str | None, *, raises: bool = False) -> None:
        self._identity = identity
        self._raises = raises

    def describe(self) -> str:
        if self._raises:
            raise RuntimeError("this source cannot answer")
        return self._identity or NO_DEVICE_REASON

    def present(self) -> bool:
        if self._raises:
            raise RuntimeError("this source cannot answer")
        return self._identity is not None

    def open(self) -> InstrumentPort:
        raise InstrumentUnavailable("this stub opens nothing")


@dataclass
class FakeDevice:
    """One enumerated USB descriptor, as the backend reports it."""

    model: str = "i1Display Pro"
    serial: str = "0123456"
    name: str = "colorimeter"


def install_backend(monkeypatch: pytest.MonkeyPatch, module: object) -> None:
    """Answer the port's lazy import from a stand-in rather than the driver.

    Both the package and the submodule are placed in `sys.modules`, so import
    resolution never reaches the filesystem and no USB code is loaded.
    """
    monkeypatch.setitem(sys.modules, "calibrate_pro.hardware", types.ModuleType("calibrate_pro.hardware"))
    monkeypatch.setitem(sys.modules, BACKEND, module)


def backend_returning(devices: object) -> types.ModuleType:
    module = types.ModuleType(BACKEND)
    module.detect_colorimeters = lambda: devices  # type: ignore[attr-defined]
    return module


def build_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    instruments: object,
    sensor: object = None,
) -> FunctionalRecoveryService:
    """Wire a read-only session over the bundled synthetic display."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    database = get_database()
    engine = SensorlessEngine(database)
    state = SessionState(measurement_route=True)
    journal = DiagnosticJournal()
    detector = DisplayDetector(
        enumerator=lambda: (load_fake_display(),),
        capability_probe=ReadOnlyCapabilityProbe(sensor=sensor, absent_reason=ABSENT_REASON),
        database=database,
        enumerator_name="tests.test_instrument_port:fake-display",
    )
    return FunctionalRecoveryService(
        state=state,
        runner=build_runner(state, journal),
        detector=detector,
        generator=AssetGenerator(engine, database),
        engine=engine,
        instruments=instruments,
    )


def test_a_reading_names_the_device_that_produced_it():
    """The identity travels with the number into the receipt."""
    port = ConnectedInstrument(FakeDriver(), "i1Display Pro (0123456)")

    reading = port.read()

    assert reading.instrument == "i1Display Pro (0123456)"
    assert reading.xyz == (21.26, 100.0, 11.81)
    assert reading.luminance == 100.0
    assert reading.integration_seconds == 1.5


def test_an_instrument_that_answers_nothing_refuses_rather_than_reading_black():
    """This is the false-success control for the measured half of the loop.

    A driver returning None has failed to measure. Turning that into a
    tristimulus of zeros would put a MEASURED evidence kind behind a black
    reading no device ever produced, and every downstream number computed from
    it would be wrong while looking measured.
    """
    port = ConnectedInstrument(FakeDriver(measurement=None), "i1Display Pro")

    with pytest.raises(InstrumentError):
        port.read()


def test_a_driver_with_no_spot_measurement_is_refused():
    port = ConnectedInstrument(object(), "unidentified colorimeter")

    with pytest.raises(InstrumentError):
        port.read()


def test_a_closed_session_takes_no_further_reading():
    driver = FakeDriver()
    port = ConnectedInstrument(driver, "i1Display Pro")
    port.close()

    with pytest.raises(InstrumentError):
        port.read()


def test_closing_twice_disconnects_once():
    """Close is idempotent, so a caller may close in a finally and again later."""
    driver = FakeDriver()
    port = ConnectedInstrument(driver, "i1Display Pro")

    port.close()
    port.close()

    assert driver.disconnects == 1


@pytest.mark.parametrize(
    "measured",
    [
        FakeMeasurement(X=float("nan")),
        FakeMeasurement(Y=float("inf")),
        FakeMeasurement(Z=-0.5),
        FakeMeasurement(Y=MAXIMUM_TRISTIMULUS + 1.0),
        FakeMeasurement(X="bright"),
        FakeMeasurement(Y=True),
    ],
)
def test_a_malformed_driver_answer_never_becomes_a_reading(measured):
    """Every rejection happens here, at the one boundary that can catch it."""
    port = ConnectedInstrument(FakeDriver(measurement=measured), "i1Display Pro")

    with pytest.raises(InstrumentError):
        port.read()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"instrument": "  ", "xyz": (1.0, 2.0, 3.0), "integration_seconds": 0.0},
        {"instrument": "i1", "xyz": (1.0, 2.0), "integration_seconds": 0.0},
        {"instrument": "i1", "xyz": [1.0, 2.0, 3.0], "integration_seconds": 0.0},
        {"instrument": "i1", "xyz": (1, 2.0, 3.0), "integration_seconds": 0.0},
        {"instrument": "i1", "xyz": (1.0, 2.0, 3.0), "integration_seconds": -1.0},
    ],
)
def test_a_reading_validates_its_own_fields(kwargs):
    with pytest.raises(InstrumentError):
        InstrumentReading(**kwargs)


def test_an_unreported_integration_time_reads_as_zero_rather_than_a_guess():
    """A driver that reports no timing gets no invented one."""
    port = ConnectedInstrument(FakeDriver(measurement=FakeMeasurement(integration_time="slow")), "i1")

    assert port.read().integration_seconds == 0.0


def test_the_default_source_reports_no_device_and_opens_nothing():
    source = NoInstrumentSource()

    assert source.present() is False
    assert source.describe() == NO_PORT_REASON
    with pytest.raises(InstrumentUnavailable):
        source.open()


def test_a_source_may_name_the_composition_that_wired_no_port():
    source = NoInstrumentSource("the fake-acceptance composition opens no instrument")

    assert "fake-acceptance" in source.describe()


@pytest.mark.parametrize("answer", [None, "not a list", 7])
def test_a_backend_that_answers_something_other_than_a_list_finds_no_instruments(monkeypatch, answer):
    install_backend(monkeypatch, backend_returning(answer))

    assert available_instruments() == ()


def test_a_backend_that_cannot_be_imported_finds_no_instruments(monkeypatch):
    """An unanswered question is not a device."""
    monkeypatch.setitem(sys.modules, BACKEND, None)

    assert available_instruments() == ()


def test_a_backend_that_raises_finds_no_instruments(monkeypatch):
    module = types.ModuleType(BACKEND)

    def explode() -> list[object]:
        raise OSError("the USB layer is unavailable")

    module.detect_colorimeters = explode  # type: ignore[attr-defined]
    install_backend(monkeypatch, module)

    assert available_instruments() == ()


def test_enumeration_names_a_device_by_model_and_serial(monkeypatch):
    install_backend(monkeypatch, backend_returning([FakeDevice(), FakeDevice(model="ColorMunki", serial="")]))

    assert available_instruments() == ("i1Display Pro (0123456)", "ColorMunki")


def test_the_sensor_capability_refuses_with_the_reason_that_nothing_answered(monkeypatch):
    install_backend(monkeypatch, backend_returning([]))
    display = load_fake_display()

    with pytest.raises(CapabilityUnavailable) as raised:
        usb_instrument_present(display)

    assert str(raised.value) == NO_DEVICE_REASON


def test_the_sensor_capability_passes_when_a_device_enumerated(monkeypatch):
    install_backend(monkeypatch, backend_returning([FakeDevice()]))

    assert usb_instrument_present(load_fake_display()) is True


def test_the_usb_source_refuses_to_open_what_never_enumerated(monkeypatch):
    install_backend(monkeypatch, backend_returning([]))
    source = UsbInstrumentSource()

    assert source.present() is False
    assert source.describe() == NO_DEVICE_REASON
    with pytest.raises(InstrumentUnavailable):
        source.open()


def test_a_device_that_refuses_dark_calibration_is_disconnected_and_refused(monkeypatch):
    """A device that will not zero itself cannot be trusted to read.

    The disconnect is asserted because leaving the session open would hold the
    device against the next attempt while the caller believes nothing opened.
    """
    opened = FakeDriver()
    opened.connect = lambda index=0: True  # type: ignore[attr-defined]
    opened.calibrate_device = lambda: False  # type: ignore[attr-defined]
    module = backend_returning([FakeDevice()])
    module.NativeBackend = lambda: opened  # type: ignore[attr-defined]
    install_backend(monkeypatch, module)

    with pytest.raises(InstrumentUnavailable):
        UsbInstrumentSource().open()

    assert opened.disconnects == 1


def test_a_device_that_will_not_open_a_session_is_refused(monkeypatch):
    refusing = FakeDriver()
    refusing.connect = lambda index=0: False  # type: ignore[attr-defined]
    module = backend_returning([FakeDevice()])
    module.NativeBackend = lambda: refusing  # type: ignore[attr-defined]
    install_backend(monkeypatch, module)

    with pytest.raises(InstrumentUnavailable):
        UsbInstrumentSource().open()


def test_an_opened_device_reads_through_the_port(monkeypatch):
    driver = FakeDriver()
    driver.connect = lambda index=0: True  # type: ignore[attr-defined]
    driver.calibrate_device = lambda: True  # type: ignore[attr-defined]
    module = backend_returning([FakeDevice()])
    module.NativeBackend = lambda: driver  # type: ignore[attr-defined]
    install_backend(monkeypatch, module)

    port = UsbInstrumentSource().open()

    assert port.identity() == "i1Display Pro (0123456)"
    assert port.read().luminance == 100.0


def test_a_session_that_found_no_instrument_is_not_qualified_to_measure(tmp_path, monkeypatch):
    """The session-level false-success control.

    ``measurement_route`` says a composition wired a port. Reporting a session
    qualified on that alone would offer a measured method on a machine with no
    colorimeter attached to it.
    """
    service = build_session(tmp_path, monkeypatch, instruments=NoInstrumentSource())

    succeeded(service.detect())

    assert service._state.instrument_identity is None
    assert service._state.measured_qualified is False


def test_detection_records_the_instrument_the_source_found(tmp_path, monkeypatch):
    def sensor(_display: DisplayInfo) -> bool:
        return True

    service = build_session(
        tmp_path,
        monkeypatch,
        instruments=StubSource("i1Display Pro (0123456)"),
        sensor=sensor,
    )

    succeeded(service.detect())

    assert service._state.instrument_identity == "i1Display Pro (0123456)"
    assert service._state.measured_qualified is True


def test_a_source_that_raises_leaves_the_session_naming_no_instrument(tmp_path, monkeypatch):
    service = build_session(tmp_path, monkeypatch, instruments=StubSource("i1", raises=True))

    succeeded(service.detect())

    assert service._state.instrument_identity is None
    assert service._state.measured_qualified is False
