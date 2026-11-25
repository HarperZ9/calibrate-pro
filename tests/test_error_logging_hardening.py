"""Planted-failure unit tests proving core exception handlers emit structured logs."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np
import pytest

from calibrate_pro.adapters.system_profile_source import WindowsSystemProfilePort
from calibrate_pro.application import instruments
from calibrate_pro.lut_system import LUTBackend, LUTManager
from calibrate_pro.profiles.mhc2 import extract_mhc2_from_profile
from calibrate_pro.profiles.vcgt import extract_vcgt_from_profile


def test_lut_manager_logs_planted_load_failure_and_returns_false(
    caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    """A planted LUT load exception must emit a structured warning and still return False."""
    manager = object.__new__(LUTManager)
    manager._backends = {}
    manager._active_backend = LUTBackend.DWM
    manager._displays = []
    manager._loaded_luts = {}

    class _ExplodingBackend:
        def load_lut(self, display_id: int, data: Any) -> bool:
            raise RuntimeError("planted DWM LUT transport failure")

    manager._backends[LUTBackend.DWM] = _ExplodingBackend()

    lut_array = np.zeros((2, 2, 2, 3), dtype=np.float32)
    with caplog.at_level(logging.WARNING, logger="calibrate_pro.lut_system"):
        ok = manager.load_lut(0, lut_array)

    assert ok is False
    assert any(
        "planted DWM LUT transport failure" in rec.getMessage() and rec.levelno == logging.WARNING
        for rec in caplog.records
    )

    caplog.clear()
    missing_file = tmp_path / "missing.cube"
    with caplog.at_level(logging.WARNING, logger="calibrate_pro.lut_system"):
        file_ok = manager.load_lut_file(0, missing_file)

    assert file_ok is False
    assert any(
        "Failed to load LUT file" in rec.getMessage() and rec.levelno == logging.WARNING for rec in caplog.records
    )


def test_vcgt_and_mhc2_extractors_log_planted_corrupt_profile_failures(
    caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    """Planted corrupt ICC payloads emit structured warnings while returning None."""
    corrupt_icc = tmp_path / "corrupt.icc"
    # Header claims 0xFFFF tags in a tiny buffer so struct.unpack fails cleanly.
    corrupt_icc.write_bytes(b"\x00" * 128 + b"\x00\x00\xff\xff" + b"\x00" * 4)

    with caplog.at_level(logging.WARNING, logger="calibrate_pro.profiles.vcgt"):
        vcgt = extract_vcgt_from_profile(corrupt_icc)

    assert vcgt is None
    assert any("Failed to extract VCGT from ICC profile" in rec.getMessage() for rec in caplog.records)

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="calibrate_pro.profiles.mhc2"):
        mhc2 = extract_mhc2_from_profile(corrupt_icc)

    assert mhc2 is None
    assert any("Failed to extract MHC2 tag" in rec.getMessage() for rec in caplog.records)


def test_available_instruments_logs_planted_usb_probe_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A planted USB colorimeter enumeration failure logs a warning and returns ()."""
    with (
        patch(
            "calibrate_pro.hardware.native_backend.detect_colorimeters",
            side_effect=RuntimeError("planted USB hub timeout"),
        ),
        caplog.at_level(logging.WARNING, logger="calibrate_pro.application.instruments"),
    ):
        found = instruments.available_instruments()

    assert found == ()
    assert any(
        "planted USB hub timeout" in rec.getMessage() and rec.levelno == logging.WARNING for rec in caplog.records
    )


def test_system_profile_port_logs_default_profile_fallback_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When default-profile lookup raises, the port logs a warning and preserves None fallback."""

    class _FakeInstaller:
        def _enumerate_system_profiles(self, display_id: str | None) -> list[str]:
            return ["sRGB.icc"]

        def get_default_profile_for_display(self, display_id: str) -> str:
            raise OSError("planted WCS no-default error")

    port = WindowsSystemProfilePort(_FakeInstaller())
    with caplog.at_level(logging.WARNING, logger="calibrate_pro.adapters.system_profile_source"):
        reading = port.read("DISPLAY1")

    assert reading.default is None
    assert reading.installed == ("sRGB.icc",)
    assert any(
        "planted WCS no-default error" in rec.getMessage() and rec.levelno == logging.WARNING for rec in caplog.records
    )
