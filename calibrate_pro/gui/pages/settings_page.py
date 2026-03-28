"""
Settings Page - Application configuration interface.
"""

from pathlib import Path

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from calibrate_pro.gui.theme import COLORS


class SettingsPage(QWidget):
    """Application settings interface."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        # Header
        header = QLabel("Settings")
        header.setStyleSheet("font-size: 20px; font-weight: 600;")
        layout.addWidget(header)

        # Settings in tabs
        tabs = QTabWidget()

        # General tab
        general_widget = self._create_general_tab()
        tabs.addTab(general_widget, "General")

        # Calibration tab
        cal_widget = self._create_calibration_tab()
        tabs.addTab(cal_widget, "Calibration")

        # Hardware tab
        hw_widget = self._create_hardware_tab()
        tabs.addTab(hw_widget, "Hardware")

        # Paths tab
        paths_widget = self._create_paths_tab()
        tabs.addTab(paths_widget, "File Paths")

        layout.addWidget(tabs)

        # Save button
        save_layout = QHBoxLayout()
        save_layout.addStretch()

        reset_btn = QPushButton("Reset to Defaults")
        save_layout.addWidget(reset_btn)

        save_btn = QPushButton("Save Settings")
        save_btn.setProperty("primary", True)
        save_layout.addWidget(save_btn)

        layout.addLayout(save_layout)

    def _create_general_tab(self) -> QWidget:
        widget = QWidget()
        layout = QFormLayout(widget)
        layout.setSpacing(16)

        # Theme
        theme_combo = QComboBox()
        theme_combo.addItems(["Dark (Recommended)", "Light", "System"])
        layout.addRow("Theme:", theme_combo)

        # Startup - enabled by default for background color management
        startup_check = QCheckBox("Start with Windows")
        startup_check.setChecked(True)  # Default to enabled
        startup_check.setToolTip("Launch Calibrate Pro at Windows startup to maintain color management")
        layout.addRow("Startup:", startup_check)

        # Minimize to tray - enabled by default
        tray_check = QCheckBox("Minimize to system tray on close")
        tray_check.setChecked(True)
        tray_check.setToolTip("Keep running in background to maintain active LUT and ICC profiles")
        layout.addRow("", tray_check)

        # Start minimized
        start_min_check = QCheckBox("Start minimized to tray")
        start_min_check.setChecked(False)
        start_min_check.setToolTip("Start the application minimized in the system tray")
        layout.addRow("", start_min_check)

        # Updates
        update_check = QCheckBox("Check for updates automatically")
        update_check.setChecked(True)
        layout.addRow("Updates:", update_check)

        # Language
        lang_combo = QComboBox()
        lang_combo.addItems(["English", "Japanese", "German", "French", "Spanish"])
        layout.addRow("Language:", lang_combo)

        # Restore CM on startup
        restore_cm_check = QCheckBox("Restore last color management state on startup")
        restore_cm_check.setChecked(True)
        restore_cm_check.setToolTip("Automatically reload the last active ICC profile and 3D LUT")
        layout.addRow("Color Mgmt:", restore_cm_check)

        return widget

    def _create_calibration_tab(self) -> QWidget:
        widget = QWidget()
        layout = QFormLayout(widget)
        layout.setSpacing(16)

        # Default profile
        profile_combo = QComboBox()
        profile_combo.addItems(["sRGB Web Standard", "Rec.709 Broadcast", "DCI-P3 Cinema", "Custom"])
        layout.addRow("Default Profile:", profile_combo)

        # LUT size
        lut_combo = QComboBox()
        lut_combo.addItems(["17x17x17 (Fast)", "33x33x33 (Balanced)", "65x65x65 (High Quality)"])
        lut_combo.setCurrentIndex(1)
        layout.addRow("3D LUT Size:", lut_combo)

        # Patch count
        patch_spin = QSpinBox()
        patch_spin.setRange(100, 10000)
        patch_spin.setValue(729)
        layout.addRow("Measurement Patches:", patch_spin)

        # Warm-up reminder
        warmup_check = QCheckBox("Show display warm-up reminder")
        warmup_check.setChecked(True)
        layout.addRow("", warmup_check)

        # Auto-verify
        verify_check = QCheckBox("Verify after calibration")
        verify_check.setChecked(True)
        layout.addRow("", verify_check)

        return widget

    def _create_hardware_tab(self) -> QWidget:
        widget = QWidget()
        layout = QFormLayout(widget)
        layout.setSpacing(16)

        # Colorimeter
        colorimeter_combo = QComboBox()
        colorimeter_combo.addItems(["Auto-detect", "i1Display Pro", "Spyder X", "ColorChecker Display", "None (Sensorless only)"])
        layout.addRow("Colorimeter:", colorimeter_combo)

        # Correction matrix
        matrix_combo = QComboBox()
        matrix_combo.addItems(["Auto (OLED)", "LCD (CCFL)", "LCD (LED)", "Custom CCSS..."])
        layout.addRow("Correction Matrix:", matrix_combo)

        # LUT loading
        lut_combo = QComboBox()
        lut_combo.addItems(["dwm_lut (Recommended)", "NVIDIA NVAPI", "AMD ADL", "Intel IGCL", "ICC Profile Only"])
        layout.addRow("LUT Loader:", lut_combo)

        # GPU detection
        gpu_label = QLabel("NVIDIA GeForce RTX 4090")
        gpu_label.setStyleSheet(f"color: {COLORS['accent']};")
        layout.addRow("Detected GPU:", gpu_label)

        return widget

    def _create_paths_tab(self) -> QWidget:
        widget = QWidget()
        layout = QFormLayout(widget)
        layout.setSpacing(16)

        # Profiles path
        profiles_layout = QHBoxLayout()
        profiles_edit = QLineEdit()
        profiles_edit.setText(str(Path.home() / "Documents" / "Calibrate Pro" / "Profiles"))
        profiles_layout.addWidget(profiles_edit)
        browse_btn = QPushButton("Browse")
        browse_btn.setMaximumWidth(80)
        profiles_layout.addWidget(browse_btn)
        layout.addRow("Profiles:", profiles_layout)

        # LUTs path
        luts_layout = QHBoxLayout()
        luts_edit = QLineEdit()
        luts_edit.setText(str(Path.home() / "Documents" / "Calibrate Pro" / "LUTs"))
        luts_layout.addWidget(luts_edit)
        browse_btn2 = QPushButton("Browse")
        browse_btn2.setMaximumWidth(80)
        luts_layout.addWidget(browse_btn2)
        layout.addRow("LUTs:", luts_layout)

        # Reports path
        reports_layout = QHBoxLayout()
        reports_edit = QLineEdit()
        reports_edit.setText(str(Path.home() / "Documents" / "Calibrate Pro" / "Reports"))
        reports_layout.addWidget(reports_edit)
        browse_btn3 = QPushButton("Browse")
        browse_btn3.setMaximumWidth(80)
        reports_layout.addWidget(browse_btn3)
        layout.addRow("Reports:", reports_layout)

        # ArgyllCMS path
        argyll_layout = QHBoxLayout()
        argyll_edit = QLineEdit()
        argyll_edit.setText("C:\\Program Files\\ArgyllCMS\\bin")
        argyll_layout.addWidget(argyll_edit)
        browse_btn4 = QPushButton("Browse")
        browse_btn4.setMaximumWidth(80)
        argyll_layout.addWidget(browse_btn4)
        layout.addRow("ArgyllCMS:", argyll_layout)

        return widget
