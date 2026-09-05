"""Shared pytest fixtures for Calibrate Pro test suite.

The active-window fixture lives here because more than one file drives the
real window, and a second copy of the hardware stubbing would be a second
place for a test to reach a display from.
"""

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pytest

os.environ["QT_API"] = "pyside6"
os.environ["QT_QPA_PLATFORM"] = "offscreen"

# Ensure the calibrate package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibrate_pro.panels.database import PanelDatabase


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(scope="session")
def panel_database():
    """Return a PanelDatabase instance (session-scoped for speed)."""
    return PanelDatabase()


@pytest.fixture(scope="session")
def qd_oled_panel(panel_database):
    """Return the PG27UCDM QD-OLED panel characterization."""
    panel = panel_database.get_panel("PG27UCDM")
    assert panel is not None, "PG27UCDM must exist in the database"
    return panel


@pytest.fixture(scope="session")
def srgb_panel(panel_database):
    """Return the GENERIC_SRGB fallback panel characterization."""
    panel = panel_database.get_panel("GENERIC_SRGB")
    assert panel is not None, "GENERIC_SRGB must exist in the database"
    return panel


@pytest.fixture
def sample_xyz():
    """Common XYZ test values (D65 white, mid-gray, red-ish)."""
    return {
        "white_d65": np.array([0.95047, 1.0, 1.08883]),
        "mid_gray": np.array([0.2034, 0.2140, 0.2330]),
        "red_ish": np.array([0.4124, 0.2126, 0.0193]),
        "black": np.array([0.0, 0.0, 0.0]),
    }


@pytest.fixture
def sample_linear_rgb():
    """Common linear sRGB test values."""
    return {
        "white": np.array([1.0, 1.0, 1.0]),
        "black": np.array([0.0, 0.0, 0.0]),
        "red": np.array([1.0, 0.0, 0.0]),
        "green": np.array([0.0, 1.0, 0.0]),
        "blue": np.array([0.0, 0.0, 1.0]),
        "mid_gray": np.array([0.2140, 0.2140, 0.2140]),
        "orange": np.array([0.8, 0.4, 0.1]),
    }


def _unreachable(*args: object, **kwargs: object) -> None:
    raise AssertionError("the window reached a hardware boundary")


@contextmanager
def active_window(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[object]:
    """Build the active window around a session that touches no hardware."""
    from calibrate_pro.application.composition import build_fake_acceptance_service
    from calibrate_pro.gui import app as gui_app
    from calibrate_pro.gui.app import CalibrateProWindow
    from calibrate_pro.hardware.ddc_ci import DDCCIController
    from calibrate_pro.hardware.i1d3_native import I1D3Driver
    from calibrate_pro.utils.startup_manager import StartupManager

    # Background services are the one part of this window that legitimately
    # reaches the machine, and they are stubbed out. What the window does after
    # that is held to the session: the enumerators below are wired to fail, so a
    # page that reads a display for itself fails every test in this file.
    monkeypatch.setattr(gui_app, "qt_display_snapshots", _unreachable)
    monkeypatch.setattr(I1D3Driver, "find_devices", _unreachable)
    monkeypatch.setattr(DDCCIController, "enumerate_monitors", _unreachable)
    monkeypatch.setattr(StartupManager, "__init__", _unreachable)

    recorded: list[tuple[str, str]] = []
    monkeypatch.setattr(CalibrateProWindow, "_start_services", lambda self: None)
    monkeypatch.setattr(CalibrateProWindow, "_check_first_run", lambda self: None)
    monkeypatch.setattr(
        CalibrateProWindow,
        "show_toast",
        lambda self, message, level="info": recorded.append((message, level)),
    )
    root = tmp_path / "session"
    built = CalibrateProWindow(service=build_fake_acceptance_service(root))
    built.toasts = recorded
    built.session_root = root
    try:
        yield built
    finally:
        built.close()


@pytest.fixture
def window(qapp: object, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[object]:
    with active_window(monkeypatch, tmp_path) as built:
        yield built


@pytest.fixture
def tray_window(qapp: object, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[object]:
    """The same window, built on a machine that has a system tray.

    ``_build_tray`` returns before building anything when Qt reports no tray,
    and the offscreen platform these tests run on reports none. Without this
    the tray entries would not exist and a test about them would pass by
    finding nothing.
    """
    from PySide6.QtWidgets import QSystemTrayIcon

    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: True))
    with active_window(monkeypatch, tmp_path) as built:
        yield built
