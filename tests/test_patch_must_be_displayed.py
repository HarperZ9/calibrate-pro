"""A reading belongs to the patch that was on screen when it was taken.

Both measurement paths used to skip the display step. The hardware engine read
the colorimeter with a comment saying a pattern window "would" be needed and
"for now, assume patch is displayed", then filed the reading under the RGB it
had asked for. The camera engine held a ``PatternDisplay`` it never called and
filed the frame under ``pattern_rgb``. The grayscale and primary passes would
have read the same unchanged screen for every patch in the sweep, and every one
of those readings would have carried a different RGB label.

These tests hold both paths to the same rule: show the patch, or return
nothing. They also cover the ``apply_to_hardware`` path in the camera engine,
which reported a completed calibration having written nothing to the display.
The Spyder driver had the same hole, and is covered in
``test_spyder_patch_display.py``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
import pytest

from calibrate_pro.hardware.hardware_calibration import HardwareCalibrationEngine
from calibrate_pro.sensorless.camera_calibration import (
    CalibrationRisk,
    CameraCalibrationEngine,
    CameraInterface,
    SimulatedCamera,
    UserConsent,
)

#: A patch the sweeps ask for, and one they ask for later in the same pass.
FIRST_PATCH = (255, 255, 255)
SECOND_PATCH = (128, 128, 128)


@dataclass
class _Reading:
    """The shape returned by ``ColorimeterBase.measure``."""

    X: float = 95.05
    Y: float = 100.0
    Z: float = 108.9
    x: float = 0.3127
    y: float = 0.3290
    cct: float = 6504.0


class _StubColorimeter:
    """Answers with a fixed reading and counts how often it was asked."""

    def __init__(self):
        self.measure_calls = 0

    def measure(self) -> _Reading:
        self.measure_calls += 1
        return _Reading()


class _RecordingDisplay:
    """Records what it was told to show, in order, alongside the reads."""

    def __init__(self, log: list[tuple[str, object]]):
        self._log = log

    def show(self, r: int, g: int, b: int) -> None:
        self._log.append(("show", (r, g, b)))

    def show_pattern(self, rgb: tuple[int, int, int], fullscreen: bool = True) -> None:
        self._log.append(("show", rgb))


class _StillCamera(CameraInterface):
    """A camera that is not the simulator, so it needs a real display."""

    def __init__(self, log: list[tuple[str, object]] | None = None):
        self._log = log if log is not None else []

    def capture(self, delay: float = 0.5) -> np.ndarray:
        self._log.append(("capture", None))
        return np.full((400, 500, 3), 96, dtype=np.uint8)


# ---------------------------------------------------------------------------
# Hardware engine
# ---------------------------------------------------------------------------


@pytest.fixture
def hardware_engine():
    """An engine holding a colorimeter, with the settle wait taken out."""
    engine = HardwareCalibrationEngine()
    engine._colorimeter = _StubColorimeter()
    engine.patch_settle_seconds = 0.0
    return engine


def test_hardware_patch_returns_nothing_without_a_display(hardware_engine):
    """No display means no reading, and the colorimeter is never asked."""
    assert hardware_engine._measure_patch(*FIRST_PATCH) is None
    assert hardware_engine._colorimeter.measure_calls == 0


def test_hardware_patch_says_why_it_returned_nothing(hardware_engine):
    """The progress channel carries the reason and the patch that was skipped."""
    messages: list[str] = []
    hardware_engine.set_progress_callback(lambda msg, pct, phase: messages.append(msg))

    hardware_engine._measure_patch(*FIRST_PATCH)

    assert any("patch display" in m for m in messages)
    assert any("255" in m for m in messages)


def test_hardware_patch_is_shown_before_it_is_read(hardware_engine):
    """The display gets the requested RGB, then the colorimeter is read."""
    log: list[tuple[str, object]] = []
    display = _RecordingDisplay(log)
    hardware_engine.set_patch_display(display.show)
    original_measure = hardware_engine._colorimeter.measure

    def measure_and_log():
        log.append(("measure", None))
        return original_measure()

    hardware_engine._colorimeter.measure = measure_and_log

    hardware_engine._measure_patch(*SECOND_PATCH)

    assert log == [("show", SECOND_PATCH), ("measure", None)]


def test_hardware_reading_keeps_the_stimulus_it_was_taken_at(hardware_engine):
    """The r, g, b on a record are the patch that was shown, not Lab.

    The Lab b* component used to be stored in the same field as the blue
    stimulus, so the blue value on every record in the grayscale and primary
    sweeps was overwritten by a Lab number the moment Lab was computed.
    """
    hardware_engine.set_patch_display(_RecordingDisplay([]).show)

    result = hardware_engine._measure_patch(*SECOND_PATCH)

    assert (result.r, result.g, result.b) == SECOND_PATCH
    assert (result.lab_l, result.lab_a, result.lab_b) != (0.0, 0.0, 0.0)


def test_hardware_sweep_shows_each_patch_it_labels(hardware_engine):
    """Two patches in a row produce two display calls, not one screen read twice."""
    log: list[tuple[str, object]] = []
    hardware_engine.set_patch_display(_RecordingDisplay(log).show)

    hardware_engine._measure_patch(*FIRST_PATCH)
    hardware_engine._measure_patch(*SECOND_PATCH)

    assert [entry[1] for entry in log] == [FIRST_PATCH, SECOND_PATCH]


def test_hardware_initialize_accepts_the_patch_display(hardware_engine):
    """``initialize`` wires the callback through, so callers need no private access."""

    class _NoMonitors:
        available = False

        def enumerate_monitors(self):
            return []

    display = _RecordingDisplay([])
    hardware_engine.initialize(
        colorimeter=hardware_engine._colorimeter,
        ddc_controller=_NoMonitors(),
        patch_display=display.show,
    )

    assert hardware_engine._patch_display == display.show


def test_sensorless_mode_is_unchanged(hardware_engine):
    """Without a colorimeter the answer is still None, not an error."""
    hardware_engine._colorimeter = None
    hardware_engine.set_patch_display(_RecordingDisplay([]).show)

    assert hardware_engine._measure_patch(*FIRST_PATCH) is None


# ---------------------------------------------------------------------------
# Camera engine
# ---------------------------------------------------------------------------


def test_camera_refuses_to_capture_with_nothing_showing_the_patch():
    """A real camera and no display is a frame of the desktop, so it raises."""
    engine = CameraCalibrationEngine(camera=_StillCamera(), display=None)

    with pytest.raises(RuntimeError) as raised:
        engine.measure_single_color(FIRST_PATCH)

    assert "pattern display" in str(raised.value)


def test_camera_shows_the_pattern_before_it_captures():
    """The display is driven with the requested RGB ahead of the capture."""
    log: list[tuple[str, object]] = []
    engine = CameraCalibrationEngine(camera=_StillCamera(log), display=_RecordingDisplay(log))

    capture = engine.measure_single_color(SECOND_PATCH)

    assert log == [("show", SECOND_PATCH), ("capture", None)]
    assert capture.pattern_rgb == SECOND_PATCH


def test_simulated_camera_still_measures_without_a_display():
    """The simulator is told what to show, so it needs no display of its own."""
    engine = CameraCalibrationEngine(camera=SimulatedCamera(), display=None)

    capture = engine.measure_single_color(FIRST_PATCH)

    assert capture.pattern_rgb == FIRST_PATCH
    assert max(capture.captured_rgb) > 0


def _approved_consent() -> UserConsent:
    return UserConsent(
        timestamp=time.time(),
        risk_level=CalibrationRisk.HIGH,
        display_name="Studio 1",
        operation="camera calibration",
        user_acknowledged_risks=True,
        hardware_modification_approved=True,
    )


def test_apply_to_hardware_reports_no_calibration_it_did_not_perform():
    """Consent in hand, nothing writes to the display, so success stays false."""
    engine = CameraCalibrationEngine(camera=SimulatedCamera())

    result = engine.run_calibration(apply_to_hardware=True, consent=_approved_consent())

    assert result.success is False
    assert "not implemented" in result.message


def test_apply_to_hardware_still_requires_consent():
    """The consent guard keeps its own message rather than the new one."""
    engine = CameraCalibrationEngine(camera=SimulatedCamera())

    result = engine.run_calibration(apply_to_hardware=True, consent=None)

    assert result.success is False
    assert "consent" in result.message


def test_measure_only_run_does_not_call_the_second_ramp_a_verification():
    """Nothing was applied, so the repeat ramp is named for what it is."""
    engine = CameraCalibrationEngine(camera=SimulatedCamera())
    stages: list[str] = []
    engine.set_progress_callback(lambda msg, pct: stages.append(msg))

    result = engine.run_calibration(apply_to_hardware=False)

    assert result.success is True
    assert "not applied" in result.message
    assert not any("Verification" in stage for stage in stages)
