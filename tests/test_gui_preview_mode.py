"""Contracts for the hardware-free Calibrate Pro preview mode."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from calibrate_pro.verification.provenance import EvidenceKind

ROOT = Path(__file__).resolve().parents[1]


def _unexpected_hardware_or_mutation_call(*args: object, **kwargs: object) -> None:
    raise AssertionError("preview mode reached a hardware or mutation boundary")


def test_preview_provider_is_generic_deterministic_and_evidence_labelled() -> None:
    from calibrate_pro.gui.preview import PreviewSnapshotProvider

    first = PreviewSnapshotProvider().snapshots()
    second = PreviewSnapshotProvider().snapshots()

    assert first == second
    assert len(first) == 1

    display = first[0]
    assert display.snapshot.name == "Reference Display"
    assert display.resolution == "3840 × 2160 @ 120 Hz"
    assert display.panel_type == "QD-OLED"
    assert display.snapshot.manufacturer == ""
    assert display.snapshot.serial == ""
    assert display.snapshot.device_id == ""
    assert display.snapshot.device_name == ""
    assert all(metric.evidence in {EvidenceKind.SIMULATED, EvidenceKind.NOT_MEASURED} for metric in display.metrics)
    assert all(
        metric.source == "bundled public preview fixture"
        for metric in display.metrics
        if metric.evidence is EvidenceKind.SIMULATED
    )


def test_preview_window_bypasses_hardware_and_disables_mutation_actions(
    qapp: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import QLabel, QPushButton

    from calibrate_pro.gui import app as gui_app
    from calibrate_pro.gui.app import CalibrateProWindow
    from calibrate_pro.hardware.ddc_ci import DDCCIController
    from calibrate_pro.hardware.i1d3_native import I1D3Driver
    from calibrate_pro.services.calibration_guard import CalibrationGuard
    from calibrate_pro.utils.startup_manager import StartupManager

    monkeypatch.setattr(gui_app, "qt_display_snapshots", _unexpected_hardware_or_mutation_call)
    monkeypatch.setattr(I1D3Driver, "find_devices", _unexpected_hardware_or_mutation_call)
    monkeypatch.setattr(DDCCIController, "enumerate_monitors", _unexpected_hardware_or_mutation_call)
    monkeypatch.setattr(StartupManager, "__init__", _unexpected_hardware_or_mutation_call)
    monkeypatch.setattr(CalibrationGuard, "start", _unexpected_hardware_or_mutation_call)

    for method_name in (
        "_build_tray",
        "_start_services",
        "_update_tray_state",
        "_check_first_run",
        "_prime_session",
        "_detect_displays",
        "_export_format",
        "_show_hdr_status",
    ):
        monkeypatch.setattr(
            CalibrateProWindow,
            method_name,
            _unexpected_hardware_or_mutation_call,
        )

    window = CalibrateProWindow(preview_mode=True)
    window.resize(1440, 900)
    window.show()
    try:
        for _ in range(20):
            qapp.processEvents()
            if window.dashboard.preview_populated:
                break

        assert window.dashboard.preview_populated
        banner_text = window.preview_banner.text()
        assert "Simulated preview" in banner_text
        assert "no hardware access" in banner_text.lower()
        assert "no display changes" in banner_text.lower()

        assert window.dashboard.preview_metrics
        assert all(
            metric.evidence in {EvidenceKind.SIMULATED, EvidenceKind.NOT_MEASURED}
            for metric in window.dashboard.preview_metrics
        )

        buttons = {button.text(): button for button in window.findChildren(QPushButton)}
        for label in ("Calibrate All", "Calibrate"):
            assert label in buttons
            assert not buttons[label].isEnabled()
        # Opening the add-profile dialog is an interface action and stays open
        # here, because the restriction narrows what reaches past the interface
        # rather than what the operator is allowed to look at. The dialog it
        # opens does nothing on its own: the preview session runs no detection
        # pass, so it has no display to describe, and reading a chosen file is
        # classified read_only and so is closed by the same restriction.
        assert buttons["Add Display Profile"].isEnabled()
        assert "QPushButton:disabled" in buttons["Add Display Profile"].styleSheet()
        assert buttons["Calibrate All"].property("primary") is False
        assert buttons["Calibrate"].property("primary") is False

        for object_name in (
            "displayNameLabel",
            "displayDetailLabel",
            "displayStatusLabel",
            "previewEvidenceLabel",
        ):
            label = window.findChild(QLabel, object_name)
            assert label is not None
            assert "background: transparent" in label.styleSheet()
        status_label = window.findChild(QLabel, "displayStatusLabel")
        assert status_label.text() == "Calibration: Not measured"

        gamut_bar = window.findChild(gui_app.GamutBar, "displayGamutBar")
        assert gamut_bar is not None
        assert "background: transparent" in gamut_bar.styleSheet()

        actions = {action.text(): action for action in window.findChildren(QAction)}
        for label in (
            "&Calibrate All",
            ".cube (Resolve / dwm_lut)",
            "&Restore Defaults",
            "&Install ICC Profile...",
            "&Test Patterns",
            "&HDR Status",
        ):
            assert label in actions
            assert not actions[label].isEnabled()

        # An action the session hides is removed rather than shown greyed out.
        # A permanently disabled "Calibrate All" would still advertise a
        # workflow this build does not have.
        assert not actions["&Calibrate All"].isVisible()
        assert buttons["Calibrate All"].isHidden()

        # Every disabled control explains itself in the session's own words.
        # Qt answers an empty tooltip with the entry's own text, so a reason is
        # present only when the tooltip says something the label does not.
        for label in ("&Restore Defaults", "&Install ICC Profile...", "&Test Patterns", "&HDR Status"):
            assert actions[label].toolTip() not in ("", label)

        assert window.stack.count() == 6
        assert window.sidebar.isEnabled()
        for label in ("&Dashboard", "&Calibrate", "&Verify", "&Profiles", "DD&C Control", "&Settings"):
            assert actions[label].isEnabled()
    finally:
        window.close()
        qapp.processEvents()


def test_preview_renderer_writes_a_nonempty_1440_by_900_png(tmp_path: Path) -> None:
    output = tmp_path / "calibrate-pro-native-preview.png"
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    result = subprocess.run(
        [sys.executable, "scripts/render_gui_preview.py", "--out", str(output)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert output.exists()
    assert output.stat().st_size > 0
    assert str(output) in result.stdout
    assert str(output.stat().st_size) in result.stdout
    assert "font=" in result.stdout
    assert "font=none" not in result.stdout.lower()
    assert "layout=settled" in result.stdout

    from PySide6.QtGui import QImage

    image = QImage(str(output))
    assert not image.isNull()
    assert (image.width(), image.height()) == (1440, 900)
