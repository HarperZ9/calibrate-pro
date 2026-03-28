"""
Calibrate Page — Professional calibration workflow.

Display selector, mode cards, target settings, progress tracking.
Runs AutoCalibrationEngine in a QThread with live progress updates.
"""

import sys
import traceback
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from calibrate_pro.gui.app import C, Card, Heading

# Worker Thread

class CalibrationWorker(QThread):
    """Runs AutoCalibrationEngine.run_calibration() off the main thread.

    Always performs DDC/CI hardware setup first (if available),
    then runs the selected calibration mode.
    """

    progress = pyqtSignal(str, float, str)   # message, 0-1, step name
    finished = pyqtSignal(bool, str)          # success, result message
    log_line = pyqtSignal(str)                # individual log lines

    def __init__(
        self,
        display_index: int = 0,
        target_gamut: str = "sRGB",
        whitepoint: str = "D65",
        gamma: str = "2.2",
        hdr_mode: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.display_index = display_index
        self.target_gamut = target_gamut
        self.whitepoint = whitepoint
        self.gamma = gamma
        self.hdr_mode = hdr_mode

    def _run_ddc_setup(self):
        """Run DDC/CI hardware setup before calibration."""
        self.progress.emit("Configuring display hardware...", 0.0, "DDC Setup")
        self.log_line.emit("Phase 0: DDC/CI hardware setup")

        try:
            from calibrate_pro.hardware.ddc_ci import DDCCIController
            from calibrate_pro.panels.database import PanelDatabase
            from calibrate_pro.panels.detection import enumerate_displays, identify_display

            ddc = DDCCIController()
            monitors = ddc.enumerate_monitors()

            if self.display_index >= len(monitors):
                self.log_line.emit(f"  DDC: Display {self.display_index} not found ({len(monitors)} available)")
                return

            monitor = monitors[self.display_index]

            # Find DDC recommendations for this monitor
            ddc_rec = None
            try:
                displays = enumerate_displays()
                if self.display_index < len(displays):
                    db = PanelDatabase()
                    panel_key = identify_display(displays[self.display_index])
                    panel = db.get_panel(panel_key) if panel_key else None
                    if panel and hasattr(panel, 'ddc') and panel.ddc:
                        ddc_rec = panel.ddc
                        self.log_line.emit(f"  Panel: {panel.name}")
            except Exception:
                pass

            # Apply auto-setup
            changes = ddc.auto_setup_for_calibration(
                monitor, ddc_recommendations=ddc_rec,
                log_fn=lambda msg: self.log_line.emit(f"  DDC: {msg}"),
            )

            if changes:
                self.log_line.emit(f"  DDC: {len(changes)} settings applied")
            else:
                self.log_line.emit("  DDC: No settings applied (monitor may not support DDC/CI)")

            import time
            time.sleep(1.0)  # Let monitor settle after DDC changes

        except Exception as e:
            self.log_line.emit(f"  DDC setup skipped: {e}")

        self.progress.emit("Hardware setup complete", 0.05, "DDC Setup")

    def run(self):
        try:
            # Phase 0: Hardware DDC setup (runs before any calibration mode)
            self._run_ddc_setup()

            from calibrate_pro.sensorless.auto_calibration import (
                AutoCalibrationEngine,
                CalibrationStep,
                CalibrationTarget,
            )

            engine = AutoCalibrationEngine()

            # Map step enum to human-readable name
            step_names = {
                CalibrationStep.DETECT_DISPLAY: "Detecting",
                CalibrationStep.MATCH_PANEL: "Matching",
                CalibrationStep.READ_DDC_SETTINGS: "DDC read",
                CalibrationStep.CALCULATE_CORRECTIONS: "Matching",
                CalibrationStep.APPLY_DDC_CORRECTIONS: "DDC adjust",
                CalibrationStep.GENERATE_ICC_PROFILE: "LUT generation",
                CalibrationStep.GENERATE_3D_LUT: "LUT generation",
                CalibrationStep.INSTALL_PROFILE: "Applying",
                CalibrationStep.APPLY_LUT: "Applying",
                CalibrationStep.VERIFY_CALIBRATION: "Verifying",
                CalibrationStep.COMPLETE: "Complete",
            }

            def on_progress(message, progress_val, step):
                readable = step_names.get(step, step.name)
                self.progress.emit(message, progress_val, readable)
                self.log_line.emit(message)

            engine.set_progress_callback(on_progress)

            # Build target
            target = CalibrationTarget()
            target.gamut = self.target_gamut

            # Whitepoint
            wp_map = {
                "D65": ("D65", (0.3127, 0.3290)),
                "D50": ("D50", (0.3457, 0.3585)),
            }
            if self.whitepoint in wp_map:
                target.whitepoint, target.whitepoint_xy = wp_map[self.whitepoint]
            else:
                target.whitepoint = self.whitepoint
                target.whitepoint_xy = (0.3127, 0.3290)

            # Gamma
            gamma_map = {
                "2.2": (2.2, "power"),
                "2.4": (2.4, "power"),
                "sRGB": (2.2, "srgb"),
                "BT.1886": (2.4, "bt1886"),
            }
            if self.gamma in gamma_map:
                target.gamma, target.gamma_type = gamma_map[self.gamma]

            result = engine.run_calibration(
                target=target,
                display_index=self.display_index,
                hdr_mode=self.hdr_mode,
            )

            self.finished.emit(result.success, result.message)

        except Exception as exc:
            tb = traceback.format_exc()
            self.log_line.emit(tb)
            self.finished.emit(False, f"Calibration error: {exc}")


class NativeCalibrationWorker(QThread):
    """Runs native i1Display3 calibration with fullscreen patch display.

    Uses the show_patch signal to tell the main thread to display colors.
    The worker waits for the patch to settle before measuring.
    """

    progress = pyqtSignal(str, float, str)
    finished = pyqtSignal(bool, str)
    log_line = pyqtSignal(str)
    show_patch = pyqtSignal(float, float, float)  # r, g, b for main thread to display

    def __init__(self, display_index: int = 0, parent=None):
        super().__init__(parent)
        self.display_index = display_index

    def _display_and_wait(self, r, g, b, settle=1.2):
        """Signal the main thread to show a patch, then wait for settle time."""
        self.show_patch.emit(r, g, b)
        import time
        time.sleep(settle)  # Wait for OLED settle + signal propagation

    def run(self):
        try:
            import os
            import struct
            import time

            import hid
            import numpy as np

            OLED_MATRIX = np.array([
                [0.03836831, -0.02175997, 0.01696057],
                [0.01449629,  0.01611903, 0.00057150],
                [-0.00004481, 0.00035042, 0.08032401],
            ])

            # Apply CCMX spectral correction for QD-OLED
            from calibrate_pro.calibration.native_loop import QDOLED_CCMX
            SENSOR_MATRIX = QDOLED_CCMX @ OLED_MATRIX

            M_MASK = 0xFFFFFFFF

            # Step 1: Open sensor
            self.progress.emit("Opening colorimeter...", 0.0, "Connecting")
            self.log_line.emit("Opening i1Display3 USB HID...")

            device = hid.device()
            device.open(0x0765, 0x5020)

            # Unlock (NEC OEM key)
            k0, k1 = 0xa9119479, 0x5b168761
            cmd = bytearray(65); cmd[0] = 0; cmd[1] = 0x99
            device.write(cmd); time.sleep(0.2)
            c = bytes(device.read(64, timeout_ms=3000))
            sc = bytearray(8)
            for i in range(8): sc[i] = c[3] ^ c[35 + i]
            ci0 = (sc[3]<<24)+(sc[0]<<16)+(sc[4]<<8)+sc[6]
            ci1 = (sc[1]<<24)+(sc[7]<<16)+(sc[2]<<8)+sc[5]
            nk0, nk1 = (-k0) & M_MASK, (-k1) & M_MASK
            co = [(nk0-ci1)&M_MASK, (nk1-ci0)&M_MASK, (ci1*nk0)&M_MASK, (ci0*nk1)&M_MASK]
            s = sum(sc)
            for sh in [0, 8, 16, 24]: s += (nk0>>sh)&0xFF; s += (nk1>>sh)&0xFF
            s0, s1 = s & 0xFF, (s >> 8) & 0xFF
            sr = bytearray(16)
            sr[0]=(((co[0]>>16)&0xFF)+s0)&0xFF; sr[1]=(((co[2]>>8)&0xFF)-s1)&0xFF
            sr[2]=((co[3]&0xFF)+s1)&0xFF; sr[3]=(((co[1]>>16)&0xFF)+s0)&0xFF
            sr[4]=(((co[2]>>16)&0xFF)-s1)&0xFF; sr[5]=(((co[3]>>16)&0xFF)-s0)&0xFF
            sr[6]=(((co[1]>>24)&0xFF)-s0)&0xFF; sr[7]=((co[0]&0xFF)-s1)&0xFF
            sr[8]=(((co[3]>>8)&0xFF)+s0)&0xFF; sr[9]=(((co[2]>>24)&0xFF)-s1)&0xFF
            sr[10]=(((co[0]>>8)&0xFF)+s0)&0xFF; sr[11]=(((co[1]>>8)&0xFF)-s1)&0xFF
            sr[12]=((co[1]&0xFF)+s1)&0xFF; sr[13]=(((co[3]>>24)&0xFF)+s1)&0xFF
            sr[14]=((co[2]&0xFF)+s0)&0xFF; sr[15]=(((co[0]>>24)&0xFF)-s0)&0xFF
            rb = bytearray(65); rb[0] = 0; rb[1] = 0x9A
            for i in range(16): rb[25+i] = c[2] ^ sr[i]
            device.write(rb); time.sleep(0.3); device.read(64, timeout_ms=3000)

            self.log_line.emit("Sensor unlocked. CCMX spectral correction applied.")

            def measure_xyz_fn(r, g, b):
                intclks = int(1.0 * 12000000)
                cmd2 = bytearray(65); cmd2[0] = 0x00; cmd2[1] = 0x01
                struct.pack_into('<I', cmd2, 2, intclks)
                device.write(cmd2)
                resp = device.read(64, timeout_ms=4000)
                if resp and resp[0] == 0x00 and resp[1] == 0x01:
                    rv = struct.unpack('<I', bytes(resp[2:6]))[0]
                    gv = struct.unpack('<I', bytes(resp[6:10]))[0]
                    bv = struct.unpack('<I', bytes(resp[10:14]))[0]
                    t = intclks / 12000000.0
                    freq = np.array([0.5*(rv+0.5)/t, 0.5*(gv+0.5)/t, 0.5*(bv+0.5)/t])
                    if np.max(freq) > 0.3:
                        return SENSOR_MATRIX @ freq
                return None

            # Step 2: Profile display via patch signal
            self.progress.emit("Profiling display...", 0.1, "Profiling")
            self.log_line.emit("Measuring per-channel TRC ramps (17 steps)...")
            self.log_line.emit("Place sensor against display center.")

            from calibrate_pro.calibration.native_loop import build_correction_lut, profile_display

            def progress_cb(msg, frac):
                self.progress.emit(msg, 0.1 + frac * 0.5, "Profiling")
                self.log_line.emit(msg)

            profile = profile_display(
                measure_fn=measure_xyz_fn,
                display_fn=self._display_and_wait,
                n_steps=17,
                progress_fn=progress_cb,
            )

            self.log_line.emit(f"White Y: {profile.white_Y:.1f} cd/m2")
            self.log_line.emit(f"White point: ({profile.white_xy[0]:.4f}, {profile.white_xy[1]:.4f})")
            self.log_line.emit(f"Red:   ({profile.red_xy[0]:.4f}, {profile.red_xy[1]:.4f})")
            self.log_line.emit(f"Green: ({profile.green_xy[0]:.4f}, {profile.green_xy[1]:.4f})")
            self.log_line.emit(f"Blue:  ({profile.blue_xy[0]:.4f}, {profile.blue_xy[1]:.4f})")

            # Step 3: Build LUT
            self.progress.emit("Building correction LUT...", 0.65, "Computing")
            self.log_line.emit("Building 33^3 chroma-adaptive correction LUT...")
            lut = build_correction_lut(profile, size=33)

            # Step 4: Save
            self.progress.emit("Saving LUT...", 0.85, "Saving")
            output_dir = os.path.expanduser("~/Documents/Calibrate Pro/Calibrations")
            os.makedirs(output_dir, exist_ok=True)
            lut_path = os.path.join(output_dir, "native_calibration.cube")
            lut.title = "Calibrate Pro - Native Measured Correction"
            lut.save(lut_path)
            self.log_line.emit(f"Saved: {lut_path}")

            # Step 5: Apply via DWM
            self.progress.emit("Applying LUT...", 0.90, "Applying")
            try:
                from calibrate_pro.lut_system.dwm_lut import DwmLutController
                dwm = DwmLutController()
                if dwm.is_available:
                    dwm.load_lut_file(0, lut_path)
                    self.log_line.emit("LUT applied via DWM.")
                else:
                    self.log_line.emit("dwm_lut not available. LUT saved for manual application.")
            except Exception as e:
                self.log_line.emit(f"DWM LUT: {e}")

            device.close()

            # Hide the patch window
            self.show_patch.emit(-1.0, -1.0, -1.0)  # Signal to close patch window

            self.progress.emit("Complete!", 1.0, "Complete")
            self.finished.emit(True,
                f"Native calibration complete.\nLUT saved to {lut_path}")

        except Exception as exc:
            self.show_patch.emit(-1.0, -1.0, -1.0)  # Close patch window on error
            tb = traceback.format_exc()
            self.log_line.emit(tb)
            self.finished.emit(False, f"Native calibration error: {exc}")


class HardwareFirstWorker(QThread):
    """Hardware-first calibration: DDC/CI + colorimeter + residual LUT."""

    progress = pyqtSignal(str, float, str)
    finished = pyqtSignal(bool, str)
    log_line = pyqtSignal(str)
    show_patch = pyqtSignal(float, float, float)

    def __init__(self, display_index: int = 0, parent=None):
        super().__init__(parent)
        self.display_index = display_index

    def _display_and_wait(self, r, g, b, settle=1.2):
        self.show_patch.emit(r, g, b)
        import time
        time.sleep(settle)

    def run(self):
        try:
            import struct
            import time

            import hid
            import numpy as np

            OLED_MATRIX = np.array([
                [0.03836831, -0.02175997, 0.01696057],
                [0.01449629,  0.01611903, 0.00057150],
                [-0.00004481, 0.00035042, 0.08032401],
            ])

            from calibrate_pro.calibration.native_loop import QDOLED_CCMX
            SENSOR = QDOLED_CCMX @ OLED_MATRIX

            M_MASK = 0xFFFFFFFF

            # Open sensor
            self.log_line.emit("Opening i1Display3...")
            device = hid.device()
            device.open(0x0765, 0x5020)

            # Unlock
            k0, k1 = 0xa9119479, 0x5b168761
            cmd = bytearray(65); cmd[0] = 0; cmd[1] = 0x99
            device.write(cmd); time.sleep(0.2)
            c = bytes(device.read(64, timeout_ms=3000))
            sc = bytearray(8)
            for i in range(8): sc[i] = c[3] ^ c[35+i]
            ci0=(sc[3]<<24)+(sc[0]<<16)+(sc[4]<<8)+sc[6]
            ci1=(sc[1]<<24)+(sc[7]<<16)+(sc[2]<<8)+sc[5]
            nk0,nk1=(-k0)&M_MASK,(-k1)&M_MASK
            co=[(nk0-ci1)&M_MASK,(nk1-ci0)&M_MASK,(ci1*nk0)&M_MASK,(ci0*nk1)&M_MASK]
            s=sum(sc)
            for sh in [0,8,16,24]: s+=(nk0>>sh)&0xFF; s+=(nk1>>sh)&0xFF
            s0,s1=s&0xFF,(s>>8)&0xFF
            sr=bytearray(16)
            sr[0]=(((co[0]>>16)&0xFF)+s0)&0xFF;sr[1]=(((co[2]>>8)&0xFF)-s1)&0xFF
            sr[2]=((co[3]&0xFF)+s1)&0xFF;sr[3]=(((co[1]>>16)&0xFF)+s0)&0xFF
            sr[4]=(((co[2]>>16)&0xFF)-s1)&0xFF;sr[5]=(((co[3]>>16)&0xFF)-s0)&0xFF
            sr[6]=(((co[1]>>24)&0xFF)-s0)&0xFF;sr[7]=((co[0]&0xFF)-s1)&0xFF
            sr[8]=(((co[3]>>8)&0xFF)+s0)&0xFF;sr[9]=(((co[2]>>24)&0xFF)-s1)&0xFF
            sr[10]=(((co[0]>>8)&0xFF)+s0)&0xFF;sr[11]=(((co[1]>>8)&0xFF)-s1)&0xFF
            sr[12]=((co[1]&0xFF)+s1)&0xFF;sr[13]=(((co[3]>>24)&0xFF)+s1)&0xFF
            sr[14]=((co[2]&0xFF)+s0)&0xFF;sr[15]=(((co[0]>>24)&0xFF)-s0)&0xFF
            rb=bytearray(65);rb[0]=0;rb[1]=0x9A
            for i in range(16): rb[25+i]=c[2]^sr[i]
            device.write(rb);time.sleep(0.3);device.read(64,timeout_ms=3000)
            self.log_line.emit("Sensor unlocked.")

            def measure():
                intclks = int(1.0 * 12000000)
                cmd2 = bytearray(65); cmd2[0] = 0x00; cmd2[1] = 0x01
                struct.pack_into('<I', cmd2, 2, intclks)
                device.write(cmd2)
                resp = device.read(64, timeout_ms=4000)
                if resp and resp[0] == 0x00 and resp[1] == 0x01:
                    rv = struct.unpack('<I', bytes(resp[2:6]))[0]
                    gv = struct.unpack('<I', bytes(resp[6:10]))[0]
                    bv = struct.unpack('<I', bytes(resp[10:14]))[0]
                    t = intclks / 12000000.0
                    freq = np.array([0.5*(rv+0.5)/t, 0.5*(gv+0.5)/t, 0.5*(bv+0.5)/t])
                    if np.max(freq) > 0.3:
                        return SENSOR @ freq
                return None

            from calibrate_pro.calibration.hardware_first import run_hardware_first_calibration

            def progress_cb(msg, frac):
                phase = "Hardware" if frac < 0.6 else "Profiling" if frac < 0.85 else "Applying"
                self.progress.emit(msg, frac, phase)
                self.log_line.emit(msg)

            result = run_hardware_first_calibration(
                display_index=self.display_index,
                target_luminance=120.0,
                target_whitepoint=(0.3127, 0.3290),
                measure_fn=measure,
                display_fn=self._display_and_wait,
                progress_fn=progress_cb,
            )

            device.close()
            self.show_patch.emit(-1.0, -1.0, -1.0)

            self.finished.emit(result.success, result.message)

        except Exception as exc:
            self.show_patch.emit(-1.0, -1.0, -1.0)
            tb = traceback.format_exc()
            self.log_line.emit(tb)
            self.finished.emit(False, f"Hardware-first calibration error: {exc}")


# Mode Card

class ModeCard(Card):
    """Selectable mode card with icon area, title, and subtitle."""

    clicked = pyqtSignal()

    def __init__(
        self,
        title: str,
        subtitle: str,
        icon_text: str,
        enabled: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self._selected = False
        self._enabled = enabled
        self.setCursor(Qt.CursorShape.PointingHandCursor if enabled else Qt.CursorShape.ForbiddenCursor)
        self.setFixedHeight(120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)

        # Icon placeholder
        icon_label = QLabel(icon_text)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet(
            f"font-size: 24px; color: {C.ACCENT_TX if enabled else C.TEXT3};"
        )
        layout.addWidget(icon_label)

        # Title
        title_label = QLabel(title)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet(
            f"font-size: 13px; font-weight: 600; "
            f"color: {C.TEXT if enabled else C.TEXT3};"
        )
        layout.addWidget(title_label)

        # Subtitle
        sub_label = QLabel(subtitle)
        sub_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub_label.setWordWrap(True)
        sub_label.setStyleSheet(
            f"font-size: 11px; color: {C.TEXT2 if enabled else C.TEXT3};"
        )
        layout.addWidget(sub_label)

        self._apply_style()

    # --- selection ---

    def set_selected(self, selected: bool):
        self._selected = selected
        self._apply_style()

    def is_selected(self) -> bool:
        return self._selected

    def _apply_style(self):
        if not self._enabled:
            self.setStyleSheet(f"""
                ModeCard {{
                    background: {C.SURFACE};
                    border: 1px solid {C.BORDER};
                    border-radius: 10px;
                    opacity: 0.5;
                }}
            """)
        elif self._selected:
            self.setStyleSheet(f"""
                ModeCard {{
                    background: {C.SURFACE2};
                    border: 2px solid {C.ACCENT_HI};
                    border-radius: 10px;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                ModeCard {{
                    background: {C.SURFACE};
                    border: 1px solid {C.BORDER};
                    border-radius: 10px;
                }}
                ModeCard:hover {{
                    border-color: {C.ACCENT};
                }}
            """)

    def mousePressEvent(self, event):
        if self._enabled:
            self.clicked.emit()
        super().mousePressEvent(event)


# Calibrate Page

class CalibratePage(QWidget):
    """Full calibration workflow page."""

    calibration_completed = pyqtSignal()  # emitted after any calibration finishes

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: CalibrationWorker | None = None
        self._sensor_detected = False
        self._displays = []
        self._build()
        QTimer.singleShot(300, self._detect_environment)

    # Build UI

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)

        content = QWidget()
        self._layout = QVBoxLayout(content)
        self._layout.setContentsMargins(32, 28, 32, 28)
        self._layout.setSpacing(20)

        # --- Header ---
        self._layout.addWidget(Heading("Calibrate Display"))

        # --- Display selector ---
        disp_card, disp_lay = Card.with_layout(QHBoxLayout, margins=(16, 12, 16, 12))
        disp_label = QLabel("Display")
        disp_label.setStyleSheet(f"font-size: 12px; color: {C.TEXT2}; font-weight: 500;")
        disp_lay.addWidget(disp_label)

        self._display_combo = QComboBox()
        self._display_combo.setMinimumWidth(280)
        self._display_combo.setStyleSheet(f"""
            QComboBox {{
                background: {C.SURFACE2};
                border: 1px solid {C.BORDER};
                border-radius: 6px;
                padding: 6px 12px;
                color: {C.TEXT};
                font-size: 13px;
            }}
            QComboBox::drop-down {{
                border: none;
                width: 24px;
            }}
            QComboBox QAbstractItemView {{
                background: {C.SURFACE};
                border: 1px solid {C.BORDER};
                color: {C.TEXT};
                selection-background-color: {C.ACCENT};
            }}
        """)
        disp_lay.addWidget(self._display_combo, stretch=1)
        self._layout.addWidget(disp_card)

        # --- Hardware setup banner ---
        hw_banner, hw_lay = Card.with_layout(QHBoxLayout, margins=(16, 10, 16, 10))
        hw_icon = QLabel("\u2699")
        hw_icon.setStyleSheet(f"font-size: 18px; color: {C.GREEN};")
        hw_lay.addWidget(hw_icon)
        hw_text = QLabel("Hardware calibration runs first in every mode. "
                         "DDC/CI adjusts brightness, contrast, and RGB gains "
                         "before software profiling begins.")
        hw_text.setWordWrap(True)
        hw_text.setStyleSheet(f"font-size: 11px; color: {C.TEXT2};")
        hw_lay.addWidget(hw_text, stretch=1)
        self._layout.addWidget(hw_banner)

        # --- Mode selector ---
        self._layout.addWidget(Heading("Profiling Mode", level=2))
        mode_row = QHBoxLayout()
        mode_row.setSpacing(12)

        self._mode_sensorless = ModeCard(
            "Sensorless", "Panel database, instant", "\u2588\u2588",
            enabled=True,
        )
        self._mode_measured = ModeCard(
            "Measured", "Colorimeter profiling", "\u25c9",
            enabled=False,
        )
        self._mode_hybrid = ModeCard(
            "Hybrid", "Database + refinement", "\u2588\u25c9",
            enabled=False,
        )
        self._mode_cards = [self._mode_sensorless, self._mode_measured, self._mode_hybrid]
        for mc in self._mode_cards:
            mc.clicked.connect(lambda card=mc: self._select_mode(card))
            mode_row.addWidget(mc)

        self._mode_sensorless.set_selected(True)
        self._layout.addLayout(mode_row)

        # --- Target settings ---
        self._layout.addWidget(Heading("Target Settings", level=2))
        target_card, target_lay = Card.with_layout(QGridLayout, margins=(20, 16, 20, 16), spacing=12)

        combo_style = f"""
            QComboBox {{
                background: {C.SURFACE2};
                border: 1px solid {C.BORDER};
                border-radius: 6px;
                padding: 6px 12px;
                color: {C.TEXT};
                min-width: 140px;
            }}
            QComboBox::drop-down {{ border: none; width: 24px; }}
            QComboBox QAbstractItemView {{
                background: {C.SURFACE};
                border: 1px solid {C.BORDER};
                color: {C.TEXT};
                selection-background-color: {C.ACCENT};
            }}
        """
        label_style = f"font-size: 12px; color: {C.TEXT2};"

        # Row 0 — Gamut
        lbl_gamut = QLabel("Target Gamut")
        lbl_gamut.setStyleSheet(label_style)
        target_lay.addWidget(lbl_gamut, 0, 0)
        self._combo_gamut = QComboBox()
        self._combo_gamut.addItems(["Native", "sRGB", "DCI-P3", "Rec.709", "AdobeRGB"])
        self._combo_gamut.setCurrentText("sRGB")
        self._combo_gamut.setStyleSheet(combo_style)
        target_lay.addWidget(self._combo_gamut, 0, 1)

        # Row 1 — White point
        lbl_wp = QLabel("White Point")
        lbl_wp.setStyleSheet(label_style)
        target_lay.addWidget(lbl_wp, 1, 0)

        wp_row = QHBoxLayout()
        wp_row.setSpacing(8)
        self._combo_wp = QComboBox()
        self._combo_wp.addItems(["D65", "D50", "Custom"])
        self._combo_wp.setStyleSheet(combo_style)
        self._combo_wp.currentTextChanged.connect(self._on_wp_changed)
        wp_row.addWidget(self._combo_wp)

        self._cct_slider = QSlider(Qt.Orientation.Horizontal)
        self._cct_slider.setRange(3000, 9500)
        self._cct_slider.setValue(6500)
        self._cct_slider.setFixedWidth(160)
        self._cct_slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                background: {C.SURFACE2};
                height: 6px;
                border-radius: 3px;
            }}
            QSlider::handle:horizontal {{
                background: {C.ACCENT_TX};
                width: 14px;
                margin: -4px 0;
                border-radius: 7px;
            }}
        """)
        self._cct_slider.setVisible(False)
        self._cct_slider.valueChanged.connect(self._on_cct_changed)
        wp_row.addWidget(self._cct_slider)

        self._cct_label = QLabel("")
        self._cct_label.setStyleSheet(f"font-size: 11px; color: {C.TEXT2};")
        self._cct_label.setVisible(False)
        wp_row.addWidget(self._cct_label)
        wp_row.addStretch()
        target_lay.addLayout(wp_row, 1, 1)

        # Row 2 — Gamma
        lbl_gamma = QLabel("Gamma")
        lbl_gamma.setStyleSheet(label_style)
        target_lay.addWidget(lbl_gamma, 2, 0)
        self._combo_gamma = QComboBox()
        self._combo_gamma.addItems(["2.2", "2.4", "sRGB", "BT.1886"])
        self._combo_gamma.setStyleSheet(combo_style)
        target_lay.addWidget(self._combo_gamma, 2, 1)

        # Row 3 — HDR
        lbl_hdr = QLabel("HDR Mode")
        lbl_hdr.setStyleSheet(label_style)
        target_lay.addWidget(lbl_hdr, 3, 0)
        self._chk_hdr = QCheckBox("Enable HDR calibration (PQ / HLG)")
        self._chk_hdr.setStyleSheet(f"""
            QCheckBox {{
                color: {C.TEXT};
                spacing: 8px;
            }}
            QCheckBox::indicator {{
                width: 16px;
                height: 16px;
                border: 1px solid {C.BORDER};
                border-radius: 3px;
                background: {C.SURFACE2};
            }}
            QCheckBox::indicator:checked {{
                background: {C.GREEN};
                border-color: {C.GREEN_HI};
            }}
        """)
        target_lay.addWidget(self._chk_hdr, 3, 1)

        self._layout.addWidget(target_card)

        # --- Quick presets ---
        preset_row = QHBoxLayout()
        preset_row.setSpacing(8)
        preset_label = QLabel("Presets")
        preset_label.setStyleSheet(f"font-size: 12px; color: {C.TEXT2}; font-weight: 500;")
        preset_row.addWidget(preset_label)

        preset_btn_style = (
            f"QPushButton {{ background: {C.SURFACE}; border: 1px solid {C.BORDER}; "
            f"border-radius: 14px; padding: 5px 14px; font-size: 11px; color: {C.TEXT}; }}"
            f"QPushButton:hover {{ border-color: {C.ACCENT}; background: {C.SURFACE2}; }}"
        )

        presets = [
            ("sRGB Web", "sRGB", "D65", "2.2", False),
            ("Rec.709", "Rec.709", "D65", "BT.1886", False),
            ("DCI-P3", "DCI-P3", "D65", "2.4", False),
            ("HDR10", "Native", "D65", "2.2", True),
            ("Photography", "sRGB", "D50", "2.2", False),
        ]

        for label, gamut, wp, gamma, hdr in presets:
            btn = QPushButton(label)
            btn.setStyleSheet(preset_btn_style)
            btn.setFixedHeight(28)
            btn.clicked.connect(
                lambda checked, g=gamut, w=wp, gm=gamma, h=hdr: self._apply_preset(g, w, gm, h)
            )
            preset_row.addWidget(btn)

        preset_row.addStretch()
        self._layout.addLayout(preset_row)

        # --- Calibrate button ---
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._btn_calibrate = QPushButton("Calibrate Display")
        self._btn_calibrate.setProperty("primary", True)
        self._btn_calibrate.setFixedHeight(44)
        self._btn_calibrate.setFixedWidth(220)
        self._btn_calibrate.setStyleSheet(f"""
            QPushButton {{
                background: {C.GREEN};
                border: 1px solid {C.GREEN_HI};
                border-radius: 8px;
                color: {C.TEXT};
                font-size: 15px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background: {C.GREEN_HI};
            }}
            QPushButton:disabled {{
                background: {C.SURFACE2};
                border-color: {C.BORDER};
                color: {C.TEXT3};
            }}
        """)
        self._btn_calibrate.clicked.connect(self._start_calibration)
        btn_row.addWidget(self._btn_calibrate)
        btn_row.addStretch()
        self._layout.addLayout(btn_row)

        # --- Progress section (hidden until calibrating) ---
        self._progress_card = Card()
        prog_lay = QVBoxLayout(self._progress_card)
        prog_lay.setContentsMargins(20, 16, 20, 16)
        prog_lay.setSpacing(10)

        self._step_label = QLabel("Ready")
        self._step_label.setStyleSheet(f"font-size: 13px; font-weight: 500; color: {C.ACCENT_TX};")
        prog_lay.addWidget(self._step_label)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 1000)
        self._progress_bar.setValue(0)
        self._progress_bar.setFixedHeight(8)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background: {C.SURFACE2};
                border: none;
                border-radius: 4px;
            }}
            QProgressBar::chunk {{
                background: {C.GREEN};
                border-radius: 4px;
            }}
        """)
        prog_lay.addWidget(self._progress_bar)

        self._log_area = QTextEdit()
        self._log_area.setReadOnly(True)
        self._log_area.setFixedHeight(180)
        self._log_area.setStyleSheet(f"""
            QTextEdit {{
                background: {C.BG};
                border: 1px solid {C.BORDER};
                border-radius: 6px;
                color: {C.TEXT2};
                font-family: "Cascadia Code", "Consolas", monospace;
                font-size: 11px;
                padding: 8px;
            }}
        """)
        prog_lay.addWidget(self._log_area)

        self._progress_card.setVisible(False)
        self._layout.addWidget(self._progress_card)

        # --- Error label (inline) ---
        self._error_label = QLabel("")
        self._error_label.setWordWrap(True)
        self._error_label.setStyleSheet(f"color: {C.RED}; font-size: 12px;")
        self._error_label.setVisible(False)
        self._layout.addWidget(self._error_label)

        self._layout.addStretch()
        scroll.setWidget(content)

    # Environment Detection

    def _detect_environment(self):
        """Populate display list and detect sensor presence."""
        self._display_combo.clear()
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
            from calibrate_pro.panels.detection import enumerate_displays, get_display_name
            self._displays = enumerate_displays()
            for i, d in enumerate(self._displays):
                name = get_display_name(d)
                res = f"{d.width}x{d.height}"
                label = f"{i + 1}. {name}  ({res})"
                self._display_combo.addItem(label)
        except Exception as exc:
            self._display_combo.addItem("Display detection unavailable")
            self._show_error(f"Could not detect displays: {exc}")

        # Sensor detection
        try:
            from calibrate_pro.hardware.i1d3_native import I1D3Driver
            devices = I1D3Driver.find_devices()
            self._sensor_detected = bool(devices)
        except Exception:
            self._sensor_detected = False

        # Enable/disable measured modes
        self._mode_measured._enabled = self._sensor_detected
        self._mode_measured.setCursor(
            Qt.CursorShape.PointingHandCursor if self._sensor_detected
            else Qt.CursorShape.ForbiddenCursor
        )
        self._mode_measured._apply_style()

        self._mode_hybrid._enabled = self._sensor_detected
        self._mode_hybrid.setCursor(
            Qt.CursorShape.PointingHandCursor if self._sensor_detected
            else Qt.CursorShape.ForbiddenCursor
        )
        self._mode_hybrid._apply_style()

        # Auto-select Measured if sensor detected
        if self._sensor_detected:
            self._select_mode(self._mode_measured)

    # Interactions

    def _select_mode(self, card: ModeCard):
        for mc in self._mode_cards:
            mc.set_selected(mc is card)

    def _apply_preset(self, gamut: str, wp: str, gamma: str, hdr: bool):
        """Apply a calibration target preset."""
        idx = self._combo_gamut.findText(gamut)
        if idx >= 0:
            self._combo_gamut.setCurrentIndex(idx)
        idx = self._combo_wp.findText(wp)
        if idx >= 0:
            self._combo_wp.setCurrentIndex(idx)
        idx = self._combo_gamma.findText(gamma)
        if idx >= 0:
            self._combo_gamma.setCurrentIndex(idx)
        self._chk_hdr.setChecked(hdr)

    def _on_wp_changed(self, text: str):
        custom = text == "Custom"
        self._cct_slider.setVisible(custom)
        self._cct_label.setVisible(custom)
        if custom:
            self._on_cct_changed(self._cct_slider.value())

    def _on_cct_changed(self, value: int):
        self._cct_label.setText(f"{value} K")

    def _show_error(self, msg: str):
        self._error_label.setText(msg)
        self._error_label.setVisible(True)

    def _hide_error(self):
        self._error_label.setText("")
        self._error_label.setVisible(False)

    # Calibration

    def _start_calibration(self):
        if self._worker is not None and self._worker.isRunning():
            return

        self._hide_error()
        self._btn_calibrate.setText("Calibrating...")
        self._btn_calibrate.setEnabled(False)
        self._progress_card.setVisible(True)
        self._progress_bar.setValue(0)
        self._log_area.clear()
        self._step_label.setText("Starting calibration...")

        display_index = max(0, self._display_combo.currentIndex())

        # All modes: hardware DDC setup first, then profiling
        # Measured/Hybrid use colorimeter, Sensorless uses panel database
        if self._sensor_detected and self._mode_measured.is_selected():
            # Measured: hardware DDC + colorimeter profiling + correction LUT
            self._worker = HardwareFirstWorker(display_index=display_index)
            self._worker.show_patch.connect(self._show_measurement_patch)
        elif self._sensor_detected and self._mode_hybrid.is_selected():
            # Hybrid: hardware DDC + colorimeter profiling + correction LUT
            self._worker = HardwareFirstWorker(display_index=display_index)
            self._worker.show_patch.connect(self._show_measurement_patch)
        else:
            # Sensorless: hardware DDC (from database) + sensorless LUT
            gamut_text = self._combo_gamut.currentText()
            gamut_map = {
                "Native": "Native",
                "sRGB": "sRGB",
                "DCI-P3": "P3",
                "Rec.709": "sRGB",
                "AdobeRGB": "AdobeRGB",
            }
            target_gamut = gamut_map.get(gamut_text, "sRGB")

            self._worker = CalibrationWorker(
                display_index=display_index,
                target_gamut=target_gamut,
                whitepoint=self._combo_wp.currentText(),
                gamma=self._combo_gamma.currentText(),
                hdr_mode=self._chk_hdr.isChecked(),
            )

        self._worker.progress.connect(self._on_progress)
        self._worker.log_line.connect(self._on_log)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _show_measurement_patch(self, r: float, g: float, b: float):
        """Display a fullscreen color patch for measurement (main thread)."""
        # Negative values = close the patch window
        if r < 0:
            if hasattr(self, '_patch_window') and self._patch_window:
                self._patch_window.close()
                self._patch_window = None
            return

        # Create the patch window on first call
        if not hasattr(self, '_patch_window') or self._patch_window is None:
            from PyQt6.QtCore import Qt as QtConst
            from PyQt6.QtWidgets import QWidget

            self._patch_window = QWidget()
            self._patch_window.setWindowFlags(
                QtConst.WindowType.FramelessWindowHint |
                QtConst.WindowType.WindowStaysOnTopHint
            )
            self._patch_window.setCursor(QtConst.CursorShape.BlankCursor)

            # Find the target display geometry
            screen = None
            screens = QApplication.screens()
            display_index = max(0, self._display_combo.currentIndex())
            if display_index < len(screens):
                screen = screens[display_index]
            elif screens:
                # Default to largest screen (likely the calibration target)
                screen = max(screens, key=lambda s: s.size().width() * s.size().height())

            if screen:
                geo = screen.geometry()
                self._patch_window.setGeometry(geo)
            else:
                self._patch_window.resize(3840, 2160)

            self._patch_window.show()

        # Set the color
        ri = max(0, min(255, int(r * 255 + 0.5)))
        gi = max(0, min(255, int(g * 255 + 0.5)))
        bi = max(0, min(255, int(b * 255 + 0.5)))
        self._patch_window.setStyleSheet(
            f"background-color: #{ri:02x}{gi:02x}{bi:02x};"
        )
        self._patch_window.update()

    def _on_progress(self, message: str, value: float, step_name: str):
        self._step_label.setText(step_name)
        self._progress_bar.setValue(int(value * 1000))

    def _on_log(self, line: str):
        self._log_area.append(line)
        # Auto-scroll
        sb = self._log_area.verticalScrollBar()
        if sb:
            sb.setValue(sb.maximum())

    def _on_finished(self, success: bool, message: str):
        self._btn_calibrate.setEnabled(True)
        if success:
            self._btn_calibrate.setText("Calibrate Display")
            self._step_label.setText("Complete")
            self._step_label.setStyleSheet(
                f"font-size: 13px; font-weight: 500; color: {C.GREEN_HI};"
            )
            self._progress_bar.setValue(1000)
            self.calibration_completed.emit()
        else:
            self._btn_calibrate.setText("Calibrate Display")
            self._step_label.setText("Failed")
            self._step_label.setStyleSheet(
                f"font-size: 13px; font-weight: 500; color: {C.RED};"
            )
            self._show_error(message)

        self._on_log(message)
        self._worker = None
