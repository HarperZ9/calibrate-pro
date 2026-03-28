"""
Software Color Control Page - GPU-Level Gamma Adjustments.

These controls modify the GPU's gamma ramps to adjust colors.
Changes are visible immediately and work on ALL displays (no DDC/CI needed).
"""

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from calibrate_pro.gui.theme import COLORS


class SoftwareColorControlPage(QWidget):
    """
    Software-based color control using GPU gamma ramps.

    This ACTUALLY changes what you see on screen by modifying the
    video signal at the GPU level. Works on ALL displays regardless
    of DDC/CI support.

    Features:
    - Brightness boost (for dark displays)
    - Contrast adjustment
    - RGB balance (white point correction)
    - Real-time preview
    - Save/load settings
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.color_loader = None
        self.current_display = 0
        self.displays = []

        # Current adjustment values
        self._brightness = 1.0      # 0.5 to 2.0 (1.0 = normal)
        self._contrast = 1.0        # 0.5 to 2.0 (1.0 = normal)
        self._gamma = 2.2           # 1.0 to 3.0 (2.2 = sRGB)
        self._red_gain = 1.0        # 0.5 to 1.5 (1.0 = normal)
        self._green_gain = 1.0
        self._blue_gain = 1.0
        self._black_level = 0.0     # 0.0 to 0.1 (lift shadows)

        self._updating = False
        self._setup_ui()
        QTimer.singleShot(300, self._initialize)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        # Header
        header_layout = QHBoxLayout()
        header = QLabel("Software Color Control (GPU Gamma)")
        header.setStyleSheet("font-size: 20px; font-weight: 600;")
        header_layout.addWidget(header)
        header_layout.addStretch()

        refresh_btn = QPushButton("Refresh Displays")
        refresh_btn.clicked.connect(self._refresh_displays)
        header_layout.addWidget(refresh_btn)

        layout.addLayout(header_layout)

        # Info banner
        info_label = QLabel(
            "These controls modify your GPU's gamma ramps to adjust colors.\n"
            "Changes are VISIBLE IMMEDIATELY and work on ALL displays (no DDC/CI needed)."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet(
            f"color: {COLORS['success']}; padding: 12px; "
            f"background-color: rgba(100,255,100,0.1); border-radius: 6px;"
        )
        layout.addWidget(info_label)

        # Display selector
        display_group = QGroupBox("Select Display")
        display_layout = QVBoxLayout(display_group)

        self.display_combo = QComboBox()
        self.display_combo.currentIndexChanged.connect(self._on_display_changed)
        display_layout.addWidget(self.display_combo)

        layout.addWidget(display_group)

        # Scroll area for controls
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(16)

        # Brightness & Contrast
        bc_group = QGroupBox("Brightness & Contrast")
        bc_layout = QVBoxLayout(bc_group)

        bc_info = QLabel(
            "If your display appears too dark, increase Brightness.\n"
            "For a 1000 nit display that's dim, try Brightness 1.5-2.0"
        )
        bc_info.setWordWrap(True)
        bc_info.setStyleSheet(f"color: {COLORS['text_secondary']}; padding: 4px;")
        bc_layout.addWidget(bc_info)

        self.brightness_slider = self._create_float_slider(
            "Brightness", 0.5, 2.0, 1.0,
            "Increases/decreases overall luminance (1.0 = no change)"
        )
        bc_layout.addLayout(self.brightness_slider['layout'])
        self.brightness_slider['slider'].valueChanged.connect(
            lambda v: self._on_slider_changed('brightness', v / 100.0)
        )

        self.contrast_slider = self._create_float_slider(
            "Contrast", 0.5, 2.0, 1.0,
            "Adjusts the difference between dark and light (1.0 = no change)"
        )
        bc_layout.addLayout(self.contrast_slider['layout'])
        self.contrast_slider['slider'].valueChanged.connect(
            lambda v: self._on_slider_changed('contrast', v / 100.0)
        )

        self.gamma_slider = self._create_float_slider(
            "Gamma", 1.0, 3.0, 2.2,
            "Display gamma curve (2.2 = sRGB, 2.4 = BT.1886)"
        )
        bc_layout.addLayout(self.gamma_slider['layout'])
        self.gamma_slider['slider'].valueChanged.connect(
            lambda v: self._on_slider_changed('gamma', v / 100.0)
        )

        scroll_layout.addWidget(bc_group)

        # RGB Gains (White Balance)
        rgb_group = QGroupBox("RGB Balance (White Point)")
        rgb_layout = QVBoxLayout(rgb_group)

        rgb_info = QLabel(
            "Adjust these to correct white point toward D65 (6500K):\n"
            "\u2022 Too warm/yellow: Decrease Red or increase Blue\n"
            "\u2022 Too cool/blue: Decrease Blue or increase Red"
        )
        rgb_info.setWordWrap(True)
        rgb_info.setStyleSheet(f"color: {COLORS['text_secondary']}; padding: 4px;")
        rgb_layout.addWidget(rgb_info)

        self.red_gain_slider = self._create_float_slider(
            "Red", 0.5, 1.5, 1.0,
            "Red channel gain (1.0 = no change)",
            value_color="#ff6b6b"
        )
        rgb_layout.addLayout(self.red_gain_slider['layout'])
        self.red_gain_slider['slider'].valueChanged.connect(
            lambda v: self._on_slider_changed('red_gain', v / 100.0)
        )

        self.green_gain_slider = self._create_float_slider(
            "Green", 0.5, 1.5, 1.0,
            "Green channel gain (1.0 = no change)",
            value_color="#69db7c"
        )
        rgb_layout.addLayout(self.green_gain_slider['layout'])
        self.green_gain_slider['slider'].valueChanged.connect(
            lambda v: self._on_slider_changed('green_gain', v / 100.0)
        )

        self.blue_gain_slider = self._create_float_slider(
            "Blue", 0.5, 1.5, 1.0,
            "Blue channel gain (1.0 = no change)",
            value_color="#74c0fc"
        )
        rgb_layout.addLayout(self.blue_gain_slider['layout'])
        self.blue_gain_slider['slider'].valueChanged.connect(
            lambda v: self._on_slider_changed('blue_gain', v / 100.0)
        )

        scroll_layout.addWidget(rgb_group)

        # Black Level (Shadow Lift)
        shadow_group = QGroupBox("Shadow / Black Level")
        shadow_layout = QVBoxLayout(shadow_group)

        self.black_level_slider = self._create_float_slider(
            "Black Level", 0.0, 0.15, 0.0,
            "Lifts shadow detail (0.0 = true black)"
        )
        shadow_layout.addLayout(self.black_level_slider['layout'])
        self.black_level_slider['slider'].valueChanged.connect(
            lambda v: self._on_slider_changed('black_level', v / 1000.0)
        )

        scroll_layout.addWidget(shadow_group)

        # Presets
        preset_group = QGroupBox("Quick Presets")
        preset_layout = QHBoxLayout(preset_group)

        presets = [
            ("Default (sRGB)", self._preset_default),
            ("Bright Boost +50%", self._preset_bright),
            ("BT.1886 (Video)", self._preset_bt1886),
            ("Warm (6000K)", self._preset_warm),
            ("Cool (7500K)", self._preset_cool),
        ]

        for name, callback in presets:
            btn = QPushButton(name)
            btn.clicked.connect(callback)
            preset_layout.addWidget(btn)

        scroll_layout.addWidget(preset_group)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)

        # Action buttons
        actions_layout = QHBoxLayout()

        apply_btn = QPushButton("Apply Now")
        apply_btn.setProperty("primary", True)
        apply_btn.setToolTip("Apply current settings to display")
        apply_btn.clicked.connect(self._apply_settings)
        actions_layout.addWidget(apply_btn)

        reset_btn = QPushButton("Reset to Default")
        reset_btn.clicked.connect(self._reset_to_default)
        actions_layout.addWidget(reset_btn)

        actions_layout.addStretch()

        save_btn = QPushButton("Save as Profile...")
        save_btn.clicked.connect(self._save_profile)
        actions_layout.addWidget(save_btn)

        load_btn = QPushButton("Load Profile...")
        load_btn.clicked.connect(self._load_profile)
        actions_layout.addWidget(load_btn)

        layout.addLayout(actions_layout)

        # Status
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet(f"color: {COLORS['text_secondary']}; padding: 8px;")
        layout.addWidget(self.status_label)

    def _create_float_slider(self, label: str, min_val: float, max_val: float,
                              default: float, tooltip: str, value_color: str = None) -> dict:
        """Create a slider for float values."""
        layout = QHBoxLayout()
        layout.setSpacing(12)

        lbl = QLabel(f"{label}:")
        lbl.setMinimumWidth(80)
        layout.addWidget(lbl)

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setMinimum(int(min_val * 100))
        slider.setMaximum(int(max_val * 100))
        slider.setValue(int(default * 100))
        slider.setToolTip(tooltip)
        layout.addWidget(slider, stretch=1)

        color = value_color or COLORS['text_primary']
        value_lbl = QLabel(f"{default:.2f}")
        value_lbl.setMinimumWidth(50)
        value_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        value_lbl.setStyleSheet(f"font-weight: 600; color: {color};")
        layout.addWidget(value_lbl)

        def update_label(val):
            value_lbl.setText(f"{val / 100.0:.2f}")

        slider.valueChanged.connect(update_label)

        return {'layout': layout, 'slider': slider, 'value_label': value_lbl}

    def _initialize(self):
        """Initialize color loader."""
        try:
            from calibrate_pro.lut_system.color_loader import ColorLoader
            self.color_loader = ColorLoader()
            self._refresh_displays()
            self.status_label.setText("\u2713 Ready - Adjust sliders and click Apply")
            self.status_label.setStyleSheet(f"color: {COLORS['success']}; padding: 8px;")
        except Exception as e:
            self.status_label.setText(f"\u274c Error: {e}")
            self.status_label.setStyleSheet(f"color: {COLORS['error']}; padding: 8px;")

    def _refresh_displays(self):
        """Refresh display list."""
        if not self.color_loader:
            return

        self.display_combo.clear()
        self.displays = self.color_loader.enumerate_displays()

        for _i, d in enumerate(self.displays):
            primary = " (Primary)" if d.get('primary') else ""
            self.display_combo.addItem(f"{d.get('monitor', 'Display')} - {d.get('adapter', 'GPU')}{primary}")

        if self.displays:
            self._on_display_changed(0)

    def _on_display_changed(self, index: int):
        """Handle display selection change."""
        if index >= 0 and index < len(self.displays):
            self.current_display = index

    def _on_slider_changed(self, param: str, value: float):
        """Handle slider value change."""
        if self._updating:
            return

        setattr(self, f'_{param}', value)

        # Auto-apply on slider change for immediate feedback
        self._apply_settings()

    def _apply_settings(self):
        """Apply current settings to display."""
        if not self.color_loader:
            return

        try:
            import numpy as np

            # Build gamma ramp
            ramp = np.zeros((256, 3), dtype=np.uint16)

            for i in range(256):
                x = i / 255.0

                # Apply adjustments
                for c, gain in enumerate([self._red_gain, self._green_gain, self._blue_gain]):
                    # Start with input
                    v = x

                    # Apply gamma (inverse for encoding)
                    v = v ** (1.0 / self._gamma)

                    # Apply contrast (pivot at 0.5)
                    v = (v - 0.5) * self._contrast + 0.5

                    # Apply brightness (gain)
                    v = v * self._brightness

                    # Apply RGB gain
                    v = v * gain

                    # Apply black level (lift)
                    v = v * (1.0 - self._black_level) + self._black_level

                    # Clamp and convert to 16-bit
                    v = max(0.0, min(1.0, v))
                    ramp[i, c] = int(v * 65535)

            # Apply to display
            success = self.color_loader.set_gamma_ramp(
                self.current_display,
                ramp[:, 0],
                ramp[:, 1],
                ramp[:, 2]
            )

            if success:
                self.status_label.setText(
                    f"\u2713 Applied: Brightness={self._brightness:.2f}, "
                    f"Contrast={self._contrast:.2f}, Gamma={self._gamma:.2f}"
                )
                self.status_label.setStyleSheet(f"color: {COLORS['success']}; padding: 8px;")
            else:
                self.status_label.setText("\u26a0\ufe0f Failed to apply gamma ramp")
                self.status_label.setStyleSheet(f"color: {COLORS['warning']}; padding: 8px;")

        except Exception as e:
            self.status_label.setText(f"\u274c Error: {e}")
            self.status_label.setStyleSheet(f"color: {COLORS['error']}; padding: 8px;")

    def _reset_to_default(self):
        """Reset all values to default."""
        self._updating = True

        self._brightness = 1.0
        self._contrast = 1.0
        self._gamma = 2.2
        self._red_gain = 1.0
        self._green_gain = 1.0
        self._blue_gain = 1.0
        self._black_level = 0.0

        self.brightness_slider['slider'].setValue(100)
        self.contrast_slider['slider'].setValue(100)
        self.gamma_slider['slider'].setValue(220)
        self.red_gain_slider['slider'].setValue(100)
        self.green_gain_slider['slider'].setValue(100)
        self.blue_gain_slider['slider'].setValue(100)
        self.black_level_slider['slider'].setValue(0)

        self._updating = False

        # Reset display to linear
        if self.color_loader:
            self.color_loader.reset_display(self.current_display)
            self.status_label.setText("\u2713 Reset to default (linear gamma)")
            self.status_label.setStyleSheet(f"color: {COLORS['success']}; padding: 8px;")

    def _preset_default(self):
        """Apply sRGB default preset."""
        self._updating = True
        self._brightness = 1.0
        self._contrast = 1.0
        self._gamma = 2.2
        self._red_gain = 1.0
        self._green_gain = 1.0
        self._blue_gain = 1.0
        self._black_level = 0.0
        self._update_sliders_from_values()
        self._updating = False
        self._apply_settings()

    def _preset_bright(self):
        """Apply brightness boost preset."""
        self._updating = True
        self._brightness = 1.5
        self._contrast = 1.1
        self._gamma = 2.2
        self._red_gain = 1.0
        self._green_gain = 1.0
        self._blue_gain = 1.0
        self._black_level = 0.02
        self._update_sliders_from_values()
        self._updating = False
        self._apply_settings()

    def _preset_bt1886(self):
        """Apply BT.1886 video preset."""
        self._updating = True
        self._brightness = 1.0
        self._contrast = 1.0
        self._gamma = 2.4
        self._red_gain = 1.0
        self._green_gain = 1.0
        self._blue_gain = 1.0
        self._black_level = 0.0
        self._update_sliders_from_values()
        self._updating = False
        self._apply_settings()

    def _preset_warm(self):
        """Apply warm white point preset."""
        self._updating = True
        self._brightness = 1.0
        self._contrast = 1.0
        self._gamma = 2.2
        self._red_gain = 1.05
        self._green_gain = 1.0
        self._blue_gain = 0.92
        self._black_level = 0.0
        self._update_sliders_from_values()
        self._updating = False
        self._apply_settings()

    def _preset_cool(self):
        """Apply cool white point preset."""
        self._updating = True
        self._brightness = 1.0
        self._contrast = 1.0
        self._gamma = 2.2
        self._red_gain = 0.92
        self._green_gain = 0.98
        self._blue_gain = 1.05
        self._black_level = 0.0
        self._update_sliders_from_values()
        self._updating = False
        self._apply_settings()

    def _update_sliders_from_values(self):
        """Update slider positions from current values."""
        self.brightness_slider['slider'].setValue(int(self._brightness * 100))
        self.contrast_slider['slider'].setValue(int(self._contrast * 100))
        self.gamma_slider['slider'].setValue(int(self._gamma * 100))
        self.red_gain_slider['slider'].setValue(int(self._red_gain * 100))
        self.green_gain_slider['slider'].setValue(int(self._green_gain * 100))
        self.blue_gain_slider['slider'].setValue(int(self._blue_gain * 100))
        self.black_level_slider['slider'].setValue(int(self._black_level * 1000))

    def _save_profile(self):
        """Save current settings as a profile."""
        import json

        filename, _ = QFileDialog.getSaveFileName(
            self, "Save Color Profile",
            "", "Color Profile (*.json)"
        )

        if filename:
            if not filename.endswith('.json'):
                filename += '.json'

            profile = {
                'brightness': self._brightness,
                'contrast': self._contrast,
                'gamma': self._gamma,
                'red_gain': self._red_gain,
                'green_gain': self._green_gain,
                'blue_gain': self._blue_gain,
                'black_level': self._black_level,
            }

            with open(filename, 'w') as f:
                json.dump(profile, f, indent=2)

            self.status_label.setText(f"\u2713 Saved profile: {filename}")

    def _load_profile(self):
        """Load settings from a profile."""
        import json

        filename, _ = QFileDialog.getOpenFileName(
            self, "Load Color Profile",
            "", "Color Profile (*.json)"
        )

        if filename:
            with open(filename) as f:
                profile = json.load(f)

            self._updating = True
            self._brightness = profile.get('brightness', 1.0)
            self._contrast = profile.get('contrast', 1.0)
            self._gamma = profile.get('gamma', 2.2)
            self._red_gain = profile.get('red_gain', 1.0)
            self._green_gain = profile.get('green_gain', 1.0)
            self._blue_gain = profile.get('blue_gain', 1.0)
            self._black_level = profile.get('black_level', 0.0)
            self._update_sliders_from_values()
            self._updating = False

            self._apply_settings()
            self.status_label.setText(f"\u2713 Loaded profile: {filename}")
