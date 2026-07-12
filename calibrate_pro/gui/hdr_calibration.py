"""
HDR Calibration GUI

Provides an unelevated user interface for staging HDR and SDR calibration
proposals. Display mutation is reserved for the confirmed actuation workflow.
"""

import sys

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class GainSlider(QWidget):
    """Custom slider for RGB gain adjustments."""

    valueChanged = Signal(float)

    def __init__(self, label: str, min_val: float = 0.5, max_val: float = 1.5, default: float = 1.0, parent=None):
        super().__init__(parent)
        self.min_val = min_val
        self.max_val = max_val
        self.steps = 200

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.label = QLabel(label)
        self.label.setFixedWidth(80)
        layout.addWidget(self.label)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, self.steps)
        self.slider.setValue(self._value_to_slider(default))
        self.slider.valueChanged.connect(self._on_slider_change)
        layout.addWidget(self.slider, 1)

        self.value_label = QLabel(f"{default:.3f}")
        self.value_label.setFixedWidth(50)
        layout.addWidget(self.value_label)

    def _value_to_slider(self, value: float) -> int:
        normalized = (value - self.min_val) / (self.max_val - self.min_val)
        return int(normalized * self.steps)

    def _slider_to_value(self, slider_val: int) -> float:
        normalized = slider_val / self.steps
        return self.min_val + normalized * (self.max_val - self.min_val)

    def _on_slider_change(self, slider_val: int):
        value = self._slider_to_value(slider_val)
        self.value_label.setText(f"{value:.3f}")
        self.valueChanged.emit(value)

    def value(self) -> float:
        return self._slider_to_value(self.slider.value())

    def setValue(self, value: float):
        self.slider.setValue(self._value_to_slider(value))


class OffsetSlider(QWidget):
    """Custom slider for RGB offset adjustments."""

    valueChanged = Signal(float)

    def __init__(self, label: str, min_val: float = -0.1, max_val: float = 0.1, default: float = 0.0, parent=None):
        super().__init__(parent)
        self.min_val = min_val
        self.max_val = max_val
        self.steps = 200

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.label = QLabel(label)
        self.label.setFixedWidth(80)
        layout.addWidget(self.label)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, self.steps)
        self.slider.setValue(self._value_to_slider(default))
        self.slider.valueChanged.connect(self._on_slider_change)
        layout.addWidget(self.slider, 1)

        self.value_label = QLabel(f"{default:+.4f}")
        self.value_label.setFixedWidth(60)
        layout.addWidget(self.value_label)

    def _value_to_slider(self, value: float) -> int:
        normalized = (value - self.min_val) / (self.max_val - self.min_val)
        return int(normalized * self.steps)

    def _slider_to_value(self, slider_val: int) -> float:
        normalized = slider_val / self.steps
        return self.min_val + normalized * (self.max_val - self.min_val)

    def _on_slider_change(self, slider_val: int):
        value = self._slider_to_value(slider_val)
        self.value_label.setText(f"{value:+.4f}")
        self.valueChanged.emit(value)

    def value(self) -> float:
        return self._slider_to_value(self.slider.value())

    def setValue(self, value: float):
        self.slider.setValue(self._value_to_slider(value))


