"""
Dialogs - Calibrate Pro

Consent dialog for hardware modification warnings and the simulated
measurement window used for colorimeter-free calibration sequences.
"""

import random

from PyQt6.QtCore import QPoint, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QGuiApplication, QPainter, QPen, QPixmap, QScreen
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from calibrate_pro.gui.theme import COLORS

# Consent Dialog - Hardware modification warnings


class ConsentDialog(QDialog):
    """Dialog for obtaining user consent before hardware modifications."""

    def __init__(self, parent=None, display_name: str = "Display", changes: list = None, risk_level: str = "MEDIUM"):
        super().__init__(parent)
        self.setWindowTitle("Calibration Consent Required")
        self.setMinimumWidth(500)
        self.setModal(True)

        self.approved = False
        self.hardware_approved = False

        self._setup_ui(display_name, changes or [], risk_level)

    def _setup_ui(self, display_name: str, changes: list, risk_level: str):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        # Header with warning icon
        header = QLabel("DISPLAY CALIBRATION")
        header.setStyleSheet(f"""
            font-size: 18px; font-weight: 700;
            color: {COLORS["warning"]};
        """)
        layout.addWidget(header)

        # Display name
        display_label = QLabel(f"Target Display: {display_name}")
        display_label.setStyleSheet(f"font-size: 14px; color: {COLORS['text_primary']};")
        layout.addWidget(display_label)

        # Risk level indicator
        risk_colors = {"LOW": COLORS["success"], "MEDIUM": COLORS["warning"], "HIGH": COLORS["error"]}
        risk_color = risk_colors.get(risk_level, COLORS["warning"])

        risk_label = QLabel(f"Risk Level: {risk_level}")
        risk_label.setStyleSheet(f"""
            font-size: 13px; font-weight: 600;
            color: {risk_color};
            padding: 4px 8px;
            background-color: {COLORS["surface_alt"]};
            border-radius: 4px;
        """)
        layout.addWidget(risk_label)

        # Changes list
        changes_group = QGroupBox("What will be modified:")
        changes_layout = QVBoxLayout(changes_group)
        for change in changes:
            change_label = QLabel(f"  {change}")
            change_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
            changes_layout.addWidget(change_label)
        layout.addWidget(changes_group)

        # Safety info
        safety_text = QPlainTextEdit()
        safety_text.setPlainText(
            "SAFETY INFORMATION:\n\n"
            "• ICC Profile: Easily reversible, no risk to hardware\n"
            "• 3D LUT: Can be removed at any time via dwm_lut\n"
            "• DDC/CI Settings: Modifies monitor RGB gains, can be reset via monitor OSD\n"
            "• All changes can be reversed at any time\n\n"
            "BENEFITS:\n"
            "• Professional color accuracy (Delta E < 1.0)\n"
            "• Consistent colors across all applications\n"
            "• Proper grayscale tracking and gamma"
        )
        safety_text.setReadOnly(True)
        safety_text.setMaximumHeight(150)
        safety_text.setStyleSheet(f"""
            background-color: {COLORS["surface_alt"]};
            border: 1px solid {COLORS["border"]};
            border-radius: 4px;
            padding: 8px;
        """)
        layout.addWidget(safety_text)

        # Consent checkboxes
        self.acknowledge_check = QCheckBox("I understand that calibration will modify my display settings")
        self.acknowledge_check.setStyleSheet(f"color: {COLORS['text_primary']};")
        layout.addWidget(self.acknowledge_check)

        self.hardware_check = QCheckBox("I approve hardware modifications via DDC/CI (if available)")
        self.hardware_check.setStyleSheet(f"color: {COLORS['text_primary']};")
        layout.addWidget(self.hardware_check)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        self.proceed_btn = QPushButton("Proceed with Calibration")
        self.proceed_btn.setProperty("primary", True)
        self.proceed_btn.setEnabled(False)
        self.proceed_btn.clicked.connect(self._on_proceed)
        button_layout.addWidget(self.proceed_btn)

        layout.addLayout(button_layout)

        # Connect checkbox to enable button
        self.acknowledge_check.stateChanged.connect(self._update_proceed_button)

    def _update_proceed_button(self):
        self.proceed_btn.setEnabled(self.acknowledge_check.isChecked())

    def _on_proceed(self):
        self.approved = self.acknowledge_check.isChecked()
        self.hardware_approved = self.hardware_check.isChecked()
        self.accept()


# Simulated Measurement Window - Hardware colorimeter simulation


