"""
Calibrate Pro — DDC Control Page

Hardware DDC/CI monitor control: brightness, contrast, RGB gain, RGB offset.
Communicates directly with the display over the DDC/CI protocol.
"""

from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from calibrate_pro.gui.app import C, Card, Heading, StatusDot

# Slider Stylesheet

SLIDER_STYLE = f"""
    QSlider::groove:horizontal {{
        background: {C.BORDER}; height: 6px; border-radius: 3px;
    }}
    QSlider::handle:horizontal {{
        background: {C.ACCENT}; width: 16px; height: 16px;
        margin: -5px 0; border-radius: 8px;
    }}
    QSlider::sub-page:horizontal {{
        background: {C.ACCENT}; border-radius: 3px;
    }}
"""

RED_SLIDER_STYLE = f"""
    QSlider::groove:horizontal {{
        background: {C.BORDER}; height: 6px; border-radius: 3px;
    }}
    QSlider::handle:horizontal {{
        background: {C.RED}; width: 16px; height: 16px;
        margin: -5px 0; border-radius: 8px;
    }}
    QSlider::sub-page:horizontal {{
        background: {C.RED}; border-radius: 3px;
    }}
"""

GREEN_SLIDER_STYLE = f"""
    QSlider::groove:horizontal {{
        background: {C.BORDER}; height: 6px; border-radius: 3px;
    }}
    QSlider::handle:horizontal {{
        background: {C.GREEN}; width: 16px; height: 16px;
        margin: -5px 0; border-radius: 8px;
    }}
    QSlider::sub-page:horizontal {{
        background: {C.GREEN}; border-radius: 3px;
    }}
"""

BLUE_SLIDER_STYLE = f"""
    QSlider::groove:horizontal {{
        background: {C.BORDER}; height: 6px; border-radius: 3px;
    }}
    QSlider::handle:horizontal {{
        background: {C.CYAN}; width: 16px; height: 16px;
        margin: -5px 0; border-radius: 8px;
    }}
    QSlider::sub-page:horizontal {{
        background: {C.CYAN}; border-radius: 3px;
    }}
"""


# Helper: labeled slider row

def _make_slider_row(
    label_text: str,
    style: str,
    min_val: int = 0,
    max_val: int = 100,
    initial: int = 50,
    label_color: str = C.TEXT,
):
    """Create a horizontal row: label — slider — value label."""
    row = QHBoxLayout()
    row.setSpacing(12)

    label = QLabel(label_text)
    label.setFixedWidth(80)
    label.setStyleSheet(f"font-size: 12px; font-weight: 500; color: {label_color};")
    row.addWidget(label)

    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setMinimum(min_val)
    slider.setMaximum(max_val)
    slider.setValue(initial)
    slider.setStyleSheet(style)
    slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    row.addWidget(slider, stretch=1)

    value_label = QLabel(str(initial))
    value_label.setFixedWidth(36)
    value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    value_label.setStyleSheet(f"font-size: 12px; color: {C.TEXT2};")
    row.addWidget(value_label)

    # Wire up the value display
    slider.valueChanged.connect(lambda v: value_label.setText(str(v)))

    return row, slider, value_label


# DDC Control Page