class HDRCalibrationWindow(QMainWindow):
    """HDR controls that produce proposals but never actuate a display."""

    proposalStaged = Signal(dict)

    def __init__(self):
        super().__init__()
        self.current_monitor: dict[str, object] | None = None
        self.pending_proposal: dict[str, object] | None = None
        self.live_update = False

        self.setWindowTitle("HDR Calibration - Calibrate Pro")
        self.setMinimumSize(800, 700)

        self._setup_ui()
        self._refresh_monitors()
        self._update_status()

        # Timer for live updates
        self.update_timer = QTimer()
        self.update_timer.setSingleShot(True)
        self.update_timer.timeout.connect(self._stage_lut_proposal)

    def _setup_ui(self):
        """Set up the user interface."""
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # Monitor selection
        monitor_group = QGroupBox("Monitor Selection")
        monitor_layout = QHBoxLayout(monitor_group)

        self.monitor_combo = QComboBox()
        self.monitor_combo.currentIndexChanged.connect(self._on_monitor_changed)
        monitor_layout.addWidget(QLabel("Monitor:"))
        monitor_layout.addWidget(self.monitor_combo, 1)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh_monitors)
        monitor_layout.addWidget(refresh_btn)

        layout.addWidget(monitor_group)

        # Status panel
        status_group = QGroupBox("Status")
        status_layout = QFormLayout(status_group)

        self.status_admin = QLabel("Standard user")
        self.status_admin.setStyleSheet("color: green;")
        self.status_dwm_lut = QLabel("Confirmed workflow")
        self.status_hdr = QLabel("Unknown")
        self.status_lut = QLabel("None")

        status_layout.addRow("Process:", self.status_admin)
        status_layout.addRow("Actuation:", self.status_dwm_lut)
        status_layout.addRow("HDR Mode:", self.status_hdr)
        status_layout.addRow("Active LUT:", self.status_lut)

        layout.addWidget(status_group)

        # Tabs for SDR/HDR
        self.tabs = QTabWidget()

        # HDR Tab
        hdr_tab = QWidget()
        hdr_layout = QVBoxLayout(hdr_tab)

        # Peak luminance
        peak_group = QGroupBox("Display Capabilities")
        peak_layout = QFormLayout(peak_group)

        self.peak_luminance = QSpinBox()
        self.peak_luminance.setRange(100, 10000)
        self.peak_luminance.setValue(1000)
        self.peak_luminance.setSuffix(" nits")
        self.peak_luminance.valueChanged.connect(self._on_param_changed)
        peak_layout.addRow("Peak Luminance:", self.peak_luminance)

        self.sdr_white = QSpinBox()
        self.sdr_white.setRange(80, 500)
        self.sdr_white.setValue(203)
        self.sdr_white.setSuffix(" nits")
        self.sdr_white.valueChanged.connect(self._on_param_changed)
        peak_layout.addRow("SDR White Level:", self.sdr_white)

        hdr_layout.addWidget(peak_group)

        # RGB Gains
        gain_group = QGroupBox("RGB Gains (White Point Correction)")
        gain_layout = QVBoxLayout(gain_group)

        self.hdr_gain_r = GainSlider("Red Gain:", 0.5, 1.5, 1.0)
        self.hdr_gain_r.valueChanged.connect(self._on_param_changed)
        gain_layout.addWidget(self.hdr_gain_r)

        self.hdr_gain_g = GainSlider("Green Gain:", 0.5, 1.5, 1.0)
        self.hdr_gain_g.valueChanged.connect(self._on_param_changed)
        gain_layout.addWidget(self.hdr_gain_g)

        self.hdr_gain_b = GainSlider("Blue Gain:", 0.5, 1.5, 1.0)
        self.hdr_gain_b.valueChanged.connect(self._on_param_changed)
        gain_layout.addWidget(self.hdr_gain_b)

        hdr_layout.addWidget(gain_group)

        # RGB Offsets
        offset_group = QGroupBox("RGB Offsets (Black Level Correction)")
        offset_layout = QVBoxLayout(offset_group)

        self.hdr_offset_r = OffsetSlider("Red Offset:", -0.05, 0.05, 0.0)
        self.hdr_offset_r.valueChanged.connect(self._on_param_changed)
        offset_layout.addWidget(self.hdr_offset_r)

        self.hdr_offset_g = OffsetSlider("Green Offset:", -0.05, 0.05, 0.0)
        self.hdr_offset_g.valueChanged.connect(self._on_param_changed)
        offset_layout.addWidget(self.hdr_offset_g)

        self.hdr_offset_b = OffsetSlider("Blue Offset:", -0.05, 0.05, 0.0)
        self.hdr_offset_b.valueChanged.connect(self._on_param_changed)
        offset_layout.addWidget(self.hdr_offset_b)

        hdr_layout.addWidget(offset_group)

        # LUT Size
        lut_group = QGroupBox("LUT Settings")
        lut_layout = QFormLayout(lut_group)

        self.lut_size = QComboBox()
        self.lut_size.addItems(["17", "33", "65"])
        self.lut_size.setCurrentText("33")
        lut_layout.addRow("LUT Size:", self.lut_size)

        self.live_checkbox = QCheckBox("Live Proposal Preview")
        self.live_checkbox.toggled.connect(self._on_live_toggle)
        lut_layout.addRow(self.live_checkbox)

        hdr_layout.addWidget(lut_group)
        hdr_layout.addStretch()

        self.tabs.addTab(hdr_tab, "HDR Calibration")

        # SDR Tab
        sdr_tab = QWidget()
        sdr_layout = QVBoxLayout(sdr_tab)

        # Gamma
        gamma_group = QGroupBox("Gamma Settings")
        gamma_layout = QFormLayout(gamma_group)

        self.target_gamma = QDoubleSpinBox()
        self.target_gamma.setRange(1.8, 2.8)
        self.target_gamma.setValue(2.2)
        self.target_gamma.setSingleStep(0.1)
        self.target_gamma.valueChanged.connect(self._on_param_changed)
        gamma_layout.addRow("Target Gamma:", self.target_gamma)

        sdr_layout.addWidget(gamma_group)

        # SDR RGB Gains
        sdr_gain_group = QGroupBox("RGB Gains")
        sdr_gain_layout = QVBoxLayout(sdr_gain_group)

        self.sdr_gain_r = GainSlider("Red Gain:", 0.5, 1.5, 1.0)
        self.sdr_gain_r.valueChanged.connect(self._on_param_changed)
        sdr_gain_layout.addWidget(self.sdr_gain_r)

        self.sdr_gain_g = GainSlider("Green Gain:", 0.5, 1.5, 1.0)
        self.sdr_gain_g.valueChanged.connect(self._on_param_changed)
        sdr_gain_layout.addWidget(self.sdr_gain_g)

        self.sdr_gain_b = GainSlider("Blue Gain:", 0.5, 1.5, 1.0)
        self.sdr_gain_b.valueChanged.connect(self._on_param_changed)
        sdr_gain_layout.addWidget(self.sdr_gain_b)

        sdr_layout.addWidget(sdr_gain_group)

        # SDR RGB Offsets
        sdr_offset_group = QGroupBox("RGB Offsets")
        sdr_offset_layout = QVBoxLayout(sdr_offset_group)

        self.sdr_offset_r = OffsetSlider("Red Offset:", -0.1, 0.1, 0.0)
        self.sdr_offset_r.valueChanged.connect(self._on_param_changed)
        sdr_offset_layout.addWidget(self.sdr_offset_r)

        self.sdr_offset_g = OffsetSlider("Green Offset:", -0.1, 0.1, 0.0)
        self.sdr_offset_g.valueChanged.connect(self._on_param_changed)
        sdr_offset_layout.addWidget(self.sdr_offset_g)

        self.sdr_offset_b = OffsetSlider("Blue Offset:", -0.1, 0.1, 0.0)
        self.sdr_offset_b.valueChanged.connect(self._on_param_changed)
        sdr_offset_layout.addWidget(self.sdr_offset_b)

        sdr_layout.addWidget(sdr_offset_group)
        sdr_layout.addStretch()

        self.tabs.addTab(sdr_tab, "SDR Calibration")

        layout.addWidget(self.tabs)

        # Buttons
        button_layout = QHBoxLayout()

        self.apply_btn = QPushButton("Stage LUT Proposal")
        self.apply_btn.clicked.connect(self._stage_lut_proposal)
        button_layout.addWidget(self.apply_btn)

        self.reset_btn = QPushButton("Reset Controls")
        self.reset_btn.clicked.connect(self._reset_controls)
        button_layout.addWidget(self.reset_btn)

        self.remove_btn = QPushButton("Stage Remove Proposal")
        self.remove_btn.clicked.connect(self._stage_remove_proposal)
        button_layout.addWidget(self.remove_btn)

        button_layout.addStretch()

        self.start_dwm_btn = QPushButton("Actuation Help")
        self.start_dwm_btn.clicked.connect(self._show_actuation_help)
        button_layout.addWidget(self.start_dwm_btn)

        layout.addLayout(button_layout)

        # Log output
        self.log = QTextEdit()
        self.log.setMaximumHeight(100)
        self.log.setReadOnly(True)
        layout.addWidget(self.log)

    def _log(self, message: str):
        """Add message to log."""
        self.log.append(message)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def _refresh_monitors(self):
        """Refresh a read-only Qt screen inventory."""
        self.monitor_combo.clear()
        primary = QApplication.primaryScreen()
        screens = QApplication.screens()
        for index, screen in enumerate(screens):
            size = screen.size()
            data: dict[str, object] = {
                "display_id": f"qt-screen:{index}:{screen.name()}",
                "friendly_name": screen.name() or f"Display {index + 1}",
                "is_primary": screen is primary,
                "is_hdr": False,
                "size": (size.width(), size.height()),
            }
            primary_str = " (Primary)" if data["is_primary"] else ""
            self.monitor_combo.addItem(
                f"{data['friendly_name']}{primary_str} - {size.width()}x{size.height()}",
                data,
            )
        self._log(f"Found {len(screens)} monitor(s) using read-only Qt inventory")

    def _on_monitor_changed(self, index: int):
        """Handle monitor selection change."""
        if index >= 0:
            data = self.monitor_combo.itemData(index)
            if isinstance(data, dict):
                self.current_monitor = data
                self._log(f"Selected: {data['friendly_name']}")

    def _update_status(self):
        """Update status panel."""
        if self.current_monitor:
            if bool(self.current_monitor.get("is_hdr", False)):
                self.status_hdr.setText("Enabled ✓")
                self.status_hdr.setStyleSheet("color: green;")
            else:
                self.status_hdr.setText("Not reported by Qt")
                self.status_hdr.setStyleSheet("color: gray;")

        if self.pending_proposal:
            self.status_lut.setText(f"Pending {str(self.pending_proposal['kind']).upper()} proposal")
        else:
            self.status_lut.setText("None")

    def _on_param_changed(self):
        """Handle parameter change."""
        if self.live_update:
            self.update_timer.stop()
            self.update_timer.start(200)

    def _on_live_toggle(self, checked: bool):
        """Toggle debounced proposal refresh; never apply live state."""
        self.live_update = checked
        if checked:
            self._stage_lut_proposal()

    def _get_hdr_params(self) -> dict:
        """Get current HDR calibration parameters."""
        return {
            "rgb_gains": (self.hdr_gain_r.value(), self.hdr_gain_g.value(), self.hdr_gain_b.value()),
            "rgb_offsets": (self.hdr_offset_r.value(), self.hdr_offset_g.value(), self.hdr_offset_b.value()),
            "whitepoint": (1.0, 1.0, 1.0),
            "peak_luminance": float(self.peak_luminance.value()),
            "lut_size": int(self.lut_size.currentText()),
        }

    def _get_sdr_params(self) -> dict:
        """Get current SDR calibration parameters."""
        return {
            "rgb_gains": (self.sdr_gain_r.value(), self.sdr_gain_g.value(), self.sdr_gain_b.value()),
            "rgb_offsets": (self.sdr_offset_r.value(), self.sdr_offset_g.value(), self.sdr_offset_b.value()),
            "whitepoint": (1.0, 1.0, 1.0),
            "target_gamma": self.target_gamma.value(),
            "lut_size": int(self.lut_size.currentText()),
        }

    def _stage_lut_proposal(self):
        """Stage selected calibration parameters for later confirmation."""
        if not self.current_monitor:
            self._log("Error: No monitor selected")
            return

        kind = "hdr" if self.tabs.currentIndex() == 0 else "sdr"
        params = self._get_hdr_params() if kind == "hdr" else self._get_sdr_params()
        self.pending_proposal = {
            "action": "generate_lut",
            "display_id": self.current_monitor["display_id"],
            "kind": kind,
            "parameters": params,
        }
        self.proposalStaged.emit(dict(self.pending_proposal))
        self._log(f"Staged {kind.upper()} LUT proposal ({params['lut_size']}³); no display changes made")
        self._update_status()

    def _reset_controls(self):
        """Reset controls to identity values without changing the display."""
        self.hdr_gain_r.setValue(1.0)
        self.hdr_gain_g.setValue(1.0)
        self.hdr_gain_b.setValue(1.0)
        self.hdr_offset_r.setValue(0.0)
        self.hdr_offset_g.setValue(0.0)
        self.hdr_offset_b.setValue(0.0)

        self.sdr_gain_r.setValue(1.0)
        self.sdr_gain_g.setValue(1.0)
        self.sdr_gain_b.setValue(1.0)
        self.sdr_offset_r.setValue(0.0)
        self.sdr_offset_g.setValue(0.0)
        self.sdr_offset_b.setValue(0.0)

        self._log("Controls reset to identity; no display changes made")

    def _stage_remove_proposal(self):
        """Stage a LUT-removal request for the confirmed workflow."""
        if not self.current_monitor:
            self._log("Error: No monitor selected")
            return
        kind = "hdr" if self.tabs.currentIndex() == 0 else "sdr"
        self.pending_proposal = {
            "action": "clear_lut",
            "display_id": self.current_monitor["display_id"],
            "kind": kind,
        }
        self.proposalStaged.emit(dict(self.pending_proposal))
        self._log(f"Staged {kind.upper()} LUT-removal proposal; no display changes made")
        self._update_status()

    def _show_actuation_help(self):
        """Explain the explicit confirmed-actuation boundary."""
        QMessageBox.information(
            self,
            "Confirmed Actuation",
            "This window stages calibration proposals only. Review and confirm the proposal in the main "
            "Calibrate Pro workflow before any display change is attempted.",
        )


def main():
    """Launch the proposal UI as the current standard user."""
    app = QApplication(sys.argv)

    # Set dark palette
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorRole.Base, QColor(25, 25, 25))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.ToolTipBase, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorRole.ToolTipText, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorRole.BrightText, Qt.GlobalColor.red)
    palette.setColor(QPalette.ColorRole.Link, QColor(42, 130, 218))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
    palette.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.black)
    app.setPalette(palette)

    window = HDRCalibrationWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
