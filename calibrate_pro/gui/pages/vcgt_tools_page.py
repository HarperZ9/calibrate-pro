"""
VCGT Tools Page - LUT to VCGT Conversion and export.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from calibrate_pro.gui.theme import COLORS


class VCGTToolsPage(QWidget):
    """VCGT (Video Card Gamma Table) tools for LUT conversion and export."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        # Header
        header = QLabel("VCGT Tools")
        header.setStyleSheet("font-size: 20px; font-weight: 600;")
        layout.addWidget(header)

        description = QLabel(
            "Convert 3D LUTs to 1D VCGT (Video Card Gamma Table) curves for use with ICC profiles "
            "or direct GPU loading. VCGT provides per-channel gamma correction at the video card level."
        )
        description.setWordWrap(True)
        description.setStyleSheet(f"color: {COLORS['text_secondary']};")
        layout.addWidget(description)

        # Main content
        content = QHBoxLayout()
        content.setSpacing(24)

        # Left panel: Conversion tools
        tools_widget = QWidget()
        tools_layout = QVBoxLayout(tools_widget)
        tools_layout.setContentsMargins(0, 0, 0, 0)
        tools_layout.setSpacing(16)

        # Input LUT
        input_group = QGroupBox("Input 3D LUT")
        input_layout = QVBoxLayout(input_group)

        lut_row = QHBoxLayout()
        self.lut_path = QLineEdit()
        self.lut_path.setPlaceholderText("Select a .cube, .3dl, or .mga file...")
        lut_row.addWidget(self.lut_path)

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_lut)
        lut_row.addWidget(browse_btn)

        input_layout.addLayout(lut_row)

        # LUT info
        self.lut_info = QLabel("No LUT loaded")
        self.lut_info.setStyleSheet(f"color: {COLORS['text_secondary']};")
        input_layout.addWidget(self.lut_info)

        tools_layout.addWidget(input_group)

        # Conversion settings
        settings_group = QGroupBox("Conversion Settings")
        settings_layout = QFormLayout(settings_group)

        self.method_combo = QComboBox()
        self.method_combo.addItems(
            [
                "Neutral Axis (grayscale extraction)",
                "Channel Maximum (preserve saturation)",
                "Luminance Weighted (perceptual)",
                "Diagonal Average",
            ]
        )
        settings_layout.addRow("Extraction Method:", self.method_combo)

        self.output_size = QComboBox()
        self.output_size.addItems(["256 points", "1024 points", "4096 points", "16384 points"])
        self.output_size.setCurrentIndex(2)  # Default to 4096
        settings_layout.addRow("Output Resolution:", self.output_size)

        tools_layout.addWidget(settings_group)

        # Export options
        export_group = QGroupBox("Export Format")
        export_layout = QVBoxLayout(export_group)

        self.export_cal = QCheckBox("ArgyllCMS .cal format")
        self.export_cal.setChecked(True)
        export_layout.addWidget(self.export_cal)

        self.export_csv = QCheckBox("CSV spreadsheet")
        export_layout.addWidget(self.export_csv)

        self.export_cube1d = QCheckBox("1D .cube format")
        self.export_cube1d.setChecked(True)
        export_layout.addWidget(self.export_cube1d)

        self.embed_icc = QCheckBox("Embed in new ICC profile")
        export_layout.addWidget(self.embed_icc)

        tools_layout.addWidget(export_group)

        # Action buttons
        actions_layout = QHBoxLayout()

        convert_btn = QPushButton("Convert to VCGT")
        convert_btn.setProperty("primary", True)
        convert_btn.clicked.connect(self._convert_to_vcgt)
        actions_layout.addWidget(convert_btn)

        apply_btn = QPushButton("Apply to Display")
        apply_btn.clicked.connect(self._apply_vcgt)
        actions_layout.addWidget(apply_btn)

        reset_btn = QPushButton("Reset Gamma")
        reset_btn.setToolTip("Reset display gamma to linear (remove all VCGT corrections)")
        reset_btn.clicked.connect(self._reset_vcgt)
        actions_layout.addWidget(reset_btn)

        tools_layout.addLayout(actions_layout)
        tools_layout.addStretch()

        content.addWidget(tools_widget, stretch=1)

        # Right panel: Preview
        preview_widget = QWidget()
        preview_layout = QVBoxLayout(preview_widget)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(16)

        # Curve preview
        curve_group = QGroupBox("VCGT Curve Preview")
        curve_layout = QVBoxLayout(curve_group)

        # Placeholder for curve visualization
        curve_preview = QFrame()
        curve_preview.setMinimumHeight(300)
        curve_preview.setStyleSheet(f"""
            background-color: {COLORS["surface_alt"]};
            border-radius: 8px;
            border: 1px solid {COLORS["border"]};
        """)

        curve_info = QLabel(
            "Load a LUT file to preview the VCGT curves.\n\n"
            "Red = Red channel\nGreen = Green channel\nBlue = Blue channel\n"
            "Gray = Neutral diagonal"
        )
        curve_info.setStyleSheet(f"color: {COLORS['text_secondary']}; padding: 16px;")
        curve_info.setAlignment(Qt.AlignmentFlag.AlignCenter)

        curve_placeholder_layout = QVBoxLayout(curve_preview)
        curve_placeholder_layout.addWidget(curve_info)

        curve_layout.addWidget(curve_preview)
        preview_layout.addWidget(curve_group)

        # Stats
        stats_group = QGroupBox("Conversion Statistics")
        stats_layout = QFormLayout(stats_group)

        self.stats_max_r = QLabel("-")
        stats_layout.addRow("Red Max Deviation:", self.stats_max_r)

        self.stats_max_g = QLabel("-")
        stats_layout.addRow("Green Max Deviation:", self.stats_max_g)

        self.stats_max_b = QLabel("-")
        stats_layout.addRow("Blue Max Deviation:", self.stats_max_b)

        self.stats_avg = QLabel("-")
        stats_layout.addRow("Average Deviation:", self.stats_avg)

        preview_layout.addWidget(stats_group)
        preview_layout.addStretch()

        content.addWidget(preview_widget, stretch=1)
        layout.addLayout(content)

    def _browse_lut(self):
        """Browse for a LUT file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select 3D LUT File", "", "LUT Files (*.cube *.3dl *.mga);;All Files (*.*)"
        )
        if file_path:
            self.lut_path.setText(file_path)
            self._load_lut_info(file_path)

    def _load_lut_info(self, file_path: str):
        """Load and display LUT information."""
        try:
            from pathlib import Path

            path = Path(file_path)

            if path.suffix.lower() == ".cube":
                # Parse CUBE file header
                with open(path) as f:
                    lines = f.readlines()[:20]

                size = "Unknown"
                title = path.stem
                for line in lines:
                    if line.startswith("LUT_3D_SIZE"):
                        size = line.split()[-1]
                    elif line.startswith("TITLE"):
                        title = line.split('"')[1] if '"' in line else line.split()[-1]

                self.lut_info.setText(f"3D LUT: {title}\nGrid size: {size}x{size}x{size}")
                self.lut_info.setStyleSheet(f"color: {COLORS['success']};")
            else:
                self.lut_info.setText(f"Loaded: {path.name}")
                self.lut_info.setStyleSheet(f"color: {COLORS['success']};")

        except Exception as e:
            self.lut_info.setText(f"Error loading LUT: {str(e)[:50]}")
            self.lut_info.setStyleSheet(f"color: {COLORS['error']};")

    def _convert_to_vcgt(self):
        """Convert loaded LUT to VCGT."""
        lut_path = self.lut_path.text()
        if not lut_path:
            QMessageBox.warning(self, "No LUT", "Please select a 3D LUT file first.")
            return

        try:
            from pathlib import Path

            from calibrate_pro.core.lut_engine import LUT3D
            from calibrate_pro.core.vcgt import export_vcgt_cal, export_vcgt_csv, export_vcgt_cube1d, lut3d_to_vcgt

            # Load the LUT
            lut = LUT3D.load(lut_path)

            # Get output size
            size_map = {"256 points": 256, "1024 points": 1024, "4096 points": 4096, "16384 points": 16384}
            output_size = size_map.get(self.output_size.currentText(), 4096)

            # Get method
            method_map = {
                "Neutral Axis (grayscale extraction)": "neutral_axis",
                "Channel Maximum (preserve saturation)": "channel_max",
                "Luminance Weighted (perceptual)": "luminance",
                "Diagonal Average": "diagonal",
            }
            method = method_map.get(self.method_combo.currentText(), "neutral_axis")

            # Convert
            vcgt = lut3d_to_vcgt(lut.data, output_size=output_size, method=method)

            # Export
            base_path = Path(lut_path).with_suffix("")
            exported = []

            if self.export_cal.isChecked():
                cal_path = str(base_path) + "_vcgt.cal"
                export_vcgt_cal(vcgt, cal_path)
                exported.append(cal_path)

            if self.export_csv.isChecked():
                csv_path = str(base_path) + "_vcgt.csv"
                export_vcgt_csv(vcgt, csv_path)
                exported.append(csv_path)

            if self.export_cube1d.isChecked():
                cube_path = str(base_path) + "_1d.cube"
                export_vcgt_cube1d(vcgt, cube_path)
                exported.append(cube_path)

            # Update stats
            import numpy as np

            linear = np.linspace(0, 1, vcgt.size)
            self.stats_max_r.setText(f"{np.max(np.abs(vcgt.red - linear)):.4f}")
            self.stats_max_g.setText(f"{np.max(np.abs(vcgt.green - linear)):.4f}")
            self.stats_max_b.setText(f"{np.max(np.abs(vcgt.blue - linear)):.4f}")
            avg_dev = np.mean(
                [
                    np.mean(np.abs(vcgt.red - linear)),
                    np.mean(np.abs(vcgt.green - linear)),
                    np.mean(np.abs(vcgt.blue - linear)),
                ]
            )
            self.stats_avg.setText(f"{avg_dev:.4f}")

            QMessageBox.information(self, "Conversion Complete", "VCGT curves exported to:\n\n" + "\n".join(exported))

        except Exception as e:
            QMessageBox.critical(self, "Conversion Error", str(e))

    def _apply_vcgt(self):
        """Apply VCGT to current display via Windows gamma ramp API."""
        lut_path = self.lut_path.text()
        if not lut_path:
            QMessageBox.warning(self, "No LUT", "Please select and convert a 3D LUT file first.")
            return

        # Confirm with user
        reply = QMessageBox.question(
            self,
            "Apply VCGT",
            "This will apply the VCGT gamma correction to your primary display.\n\n"
            "The changes modify the Windows gamma ramp and will remain active "
            "until system restart or manual reset.\n\n"
            "Do you want to continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            from calibrate_pro.core.lut_engine import LUT3D
            from calibrate_pro.core.vcgt import apply_vcgt_windows, lut3d_to_vcgt

            # Load the 3D LUT
            lut = LUT3D.load(lut_path)

            # Get the conversion method from combo
            method_map = {
                "Neutral Axis (grayscale extraction)": "neutral_axis",
                "Channel Maximum (preserve saturation)": "channel_max",
                "Luminance Weighted (perceptual)": "luminance",
                "Diagonal Average": "diagonal",
            }
            method = method_map.get(self.method_combo.currentText(), "neutral_axis")

            # Convert 3D LUT to VCGT curves
            vcgt = lut3d_to_vcgt(lut.data, output_size=256, method=method)

            # Apply to primary display (index 0)
            success = apply_vcgt_windows(vcgt, display_index=0)

            if success:
                QMessageBox.information(
                    self,
                    "VCGT Applied",
                    "VCGT gamma correction has been applied to the primary display.\n\n"
                    "The correction is now active. To remove it:\n"
                    "- Use the 'Reset Gamma' button below, or\n"
                    "- Restart your computer",
                )
            else:
                QMessageBox.warning(
                    self,
                    "Application Failed",
                    "Failed to apply VCGT. This may be due to:\n"
                    "- Insufficient permissions\n"
                    "- Display driver limitations\n"
                    "- Windows color management restrictions\n\n"
                    "Try running as Administrator.",
                )

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to apply VCGT:\n\n{str(e)}")

    def _reset_vcgt(self):
        """Reset display gamma to linear (remove VCGT correction)."""
        try:
            from calibrate_pro.core.vcgt import reset_vcgt_windows

            success = reset_vcgt_windows(display_index=0)

            if success:
                QMessageBox.information(
                    self, "Reset Complete", "Display gamma has been reset to linear (no correction)."
                )
            else:
                QMessageBox.warning(self, "Reset Failed", "Failed to reset gamma ramp.")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
