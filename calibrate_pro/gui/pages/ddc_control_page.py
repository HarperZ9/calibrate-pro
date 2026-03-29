"""
DDC/CI Hardware Control Page - Comprehensive Monitor Control.

Features:
- VCP Code Scanner: Discover all supported VCP codes
- Raw VCP Control: Read/write any VCP code
- Common Controls: Brightness, contrast, RGB, color presets
- Monitor Info: Capabilities, firmware, usage time

NOTE: Not all monitors support all features. Use the scanner
to discover what your monitor actually supports.
"""

import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
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
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from calibrate_pro.gui.theme import COLORS


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

        self.colorimeter_status = QLabel("No colorimeter detected")
        self.colorimeter_status.setStyleSheet(f"color: {COLORS['warning']}; padding: 8px;")
        colorimeter_layout.addWidget(self.colorimeter_status)

        detect_btn_layout = QHBoxLayout()
        detect_colorimeter_btn = QPushButton("Detect Colorimeter")
        detect_colorimeter_btn.clicked.connect(self._detect_colorimeter)
        detect_btn_layout.addWidget(detect_colorimeter_btn)

        self.colorimeter_combo = QComboBox()
        self.colorimeter_combo.addItems(
            [
                "Auto-detect",
                "i1Display Pro",
                "Spyder X",
                "ColorChecker Display",
                "ArgyllCMS (any device)",
            ]
        )
        detect_btn_layout.addWidget(self.colorimeter_combo)
        detect_btn_layout.addStretch()

        colorimeter_layout.addLayout(detect_btn_layout)

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

    def _detect_colorimeter(self):
        """Detect connected colorimeter devices."""
        self.colorimeter_status.setText("Searching for colorimeters...")
        self.colorimeter_status.setStyleSheet(f"color: {COLORS['text_secondary']}; padding: 8px;")
        QApplication.processEvents()

        try:
            # Try ArgyllCMS backend
            from calibrate_pro.hardware.argyll_backend import ArgyllBackend

            backend = ArgyllBackend()
            devices = backend.enumerate_devices()

            if devices:
                device = devices[0]
                self.colorimeter_status.setText(f"\u2713 Found: {device.name} ({device.manufacturer})")
                self.colorimeter_status.setStyleSheet(f"color: {COLORS['success']}; padding: 8px;")
                self._colorimeter = backend
                return

            # No devices found
            self.colorimeter_status.setText(
                "No colorimeter detected. Connect a device and try again.\n"
                "Supported: i1Display Pro, Spyder X, ColorChecker Display, etc."
            )
            self.colorimeter_status.setStyleSheet(f"color: {COLORS['warning']}; padding: 8px;")

        except Exception as e:
            self.colorimeter_status.setText(f"ArgyllCMS not found. Install from argyllcms.com\nError: {e}")
            self.colorimeter_status.setStyleSheet(f"color: {COLORS['error']}; padding: 8px;")

    def _start_hardware_calibration(self):
        """Start the full hardware calibration process."""
        if not self.ddc_controller or not self.current_monitor:
            QMessageBox.warning(self, "No Monitor", "Select a DDC/CI monitor first.")
            return

        self.auto_log.clear()
        self.auto_progress.setValue(0)
        self.auto_results.setText("")
        self.start_calibration_btn.setEnabled(False)

        try:
            from calibrate_pro.hardware.hardware_calibration import (
                CalibrationTargets,
                HardwareCalibrationEngine,
            )

            engine = HardwareCalibrationEngine()

            # Get colorimeter if available
            colorimeter = getattr(self, "_colorimeter", None)

            # Initialize
            if not engine.initialize(
                colorimeter=colorimeter,
                ddc_controller=self.ddc_controller,
                display_index=self.monitor_combo.currentIndex(),
            ):
                self.auto_log.appendPlainText("ERROR: Failed to initialize calibration engine")
                return

            # Set targets
            targets = CalibrationTargets()
            targets.target_luminance = self.auto_luminance_spin.value()

            # White point
            wp_map = {
                "D65 (6504K)": (0.3127, 0.3290, 6504),
                "D50 (5003K)": (0.3457, 0.3585, 5003),
                "D55 (5503K)": (0.3324, 0.3474, 5503),
                "D75 (7504K)": (0.2990, 0.3149, 7504),
            }
            wp_text = self.auto_whitepoint_combo.currentText()
            if wp_text in wp_map:
                targets.whitepoint_x, targets.whitepoint_y, targets.whitepoint_cct = wp_map[wp_text]

            # Gamma
            gamma_map = {"2.2 (Standard)": 2.2, "2.4 (BT.1886)": 2.4, "sRGB": 2.2, "2.0": 2.0, "2.6": 2.6}
            targets.gamma = gamma_map.get(self.auto_gamma_combo.currentText(), 2.2)

            # Progress callback
            def update_progress(msg, progress, phase):
                self.auto_log.appendPlainText(msg)
                self.auto_progress.setValue(int(progress * 100))
                self.auto_progress.setFormat(f"{phase.name}: {int(progress * 100)}%")
                QApplication.processEvents()

            engine.set_progress_callback(update_progress)

            # Run calibration
            self.auto_log.appendPlainText("Starting hardware calibration...")
            result = engine.run_hardware_calibration(targets=targets)

            # Display results
            for log_entry in result.adjustments_log:
                self.auto_log.appendPlainText(log_entry)

            if result.success:
                self.auto_progress.setValue(100)
                self.auto_progress.setFormat("Complete!")

                summary = "\u2713 Calibration Complete\n\n"
                summary += f"White Point: {targets.whitepoint} ({targets.whitepoint_cct}K)\n"
                summary += f"Target Luminance: {targets.target_luminance} cd/m\u00b2\n"

                if result.delta_e_after > 0:
                    summary += f"Final Delta E: {result.delta_e_after:.2f}\n"

                summary += f"\nRGB Gains: R={result.final_state.red_gain}, "
                summary += f"G={result.final_state.green_gain}, B={result.final_state.blue_gain}"

                self.auto_results.setText(summary)
                self.auto_results.setStyleSheet(f"color: {COLORS['success']}; padding: 8px;")

                # Refresh common controls tab values
                self._read_current_values()
            else:
                self.auto_progress.setFormat("Failed")
                self.auto_results.setText(f"Calibration failed: {result.message}")
                self.auto_results.setStyleSheet(f"color: {COLORS['error']}; padding: 8px;")

        except Exception as e:
            self.auto_log.appendPlainText(f"ERROR: {e}")
            self.auto_results.setText(f"Error: {e}")
            self.auto_results.setStyleSheet(f"color: {COLORS['error']}; padding: 8px;")

        finally:
            self.start_calibration_btn.setEnabled(True)

    def _quick_white_balance(self):
        """Run quick white balance adjustment."""
        if not self.ddc_controller or not self.current_monitor:
            QMessageBox.warning(self, "No Monitor", "Select a DDC/CI monitor first.")
            return

        colorimeter = getattr(self, "_colorimeter", None)
        if not colorimeter:
            QMessageBox.information(
                self,
                "Colorimeter Required",
                "Quick white balance requires a colorimeter to measure actual display output.\n\n"
                "Click 'Detect Colorimeter' first, or use 'Sensorless Calibration' instead.",
            )
            return

        try:
            from calibrate_pro.hardware.hardware_calibration import HardwareCalibrationEngine

            engine = HardwareCalibrationEngine()
            engine.initialize(
                colorimeter=colorimeter,
                ddc_controller=self.ddc_controller,
                display_index=self.monitor_combo.currentIndex(),
            )

            self.auto_log.appendPlainText("Starting quick white balance...")
            success, msg, (r, g, b) = engine.run_quick_white_balance()

            self.auto_log.appendPlainText(msg)
            self.auto_log.appendPlainText(f"Final RGB gains: R={r}, G={g}, B={b}")

            if success:
                self.auto_results.setText(f"\u2713 White balance achieved!\nRGB: ({r}, {g}, {b})")
                self.auto_results.setStyleSheet(f"color: {COLORS['success']}; padding: 8px;")
            else:
                self.auto_results.setText(f"White balance: {msg}\nRGB: ({r}, {g}, {b})")
                self.auto_results.setStyleSheet(f"color: {COLORS['warning']}; padding: 8px;")

            self._read_current_values()

        except Exception as e:
            self.auto_log.appendPlainText(f"ERROR: {e}")

    def _run_sensorless_calibration(self):
        """Run scientifically accurate sensorless calibration using panel database."""
        if not self.ddc_controller or not self.current_monitor:
            QMessageBox.warning(self, "No Monitor", "Select a DDC/CI monitor first.")
            return

        self.auto_log.clear()
        self.auto_progress.setValue(0)

        try:
            from calibrate_pro.hardware.sensorless_calibration import (
                ILLUMINANTS,
                CalibrationTarget,
                SensorlessCalibrationEngine,
            )

            engine = SensorlessCalibrationEngine()

            def progress_callback(msg, progress):
                self.auto_log.appendPlainText(msg)
                self.auto_progress.setValue(int(progress * 100))
                QApplication.processEvents()

            engine.set_progress_callback(progress_callback)

            # Initialize engine with DDC controller
            if not engine.initialize(self.ddc_controller, self.monitor_combo.currentIndex()):
                self.auto_log.appendPlainText("ERROR: Failed to initialize calibration engine")
                return

            # Get target settings from UI
            whitepoint = self.auto_whitepoint_combo.currentText()
            wp_xy = ILLUMINANTS.get(whitepoint, ILLUMINANTS["D65"])

            target = CalibrationTarget(
                whitepoint=whitepoint,
                whitepoint_x=wp_xy[0],
                whitepoint_y=wp_xy[1],
                luminance=float(self.auto_luminance_spin.value()),
                gamma=float(self.auto_gamma_combo.currentText()),
                gamut=self.auto_gamut_combo.currentText(),
            )

            self.auto_log.appendPlainText("=" * 50)
            self.auto_log.appendPlainText("SENSORLESS HARDWARE CALIBRATION")
            self.auto_log.appendPlainText("=" * 50)
            self.auto_log.appendPlainText("")
            self.auto_log.appendPlainText("Using Newton-Raphson optimization with")
            self.auto_log.appendPlainText("panel characterization database for")
            self.auto_log.appendPlainText("scientifically accurate calibration.")
            self.auto_log.appendPlainText("")

            # Show panel info
            if engine._panel_profile:
                panel = engine._panel_profile
                self.auto_log.appendPlainText(f"Panel: {panel.manufacturer} {panel.model_pattern.split('|')[0]}")
                self.auto_log.appendPlainText(f"Type: {panel.panel_type}")
            if engine._edid_colorimetry:
                edid = engine._edid_colorimetry
                self.auto_log.appendPlainText(f"EDID CCT: {edid['cct']}K")
            self.auto_log.appendPlainText("")

            # Run calibration
            result = engine.calibrate(target, output_dir=None)

            self.auto_progress.setValue(100)

            # Log all messages
            for msg in result.messages:
                self.auto_log.appendPlainText(msg)

            if result.success:
                # Determine accuracy rating
                if result.estimated_delta_e_white < 1.0:
                    rating = "REFERENCE GRADE"
                    rating_color = COLORS["success"]
                elif result.estimated_delta_e_white < 2.0:
                    rating = "PROFESSIONAL GRADE"
                    rating_color = COLORS["success"]
                elif result.estimated_delta_e_white < 3.0:
                    rating = "PHOTO EDITING GRADE"
                    rating_color = COLORS["warning"]
                else:
                    rating = "GENERAL USE"
                    rating_color = COLORS["warning"]

                self.auto_results.setText(
                    f"CALIBRATION COMPLETE!\n\n"
                    f"Accuracy: {rating}\n"
                    f"White Point Delta E: {result.estimated_delta_e_white:.3f}\n"
                    f"Grayscale Delta E: {result.estimated_delta_e_gray:.2f}\n"
                    f"Estimated CCT: {result.estimated_cct}K\n\n"
                    f"Applied Settings:\n"
                    f"  Brightness: {result.brightness}\n"
                    f"  RGB Gain: R={result.red_gain}, G={result.green_gain}, B={result.blue_gain}"
                )
                self.auto_results.setStyleSheet(f"color: {rating_color}; padding: 8px;")
            else:
                self.auto_results.setText("Calibration failed")
                self.auto_results.setStyleSheet(f"color: {COLORS['error']}; padding: 8px;")

            self._read_current_values()

        except Exception as e:
            import traceback

            self.auto_log.appendPlainText(f"ERROR: {e}")
            self.auto_log.appendPlainText(traceback.format_exc())
            self.auto_results.setText(f"Error: {e}")

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
        """Initialize DDC/CI controller and enumerate monitors."""
        try:
            from calibrate_pro.hardware.ddc_ci import DDCCIController

            self.ddc_controller = DDCCIController()

            if not self.ddc_controller.available:
                self.status_label.setText(
                    "\u274c DDC/CI is not available on this system. Monitor hardware control requires DDC/CI support."
                )
                self.status_label.setStyleSheet(f"color: {COLORS['error']}; padding: 8px;")
                return

            self._refresh_monitors()

        except Exception as e:
            self.status_label.setText(f"\u274c Failed to initialize DDC/CI: {e}")
            self.status_label.setStyleSheet(f"color: {COLORS['error']}; padding: 8px;")

    def _refresh_monitors(self):
        """Refresh the list of DDC/CI capable monitors."""
        if not self.ddc_controller or not self.ddc_controller.available:
            return

        self.monitor_combo.clear()
        self.monitors = self.ddc_controller.enumerate_monitors()

        if not self.monitors:
            self.status_label.setText(
                "\u26a0\ufe0f No DDC/CI capable monitors found. "
                "Some monitors don't support DDC/CI, or it may be disabled in monitor settings."
            )
            self.status_label.setStyleSheet(f"color: {COLORS['warning']}; padding: 8px;")
            return

        for i, monitor in enumerate(self.monitors):
            name = monitor.get("name", f"Monitor {i + 1}")
            caps = monitor.get("capabilities")
            rgb_support = "\u2713 RGB" if caps and caps.has_rgb_gain else "\u25cb Basic"
            self.monitor_combo.addItem(f"{name} [{rgb_support}]")

        self.status_label.setText(
            f"\u2713 Found {len(self.monitors)} DDC/CI monitor(s). Adjust sliders to see live changes on your display."
        )
        self.status_label.setStyleSheet(f"color: {COLORS['success']}; padding: 8px;")

        if self.monitors:
            self._on_monitor_changed(0)

    def _on_monitor_changed(self, index: int):
        """Handle monitor selection change."""
        if index < 0 or index >= len(self.monitors):
            return

        self.current_monitor = self.monitors[index]
        caps = self.current_monitor.get("capabilities")

        # Track supported features for this monitor
        self._supported_features = {
            "brightness": False,
            "contrast": False,
            "rgb_gain": False,
            "rgb_black": False,
        }

        if caps:
            cap_text = []
            supported_unsupported = []

            # Check brightness (VCP 0x10)
            if 0x10 in caps.supported_vcp_codes:
                cap_text.append("Brightness \u2713")
                self._supported_features["brightness"] = True
            else:
                supported_unsupported.append("Brightness \u2717")

            # Check contrast (VCP 0x12)
            if 0x12 in caps.supported_vcp_codes:
                cap_text.append("Contrast \u2713")
                self._supported_features["contrast"] = True
            else:
                supported_unsupported.append("Contrast \u2717")

            # Check RGB Gain
            if caps.has_rgb_gain:
                cap_text.append("RGB Gain \u2713")
                self._supported_features["rgb_gain"] = True
            else:
                supported_unsupported.append("RGB Gain \u2717")

            # Check RGB Black Level
            if caps.has_rgb_black_level:
                cap_text.append("RGB Black Level \u2713")
                self._supported_features["rgb_black"] = True
            else:
                supported_unsupported.append("RGB Black \u2717")

            status = ", ".join(cap_text) if cap_text else "None"
            if supported_unsupported:
                status += f" | Not supported: {', '.join(supported_unsupported)}"
            self.capabilities_label.setText(f"Capabilities: {status}")
        else:
            self.capabilities_label.setText("Capabilities: Could not query capabilities")

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
        """Read current DDC/CI values from the selected monitor."""
        if not self.ddc_controller or not self.current_monitor:
            return

        self._updating_sliders = True

        try:
            settings = self.ddc_controller.get_settings(self.current_monitor)

            if settings.brightness > 0:
                self.brightness_slider["slider"].setValue(settings.brightness)
            if settings.contrast > 0:
                self.contrast_slider["slider"].setValue(settings.contrast)
            if settings.red_gain > 0:
                self.red_gain_slider["slider"].setValue(settings.red_gain)
            if settings.green_gain > 0:
                self.green_gain_slider["slider"].setValue(settings.green_gain)
            if settings.blue_gain > 0:
                self.blue_gain_slider["slider"].setValue(settings.blue_gain)
            if settings.red_black_level > 0:
                self.red_black_slider["slider"].setValue(settings.red_black_level)
            if settings.green_black_level > 0:
                self.green_black_slider["slider"].setValue(settings.green_black_level)
            if settings.blue_black_level > 0:
                self.blue_black_slider["slider"].setValue(settings.blue_black_level)

        except Exception as e:
            self.status_label.setText(f"\u26a0\ufe0f Error reading values: {e}")

        self._updating_sliders = False

    def _send_ddc_value(self, setting_name: str, value: int):
        """Send a DDC/CI command to update a monitor setting."""
        if not self.ddc_controller or not self.current_monitor:
            return

        try:
            from calibrate_pro.hardware.ddc_ci import VCPCode

            code_map = {
                "Brightness": VCPCode.BRIGHTNESS,
                "Contrast": VCPCode.CONTRAST,
                "Red Gain": VCPCode.RED_GAIN,
                "Green Gain": VCPCode.GREEN_GAIN,
                "Blue Gain": VCPCode.BLUE_GAIN,
                "Red Black": VCPCode.RED_BLACK_LEVEL,
                "Green Black": VCPCode.GREEN_BLACK_LEVEL,
                "Blue Black": VCPCode.BLUE_BLACK_LEVEL,
            }

            vcp_code = code_map.get(setting_name)
            if vcp_code:
                success = self.ddc_controller.set_vcp(self.current_monitor, vcp_code, value)
                if success:
                    self.status_label.setText(f"\u2713 Set {setting_name} to {value}")
                    self.status_label.setStyleSheet(f"color: {COLORS['success']}; padding: 8px;")
                else:
                    self.status_label.setText(f"\u26a0\ufe0f Failed to set {setting_name}")
                    self.status_label.setStyleSheet(f"color: {COLORS['warning']}; padding: 8px;")

        except Exception as e:
            self.status_label.setText(f"\u26a0\ufe0f Error: {e}")
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

        # Apply all values
        if self.ddc_controller and self.current_monitor:
            self._send_ddc_value("Brightness", 50)
            self._send_ddc_value("Contrast", 50)
            self._send_ddc_value("Red Gain", 100)
            self._send_ddc_value("Green Gain", 100)
            self._send_ddc_value("Blue Gain", 100)

    def _test_ddc_connection(self):
        """Test DDC/CI by visibly flashing brightness."""
        if not self.ddc_controller or not self.current_monitor:
            QMessageBox.warning(self, "No Monitor", "No DDC/CI capable monitor is selected.")
            return

        # Check if brightness is supported
        if not self._supported_features.get("brightness", False):
            QMessageBox.warning(
                self,
                "Brightness Not Supported",
                "This monitor does not support brightness control via DDC/CI.\n\n"
                "DDC/CI control may not work on this monitor.\n"
                "Many monitors have DDC/CI disabled by default - check your monitor's OSD settings.",
            )
            return

        try:
            from calibrate_pro.hardware.ddc_ci import VCPCode

            # Get current brightness
            settings = self.ddc_controller.get_settings(self.current_monitor)
            original_brightness = settings.brightness if settings.brightness > 0 else 100

            self.status_label.setText("Testing DDC/CI... Watch for brightness changes!")
            self.status_label.setStyleSheet(f"color: {COLORS['accent']}; padding: 8px;")
            QApplication.processEvents()

            # Flash sequence: dim -> bright -> original
            test_sequence = [
                (30, "Dimming to 30%..."),
                (100, "Brightening to 100%..."),
                (original_brightness, f"Restoring to {original_brightness}%..."),
            ]

            for brightness, msg in test_sequence:
                self.status_label.setText(f"Testing: {msg}")
                QApplication.processEvents()

                success = self.ddc_controller.set_vcp(self.current_monitor, VCPCode.BRIGHTNESS, brightness)

                if not success:
                    QMessageBox.warning(
                        self,
                        "DDC/CI Test Failed",
                        f"Failed to set brightness to {brightness}%.\n\n"
                        "DDC/CI commands are being rejected by the monitor.\n"
                        "This could mean:\n"
                        "\u2022 DDC/CI is disabled in monitor OSD settings\n"
                        "\u2022 Monitor doesn't fully support DDC/CI\n"
                        "\u2022 Cable doesn't support DDC/CI (use HDMI or DisplayPort)\n"
                        "\u2022 GPU driver issue",
                    )
                    return

                time.sleep(0.8)  # Visible delay

            self.status_label.setText("\u2713 DDC/CI test complete! If you saw brightness changes, DDC is working.")
            self.status_label.setStyleSheet(f"color: {COLORS['success']}; padding: 8px;")

            QMessageBox.information(
                self,
                "DDC/CI Test",
                "Did you see the screen brightness change?\n\n"
                "YES - DDC/CI is working correctly.\n"
                "NO - DDC/CI is not working. Check:\n"
                "\u2022 Monitor OSD: Enable DDC/CI option\n"
                "\u2022 Use HDMI or DisplayPort (not VGA)\n"
                "\u2022 Some monitors ignore DDC brightness commands",
            )

        except Exception as e:
            self.status_label.setText(f"\u274c Test failed: {e}")
            self.status_label.setStyleSheet(f"color: {COLORS['error']}; padding: 8px;")

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
        """Scan all VCP codes to discover monitor capabilities."""
        if not self.ddc_controller or not self.current_monitor:
            QMessageBox.warning(self, "No Monitor", "No DDC/CI monitor selected.")
            return

        self.scan_btn.setEnabled(False)
        self.scan_btn.setText("Scanning...")
        self.vcp_table.setRowCount(0)
        self._discovered_vcp_codes = {}

        # Import VCP_DESCRIPTIONS for code names
        try:
            from calibrate_pro.hardware.ddc_ci import VCP_DESCRIPTIONS
        except ImportError:
            VCP_DESCRIPTIONS = {}

        def update_progress(code, total):
            self.scan_progress.setValue(code)
            self.scan_progress.setFormat(f"Scanning 0x{code:02X} ({code}/{total})")
            QApplication.processEvents()

        try:
            # Perform the scan
            self._discovered_vcp_codes = self.ddc_controller.scan_all_vcp_codes(
                self.current_monitor, progress_callback=update_progress
            )

            # Populate table
            self.vcp_table.setRowCount(len(self._discovered_vcp_codes))

            for row, (code, (current, maximum)) in enumerate(sorted(self._discovered_vcp_codes.items())):
                # Code column
                code_item = QTableWidgetItem(f"0x{code:02X}")
                code_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.vcp_table.setItem(row, 0, code_item)

                # Name column
                if code in VCP_DESCRIPTIONS:
                    name, desc = VCP_DESCRIPTIONS[code]
                    name_item = QTableWidgetItem(f"{name}")
                    name_item.setToolTip(desc)
                else:
                    name_item = QTableWidgetItem("Unknown")
                self.vcp_table.setItem(row, 1, name_item)

                # Current value column
                current_item = QTableWidgetItem(str(current))
                current_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.vcp_table.setItem(row, 2, current_item)

                # Maximum value column
                max_item = QTableWidgetItem(str(maximum))
                max_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.vcp_table.setItem(row, 3, max_item)

                # Actions column - Add a "Test" button
                test_btn = QPushButton("Test")
                test_btn.setMaximumWidth(60)
                test_btn.clicked.connect(lambda checked, c=code, m=maximum: self._test_vcp_code(c, m))
                self.vcp_table.setCellWidget(row, 4, test_btn)

            self.scan_progress.setValue(256)
            self.scan_progress.setFormat("Scan complete")
            self.scan_summary.setText(
                f"\u2713 Found {len(self._discovered_vcp_codes)} supported VCP codes on this monitor."
            )
            self.scan_summary.setStyleSheet(f"color: {COLORS['success']}; padding: 8px;")

        except Exception as e:
            self.scan_summary.setText(f"\u274c Scan failed: {e}")
            self.scan_summary.setStyleSheet(f"color: {COLORS['error']}; padding: 8px;")

        finally:
            self.scan_btn.setEnabled(True)
            self.scan_btn.setText("Scan All VCP Codes")

    def _test_vcp_code(self, code: int, maximum: int):
        """Test a specific VCP code by toggling its value."""
        if not self.ddc_controller or not self.current_monitor:
            return

        try:
            # Read current
            current, _ = self.ddc_controller.get_vcp(self.current_monitor, code)

            # Try a different value
            if maximum > 0:
                test_value = maximum if current < maximum // 2 else 0
            else:
                test_value = 50 if current != 50 else 0

            success, msg = self.ddc_controller.try_set_vcp(self.current_monitor, code, test_value)

            if success:
                QMessageBox.information(
                    self,
                    "VCP Test",
                    f"VCP 0x{code:02X}: {msg}\n\nIf you saw a change on your monitor, this code is working!",
                )
            else:
                QMessageBox.warning(
                    self, "VCP Test", f"VCP 0x{code:02X}: {msg}\n\nThis code may be read-only or not fully supported."
                )

            # Restore original value
            self.ddc_controller.set_vcp(self.current_monitor, code, current)

        except Exception as e:
            QMessageBox.warning(self, "VCP Test Error", f"Error testing VCP 0x{code:02X}: {e}")

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
        """Read a raw VCP code value."""
        if not self.ddc_controller or not self.current_monitor:
            self.read_result.setText("Result: No monitor selected")
            return

        try:
            code = self._parse_vcp_code(self.read_code_input.text())

            current, maximum = self.ddc_controller.get_vcp(self.current_monitor, code)
            self.read_result.setText(f"Result: Current={current}, Max={maximum}")
            self.read_result.setStyleSheet(f"color: {COLORS['success']};")

        except ValueError:
            self.read_result.setText("Result: Invalid code format")
            self.read_result.setStyleSheet(f"color: {COLORS['error']};")
        except Exception as e:
            self.read_result.setText(f"Result: Error - {e}")
            self.read_result.setStyleSheet(f"color: {COLORS['error']};")

    def _write_raw_vcp(self):
        """Write a raw VCP code value."""
        if not self.ddc_controller or not self.current_monitor:
            self.write_result.setText("Result: No monitor selected")
            return

        try:
            code = self._parse_vcp_code(self.write_code_input.text())
            value = int(self.write_value_input.text().strip())

            success, msg = self.ddc_controller.try_set_vcp(self.current_monitor, code, value)

            if success:
                self.write_result.setText(f"Result: {msg}")
                self.write_result.setStyleSheet(f"color: {COLORS['success']};")
            else:
                self.write_result.setText(f"Result: {msg}")
                self.write_result.setStyleSheet(f"color: {COLORS['warning']};")

        except ValueError:
            self.write_result.setText("Result: Invalid code or value format")
            self.write_result.setStyleSheet(f"color: {COLORS['error']};")
        except Exception as e:
            self.write_result.setText(f"Result: Error - {e}")
            self.write_result.setStyleSheet(f"color: {COLORS['error']};")

    # =========================================================================
    # Preset Control Methods
    # =========================================================================

    def _apply_color_preset(self):
        """Apply the selected color temperature preset."""
        if not self.ddc_controller or not self.current_monitor:
            self.preset_status.setText("Status: No monitor selected")
            return

        try:
            from calibrate_pro.hardware.ddc_ci import VCPCode

            # Extract value from combo selection (format: "N - Description")
            selection = self.color_preset_combo.currentText()
            value = int(selection.split(" - ")[0])

            success, msg = self.ddc_controller.try_set_vcp(self.current_monitor, VCPCode.COLOR_PRESET, value)

            if success:
                self.preset_status.setText(f"Status: \u2713 {msg}")
                self.preset_status.setStyleSheet(f"color: {COLORS['success']};")
            else:
                self.preset_status.setText(f"Status: \u26a0 {msg}")
                self.preset_status.setStyleSheet(f"color: {COLORS['warning']};")

        except Exception as e:
            self.preset_status.setText(f"Status: \u274c Error - {e}")
            self.preset_status.setStyleSheet(f"color: {COLORS['error']};")

    def _read_color_preset(self):
        """Read the current color temperature preset."""
        if not self.ddc_controller or not self.current_monitor:
            self.preset_status.setText("Status: No monitor selected")
            return

        try:
            from calibrate_pro.hardware.ddc_ci import VCPCode

            current, maximum = self.ddc_controller.get_vcp(self.current_monitor, VCPCode.COLOR_PRESET)
            self.preset_status.setText(f"Status: Current preset = {current} (max: {maximum})")
            self.preset_status.setStyleSheet(f"color: {COLORS['text_secondary']};")

            # Try to select the current preset in the combo
            for i in range(self.color_preset_combo.count()):
                if self.color_preset_combo.itemText(i).startswith(f"{current} "):
                    self.color_preset_combo.setCurrentIndex(i)
                    break

        except Exception as e:
            self.preset_status.setText(f"Status: \u274c Cannot read - {e}")
            self.preset_status.setStyleSheet(f"color: {COLORS['error']};")

    def _apply_image_mode(self):
        """Apply the selected image mode preset."""
        if not self.ddc_controller or not self.current_monitor:
            self.image_mode_status.setText("Status: No monitor selected")
            return

        try:
            from calibrate_pro.hardware.ddc_ci import VCPCode

            selection = self.image_mode_combo.currentText()
            value = int(selection.split(" - ")[0])

            success, msg = self.ddc_controller.try_set_vcp(self.current_monitor, VCPCode.IMAGE_MODE, value)

            if success:
                self.image_mode_status.setText(f"Status: \u2713 {msg}")
                self.image_mode_status.setStyleSheet(f"color: {COLORS['success']};")
            else:
                self.image_mode_status.setText(f"Status: \u26a0 {msg}")
                self.image_mode_status.setStyleSheet(f"color: {COLORS['warning']};")

        except Exception as e:
            self.image_mode_status.setText(f"Status: \u274c Error - {e}")
            self.image_mode_status.setStyleSheet(f"color: {COLORS['error']};")

    def _read_image_mode(self):
        """Read the current image mode."""
        if not self.ddc_controller or not self.current_monitor:
            self.image_mode_status.setText("Status: No monitor selected")
            return

        try:
            from calibrate_pro.hardware.ddc_ci import VCPCode

            current, maximum = self.ddc_controller.get_vcp(self.current_monitor, VCPCode.IMAGE_MODE)
            self.image_mode_status.setText(f"Status: Current mode = {current} (max: {maximum})")
            self.image_mode_status.setStyleSheet(f"color: {COLORS['text_secondary']};")

            # Try to select the current mode in the combo
            for i in range(self.image_mode_combo.count()):
                if self.image_mode_combo.itemText(i).startswith(f"{current} "):
                    self.image_mode_combo.setCurrentIndex(i)
                    break

        except Exception as e:
            self.image_mode_status.setText(f"Status: \u274c Cannot read - {e}")
            self.image_mode_status.setStyleSheet(f"color: {COLORS['error']};")

    def _apply_gamma_preset(self):
        """Apply the selected gamma preset."""
        if not self.ddc_controller or not self.current_monitor:
            self.gamma_status.setText("Status: No monitor selected")
            return

        try:
            from calibrate_pro.hardware.ddc_ci import VCPCode

            selection = self.gamma_combo.currentText()
            value = int(selection.split(" - ")[0])

            success, msg = self.ddc_controller.try_set_vcp(self.current_monitor, VCPCode.GAMMA, value)

            if success:
                self.gamma_status.setText(f"Status: \u2713 {msg}")
                self.gamma_status.setStyleSheet(f"color: {COLORS['success']};")
            else:
                self.gamma_status.setText(f"Status: \u26a0 {msg}")
                self.gamma_status.setStyleSheet(f"color: {COLORS['warning']};")

        except Exception as e:
            self.gamma_status.setText(f"Status: \u274c Error - {e}")
            self.gamma_status.setStyleSheet(f"color: {COLORS['error']};")

    def _read_gamma_preset(self):
        """Read the current gamma preset."""
        if not self.ddc_controller or not self.current_monitor:
            self.gamma_status.setText("Status: No monitor selected")
            return

        try:
            from calibrate_pro.hardware.ddc_ci import VCPCode

            current, maximum = self.ddc_controller.get_vcp(self.current_monitor, VCPCode.GAMMA)
            self.gamma_status.setText(f"Status: Current gamma = {current} (max: {maximum})")
            self.gamma_status.setStyleSheet(f"color: {COLORS['text_secondary']};")

            # Try to select the current gamma in the combo
            for i in range(self.gamma_combo.count()):
                if self.gamma_combo.itemText(i).startswith(f"{current} "):
                    self.gamma_combo.setCurrentIndex(i)
                    break

        except Exception as e:
            self.gamma_status.setText(f"Status: \u274c Cannot read - {e}")
            self.gamma_status.setStyleSheet(f"color: {COLORS['error']};")