class DDCControlPage(QWidget):
    """DDC/CI hardware control page."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._controller = None
        self._monitors: list[dict[str, Any]] = []
        self._current_monitor: dict[str, Any] | None = None
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(20)

        # --- Header ---
        layout.addWidget(Heading("DDC/CI Control"))

        # --- Display selector ---
        selector_card, selector_layout = Card.with_layout(
            QHBoxLayout, margins=(16, 12, 16, 12), spacing=12,
        )

        sel_label = QLabel("Display")
        sel_label.setStyleSheet(f"font-size: 12px; font-weight: 500; color: {C.TEXT};")
        selector_layout.addWidget(sel_label)

        self._display_combo = QComboBox()
        self._display_combo.setMinimumWidth(300)
        self._display_combo.addItem("Detecting displays...")
        self._display_combo.currentIndexChanged.connect(self._on_display_changed)
        selector_layout.addWidget(self._display_combo, stretch=1)

        self._status_dot = StatusDot(C.TEXT3, 10)
        selector_layout.addWidget(self._status_dot)

        layout.addWidget(selector_card)

        # --- Brightness & Contrast ---
        bc_card, bc_layout = Card.with_layout(spacing=14)

        bc_heading = QLabel("Brightness & Contrast")
        bc_heading.setStyleSheet(
            f"font-size: 13px; font-weight: 500; color: {C.TEXT};"
        )
        bc_layout.addWidget(bc_heading)

        row, self._brightness_slider, _ = _make_slider_row(
            "Brightness", SLIDER_STYLE, initial=50,
        )
        self._brightness_slider.valueChanged.connect(self._set_brightness)
        bc_layout.addLayout(row)

        row, self._contrast_slider, _ = _make_slider_row(
            "Contrast", SLIDER_STYLE, initial=50,
        )
        self._contrast_slider.valueChanged.connect(self._set_contrast)
        bc_layout.addLayout(row)

        layout.addWidget(bc_card)

        # --- RGB Gain ---
        gain_card, gain_layout = Card.with_layout(spacing=14)

        gain_heading = QLabel("RGB Gain (highlights)")
        gain_heading.setStyleSheet(
            f"font-size: 13px; font-weight: 500; color: {C.TEXT};"
        )
        gain_layout.addWidget(gain_heading)

        row, self._red_gain_slider, _ = _make_slider_row(
            "Red", RED_SLIDER_STYLE, initial=50, label_color=C.RED,
        )
        self._red_gain_slider.valueChanged.connect(
            lambda v: self._set_vcp_safe("RED_GAIN", v)
        )
        gain_layout.addLayout(row)

        row, self._green_gain_slider, _ = _make_slider_row(
            "Green", GREEN_SLIDER_STYLE, initial=50, label_color=C.GREEN,
        )
        self._green_gain_slider.valueChanged.connect(
            lambda v: self._set_vcp_safe("GREEN_GAIN", v)
        )
        gain_layout.addLayout(row)

        row, self._blue_gain_slider, _ = _make_slider_row(
            "Blue", BLUE_SLIDER_STYLE, initial=50, label_color=C.CYAN,
        )
        self._blue_gain_slider.valueChanged.connect(
            lambda v: self._set_vcp_safe("BLUE_GAIN", v)
        )
        gain_layout.addLayout(row)

        layout.addWidget(gain_card)

        # --- RGB Offset (Black Level) ---
        offset_card, offset_layout = Card.with_layout(spacing=14)

        offset_heading = QLabel("RGB Offset (shadows)")
        offset_heading.setStyleSheet(
            f"font-size: 13px; font-weight: 500; color: {C.TEXT};"
        )
        offset_layout.addWidget(offset_heading)

        row, self._red_offset_slider, _ = _make_slider_row(
            "Red", RED_SLIDER_STYLE, initial=50, label_color=C.RED,
        )
        self._red_offset_slider.valueChanged.connect(
            lambda v: self._set_vcp_safe("RED_BLACK_LEVEL", v)
        )
        offset_layout.addLayout(row)

        row, self._green_offset_slider, _ = _make_slider_row(
            "Green", GREEN_SLIDER_STYLE, initial=50, label_color=C.GREEN,
        )
        self._green_offset_slider.valueChanged.connect(
            lambda v: self._set_vcp_safe("GREEN_BLACK_LEVEL", v)
        )
        offset_layout.addLayout(row)

        row, self._blue_offset_slider, _ = _make_slider_row(
            "Blue", BLUE_SLIDER_STYLE, initial=50, label_color=C.CYAN,
        )
        self._blue_offset_slider.valueChanged.connect(
            lambda v: self._set_vcp_safe("BLUE_BLACK_LEVEL", v)
        )
        offset_layout.addLayout(row)

        layout.addWidget(offset_card)

        # --- Display Mode & Gamma ---
        mode_card, mode_layout = Card.with_layout(spacing=14)

        mode_heading = QLabel("Display Mode")
        mode_heading.setStyleSheet(
            f"font-size: 13px; font-weight: 500; color: {C.TEXT};"
        )
        mode_layout.addWidget(mode_heading)

        combo_style = (
            f"QComboBox {{ background: {C.SURFACE2}; border: 1px solid {C.BORDER}; "
            f"border-radius: 6px; padding: 6px 12px; color: {C.TEXT}; min-width: 160px; }}"
            f"QComboBox::drop-down {{ border: none; width: 24px; }}"
            f"QComboBox QAbstractItemView {{ background: {C.SURFACE}; "
            f"border: 1px solid {C.BORDER}; color: {C.TEXT}; "
            f"selection-background-color: {C.ACCENT}; }}"
        )

        # Picture mode combo
        pic_row = QHBoxLayout()
        pic_row.setSpacing(8)
        pic_label = QLabel("Picture Mode")
        pic_label.setFixedWidth(100)
        pic_label.setStyleSheet(f"font-size: 12px; color: {C.TEXT2};")
        pic_row.addWidget(pic_label)
        self._picture_mode_combo = QComboBox()
        self._picture_mode_combo.addItems([
            "Standard", "Custom 1", "Custom 2", "Custom 3",
            "sRGB", "Cinema", "Game", "FPS", "RTS",
            "Vivid", "Eco", "User", "Filmmaker",
        ])
        self._picture_mode_combo.setStyleSheet(combo_style)
        self._picture_mode_combo.currentIndexChanged.connect(
            lambda idx: self._set_vcp_safe("IMAGE_MODE", idx)
        )
        pic_row.addWidget(self._picture_mode_combo, stretch=1)
        mode_layout.addLayout(pic_row)

        # Color preset combo
        color_row = QHBoxLayout()
        color_row.setSpacing(8)
        color_label = QLabel("Color Preset")
        color_label.setFixedWidth(100)
        color_label.setStyleSheet(f"font-size: 12px; color: {C.TEXT2};")
        color_row.addWidget(color_label)
        self._color_preset_combo = QComboBox()
        self._color_preset_combo.addItems([
            "Native", "sRGB", "4000K", "5000K", "5500K",
            "6500K", "7500K", "8200K", "9300K", "11500K",
            "User 1", "User 2", "User 3",
        ])
        self._color_preset_combo.setStyleSheet(combo_style)
        self._color_preset_combo.currentIndexChanged.connect(
            lambda idx: self._set_vcp_safe("COLOR_PRESET", idx)
        )
        color_row.addWidget(self._color_preset_combo, stretch=1)
        mode_layout.addLayout(color_row)

        # Gamma slider
        gamma_row, self._gamma_slider, _ = _make_slider_row(
            "Gamma", SLIDER_STYLE, initial=22, label_color=C.TEXT,
        )
        self._gamma_slider.setRange(10, 30)
        self._gamma_slider.setValue(22)
        self._gamma_slider.setToolTip("Gamma value x10 (22 = gamma 2.2)")
        self._gamma_slider.valueChanged.connect(
            lambda v: self._set_vcp_safe("GAMMA", v)
        )
        mode_layout.addLayout(gamma_row)

        # Factory reset button (specific resets)
        reset_color_btn = QPushButton("Reset Factory Color")
        reset_color_btn.setFixedHeight(30)
        reset_color_btn.setStyleSheet(
            f"QPushButton {{ font-size: 11px; padding: 4px 16px; "
            f"background: {C.SURFACE}; border: 1px solid {C.BORDER}; border-radius: 8px; "
            f"color: {C.TEXT2}; }}"
            f"QPushButton:hover {{ border-color: {C.ACCENT}; }}"
        )
        reset_color_btn.setToolTip("VCP 0x0A: Restore factory color settings only")
        reset_color_btn.clicked.connect(
            lambda: self._set_vcp_safe("RESTORE_FACTORY_COLOR", 1)
        )
        mode_layout.addWidget(reset_color_btn)

        layout.addWidget(mode_card)

        # --- Action buttons ---
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addStretch()

        read_btn = QPushButton("Read Current")
        read_btn.setFixedHeight(36)
        read_btn.setProperty("primary", True)
        read_btn.setStyleSheet(
            f"QPushButton {{ background: {C.ACCENT}; color: white; "
            f"border: none; border-radius: 10px; font-size: 12px; "
            f"font-weight: 600; padding: 6px 22px; }}"
            f"QPushButton:hover {{ background: {C.ACCENT_HI}; }}"
        )
        read_btn.clicked.connect(self._read_current)
        btn_row.addWidget(read_btn)

        reset_btn = QPushButton("Reset to Default")
        reset_btn.setFixedHeight(36)
        reset_btn.setStyleSheet(
            f"QPushButton {{ background: {C.SURFACE}; border: 1px solid {C.BORDER}; "
            f"border-radius: 10px; font-size: 12px; padding: 6px 22px; "
            f"color: {C.RED}; }}"
            f"QPushButton:hover {{ border-color: {C.RED}; background: {C.SURFACE2}; }}"
        )
        reset_btn.clicked.connect(self._reset_defaults)
        btn_row.addWidget(reset_btn)

        layout.addLayout(btn_row)

        # Status label for DDC feedback
        self._status_label = QLabel("")
        self._status_label.setStyleSheet(f"font-size: 11px; color: {C.TEXT3};")
        layout.addWidget(self._status_label)

        # --- Advanced: Raw VCP Read/Write ---
        adv_card, adv_layout = Card.with_layout(spacing=14)

        adv_heading = QLabel("Advanced \u2014 Raw VCP Read/Write")
        adv_heading.setStyleSheet(
            f"font-size: 13px; font-weight: 500; color: {C.TEXT};"
        )
        adv_layout.addWidget(adv_heading)

        adv_desc = QLabel(
            "Read or write arbitrary VCP codes directly. "
            "Use with caution \u2014 invalid codes may be ignored or cause unexpected behavior."
        )
        adv_desc.setStyleSheet(f"font-size: 11px; color: {C.TEXT3};")
        adv_desc.setWordWrap(True)
        adv_layout.addWidget(adv_desc)

        # VCP Code input row
        code_row = QHBoxLayout()
        code_row.setSpacing(10)

        code_label = QLabel("VCP Code")
        code_label.setFixedWidth(80)
        code_label.setStyleSheet(f"font-size: 12px; font-weight: 500; color: {C.TEXT};")
        code_row.addWidget(code_label)

        self._vcp_code_spin = QSpinBox()
        self._vcp_code_spin.setRange(0x00, 0xFF)
        self._vcp_code_spin.setPrefix("0x")
        self._vcp_code_spin.setDisplayIntegerBase(16)
        self._vcp_code_spin.setValue(0x10)  # Default to brightness
        self._vcp_code_spin.setFixedWidth(100)
        self._vcp_code_spin.setFixedHeight(32)
        self._vcp_code_spin.setStyleSheet(
            f"QSpinBox {{ background: {C.SURFACE2}; border: 1px solid {C.BORDER}; "
            f"border-radius: 6px; padding: 4px 8px; color: {C.TEXT}; font-size: 12px; "
            f"font-family: 'Cascadia Code', 'Consolas', monospace; }}"
            f"QSpinBox::up-button, QSpinBox::down-button {{ width: 16px; }}"
        )
        code_row.addWidget(self._vcp_code_spin)

        self._vcp_read_btn = QPushButton("Read")
        self._vcp_read_btn.setFixedHeight(32)
        self._vcp_read_btn.setFixedWidth(70)
        self._vcp_read_btn.setProperty("primary", True)
        self._vcp_read_btn.setStyleSheet(
            f"QPushButton {{ background: {C.ACCENT}; color: white; "
            f"border: none; border-radius: 10px; font-size: 11px; "
            f"font-weight: 600; padding: 4px 14px; }}"
            f"QPushButton:hover {{ background: {C.ACCENT_HI}; }}"
        )
        self._vcp_read_btn.clicked.connect(self._raw_vcp_read)
        code_row.addWidget(self._vcp_read_btn)

        code_row.addStretch()
        adv_layout.addLayout(code_row)

        # Write row: value spinbox + write button
        write_row = QHBoxLayout()
        write_row.setSpacing(10)

        write_label = QLabel("Value")
        write_label.setFixedWidth(80)
        write_label.setStyleSheet(f"font-size: 12px; font-weight: 500; color: {C.TEXT};")
        write_row.addWidget(write_label)

        self._vcp_value_spin = QSpinBox()
        self._vcp_value_spin.setRange(0, 65535)
        self._vcp_value_spin.setValue(0)
        self._vcp_value_spin.setFixedWidth(100)
        self._vcp_value_spin.setFixedHeight(32)
        self._vcp_value_spin.setStyleSheet(
            f"QSpinBox {{ background: {C.SURFACE2}; border: 1px solid {C.BORDER}; "
            f"border-radius: 6px; padding: 4px 8px; color: {C.TEXT}; font-size: 12px; "
            f"font-family: 'Cascadia Code', 'Consolas', monospace; }}"
            f"QSpinBox::up-button, QSpinBox::down-button {{ width: 16px; }}"
        )
        write_row.addWidget(self._vcp_value_spin)

        self._vcp_write_btn = QPushButton("Write")
        self._vcp_write_btn.setFixedHeight(32)
        self._vcp_write_btn.setFixedWidth(70)
        self._vcp_write_btn.setStyleSheet(
            f"QPushButton {{ background: {C.SURFACE}; border: 1px solid {C.BORDER}; "
            f"border-radius: 10px; font-size: 11px; padding: 4px 14px; "
            f"color: {C.RED}; font-weight: 600; }}"
            f"QPushButton:hover {{ border-color: {C.RED}; background: {C.SURFACE2}; }}"
        )
        self._vcp_write_btn.clicked.connect(self._raw_vcp_write)
        write_row.addWidget(self._vcp_write_btn)

        write_row.addStretch()
        adv_layout.addLayout(write_row)

        # Result label
        self._vcp_result_label = QLabel("")
        self._vcp_result_label.setStyleSheet(
            f"font-size: 11px; color: {C.TEXT2}; "
            f"font-family: 'Cascadia Code', 'Consolas', monospace; "
            f"background: {C.SURFACE2}; border-radius: 6px; padding: 8px 12px;"
        )
        self._vcp_result_label.setWordWrap(True)
        self._vcp_result_label.setMinimumHeight(32)
        self._vcp_result_label.hide()
        adv_layout.addWidget(self._vcp_result_label)

        layout.addWidget(adv_card)

        layout.addStretch()
        scroll.setWidget(content)

        # --- Initialize controller ---
        self._init_controller()

    # Controller & Monitor Management

    def _init_controller(self):
        """Initialize the DDC/CI controller and detect monitors."""
        try:
            from calibrate_pro.hardware.ddc_ci import DDCCIController
            self._controller = DDCCIController()

            if not self._controller.available:
                self._display_combo.clear()
                self._display_combo.addItem("DDC/CI not available on this system")
                self._status_dot.set_color(C.RED)
                return

            self._monitors = self._controller.enumerate_monitors()
            self._display_combo.clear()

            if not self._monitors:
                self._display_combo.addItem("No DDC/CI monitors found")
                self._status_dot.set_color(C.YELLOW)
                return

            for mon in self._monitors:
                name = mon.get("name", "Unknown Monitor")
                self._display_combo.addItem(str(name))

            self._status_dot.set_color(C.GREEN)

            # Auto-select first monitor and read settings
            if self._monitors:
                self._current_monitor = self._monitors[0]
                self._read_current()

        except Exception as e:
            self._display_combo.clear()
            self._display_combo.addItem(f"Error: {e}")
            self._status_dot.set_color(C.RED)

    def _on_display_changed(self, index: int):
        """Handle display selector change."""
        if 0 <= index < len(self._monitors):
            self._current_monitor = self._monitors[index]
            self._read_current()

    # Read / Write VCP

    def _read_current(self):
        """Read all control values from the currently selected monitor."""
        if not self._controller or not self._current_monitor:
            return

        try:

            settings = self._controller.get_settings(self._current_monitor)

            # Block signals while updating sliders to avoid writing back
            for slider, value in [
                (self._brightness_slider, settings.brightness),
                (self._contrast_slider, settings.contrast),
                (self._red_gain_slider, settings.red_gain),
                (self._green_gain_slider, settings.green_gain),
                (self._blue_gain_slider, settings.blue_gain),
                (self._red_offset_slider, settings.red_black_level),
                (self._green_offset_slider, settings.green_black_level),
                (self._blue_offset_slider, settings.blue_black_level),
            ]:
                slider.blockSignals(True)
                slider.setValue(value)
                slider.blockSignals(False)

            self._status_dot.set_color(C.GREEN)

        except Exception as e:
            QMessageBox.warning(
                self, "Read Error",
                f"Failed to read monitor settings:\n{e}"
            )
            self._status_dot.set_color(C.RED)

    def _set_brightness(self, value: int):
        """Set brightness via DDC/CI."""
        self._set_vcp_safe("BRIGHTNESS", value)

    def _set_contrast(self, value: int):
        """Set contrast via DDC/CI."""
        self._set_vcp_safe("CONTRAST", value)

    def _set_vcp_safe(self, code_name: str, value: int):
        """Safely set a VCP code, with error feedback."""
        if not self._controller or not self._current_monitor:
            return

        try:
            from calibrate_pro.hardware.ddc_ci import VCPCode
            code = getattr(VCPCode, code_name)
            self._controller.set_vcp(self._current_monitor, code, value)
        except Exception as e:
            import logging
            logging.getLogger(__name__).debug("DDC set %s=%d failed: %s", code_name, value, e)
            # Show brief status feedback
            if hasattr(self, '_status_label'):
                self._status_label.setText(f"DDC command failed: {code_name}")
                self._status_label.setStyleSheet("font-size: 11px; color: #d08888;")

    def _raw_vcp_read(self):
        """Read a raw VCP code and display the current/max values."""
        if not self._controller or not self._current_monitor:
            self._vcp_result_label.setText("No monitor selected.")
            self._vcp_result_label.setStyleSheet(
                f"font-size: 11px; color: {C.RED}; "
                f"font-family: 'Cascadia Code', 'Consolas', monospace; "
                f"background: {C.SURFACE2}; border-radius: 6px; padding: 8px 12px;"
            )
            self._vcp_result_label.show()
            return

        code = self._vcp_code_spin.value()
        try:
            current, maximum = self._controller.get_vcp(
                self._current_monitor, code
            )
            self._vcp_result_label.setText(
                f"VCP 0x{code:02X}:  current = {current}  |  max = {maximum}"
            )
            self._vcp_result_label.setStyleSheet(
                f"font-size: 11px; color: {C.GREEN}; "
                f"font-family: 'Cascadia Code', 'Consolas', monospace; "
                f"background: {C.SURFACE2}; border-radius: 6px; padding: 8px 12px;"
            )
            # Pre-fill the write value with the current value
            self._vcp_value_spin.setValue(current)
        except Exception as e:
            self._vcp_result_label.setText(
                f"Read VCP 0x{code:02X} failed: {e}"
            )
            self._vcp_result_label.setStyleSheet(
                f"font-size: 11px; color: {C.RED}; "
                f"font-family: 'Cascadia Code', 'Consolas', monospace; "
                f"background: {C.SURFACE2}; border-radius: 6px; padding: 8px 12px;"
            )
        self._vcp_result_label.show()

    def _raw_vcp_write(self):
        """Write a raw VCP value to the selected monitor."""
        if not self._controller or not self._current_monitor:
            self._vcp_result_label.setText("No monitor selected.")
            self._vcp_result_label.setStyleSheet(
                f"font-size: 11px; color: {C.RED}; "
                f"font-family: 'Cascadia Code', 'Consolas', monospace; "
                f"background: {C.SURFACE2}; border-radius: 6px; padding: 8px 12px;"
            )
            self._vcp_result_label.show()
            return

        code = self._vcp_code_spin.value()
        value = self._vcp_value_spin.value()
        try:
            self._controller.set_vcp(self._current_monitor, code, value)
            self._vcp_result_label.setText(
                f"VCP 0x{code:02X} set to {value}  \u2714"
            )
            self._vcp_result_label.setStyleSheet(
                f"font-size: 11px; color: {C.GREEN}; "
                f"font-family: 'Cascadia Code', 'Consolas', monospace; "
                f"background: {C.SURFACE2}; border-radius: 6px; padding: 8px 12px;"
            )
        except Exception as e:
            self._vcp_result_label.setText(
                f"Write VCP 0x{code:02X} = {value} failed: {e}"
            )
            self._vcp_result_label.setStyleSheet(
                f"font-size: 11px; color: {C.RED}; "
                f"font-family: 'Cascadia Code', 'Consolas', monospace; "
                f"background: {C.SURFACE2}; border-radius: 6px; padding: 8px 12px;"
            )
        self._vcp_result_label.show()

    def _reset_defaults(self):
        """Reset all controls to factory defaults."""
        if not self._controller or not self._current_monitor:
            QMessageBox.information(
                self, "No Monitor",
                "No DDC/CI monitor is selected."
            )
            return

        reply = QMessageBox.question(
            self, "Reset to Default",
            "Reset all monitor settings to factory defaults?\n\n"
            "This sends the DDC/CI factory-reset command.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            from calibrate_pro.hardware.ddc_ci import VCPCode
            self._controller.set_vcp(
                self._current_monitor,
                VCPCode.RESTORE_FACTORY_DEFAULTS,
                1,
            )
            # Re-read after reset
            self._read_current()
        except Exception as e:
            QMessageBox.warning(
                self, "Reset Error",
                f"Factory reset failed:\n{e}"
            )