class SimulatedMeasurementWindow(QWidget):
    """
    Fullscreen window that simulates hardware colorimeter measurements.

    Features:
    - Centered color patch display (like colorimeter positioning)
    - Audio beeps for each measurement
    - Progress display with patch info
    - Random color sequences for visual feedback
    """

    measurement_complete = pyqtSignal(int, tuple)  # patch_index, (r, g, b)
    sequence_complete = pyqtSignal()
    closed = pyqtSignal()

    # Default measurement sequence - grayscale + primaries + ColorChecker subset
    DEFAULT_PATCHES = [
        # Grayscale ramp
        (0, 0, 0),
        (26, 26, 26),
        (51, 51, 51),
        (77, 77, 77),
        (102, 102, 102),
        (128, 128, 128),
        (153, 153, 153),
        (179, 179, 179),
        (204, 204, 204),
        (230, 230, 230),
        (255, 255, 255),
        # Primaries
        (255, 0, 0),
        (0, 255, 0),
        (0, 0, 255),
        # Secondaries
        (255, 255, 0),
        (0, 255, 255),
        (255, 0, 255),
        # ColorChecker key patches
        (115, 82, 68),
        (194, 150, 130),
        (98, 122, 157),
        (87, 108, 67),
        (133, 128, 177),
        (214, 126, 44),
        (56, 61, 150),
        (70, 148, 73),
        (175, 54, 60),
        (231, 199, 31),
        (187, 86, 149),
        (8, 133, 161),
    ]

    def __init__(self, parent=None, screen: QScreen = None):
        super().__init__(parent)
        self.target_screen = screen
        self.patches = list(self.DEFAULT_PATCHES)
        self.current_index = 0
        self.running = False
        self.measurement_delay = 800  # ms between measurements
        self.settle_time = 200  # ms for display to settle before "reading"

        # Timers
        self.measurement_timer = QTimer()
        self.measurement_timer.timeout.connect(self._on_measurement_tick)

        self._setup_ui()
        self._setup_audio()

    def _setup_ui(self):
        """Setup the fullscreen measurement UI."""
        self.setWindowTitle("Calibrate Pro - Measuring")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        # Main layout with black background
        self.setStyleSheet("background-color: #000000;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Central area for color patch
        self.patch_container = QWidget()
        self.patch_container.setStyleSheet("background-color: #000000;")
        patch_layout = QVBoxLayout(self.patch_container)
        patch_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # The color patch (centered square)
        self.color_patch = QFrame()
        self.color_patch.setFixedSize(280, 280)
        self.color_patch.setStyleSheet("""
            QFrame {
                background-color: rgb(128, 128, 128);
                border: 3px solid #333333;
                border-radius: 4px;
            }
        """)
        patch_layout.addWidget(self.color_patch, alignment=Qt.AlignmentFlag.AlignCenter)

        # Measurement crosshair overlay
        self.crosshair = QLabel(self.color_patch)
        self.crosshair.setFixedSize(280, 280)
        self.crosshair.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.crosshair.setStyleSheet("background: transparent;")
        self._draw_crosshair()

        layout.addWidget(self.patch_container, 1)

        # Bottom info panel
        self.info_panel = QFrame()
        self.info_panel.setFixedHeight(100)
        self.info_panel.setStyleSheet("""
            QFrame {
                background-color: rgba(30, 30, 30, 220);
                border-top: 1px solid #404040;
            }
            QLabel {
                color: #e0e0e0;
                background: transparent;
            }
        """)

        info_layout = QVBoxLayout(self.info_panel)
        info_layout.setContentsMargins(24, 12, 24, 12)
        info_layout.setSpacing(8)

        # Title row
        title_row = QHBoxLayout()

        self.title_label = QLabel("CALIBRATE PRO - MEASUREMENT MODE")
        self.title_label.setStyleSheet("font-size: 14px; font-weight: 600; color: #4a9eff;")
        title_row.addWidget(self.title_label)

        title_row.addStretch()

        self.patch_counter = QLabel("Patch 0 / 0")
        self.patch_counter.setStyleSheet("font-size: 13px; color: #a0a0a0;")
        title_row.addWidget(self.patch_counter)

        info_layout.addLayout(title_row)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #383838;
                border: none;
                border-radius: 3px;
            }
            QProgressBar::chunk {
                background-color: #4a9eff;
                border-radius: 3px;
            }
        """)
        info_layout.addWidget(self.progress_bar)

        # Status row
        status_row = QHBoxLayout()

        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("font-size: 12px; color: #808080;")
        status_row.addWidget(self.status_label)

        status_row.addStretch()

        self.rgb_label = QLabel("RGB: ---, ---, ---")
        self.rgb_label.setStyleSheet("font-size: 12px; color: #808080; font-family: 'Consolas', monospace;")
        status_row.addWidget(self.rgb_label)

        info_layout.addLayout(status_row)

        layout.addWidget(self.info_panel)

        # Keyboard shortcut to cancel
        from PyQt6.QtGui import QKeySequence, QShortcut

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self._cancel_measurement)

    def _draw_crosshair(self):
        """Draw a crosshair overlay on the patch."""
        pixmap = QPixmap(280, 280)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw crosshair lines
        pen = QPen(QColor(255, 255, 255, 60), 1, Qt.PenStyle.DashLine)
        painter.setPen(pen)

        # Vertical line
        painter.drawLine(140, 40, 140, 240)
        # Horizontal line
        painter.drawLine(40, 140, 240, 140)

        # Center circle (sensor position)
        painter.setPen(QPen(QColor(255, 255, 255, 100), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPoint(140, 140), 30, 30)

        # Inner target circle
        painter.setPen(QPen(QColor(74, 158, 255, 150), 2))
        painter.drawEllipse(QPoint(140, 140), 10, 10)

        painter.end()
        self.crosshair.setPixmap(pixmap)

    def _setup_audio(self):
        """Setup audio for beeps."""
        self.beep_enabled = True
        try:
            import winsound

            self.winsound = winsound
        except ImportError:
            self.winsound = None
            self.beep_enabled = False

    def _play_beep(self, frequency: int = 800, duration: int = 100):
        """Play a beep sound."""
        if self.beep_enabled and self.winsound:
            try:
                # Run async to not block UI
                import threading

                threading.Thread(target=self.winsound.Beep, args=(frequency, duration), daemon=True).start()
            except Exception:
                pass

    def _play_measurement_beep(self):
        """Play the characteristic measurement beep."""
        self._play_beep(1000, 50)

    def _play_complete_beep(self):
        """Play completion beep sequence."""
        import threading

        def beep_sequence():
            import time

            if self.winsound:
                self.winsound.Beep(800, 100)
                time.sleep(0.1)
                self.winsound.Beep(1000, 100)
                time.sleep(0.1)
                self.winsound.Beep(1200, 150)

        threading.Thread(target=beep_sequence, daemon=True).start()

    def set_patches(self, patches: list[tuple]):
        """Set custom patch sequence."""
        self.patches = list(patches)
        self.current_index = 0

    def add_random_patches(self, count: int = 10):
        """Add random color patches to the sequence."""
        for _ in range(count):
            r = random.randint(0, 255)
            g = random.randint(0, 255)
            b = random.randint(0, 255)
            self.patches.append((r, g, b))

    def show_fullscreen(self, screen: QScreen = None):
        """Show measurement window fullscreen on target screen."""
        target = screen or self.target_screen or QGuiApplication.primaryScreen()

        if target:
            self.setGeometry(target.geometry())

        self.showFullScreen()

    def start_measurements(self):
        """Start the measurement sequence."""
        if not self.patches:
            return

        self.current_index = 0
        self.running = True
        self.progress_bar.setMaximum(len(self.patches))
        self.progress_bar.setValue(0)

        # Show first patch
        self._show_current_patch()

        # Start measurement timer
        self.measurement_timer.start(self.measurement_delay)

    def _show_current_patch(self):
        """Display the current patch color."""
        if self.current_index >= len(self.patches):
            return

        r, g, b = self.patches[self.current_index]

        # Update patch color
        self.color_patch.setStyleSheet(f"""
            QFrame {{
                background-color: rgb({r}, {g}, {b});
                border: 3px solid #333333;
                border-radius: 4px;
            }}
        """)

        # Update labels
        self.patch_counter.setText(f"Patch {self.current_index + 1} / {len(self.patches)}")
        self.rgb_label.setText(f"RGB: {r:3d}, {g:3d}, {b:3d}")
        self.status_label.setText("Measuring...")
        self.status_label.setStyleSheet("font-size: 12px; color: #4a9eff;")

    def _on_measurement_tick(self):
        """Handle measurement timer tick."""
        if not self.running:
            self.measurement_timer.stop()
            return

        # Play beep
        self._play_measurement_beep()

        # Update status to show "reading"
        self.status_label.setText("Reading sensor...")
        self.status_label.setStyleSheet("font-size: 12px; color: #4caf50;")

        # Emit measurement signal
        rgb = self.patches[self.current_index]
        self.measurement_complete.emit(self.current_index, rgb)

        # Update progress
        self.progress_bar.setValue(self.current_index + 1)

        # Move to next patch
        self.current_index += 1

        if self.current_index >= len(self.patches):
            # Sequence complete
            self._on_sequence_complete()
        else:
            # Brief pause then show next patch
            QTimer.singleShot(self.settle_time, self._show_current_patch)

    def _on_sequence_complete(self):
        """Handle completion of measurement sequence."""
        self.running = False
        self.measurement_timer.stop()

        self._play_complete_beep()

        self.status_label.setText("Measurement sequence complete!")
        self.status_label.setStyleSheet("font-size: 12px; color: #4caf50;")
        self.patch_counter.setText(f"Complete: {len(self.patches)} patches")

        # Show completion color (white)
        self.color_patch.setStyleSheet("""
            QFrame {
                background-color: rgb(255, 255, 255);
                border: 3px solid #4caf50;
                border-radius: 4px;
            }
        """)

        # Emit completion signal
        self.sequence_complete.emit()

        # Close after delay
        QTimer.singleShot(1500, self.close)

    def _cancel_measurement(self):
        """Cancel the measurement sequence."""
        self.running = False
        self.measurement_timer.stop()
        self.close()

    def closeEvent(self, event):
        """Handle window close."""
        self.running = False
        self.measurement_timer.stop()
        self.closed.emit()
        super().closeEvent(event)
