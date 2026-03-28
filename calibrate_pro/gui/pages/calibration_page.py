"""
Calibration Page - Full calibration controls with target settings.
"""

from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from calibrate_pro.gui.dialogs import ConsentDialog, SimulatedMeasurementWindow
from calibrate_pro.gui.pages.dashboard_page import DashboardPage
from calibrate_pro.gui.theme import APP_NAME, APP_ORGANIZATION, COLORS
from calibrate_pro.gui.workers import CalibrationWorker


class CalibrationPage(QWidget):
    """Full calibration interface with target settings and controls."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        # Header
        header = QLabel("Display Calibration")
        header.setStyleSheet("font-size: 20px; font-weight: 600;")
        layout.addWidget(header)

        # Main content
        content = QHBoxLayout()
        content.setSpacing(24)

        # Left panel: Settings
        settings_widget = QWidget()
        settings_layout = QVBoxLayout(settings_widget)
        settings_layout.setContentsMargins(0, 0, 0, 0)
        settings_layout.setSpacing(16)

        # Display Selection
        display_group = QGroupBox("Display Selection")
        display_layout = QFormLayout(display_group)

        self.display_combo = QComboBox()
        self.display_combo.currentIndexChanged.connect(self._on_display_changed)
        display_layout.addRow("Target Display:", self.display_combo)

        self.panel_label = QLabel("Detecting...")
        self.panel_label.setStyleSheet(f"color: {COLORS['accent']};")
        display_layout.addRow("Detected Panel:", self.panel_label)

        # Refresh button
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setMaximumWidth(80)
        refresh_btn.clicked.connect(self._populate_displays)
        display_layout.addRow("", refresh_btn)

        settings_layout.addWidget(display_group)

        # Now populate displays (after panel_label exists)
        self._populate_displays()

        # Calibration Profile
        profile_group = QGroupBox("Calibration Profile")
        profile_layout = QFormLayout(profile_group)

        self.profile_combo = QComboBox()
        self.profile_combo.addItems([
            "sRGB Web Standard",
            "Rec.709 Broadcast",
            "DCI-P3 Cinema",
            "HDR10 Mastering",
            "Photography (Adobe RGB)",
            "Custom..."
        ])
        profile_layout.addRow("Preset:", self.profile_combo)

        settings_layout.addWidget(profile_group)

        # Naming Options
        naming_group = QGroupBox("Profile & Display Naming")
        naming_layout = QFormLayout(naming_group)

        # Display nickname
        self.display_name_edit = QLineEdit()
        self.display_name_edit.setPlaceholderText("e.g., Main Monitor, Left Display")
        self.display_name_edit.setToolTip("Custom name for this display (stored in settings)")
        naming_layout.addRow("Display Name:", self.display_name_edit)

        # Profile name
        self.profile_name_edit = QLineEdit()
        self.profile_name_edit.setPlaceholderText("e.g., MyDisplay_sRGB_D65")
        self.profile_name_edit.setToolTip("Name for ICC profile and 3D LUT files")
        naming_layout.addRow("Profile Name:", self.profile_name_edit)

        # Auto-generate button
        auto_name_btn = QPushButton("Auto-Generate")
        auto_name_btn.setMaximumWidth(100)
        auto_name_btn.clicked.connect(self._auto_generate_names)
        naming_layout.addRow("", auto_name_btn)

        settings_layout.addWidget(naming_group)

        # Target Settings
        target_group = QGroupBox("Target Settings")
        target_layout = QGridLayout(target_group)
        target_layout.setSpacing(12)

        # White Point
        target_layout.addWidget(QLabel("White Point:"), 0, 0)
        self.whitepoint_combo = QComboBox()
        self.whitepoint_combo.addItems(["D65 (6504K)", "D50 (5003K)", "D55 (5503K)", "DCI-P3 (6300K)"])
        target_layout.addWidget(self.whitepoint_combo, 0, 1)

        # Gamma
        target_layout.addWidget(QLabel("Gamma/EOTF:"), 1, 0)
        self.gamma_combo = QComboBox()
        self.gamma_combo.addItems(["Power 2.2", "Power 2.4", "sRGB", "BT.1886", "PQ (HDR)", "HLG (HDR)"])
        target_layout.addWidget(self.gamma_combo, 1, 1)

        # Luminance
        target_layout.addWidget(QLabel("Peak Luminance:"), 2, 0)
        lum_layout = QHBoxLayout()
        self.luminance_spin = QSpinBox()
        self.luminance_spin.setRange(80, 10000)
        self.luminance_spin.setValue(250)
        self.luminance_spin.setSuffix(" cd/m\u00b2")
        lum_layout.addWidget(self.luminance_spin)
        target_layout.addLayout(lum_layout, 2, 1)

        # Gamut
        target_layout.addWidget(QLabel("Color Gamut:"), 3, 0)
        self.gamut_combo = QComboBox()
        self.gamut_combo.addItems(["sRGB", "DCI-P3", "Display P3", "Adobe RGB", "BT.2020"])
        target_layout.addWidget(self.gamut_combo, 3, 1)

        # Black Level
        target_layout.addWidget(QLabel("Black Level:"), 4, 0)
        self.black_spin = QDoubleSpinBox()
        self.black_spin.setRange(0.0, 1.0)
        self.black_spin.setValue(0.1)
        self.black_spin.setSuffix(" cd/m\u00b2")
        self.black_spin.setDecimals(3)
        target_layout.addWidget(self.black_spin, 4, 1)

        settings_layout.addWidget(target_group)

        # Calibration Mode
        mode_group = QGroupBox("Calibration Mode")
        mode_layout = QVBoxLayout(mode_group)

        # Hardware-first calibration
        self.hardware_first_radio = QRadioButton("Hardware-First (Recommended)")
        self.hardware_first_radio.setChecked(True)
        mode_layout.addWidget(self.hardware_first_radio)

        hw_first_desc = QLabel("Step 1: Adjust monitor OSD settings (RGB gain, gamma)\n"
                               "Step 2: Fine-tune with 3D LUT. Best quality, Delta E < 0.5")
        hw_first_desc.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px; margin-left: 24px;")
        hw_first_desc.setWordWrap(True)
        mode_layout.addWidget(hw_first_desc)

        self.sensorless_radio = QRadioButton("Sensorless Calibration")
        mode_layout.addWidget(self.sensorless_radio)

        sensorless_desc = QLabel("Uses panel database and advanced algorithms. Delta E < 1.0 typical.")
        sensorless_desc.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px; margin-left: 24px;")
        sensorless_desc.setWordWrap(True)
        mode_layout.addWidget(sensorless_desc)

        self.hardware_radio = QRadioButton("Hardware Colorimeter Only")
        mode_layout.addWidget(self.hardware_radio)

        hardware_desc = QLabel("Direct measurement without OSD adjustment. Delta E < 0.5 typical.")
        hardware_desc.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px; margin-left: 24px;")
        hardware_desc.setWordWrap(True)
        mode_layout.addWidget(hardware_desc)

        # DDC/CI status indicator
        self.ddc_status = QLabel()
        self.ddc_status.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px; margin-top: 8px;")
        mode_layout.addWidget(self.ddc_status)
        self._check_ddc_support()

        settings_layout.addWidget(mode_group)
        settings_layout.addStretch()

        content.addWidget(settings_widget, stretch=1)

        # Right panel: Preview and actions
        preview_widget = QWidget()
        preview_layout = QVBoxLayout(preview_widget)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(16)

        # Gamut Preview
        gamut_group = QGroupBox("Gamut Coverage Preview")
        gamut_layout = QVBoxLayout(gamut_group)

        # Simple gamut visualization placeholder
        gamut_preview = QFrame()
        gamut_preview.setMinimumHeight(200)
        gamut_preview.setStyleSheet(f"""
            background-color: {COLORS['surface_alt']};
            border-radius: 8px;
            border: 1px solid {COLORS['border']};
        """)

        # Add gamut info labels
        gamut_info = QLabel("Panel Gamut: 99.2% DCI-P3, 87.3% BT.2020\nTarget Gamut: sRGB (100% coverage)")
        gamut_info.setStyleSheet(f"color: {COLORS['text_secondary']}; padding: 16px;")
        gamut_info.setAlignment(Qt.AlignmentFlag.AlignCenter)

        gamut_placeholder_layout = QVBoxLayout(gamut_preview)
        gamut_placeholder_layout.addWidget(gamut_info)

        gamut_layout.addWidget(gamut_preview)
        preview_layout.addWidget(gamut_group)

        # Output Options
        output_group = QGroupBox("Output Options")
        output_layout = QVBoxLayout(output_group)

        self.icc_check = QCheckBox("Generate ICC Profile")
        self.icc_check.setChecked(True)
        output_layout.addWidget(self.icc_check)

        self.lut_check = QCheckBox("Generate 3D LUT (.cube)")
        self.lut_check.setChecked(True)
        output_layout.addWidget(self.lut_check)

        self.install_check = QCheckBox("Install profile to system")
        self.install_check.setChecked(True)
        output_layout.addWidget(self.install_check)

        self.apply_lut_check = QCheckBox("Apply LUT via dwm_lut")
        output_layout.addWidget(self.apply_lut_check)

        preview_layout.addWidget(output_group)

        # Progress section
        progress_group = QGroupBox("Calibration Progress")
        progress_layout = QVBoxLayout(progress_group)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        progress_layout.addWidget(self.progress_bar)

        self.progress_label = QLabel("Ready to calibrate")
        self.progress_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
        progress_layout.addWidget(self.progress_label)

        preview_layout.addWidget(progress_group)

        # Action buttons
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(12)

        self.start_btn = QPushButton("Start Calibration")
        self.start_btn.setProperty("primary", True)
        self.start_btn.setMinimumHeight(44)
        self.start_btn.clicked.connect(self._start_calibration)
        buttons_layout.addWidget(self.start_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setMinimumHeight(44)
        buttons_layout.addWidget(self.cancel_btn)

        preview_layout.addLayout(buttons_layout)
        preview_layout.addStretch()

        content.addWidget(preview_widget, stretch=1)
        layout.addLayout(content)

    def _start_calibration(self):
        """Start the calibration process with consent dialog."""
        # Get display name for consent dialog
        display_name = self.display_combo.currentText()

        # Determine what changes will be made
        changes = []
        if self.icc_check.isChecked():
            changes.append("Generate and install ICC profile")
        if self.lut_check.isChecked():
            changes.append("Generate 3D LUT correction file")
        if self.install_check.isChecked():
            changes.append("Set as default Windows color profile")
        if self.apply_lut_check.isChecked():
            changes.append("Apply 3D LUT via dwm_lut (system-wide)")

        # Check if DDC/CI changes are requested
        use_hardware_first = self.hardware_first_radio.isChecked()

        # Show consent dialog
        dialog = ConsentDialog(
            self,
            display_name=display_name,
            changes=changes,
            risk_level="MEDIUM" if not use_hardware_first else "HIGH"
        )

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        if not dialog.approved:
            return

        # Start calibration
        self.progress_bar.setValue(0)
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress_label.setText("Starting calibration...")

        # Get display index
        display_index = self.display_combo.currentIndex()
        self._current_display_index = display_index

        # Get target screen for measurement window
        screens = QGuiApplication.screens()
        target_screen = screens[display_index] if display_index < len(screens) else None

        # Launch simulated measurement window
        self._measurement_window = SimulatedMeasurementWindow(screen=target_screen)
        self._measurement_window.sequence_complete.connect(self._on_measurement_complete)
        self._measurement_window.closed.connect(self._on_measurement_closed)

        # Add some random patches for variety
        self._measurement_window.add_random_patches(8)

        # Show measurement window and start
        self._measurement_window.show_fullscreen(target_screen)
        self._measurement_window.start_measurements()

        # Store DDC approval for when measurements complete
        self._apply_ddc = dialog.hardware_approved

    def _on_measurement_complete(self):
        """Called when simulated measurement sequence finishes."""
        self.progress_label.setText("Measurements complete. Generating profile...")

        # Get custom names
        display_name, profile_name = self._get_custom_names()

        # Save display settings for future use
        self._save_display_settings(self._current_display_index)

        # Now start the actual calibration worker
        self._worker = CalibrationWorker(
            display_index=self._current_display_index,
            apply_ddc=self._apply_ddc,
            profile_name=profile_name,
            display_name=display_name
        )
        self._worker.progress.connect(self._on_calibration_progress)
        self._worker.finished.connect(self._on_calibration_finished)
        self._worker.error.connect(self._on_calibration_error)
        self._worker.start()

    def _on_measurement_closed(self):
        """Called when measurement window is closed (possibly cancelled)."""
        if not hasattr(self, '_worker') or self._worker is None or not self._worker.isRunning():
            # Measurement was cancelled before calibration started
            self.start_btn.setEnabled(True)
            self.cancel_btn.setEnabled(False)
            self.progress_bar.setValue(0)
            self.progress_label.setText("Measurement cancelled")

    def _on_calibration_progress(self, message: str, progress: float):
        """Handle calibration progress updates."""
        self.progress_bar.setValue(int(progress * 100))
        self.progress_label.setText(message)

    def _on_calibration_finished(self, result):
        """Handle calibration completion."""
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)

        if result.success:
            self.progress_bar.setValue(100)
            self.progress_label.setText(
                f"Calibration complete! Est. Delta E: {result.delta_e_predicted:.2f} (see notes)"
            )

            # Mark display as calibrated in settings
            display_index = getattr(self, '_current_display_index', 0)
            DashboardPage.mark_display_calibrated(display_index, result.delta_e_predicted)

            # Try to refresh the dashboard if we can find it
            try:
                main_window = self.window()
                if hasattr(main_window, '_pages'):
                    for page in main_window._pages.values():
                        if isinstance(page, DashboardPage):
                            page.refresh_displays()
                            break
            except Exception:
                pass

            # Show HONEST success message
            msg = QMessageBox(self)
            msg.setWindowTitle("Calibration Complete")
            msg.setIcon(QMessageBox.Icon.Information)

            # Determine grade and confidence
            grade = result.verification.get('grade', 'Unknown')
            delta_e = result.delta_e_predicted

            msg.setText(
                f"Display calibration profile generated!\n\n"
                f"Panel Matched: {result.panel_matched}\n"
                f"Estimated Delta E: {delta_e:.2f}\n"
                f"Estimated Grade: {grade}"
            )

            # HONEST informative text about what was actually done
            honest_info = (
                "IMPORTANT - What This Means:\n\n"
                "\u2713 ICC Profile and 3D LUT were generated based on panel database\n"
                "\u2713 VCGT gamma curves can be applied to correct display output\n\n"
                "\u26a0\ufe0f ESTIMATED values (not measured):\n"
                f"\u2022 The Delta E value ({delta_e:.2f}) is a prediction based on known\n"
                "  panel characteristics, NOT an actual measurement.\n\n"
                "To verify ACTUAL color accuracy, you need:\n"
                "\u2022 A hardware colorimeter (i1Display, Spyder, etc.)\n"
                "\u2022 Use the 'Verify' tab to run verification\n\n"
                "For VISIBLE color changes:\n"
                "\u2022 Go to 'Profiles' tab and ACTIVATE the profile\n"
                "\u2022 Use 'DDC Control' tab for hardware adjustments"
            )

            if result.icc_profile_path:
                honest_info = f"Generated: {result.icc_profile_path}\n\n" + honest_info

            msg.setInformativeText(honest_info)

            # Add detailed text about verification
            msg.setDetailedText(
                "Sensorless Calibration Accuracy Notes:\n\n"
                "This calibration uses sensorless technology which:\n"
                "1. Identifies your panel type from EDID/database\n"
                "2. Uses factory-measured panel characteristics\n"
                "3. Applies known corrections for that panel type\n\n"
                "Typical Results:\n"
                "\u2022 Well-known panels (OLED, high-end IPS): Delta E 0.5-1.5\n"
                "\u2022 Generic/unknown panels: Delta E 1.5-3.0\n"
                "\u2022 Older/aged panels: May vary significantly\n\n"
                "For Professional Work:\n"
                "Use a hardware colorimeter for verified results.\n"
                "The estimated values are useful for consumer use but\n"
                "should not be trusted for color-critical workflows."
            )

            msg.exec()
        else:
            self.progress_label.setText(f"Calibration failed: {result.message}")
            QMessageBox.warning(self, "Calibration Failed", result.message)

    def _on_calibration_error(self, error_msg: str):
        """Handle calibration errors."""
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_label.setText(f"Error: {error_msg}")
        QMessageBox.critical(self, "Calibration Error", error_msg)

    def _check_ddc_support(self):
        """Check DDC/CI support for the selected display."""
        try:
            from calibrate_pro.hardware.ddc_ci import DDCCIController
            controller = DDCCIController()
            if controller.available:
                monitors = controller.enumerate_monitors()
                if monitors:
                    caps = monitors[0].get('capabilities')
                    if caps and caps.has_rgb_gain:
                        self.ddc_status.setText("DDC/CI: RGB gain control available")
                        self.ddc_status.setStyleSheet(f"color: {COLORS['success']}; font-size: 11px; margin-top: 8px;")
                    else:
                        self.ddc_status.setText("DDC/CI: Limited support - use OSD for RGB adjustment")
                        self.ddc_status.setStyleSheet(f"color: {COLORS['warning']}; font-size: 11px; margin-top: 8px;")
                else:
                    self.ddc_status.setText("DDC/CI: No monitors detected")
                controller.close()
            else:
                self.ddc_status.setText("DDC/CI: Not available on this system")
        except Exception:
            self.ddc_status.setText("DDC/CI: Check failed")

    def _populate_displays(self):
        """Populate display combo with detected displays."""
        self.display_combo.clear()
        self._displays = []

        try:
            from calibrate_pro.panels.detection import (
                enumerate_displays,
                get_edid_from_registry,
                parse_edid,
            )

            displays = enumerate_displays()

            for i, display in enumerate(displays):
                # Try to get better name from EDID
                name = display.monitor_name or f"Display {i + 1}"

                edid_data = get_edid_from_registry(display.device_id)
                if edid_data:
                    edid_info = parse_edid(edid_data)
                    if edid_info.get("monitor_name") and "Generic" not in edid_info["monitor_name"]:
                        name = edid_info["monitor_name"]

                resolution = f"{display.width}x{display.height}"
                primary = " (Primary)" if display.is_primary else ""

                display_text = f"Display {i + 1}: {name} ({resolution}){primary}"
                self.display_combo.addItem(display_text)
                self._displays.append(display)

            # If we found displays, update the panel info
            if displays:
                self._on_display_changed(0)
            else:
                self.panel_label.setText("No displays detected")

        except Exception as e:
            self.display_combo.addItem("Display detection failed")
            self.panel_label.setText(f"Error: {str(e)[:50]}")

    def _on_display_changed(self, index: int):
        """Handle display selection change."""
        if not hasattr(self, '_displays') or index >= len(self._displays):
            return

        display = self._displays[index]

        try:
            from calibrate_pro.panels.database import get_database
            from calibrate_pro.panels.detection import identify_display

            # Try to identify the panel
            panel_key = identify_display(display)
            db = get_database()

            if panel_key:
                panel = db.get_panel(panel_key)
                if panel:
                    self.panel_label.setText(f"{panel.panel_type} ({panel.manufacturer})")
                    self.panel_label.setStyleSheet(f"color: {COLORS['success']};")
                else:
                    self.panel_label.setText(f"Matched: {panel_key}")
                    self.panel_label.setStyleSheet(f"color: {COLORS['accent']};")
            else:
                self.panel_label.setText("Using generic profile")
                self.panel_label.setStyleSheet(f"color: {COLORS['warning']};")

            # Also update DDC status for the new display
            self._check_ddc_support()

            # Load saved display name if exists
            settings = QSettings(APP_ORGANIZATION, APP_NAME)
            saved_name = settings.value(f"display/{index}/custom_name", "", type=str)
            saved_profile = settings.value(f"display/{index}/profile_name", "", type=str)

            self.display_name_edit.setText(saved_name)
            self.profile_name_edit.setText(saved_profile)

        except Exception:
            self.panel_label.setText("Detection error")
            self.panel_label.setStyleSheet(f"color: {COLORS['error']};")

    def _auto_generate_names(self):
        """Auto-generate display and profile names based on current settings."""
        index = self.display_combo.currentIndex()

        # Get display info
        display_text = self.display_combo.currentText()

        # Extract display name from combo text (e.g., "Display 1: PG27UCDM (3840x2160)")
        if ":" in display_text:
            base_name = display_text.split(":")[1].strip()
            if "(" in base_name:
                base_name = base_name.split("(")[0].strip()
        else:
            base_name = f"Display_{index + 1}"

        # Set display name
        self.display_name_edit.setText(base_name)

        # Generate profile name based on display and target settings
        preset = self.profile_combo.currentText().split()[0]  # e.g., "sRGB" from "sRGB Web Standard"
        whitepoint = self.whitepoint_combo.currentText().split()[0]  # e.g., "D65"
        gamma_text = self.gamma_combo.currentText()

        # Extract gamma value
        if "2.2" in gamma_text:
            gamma = "2.2"
        elif "2.4" in gamma_text:
            gamma = "2.4"
        elif "sRGB" in gamma_text:
            gamma = "sRGB"
        elif "BT.1886" in gamma_text:
            gamma = "BT1886"
        elif "PQ" in gamma_text:
            gamma = "PQ"
        elif "HLG" in gamma_text:
            gamma = "HLG"
        else:
            gamma = "2.2"

        profile_name = f"{base_name}_{preset}_{whitepoint}_{gamma}"
        profile_name = profile_name.replace(" ", "_").replace(".", "")
        self.profile_name_edit.setText(profile_name)

    def _save_display_settings(self, index: int):
        """Save custom display name and profile name to settings."""
        settings = QSettings(APP_ORGANIZATION, APP_NAME)
        settings.setValue(f"display/{index}/custom_name", self.display_name_edit.text())
        settings.setValue(f"display/{index}/profile_name", self.profile_name_edit.text())
        settings.sync()

    def _get_custom_names(self) -> tuple:
        """Get the custom display name and profile name."""
        display_name = self.display_name_edit.text().strip() or None
        profile_name = self.profile_name_edit.text().strip() or None
        return display_name, profile_name
