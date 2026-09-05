"""DDC/CI proposal editor with a strict, confirmed actuation boundary."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTableWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from calibrate_pro import __release_series__
from calibrate_pro.gui.theme import COLORS
from calibrate_pro.workflow import DDC_WRITE_CODES, ApplyPlan, CalibrationMethod

COLORIMETER_CLOSED = (
    "Measured calibration is closed in this build, so no colorimeter is opened from this page. "
    "A detect button here used to enumerate devices through ArgyllCMS and report a product name "
    "as a found instrument. That is an instrument read taken outside the session that decides "
    "whether a measurement may be taken, gives it a receipt, and records that it happened."
)


class DDCControlPage(QWidget):
    """
    Comprehensive DDC/CI hardware control panel.

    Features:
    - VCP Code Scanner: Discover all supported VCP codes
    - Raw VCP Control: Read/write any VCP code
    - Common Controls: Brightness, contrast, RGB, color presets
    - Monitor Info: Capabilities, firmware, usage time

    NOTE: Not all monitors support all features. Use the scanner
    to discover what your monitor actually supports.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ddc_controller = None
        self.current_monitor = None
        self.monitors = []
        self._updating_sliders = False
        self._supported_features = {}
        self._discovered_vcp_codes = {}  # {code: (current, max)}
        self._pending_changes: dict[str, int] = {}
        self._pending_plan: ApplyPlan | None = None
        self._setup_ui()
        QTimer.singleShot(500, self._initialize_ddc)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        # Header
        header_layout = QHBoxLayout()
        header = QLabel("Hardware Monitor Control (DDC/CI)")
        header.setStyleSheet("font-size: 20px; font-weight: 600;")
        header_layout.addWidget(header)
        header_layout.addStretch()

        refresh_btn = QPushButton("Refresh Monitors")
        refresh_btn.clicked.connect(self._refresh_monitors)
        header_layout.addWidget(refresh_btn)

        layout.addLayout(header_layout)

        # Status message
        self.status_label = QLabel("Initializing DDC/CI...")
        self.status_label.setStyleSheet(f"color: {COLORS['text_secondary']}; padding: 8px;")
        layout.addWidget(self.status_label)

        # Monitor selector
        monitor_group = QGroupBox("Select Monitor")
        monitor_layout = QVBoxLayout(monitor_group)

        self.monitor_combo = QComboBox()
        self.monitor_combo.currentIndexChanged.connect(self._on_monitor_changed)
        monitor_layout.addWidget(self.monitor_combo)

        self.capabilities_label = QLabel("Capabilities: Unknown")
        self.capabilities_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
        self.capabilities_label.setWordWrap(True)
        monitor_layout.addWidget(self.capabilities_label)

        layout.addWidget(monitor_group)

        # Tabbed interface for different control modes
        self.control_tabs = QTabWidget()
        self.control_tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: 1px solid {COLORS["border"]};
                border-radius: 4px;
                background: {COLORS["surface"]};
            }}
            QTabBar::tab {{
                background: {COLORS["background_alt"]};
                color: {COLORS["text_secondary"]};
                padding: 8px 16px;
                margin-right: 2px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }}
            QTabBar::tab:selected {{
                background: {COLORS["surface"]};
                color: {COLORS["text_primary"]};
            }}
            QTabBar::tab:hover {{
                background: {COLORS["surface_alt"]};
            }}
        """)

        # Tab 1: Common Controls
        self._setup_common_controls_tab()

        # Tab 2: VCP Scanner
        self._setup_vcp_scanner_tab()

        # Tab 3: Raw VCP Control
        self._setup_raw_vcp_tab()

        # Tab 4: Presets
        self._setup_presets_tab()

        layout.addWidget(self.control_tabs)

        # Action buttons at bottom
        actions_layout = QHBoxLayout()

        test_btn = QPushButton("Test DDC Connection")
        test_btn.setToolTip("Flashes brightness to confirm DDC/CI is actually working")
        test_btn.clicked.connect(self._test_ddc_connection)
        actions_layout.addWidget(test_btn)

        read_btn = QPushButton("Read Current Values")
        read_btn.clicked.connect(self._read_current_values)
        actions_layout.addWidget(read_btn)

        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.clicked.connect(self._reset_to_defaults)
        actions_layout.addWidget(reset_btn)

        actions_layout.addStretch()

        apply_d65_btn = QPushButton("Auto-Calibrate to D65")
        apply_d65_btn.setProperty("primary", True)
        apply_d65_btn.setToolTip("Attempts to automatically adjust RGB gains for D65 white point")
        apply_d65_btn.clicked.connect(self._auto_calibrate_d65)
        actions_layout.addWidget(apply_d65_btn)

        layout.addLayout(actions_layout)

    def _setup_common_controls_tab(self):
        """Setup the common controls tab with brightness, contrast, RGB sliders."""
        common_widget = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(16)

        # Brightness & Contrast
        self.basic_group = QGroupBox("Brightness & Contrast")
        basic_layout = QVBoxLayout(self.basic_group)

        self.brightness_slider = self._create_slider_row(
            "Brightness", 0, 100, 50, "Adjusts monitor backlight/OLED pixel brightness"
        )
        basic_layout.addLayout(self.brightness_slider["layout"])

        self.contrast_slider = self._create_slider_row("Contrast", 0, 100, 50, "Adjusts display contrast ratio")
        basic_layout.addLayout(self.contrast_slider["layout"])

        scroll_layout.addWidget(self.basic_group)

        # RGB Gain (White Balance)
        self.rgb_group = QGroupBox("RGB Gain (White Balance) - Adjusts D65 White Point")
        rgb_layout = QVBoxLayout(self.rgb_group)

        self.rgb_unsupported_label = QLabel(
            "\u274c RGB Gain is NOT supported by this monitor via DDC/CI.\n"
            "You must adjust white balance through the monitor's OSD menu."
        )
        self.rgb_unsupported_label.setWordWrap(True)
        self.rgb_unsupported_label.setStyleSheet(
            f"color: {COLORS['error']}; padding: 8px; background-color: rgba(255,100,100,0.1); border-radius: 4px;"
        )
        self.rgb_unsupported_label.setVisible(False)
        rgb_layout.addWidget(self.rgb_unsupported_label)

        rgb_info = QLabel(
            "Adjust these to achieve D65 (6504K) white point. Values should be near 100 for neutral gray at all levels."
        )
        rgb_info.setWordWrap(True)
        rgb_info.setStyleSheet(f"color: {COLORS['text_secondary']}; padding: 4px;")
        rgb_layout.addWidget(rgb_info)

        self.red_gain_slider = self._create_slider_row(
            "Red Gain", 0, 100, 100, "Increases red in highlights (warm)", value_color="#ff6b6b"
        )
        rgb_layout.addLayout(self.red_gain_slider["layout"])

        self.green_gain_slider = self._create_slider_row(
            "Green Gain", 0, 100, 100, "Increases green in highlights", value_color="#69db7c"
        )
        rgb_layout.addLayout(self.green_gain_slider["layout"])

        self.blue_gain_slider = self._create_slider_row(
            "Blue Gain", 0, 100, 100, "Increases blue in highlights (cool)", value_color="#74c0fc"
        )
        rgb_layout.addLayout(self.blue_gain_slider["layout"])

        scroll_layout.addWidget(self.rgb_group)

        # RGB Black Level
        self.black_group = QGroupBox("RGB Black Level (Shadow Balance)")
        black_layout = QVBoxLayout(self.black_group)

        self.black_unsupported_label = QLabel("\u274c RGB Black Level is NOT supported by this monitor via DDC/CI.")
        self.black_unsupported_label.setWordWrap(True)
        self.black_unsupported_label.setStyleSheet(
            f"color: {COLORS['error']}; padding: 8px; background-color: rgba(255,100,100,0.1); border-radius: 4px;"
        )
        self.black_unsupported_label.setVisible(False)
        black_layout.addWidget(self.black_unsupported_label)

        black_info = QLabel("Adjusts color balance in shadows/blacks. Keep balanced for neutral grays.")
        black_info.setWordWrap(True)
        black_info.setStyleSheet(f"color: {COLORS['text_secondary']}; padding: 4px;")
        black_layout.addWidget(black_info)

        self.red_black_slider = self._create_slider_row(
            "Red Black", 0, 100, 50, "Red level in shadows", value_color="#ff6b6b"
        )
        black_layout.addLayout(self.red_black_slider["layout"])

        self.green_black_slider = self._create_slider_row(
            "Green Black", 0, 100, 50, "Green level in shadows", value_color="#69db7c"
        )
        black_layout.addLayout(self.green_black_slider["layout"])

        self.blue_black_slider = self._create_slider_row(
            "Blue Black", 0, 100, 50, "Blue level in shadows", value_color="#74c0fc"
        )
        black_layout.addLayout(self.blue_black_slider["layout"])

        scroll_layout.addWidget(self.black_group)
        scroll_layout.addStretch()

        scroll.setWidget(scroll_widget)

        common_layout = QVBoxLayout(common_widget)
        common_layout.setContentsMargins(0, 0, 0, 0)
        common_layout.addWidget(scroll)

        self.control_tabs.addTab(common_widget, "Common Controls")

    def _setup_vcp_scanner_tab(self):
        """Setup the VCP code scanner tab."""
        scanner_widget = QWidget()
        layout = QVBoxLayout(scanner_widget)
        layout.setSpacing(12)

        # Info header
        info_label = QLabel(
            "Scan all VCP codes (0x00-0xFF) to discover what your monitor actually supports.\n"
            "This performs a brute-force test of all 256 possible codes."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet(f"color: {COLORS['text_secondary']}; padding: 8px;")
        layout.addWidget(info_label)

        # Scan controls
        scan_layout = QHBoxLayout()

        self.scan_btn = QPushButton("Scan All VCP Codes")
        self.scan_btn.setProperty("primary", True)
        self.scan_btn.clicked.connect(self._scan_vcp_codes)
        scan_layout.addWidget(self.scan_btn)

        self.scan_progress = QProgressBar()
        self.scan_progress.setMaximum(256)
        self.scan_progress.setValue(0)
        self.scan_progress.setTextVisible(True)
        self.scan_progress.setFormat("Ready to scan")
        scan_layout.addWidget(self.scan_progress, stretch=1)

        layout.addLayout(scan_layout)

        # Results table
        self.vcp_table = QTableWidget()
        self.vcp_table.setColumnCount(5)
        self.vcp_table.setHorizontalHeaderLabels(["Code", "Name", "Current", "Maximum", "Actions"])
        self.vcp_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.vcp_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.vcp_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.vcp_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.vcp_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.vcp_table.setAlternatingRowColors(True)
        self.vcp_table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {COLORS["surface"]};
                gridline-color: {COLORS["border"]};
            }}
            QTableWidget::item {{
                padding: 4px 8px;
            }}
            QTableWidget::item:alternate {{
                background-color: {COLORS["background_alt"]};
            }}
            QHeaderView::section {{
                background-color: {COLORS["background_alt"]};
                color: {COLORS["text_primary"]};
                padding: 6px;
                border: none;
                border-bottom: 1px solid {COLORS["border"]};
            }}
        """)
        layout.addWidget(self.vcp_table)

        # Summary label
        self.scan_summary = QLabel("No scan performed yet.")
        self.scan_summary.setStyleSheet(f"color: {COLORS['text_secondary']}; padding: 8px;")
        layout.addWidget(self.scan_summary)

        self.control_tabs.addTab(scanner_widget, "VCP Scanner")

    def _setup_raw_vcp_tab(self):
        """Setup the raw VCP read/write tab."""
        raw_widget = QWidget()
        layout = QVBoxLayout(raw_widget)
        layout.setSpacing(12)

        # Info header
        info_label = QLabel(
            "Read or write any VCP code directly. Use with caution - some codes can\n"
            "affect monitor behavior in unexpected ways. Refer to MCCS specification."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet(f"color: {COLORS['text_secondary']}; padding: 8px;")
        layout.addWidget(info_label)

        # Read section
        read_group = QGroupBox("Read VCP Code")
        read_layout = QHBoxLayout(read_group)

        read_layout.addWidget(QLabel("VCP Code:"))
        self.read_code_input = QLineEdit()
        self.read_code_input.setPlaceholderText("e.g. 0x10 or 16")
        self.read_code_input.setMaximumWidth(120)
        read_layout.addWidget(self.read_code_input)

        self.read_btn = QPushButton("Read")
        self.read_btn.clicked.connect(self._read_raw_vcp)
        read_layout.addWidget(self.read_btn)

        self.read_result = QLabel("Result: -")
        self.read_result.setStyleSheet(f"color: {COLORS['text_secondary']};")
        read_layout.addWidget(self.read_result)

        read_layout.addStretch()
        layout.addWidget(read_group)

        # Write section
        write_group = QGroupBox("Write VCP Code")
        write_layout = QHBoxLayout(write_group)

        write_layout.addWidget(QLabel("VCP Code:"))
        self.write_code_input = QLineEdit()
        self.write_code_input.setPlaceholderText("e.g. 0x10")
        self.write_code_input.setMaximumWidth(120)
        write_layout.addWidget(self.write_code_input)

        write_layout.addWidget(QLabel("Value:"))
        self.write_value_input = QLineEdit()
        self.write_value_input.setPlaceholderText("0-max")
        self.write_value_input.setMaximumWidth(80)
        write_layout.addWidget(self.write_value_input)

        self.write_btn = QPushButton("Write")
        self.write_btn.clicked.connect(self._write_raw_vcp)
        write_layout.addWidget(self.write_btn)

        self.write_result = QLabel("Result: -")
        self.write_result.setStyleSheet(f"color: {COLORS['text_secondary']};")
        write_layout.addWidget(self.write_result)

        write_layout.addStretch()
        layout.addWidget(write_group)

        # Common VCP codes reference
        ref_group = QGroupBox("Common VCP Codes Reference")
        ref_layout = QVBoxLayout(ref_group)

        ref_text = QLabel(
            "0x10 - Brightness (luminance)\n"
            "0x12 - Contrast\n"
            "0x14 - Color Preset (1=Native, 5=6500K, etc.)\n"
            "0x16/0x18/0x1A - RGB Gain (Red/Green/Blue)\n"
            "0x6C/0x6E/0x70 - RGB Black Level\n"
            "0x60 - Input Source\n"
            "0x87 - Sharpness\n"
            "0x8A - Saturation\n"
            "0xDB - Image Mode (Picture preset)\n"
            "0xD6 - Power Mode (DPMS)\n"
            "0xF2 - Gamma preset"
        )
        ref_text.setStyleSheet(f"color: {COLORS['text_secondary']}; font-family: monospace;")
        ref_layout.addWidget(ref_text)
        layout.addWidget(ref_group)

        layout.addStretch()

        self.control_tabs.addTab(raw_widget, "Raw VCP Control")

    def _setup_presets_tab(self):
        """Setup the color/gamma presets tab."""
        presets_widget = QWidget()
        layout = QVBoxLayout(presets_widget)
        layout.setSpacing(12)

        # Color Temperature Preset (VCP 0x14)
        color_group = QGroupBox("Color Temperature / Preset (VCP 0x14)")
        color_layout = QVBoxLayout(color_group)

        color_info = QLabel("Select a color temperature preset. Available presets depend on your monitor.")
        color_info.setWordWrap(True)
        color_info.setStyleSheet(f"color: {COLORS['text_secondary']}; padding: 4px;")
        color_layout.addWidget(color_info)

        preset_row = QHBoxLayout()
        self.color_preset_combo = QComboBox()
        self.color_preset_combo.addItems(
            [
                "1 - Native/sRGB",
                "2 - 4000K (Warm)",
                "3 - 5000K (Warm)",
                "4 - 5500K",
                "5 - 6500K (D65)",
                "6 - 7500K (Cool)",
                "7 - 8200K (Cool)",
                "8 - 9300K (Cool)",
                "9 - 10000K",
                "10 - 11500K",
                "11 - User 1",
                "12 - User 2",
                "13 - User 3",
            ]
        )
        self.color_preset_combo.setCurrentIndex(4)  # Default to 6500K
        preset_row.addWidget(self.color_preset_combo)

        apply_preset_btn = QPushButton("Apply")
        apply_preset_btn.clicked.connect(self._apply_color_preset)
        preset_row.addWidget(apply_preset_btn)

        read_preset_btn = QPushButton("Read Current")
        read_preset_btn.clicked.connect(self._read_color_preset)
        preset_row.addWidget(read_preset_btn)

        preset_row.addStretch()
        color_layout.addLayout(preset_row)

        self.preset_status = QLabel("Status: Unknown")
        self.preset_status.setStyleSheet(f"color: {COLORS['text_secondary']};")
        color_layout.addWidget(self.preset_status)

        layout.addWidget(color_group)

        # Image Mode (VCP 0xDB)
        image_group = QGroupBox("Image Mode / Picture Preset (VCP 0xDB)")
        image_layout = QVBoxLayout(image_group)

        image_info = QLabel("Picture mode presets like Standard, Movie, Game, Photo, etc.")
        image_info.setWordWrap(True)
        image_info.setStyleSheet(f"color: {COLORS['text_secondary']}; padding: 4px;")
        image_layout.addWidget(image_info)

        image_row = QHBoxLayout()
        self.image_mode_combo = QComboBox()
        self.image_mode_combo.addItems(
            [
                "0 - Standard",
                "1 - Movie/Cinema",
                "2 - Game",
                "3 - Photo/Graphics",
                "4 - Text/Office",
                "5 - Dynamic",
                "6 - Custom 1",
                "7 - Custom 2",
            ]
        )
        image_row.addWidget(self.image_mode_combo)

        apply_image_btn = QPushButton("Apply")
        apply_image_btn.clicked.connect(self._apply_image_mode)
        image_row.addWidget(apply_image_btn)

        read_image_btn = QPushButton("Read Current")
        read_image_btn.clicked.connect(self._read_image_mode)
        image_row.addWidget(read_image_btn)

        image_row.addStretch()
        image_layout.addLayout(image_row)

        self.image_mode_status = QLabel("Status: Unknown")
        self.image_mode_status.setStyleSheet(f"color: {COLORS['text_secondary']};")
        image_layout.addWidget(self.image_mode_status)

        layout.addWidget(image_group)

        # Gamma (VCP 0xF2)
        gamma_group = QGroupBox("Gamma Preset (VCP 0xF2)")
        gamma_layout = QVBoxLayout(gamma_group)

        gamma_info = QLabel("Gamma curve preset. Values are manufacturer-specific.")
        gamma_info.setWordWrap(True)
        gamma_info.setStyleSheet(f"color: {COLORS['text_secondary']}; padding: 4px;")
        gamma_layout.addWidget(gamma_info)

        gamma_row = QHBoxLayout()
        self.gamma_combo = QComboBox()
        self.gamma_combo.addItems(
            [
                "0 - Native/Default",
                "1 - 1.8",
                "2 - 2.0",
                "3 - 2.2 (sRGB)",
                "4 - 2.4 (BT.1886)",
                "5 - 2.6",
            ]
        )
        self.gamma_combo.setCurrentIndex(3)  # Default to 2.2
        gamma_row.addWidget(self.gamma_combo)

        apply_gamma_btn = QPushButton("Apply")
        apply_gamma_btn.clicked.connect(self._apply_gamma_preset)
        gamma_row.addWidget(apply_gamma_btn)

        read_gamma_btn = QPushButton("Read Current")
        read_gamma_btn.clicked.connect(self._read_gamma_preset)
        gamma_row.addWidget(read_gamma_btn)

        gamma_row.addStretch()
        gamma_layout.addLayout(gamma_row)

        self.gamma_status = QLabel("Status: Unknown")
        self.gamma_status.setStyleSheet(f"color: {COLORS['text_secondary']};")
        gamma_layout.addWidget(self.gamma_status)

        layout.addWidget(gamma_group)

        layout.addStretch()

        self.control_tabs.addTab(presets_widget, "Presets")

        # Tab 5: Auto-Calibration
        self._setup_auto_calibration_tab()

    def _setup_auto_calibration_tab(self):
        """Setup the automatic hardware calibration tab."""
        auto_widget = QWidget()
        layout = QVBoxLayout(auto_widget)
        layout.setSpacing(12)

        # Header
        header = QLabel("Automatic Hardware Calibration")
        header.setStyleSheet("font-size: 16px; font-weight: 600;")
        layout.addWidget(header)

        # Info
        info_label = QLabel(
            "Achieve scientifically accurate calibration by measuring display output\n"
            "and iteratively adjusting hardware settings. This requires a colorimeter\n"
            "for true accuracy, or uses panel database estimates in sensorless mode."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet(f"color: {COLORS['text_secondary']}; padding: 8px;")
        layout.addWidget(info_label)

        # Colorimeter status
        colorimeter_group = QGroupBox("Measurement Device")
        colorimeter_layout = QVBoxLayout(colorimeter_group)

        self.colorimeter_status = QLabel(COLORIMETER_CLOSED)
        self.colorimeter_status.setStyleSheet(f"color: {COLORS['text_secondary']}; padding: 8px;")
        self.colorimeter_status.setWordWrap(True)
        colorimeter_layout.addWidget(self.colorimeter_status)

        layout.addWidget(colorimeter_group)

        # Calibration targets
        targets_group = QGroupBox("Calibration Targets")
        targets_layout = QGridLayout(targets_group)

        # White point
        targets_layout.addWidget(QLabel("White Point:"), 0, 0)
        self.auto_whitepoint_combo = QComboBox()
        self.auto_whitepoint_combo.addItems(["D65 (6504K)", "D50 (5003K)", "D55 (5503K)", "D75 (7504K)", "Native"])
        targets_layout.addWidget(self.auto_whitepoint_combo, 0, 1)

        # Target luminance
        targets_layout.addWidget(QLabel("Luminance:"), 0, 2)
        self.auto_luminance_spin = QSpinBox()
        self.auto_luminance_spin.setRange(80, 1000)
        self.auto_luminance_spin.setValue(120)
        self.auto_luminance_spin.setSuffix(" cd/m\u00b2")
        targets_layout.addWidget(self.auto_luminance_spin, 0, 3)

        # Gamma
        targets_layout.addWidget(QLabel("Gamma:"), 1, 0)
        self.auto_gamma_combo = QComboBox()
        self.auto_gamma_combo.addItems(["2.2 (Standard)", "2.4 (BT.1886)", "sRGB", "2.0", "2.6"])
        targets_layout.addWidget(self.auto_gamma_combo, 1, 1)

        # Gamut
        targets_layout.addWidget(QLabel("Gamut:"), 1, 2)
        self.auto_gamut_combo = QComboBox()
        self.auto_gamut_combo.addItems(["sRGB", "DCI-P3", "Adobe RGB", "BT.2020", "Native"])
        targets_layout.addWidget(self.auto_gamut_combo, 1, 3)

        layout.addWidget(targets_group)

        # Calibration options
        options_group = QGroupBox("Calibration Options")
        options_layout = QVBoxLayout(options_group)

        self.auto_adjust_brightness = QCheckBox("Adjust brightness to target luminance")
        self.auto_adjust_brightness.setChecked(True)
        options_layout.addWidget(self.auto_adjust_brightness)

        self.auto_adjust_white_balance = QCheckBox("Adjust RGB gains for white balance (D65)")
        self.auto_adjust_white_balance.setChecked(True)
        options_layout.addWidget(self.auto_adjust_white_balance)

        self.auto_generate_profile = QCheckBox("Generate ICC profile")
        self.auto_generate_profile.setChecked(True)
        options_layout.addWidget(self.auto_generate_profile)

        self.auto_generate_lut = QCheckBox("Generate 3D LUT for gamut/gamma correction")
        self.auto_generate_lut.setChecked(True)
        options_layout.addWidget(self.auto_generate_lut)

        self.auto_verify = QCheckBox("Verify calibration with grayscale test")
        self.auto_verify.setChecked(True)
        options_layout.addWidget(self.auto_verify)

        layout.addWidget(options_group)

        # Progress
        progress_group = QGroupBox("Calibration Progress")
        progress_layout = QVBoxLayout(progress_group)

        self.auto_progress = QProgressBar()
        self.auto_progress.setMaximum(100)
        self.auto_progress.setValue(0)
        self.auto_progress.setTextVisible(True)
        self.auto_progress.setFormat("Ready")
        progress_layout.addWidget(self.auto_progress)

        self.auto_log = QPlainTextEdit()
        self.auto_log.setReadOnly(True)
        self.auto_log.setMaximumHeight(150)
        self.auto_log.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {COLORS["background_alt"]};
                font-family: 'Consolas', monospace;
                font-size: 11px;
            }}
        """)
        progress_layout.addWidget(self.auto_log)

        layout.addWidget(progress_group)

        # Action buttons
        action_layout = QHBoxLayout()

        self.start_calibration_btn = QPushButton("Start Hardware Calibration")
        self.start_calibration_btn.setProperty("primary", True)
        self.start_calibration_btn.clicked.connect(self._start_hardware_calibration)
        action_layout.addWidget(self.start_calibration_btn)

        quick_wb_btn = QPushButton("Quick White Balance")
        quick_wb_btn.setToolTip("Fast white balance adjustment only")
        quick_wb_btn.clicked.connect(self._quick_white_balance)
        action_layout.addWidget(quick_wb_btn)

        sensorless_btn = QPushButton("Sensorless Calibration")
        sensorless_btn.setToolTip("Calibrate using panel database (no colorimeter)")
        sensorless_btn.clicked.connect(self._run_sensorless_calibration)
        action_layout.addWidget(sensorless_btn)

        action_layout.addStretch()

        stop_btn = QPushButton("Stop")
        stop_btn.clicked.connect(self._stop_calibration)
        action_layout.addWidget(stop_btn)

        layout.addLayout(action_layout)

        # Results summary
        self.auto_results = QLabel("")
        self.auto_results.setWordWrap(True)
        self.auto_results.setStyleSheet("padding: 8px;")
        layout.addWidget(self.auto_results)

        self.control_tabs.addTab(auto_widget, "Auto Calibration")

    def _start_hardware_calibration(self):
        """Build a measured-calibration preview without display writes."""
        self.auto_log.clear()
        whitepoint = self.auto_whitepoint_combo.currentText().split(" ", 1)[0]
        gamma = self.auto_gamma_combo.currentText().split(" ", 1)[0]
        self._pending_plan = ApplyPlan(
            display_id=str(max(0, self.monitor_combo.currentIndex())),
            method=CalibrationMethod.MEASURED,
            target_whitepoint=whitepoint,
            target_gamma=gamma,
            target_gamut=self.auto_gamut_combo.currentText(),
            ddc_changes=tuple(self._pending_changes.items()),
        )
        self.auto_progress.setValue(100)
        self.auto_progress.setFormat("Preview ready")
        self.auto_log.appendPlainText("Measured plan staged. No DDC/CI command was sent.")
        self.auto_results.setText("Preview ready; review and explicit confirmation are required before apply.")
        self.auto_results.setStyleSheet(f"color: {COLORS['warning']}; padding: 8px;")

    def _quick_white_balance(self):
        """Keep quick white balance behind the confirmed plan workflow."""
        QMessageBox.information(
            self,
            "Confirmation Required",
            "No white-balance command was sent. Run measured calibration to build a reviewable plan.",
        )

    def _run_sensorless_calibration(self):
        """Build a sensorless proposal without changing monitor state."""
        self.auto_log.clear()
        whitepoint = self.auto_whitepoint_combo.currentText().split(" ", 1)[0]
        gamma = self.auto_gamma_combo.currentText().split(" ", 1)[0]
        self._pending_plan = ApplyPlan(
            display_id=str(max(0, self.monitor_combo.currentIndex())),
            method=CalibrationMethod.SENSORLESS,
            target_whitepoint=whitepoint,
            target_gamma=gamma,
            target_gamut=self.auto_gamut_combo.currentText(),
            ddc_changes=tuple(self._pending_changes.items()),
        )
        self.auto_progress.setValue(100)
        self.auto_progress.setFormat("Preview ready")
        self.auto_log.appendPlainText("Sensorless plan staged. No DDC/CI command was sent.")
        self.auto_results.setText("Preview ready; review and explicit confirmation are required before apply.")
        self.auto_results.setStyleSheet(f"color: {COLORS['warning']}; padding: 8px;")

    def _stop_calibration(self):
        """Stop ongoing calibration."""
        self.auto_log.appendPlainText("Calibration stopped by user.")
        self.auto_progress.setFormat("Stopped")
        self.start_calibration_btn.setEnabled(True)

    def _create_slider_row(
        self, label: str, min_val: int, max_val: int, default: int, tooltip: str, value_color: str = None
    ) -> dict:
        """Create a labeled slider with value display."""
        layout = QHBoxLayout()
        layout.setSpacing(12)

        # Label
        lbl = QLabel(f"{label}:")
        lbl.setMinimumWidth(100)
        layout.addWidget(lbl)

        # Slider
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setMinimum(min_val)
        slider.setMaximum(max_val)
        slider.setValue(default)
        slider.setToolTip(tooltip)
        layout.addWidget(slider, stretch=1)

        # Value label
        color = value_color or COLORS["text_primary"]
        value_lbl = QLabel(str(default))
        value_lbl.setMinimumWidth(40)
        value_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        value_lbl.setStyleSheet(f"font-weight: 600; color: {color};")
        layout.addWidget(value_lbl)

        # Connect slider to update value label and send DDC command
        def on_value_changed(val):
            value_lbl.setText(str(val))
            if not self._updating_sliders:
                self._send_ddc_value(label, val)

        slider.valueChanged.connect(on_value_changed)

        return {"layout": layout, "slider": slider, "value_label": value_lbl}

    def _initialize_ddc(self):
        """Populate basic Qt display observations without opening DDC/CI."""
        self._refresh_monitors()

    def _refresh_monitors(self):
        """Refresh Qt-observed displays for proposal targeting."""
        self.monitor_combo.clear()
        self.monitors = [
            {"name": screen.name() or f"Display {index + 1}", "screen": screen}
            for index, screen in enumerate(QApplication.screens())
        ]

        if not self.monitors:
            self.status_label.setText("No displays were observed through Qt.")
            self.status_label.setStyleSheet(f"color: {COLORS['warning']}; padding: 8px;")
            return

        for i, monitor in enumerate(self.monitors):
            name = monitor.get("name", f"Monitor {i + 1}")
            self.monitor_combo.addItem(str(name))

        self.status_label.setText(
            f"Found {len(self.monitors)} display(s). Controls build a preview; confirmation is required before apply."
        )
        self.status_label.setStyleSheet(f"color: {COLORS['warning']}; padding: 8px;")

        if self.monitors:
            self._on_monitor_changed(0)

    def _on_monitor_changed(self, index: int):
        """Handle monitor selection change."""
        if index < 0 or index >= len(self.monitors):
            return

        self.current_monitor = self.monitors[index]
        # These are the only controls representable by ApplyPlan. Hardware
        # support is validated later inside the confirmed transaction.
        self._supported_features = {
            "brightness": True,
            "contrast": True,
            "rgb_gain": True,
            "rgb_black": True,
        }
        self.capabilities_label.setText("Capabilities: validated only during confirmed apply")

        # Enable/disable sliders based on support
        self._update_slider_states()

        # Read current values
        self._read_current_values()

    def _update_slider_states(self):
        """Enable/disable sliders based on monitor capabilities."""
        # Brightness/Contrast
        has_brightness = self._supported_features.get("brightness", False)
        has_contrast = self._supported_features.get("contrast", False)
        self.brightness_slider["slider"].setEnabled(has_brightness)
        self.contrast_slider["slider"].setEnabled(has_contrast)

        if not has_brightness and not has_contrast:
            self.basic_group.setTitle("Brightness & Contrast (NOT SUPPORTED)")
        else:
            self.basic_group.setTitle("Brightness & Contrast")

        # RGB Gain
        has_rgb_gain = self._supported_features.get("rgb_gain", False)
        self.rgb_unsupported_label.setVisible(not has_rgb_gain)
        self.red_gain_slider["slider"].setEnabled(has_rgb_gain)
        self.green_gain_slider["slider"].setEnabled(has_rgb_gain)
        self.blue_gain_slider["slider"].setEnabled(has_rgb_gain)

        if has_rgb_gain:
            self.rgb_group.setTitle("RGB Gain (White Balance) - Adjusts D65 White Point")
        else:
            self.rgb_group.setTitle("RGB Gain (White Balance) - NOT SUPPORTED")

        # RGB Black Level
        has_rgb_black = self._supported_features.get("rgb_black", False)
        self.black_unsupported_label.setVisible(not has_rgb_black)
        self.red_black_slider["slider"].setEnabled(has_rgb_black)
        self.green_black_slider["slider"].setEnabled(has_rgb_black)
        self.blue_black_slider["slider"].setEnabled(has_rgb_black)

        if has_rgb_black:
            self.black_group.setTitle("RGB Black Level (Shadow Balance)")
        else:
            self.black_group.setTitle("RGB Black Level (Shadow Balance) - NOT SUPPORTED")

    def _read_current_values(self):
        """Keep prior-state capture inside the confirmed transaction."""
        self.status_label.setText("Current DDC values are captured only after confirmation")

    def _send_ddc_value(self, setting_name: str, value: int):
        """Stage an allowlisted DDC target without sending a command."""
        code_map = {
            "Brightness": "BRIGHTNESS",
            "Contrast": "CONTRAST",
            "Red Gain": "RED_GAIN",
            "Green Gain": "GREEN_GAIN",
            "Blue Gain": "BLUE_GAIN",
            "Red Black": "RED_BLACK_LEVEL",
            "Green Black": "GREEN_BLACK_LEVEL",
            "Blue Black": "BLUE_BLACK_LEVEL",
        }
        code = code_map.get(setting_name)
        if code not in DDC_WRITE_CODES:
            self.status_label.setText(f"{setting_name} is not representable by the {__release_series__} ApplyPlan")
            return
        self._pending_changes[code] = value
        self.status_label.setText(
            f"Preview staged: {setting_name}={value} ({len(self._pending_changes)} change(s)); confirmation required"
        )
        self.status_label.setStyleSheet(f"color: {COLORS['warning']}; padding: 8px;")

    def _reset_to_defaults(self):
        """Reset all values to factory defaults."""
        reply = QMessageBox.question(
            self,
            "Reset to Defaults",
            "Reset all DDC/CI values to factory defaults?\n\n"
            "This will set brightness/contrast to 50 and RGB gains to 100.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        self._updating_sliders = True

        defaults = [
            (self.brightness_slider, 50),
            (self.contrast_slider, 50),
            (self.red_gain_slider, 100),
            (self.green_gain_slider, 100),
            (self.blue_gain_slider, 100),
            (self.red_black_slider, 50),
            (self.green_black_slider, 50),
            (self.blue_black_slider, 50),
        ]

        for slider_dict, value in defaults:
            slider_dict["slider"].setValue(value)

        self._updating_sliders = False

        self._send_ddc_value("Brightness", 50)
        self._send_ddc_value("Contrast", 50)
        self._send_ddc_value("Red Gain", 100)
        self._send_ddc_value("Green Gain", 100)
        self._send_ddc_value("Blue Gain", 100)

    def _test_ddc_connection(self):
        """Avoid a visible write-based connection test outside confirmation."""
        QMessageBox.information(
            self,
            "Connection Test Disabled",
            "No brightness flash was sent. DDC/CI capability is validated during confirmed apply.",
        )

    def _auto_calibrate_d65(self):
        """Attempt automatic D65 white point calibration."""
        QMessageBox.information(
            self,
            "Auto-Calibrate to D65",
            "This feature requires a colorimeter (hardware sensor) to measure "
            "actual display output and iteratively adjust RGB gains.\n\n"
            "Without a colorimeter, you can manually adjust:\n"
            "\u2022 If image looks too warm (yellow/red): Reduce Red Gain, increase Blue Gain\n"
            "\u2022 If image looks too cool (blue): Reduce Blue Gain, increase Red Gain\n"
            "\u2022 If image looks green: Reduce Green Gain\n\n"
            "Target: Neutral gray at all brightness levels",
        )

    # =========================================================================
    # VCP Scanner Methods
    # =========================================================================

    def _scan_vcp_codes(self):
        """Keep arbitrary VCP probing outside the bounded application surface."""
        self.vcp_table.setRowCount(0)
        self._discovered_vcp_codes = {}
        self.scan_progress.setValue(0)
        self.scan_progress.setFormat("Disabled")
        self.scan_summary.setText(f"Raw VCP scanning is disabled in version {__release_series__}; no command was sent.")
        self.scan_summary.setStyleSheet(f"color: {COLORS['warning']}; padding: 8px;")

    def _test_vcp_code(self, code: int, maximum: int):
        """Reject arbitrary VCP toggle tests."""
        QMessageBox.information(
            self,
            "VCP Test Disabled",
            f"VCP 0x{code:02X} was not changed (reported max {maximum}).",
        )

    # =========================================================================
    # Raw VCP Control Methods
    # =========================================================================

    def _parse_vcp_code(self, text: str) -> int:
        """Parse a VCP code from user input (hex or decimal)."""
        text = text.strip()
        if text.startswith("0x") or text.startswith("0X"):
            return int(text, 16)
        return int(text)

    def _read_raw_vcp(self):
        """Reject raw VCP reads outside the bounded capability adapter."""
        try:
            code = self._parse_vcp_code(self.read_code_input.text())
            self.read_result.setText(f"Result: VCP 0x{code:02X} raw access is disabled in {__release_series__}")
            self.read_result.setStyleSheet(f"color: {COLORS['warning']};")
        except ValueError:
            self.read_result.setText("Result: Invalid code format")
            self.read_result.setStyleSheet(f"color: {COLORS['error']};")

    def _write_raw_vcp(self):
        """Reject raw VCP writes that have no ApplyPlan representation."""
        try:
            code = self._parse_vcp_code(self.write_code_input.text())
            value = int(self.write_value_input.text().strip())
            self.write_result.setText(
                f"Result: VCP 0x{code:02X}={value} was not sent; disabled in {__release_series__}"
            )
            self.write_result.setStyleSheet(f"color: {COLORS['warning']};")
        except ValueError:
            self.write_result.setText("Result: Invalid code or value format")
            self.write_result.setStyleSheet(f"color: {COLORS['error']};")

    # =========================================================================
    # Preset Control Methods
    # =========================================================================

    def _apply_color_preset(self):
        """Keep color presets disabled until they map to ApplyPlan."""
        self.preset_status.setText(f"Status: disabled in {__release_series__}; no command sent")
        self.preset_status.setStyleSheet(f"color: {COLORS['warning']};")

    def _read_color_preset(self):
        """Keep preset reads inside the bounded capability adapter."""
        self.preset_status.setText("Status: captured only during confirmed apply")

    def _apply_image_mode(self):
        """Keep image modes disabled until they map to ApplyPlan."""
        self.image_mode_status.setText(f"Status: disabled in {__release_series__}; no command sent")
        self.image_mode_status.setStyleSheet(f"color: {COLORS['warning']};")

    def _read_image_mode(self):
        """Keep image-mode reads inside the bounded capability adapter."""
        self.image_mode_status.setText("Status: captured only during confirmed apply")

    def _apply_gamma_preset(self):
        """Keep gamma presets disabled until they map to ApplyPlan."""
        self.gamma_status.setText(f"Status: disabled in {__release_series__}; no command sent")
        self.gamma_status.setStyleSheet(f"color: {COLORS['warning']};")

    def _read_gamma_preset(self):
        """Keep gamma reads inside the bounded capability adapter."""
        self.gamma_status.setText("Status: captured only during confirmed apply")
