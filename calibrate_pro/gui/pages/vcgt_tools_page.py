"""
VCGT Tools Page - LUT to VCGT Conversion and export.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
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
        self._pending_vcgt_source: str | None = None
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
        """Defer conversion until pure exporters are separated from writers."""
        lut_path = self.lut_path.text()
        if not lut_path:
            QMessageBox.warning(self, "No LUT", "Please select a 3D LUT file first.")
            return
        self._pending_vcgt_source = lut_path
        QMessageBox.information(
            self,
            "Conversion Deferred",
            "No VCGT was exported or applied. Version 1.1 keeps conversion disabled until its pure exporter is isolated from display writers.",
        )

    def _apply_vcgt(self):
        """Stage a VCGT source selection without applying a gamma ramp."""
        lut_path = self.lut_path.text()
        if not lut_path:
            QMessageBox.warning(self, "No LUT", "Please select and convert a 3D LUT file first.")
            return

        self._pending_vcgt_source = lut_path
        QMessageBox.information(
            self,
            "Confirmation Required",
            "No gamma ramp was changed. Convert to a bounded VCGT asset, then review and confirm its exact apply plan.",
        )

    def _reset_vcgt(self):
        """Keep gamma reset behind an explicit confirmed plan."""
        QMessageBox.information(
            self,
            "Confirmation Required",
            "No gamma ramp was reset. Review and confirm a reset plan in Calibrate.",
        )
