"""
Calibration Profile Details Widget

Displays detailed calibration information for each monitor including:
- Panel type and specifications
- Calibration status and Delta E
- LUT file information
- Color correction details
- Auto-load status
"""

import hashlib
import os

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from calibrate_pro.verification.provenance import EvidenceKind, MetricValue

# Colors matching main theme
COLORS = {
    "background": "#1a1a1a",
    "surface": "#2d2d2d",
    "surface_alt": "#383838",
    "border": "#404040",
    "text_primary": "#e0e0e0",
    "text_secondary": "#a0a0a0",
    "accent": "#4a9eff",
    "success": "#4caf50",
    "warning": "#ff9800",
    "error": "#f44336",
}


class CalibrationProfileCard(QFrame):
    """Card showing detailed calibration profile for a single display."""

    def __init__(self, display_id: int, parent=None):
        super().__init__(parent)
        self.display_id = display_id
        self.profile_data = {}
        self._setup_ui()
        self._load_profile()

    def _setup_ui(self):
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS["surface"]};
                border: 1px solid {COLORS["border"]};
                border-radius: 12px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Header with display name and status
        header = QHBoxLayout()

        self.title_label = QLabel(f"Display {self.display_id}")
        self.title_label.setStyleSheet("font-size: 18px; font-weight: 700;")
        header.addWidget(self.title_label)

        header.addStretch()

        self.status_label = QLabel("Loading...")
        self.status_label.setStyleSheet(f"""
            background-color: {COLORS["surface_alt"]};
            padding: 6px 12px;
            border-radius: 12px;
            font-weight: 600;
        """)
        header.addWidget(self.status_label)

        layout.addLayout(header)

        # Panel info section
        panel_group = QGroupBox("Panel Information")
        panel_layout = QGridLayout(panel_group)
        panel_layout.setSpacing(8)

        self.manufacturer_label = self._create_info_row(panel_layout, 0, "Manufacturer:", "-")
        self.model_label = self._create_info_row(panel_layout, 1, "Model:", "-")
        self.panel_type_label = self._create_info_row(panel_layout, 2, "Panel Type:", "-")
        self.resolution_label = self._create_info_row(panel_layout, 3, "Resolution:", "-")
        self.gamut_label = self._create_info_row(panel_layout, 4, "Native Gamut:", "-")
        self.hdr_label = self._create_info_row(panel_layout, 5, "HDR Support:", "-")

        layout.addWidget(panel_group)

        # Calibration info section
        cal_group = QGroupBox("Calibration Status")
        cal_layout = QGridLayout(cal_group)
        cal_layout.setSpacing(8)

        self.target_label = self._create_info_row(cal_layout, 0, "Target:", "-")
        self.delta_e_label = self._create_info_row(cal_layout, 1, "Delta E:", "-")
        self.grade_label = self._create_info_row(cal_layout, 2, "Grade:", "-")
        self.calibrated_date_label = self._create_info_row(cal_layout, 3, "Calibrated:", "-")

        layout.addWidget(cal_group)

        # LUT info section
        lut_group = QGroupBox("3D LUT Information")
        lut_layout = QGridLayout(lut_group)
        lut_layout.setSpacing(8)

        self.lut_file_label = self._create_info_row(lut_layout, 0, "LUT File:", "-")
        self.lut_size_label = self._create_info_row(lut_layout, 1, "LUT Size:", "-")
        self.lut_nodes_label = self._create_info_row(lut_layout, 2, "Color Nodes:", "-")
        self.lut_status_label = self._create_info_row(lut_layout, 3, "Status:", "-")

        layout.addWidget(lut_group)

        # Color correction preview
        correction_group = QGroupBox("Color Corrections Applied")
        correction_layout = QVBoxLayout(correction_group)

        self.correction_table = QTableWidget(4, 4)
        self.correction_table.setHorizontalHeaderLabels(["Color", "Native", "Corrected", "Delta"])
        self.correction_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.correction_table.verticalHeader().setVisible(False)
        self.correction_table.setMaximumHeight(150)
        self.correction_table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {COLORS["surface_alt"]};
                border: 1px solid {COLORS["border"]};
                border-radius: 6px;
            }}
        """)
        correction_layout.addWidget(self.correction_table)

        layout.addWidget(correction_group)

        # Action buttons
        button_layout = QHBoxLayout()

        self.reload_btn = QPushButton("Reload LUT")
        self.reload_btn.clicked.connect(self._reload_lut)
        button_layout.addWidget(self.reload_btn)

        self.recalibrate_btn = QPushButton("Recalibrate")
        self.recalibrate_btn.setStyleSheet(f"background-color: {COLORS['accent']};")
        self.recalibrate_btn.clicked.connect(self._recalibrate)
        button_layout.addWidget(self.recalibrate_btn)

        layout.addLayout(button_layout)

    def _create_info_row(self, layout: QGridLayout, row: int, label: str, value: str) -> QLabel:
        """Create a label-value row in a grid layout."""
        label_widget = QLabel(label)
        label_widget.setStyleSheet(f"color: {COLORS['text_secondary']};")
        layout.addWidget(label_widget, row, 0)

        value_widget = QLabel(value)
        value_widget.setStyleSheet("font-weight: 500;")
        layout.addWidget(value_widget, row, 1)

        return value_widget

    def _load_profile(self):
        """Load persisted, read-only calibration metadata for this display."""
        try:
            from calibrate_pro.panels.database import PanelDatabase
            from calibrate_pro.utils.startup_manager import StartupManager

            manager = StartupManager()
            db = PanelDatabase()

            profile = manager.get_display_calibration(self.display_id)
            if not profile:
                self._show_no_profile()
                return

            panel = db.get_panel(profile.model) if profile.model else None

            self.title_label.setText(f"Display {self.display_id} - {profile.display_name or 'Unknown'}")

            if profile.lut_path or profile.icc_path:
                self.status_label.setText("CALIBRATED")
                self.status_label.setStyleSheet(f"""
                    background-color: {COLORS["success"]};
                    color: white;
                    padding: 6px 12px;
                    border-radius: 12px;
                    font-weight: 600;
                """)
            else:
                self.status_label.setText("NOT CALIBRATED")
                self.status_label.setStyleSheet(f"""
                    background-color: {COLORS["warning"]};
                    color: white;
                    padding: 6px 12px;
                    border-radius: 12px;
                    font-weight: 600;
                """)

            self.manufacturer_label.setText("Unknown")
            self.model_label.setText(profile.model or "Unknown")
            self.panel_type_label.setText(panel.panel_type if panel else "Unknown")

            if panel:
                gamut = "Wide Gamut (DCI-P3+)" if panel.capabilities.wide_gamut else "sRGB"
                self.gamut_label.setText(gamut)
                hdr = "Yes" if panel.capabilities.hdr_capable else "No"
                self.hdr_label.setText(hdr)

            # Calibration info
            self.target_label.setText("HDR" if profile.hdr_mode else "sRGB")

            if profile.lut_path or profile.icc_path:
                delta_e = (
                    profile.delta_e_avg
                    if isinstance(profile.delta_e_avg, MetricValue)
                    else MetricValue(None, "dE2000", EvidenceKind.NOT_MEASURED)
                )
                self.delta_e_label.setText(delta_e.display_text())
                self.delta_e_label.setToolTip(f"Evidence source: {delta_e.source or 'Not measured'}")
                self.grade_label.setText("Not assigned")
                self.grade_label.setToolTip("No quality grade is assigned without an approved rubric.")

            if profile.last_calibrated:
                self.calibrated_date_label.setText(profile.last_calibrated.replace("T", " ")[:16])

            # LUT info
            if profile.lut_path and os.path.exists(profile.lut_path):
                self.lut_file_label.setText(os.path.basename(profile.lut_path))
                size_kb = os.path.getsize(profile.lut_path) / 1024
                self.lut_size_label.setText(f"{size_kb:.0f} KB")
                self.lut_nodes_label.setText("33x33x33 (35,937 nodes)")

                self.lut_status_label.setText("SAVED — apply confirmation required")
                self.lut_status_label.setStyleSheet(f"color: {COLORS['accent']}; font-weight: 500;")
            else:
                self.lut_file_label.setText("Not generated")
                self.lut_status_label.setText("None")

            # Color corrections table
            self._populate_corrections_table(panel)

        except Exception as e:
            self.status_label.setText(f"Error: {str(e)[:30]}")

    def _show_no_profile(self):
        """Show message when no profile is available."""
        self.status_label.setText("NO PROFILE")
        self.status_label.setStyleSheet(f"""
            background-color: {COLORS["error"]};
            color: white;
            padding: 6px 12px;
            border-radius: 12px;
            font-weight: 600;
        """)

    def _populate_corrections_table(self, panel):
        """Fill the corrections table with color data."""
        colors = ["Red", "Green", "Blue", "White"]

        srgb = {"Red": (0.64, 0.33), "Green": (0.30, 0.60), "Blue": (0.15, 0.06), "White": (0.3127, 0.3290)}

        source = None
        if panel:
            native = {
                "Red": (panel.native_primaries.red.x, panel.native_primaries.red.y),
                "Green": (panel.native_primaries.green.x, panel.native_primaries.green.y),
                "Blue": (panel.native_primaries.blue.x, panel.native_primaries.blue.y),
                "White": (panel.native_primaries.white.x, panel.native_primaries.white.y),
            }
            receipt = hashlib.sha256(repr(panel).encode("utf-8")).hexdigest()
            source = f"panel-characterization:{type(panel).__name__}:{receipt}"
        else:
            native = None

        for i, color in enumerate(colors):
            self.correction_table.setItem(i, 0, QTableWidgetItem(color))

            native_xy = native[color] if native else None
            if native_xy is None:
                self.correction_table.setItem(i, 1, QTableWidgetItem("Not measured"))
            else:
                nx, ny = native_xy
                self.correction_table.setItem(i, 1, QTableWidgetItem(f"({nx:.3f}, {ny:.3f})"))

            sx, sy = srgb[color]
            self.correction_table.setItem(i, 2, QTableWidgetItem(f"({sx:.3f}, {sy:.3f})"))

            if native_xy is None or source is None:
                delta = MetricValue(None, "xy distance", EvidenceKind.NOT_MEASURED)
            else:
                import math

                nx, ny = native_xy
                value = math.sqrt((sx - nx) ** 2 + (sy - ny) ** 2)
                delta = MetricValue(value, "xy distance", EvidenceKind.ESTIMATED, source)
            delta_item = QTableWidgetItem(delta.display_text(4))
            delta_item.setToolTip(f"Evidence source: {delta.source or 'Not measured'}")
            self.correction_table.setItem(i, 3, delta_item)

    def _reload_lut(self):
        """Explain the confirmed workflow; never reload directly from a card."""
        QMessageBox.information(
            self,
            "Confirmation Required",
            "No LUT was loaded. Open Calibrate to preview and confirm the exact display change.",
        )

    def _recalibrate(self):
        """Route recalibration to the review-first workflow."""
        QMessageBox.information(
            self,
            "Open Calibrate",
            f"No change was made to Display {self.display_id}. Build and confirm a new plan in Calibrate.",
        )


class CalibrationDetailsWidget(QWidget):
    """Widget containing calibration details for all displays."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header_frame = QFrame()
        header_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS["surface"]};
                border-bottom: 1px solid {COLORS["border"]};
            }}
        """)
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(24, 16, 24, 16)

        title = QLabel("Calibration Profiles")
        title.setStyleSheet("font-size: 20px; font-weight: 700;")
        header_layout.addWidget(title)

        header_layout.addStretch()

        # Auto-load status
        self.autoload_label = QLabel("Auto-Load: Checking...")
        self.autoload_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
        header_layout.addWidget(self.autoload_label)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh_profiles)
        header_layout.addWidget(refresh_btn)

        layout.addWidget(header_frame)

        # Scrollable content area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; }")

        content = QWidget()
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setContentsMargins(24, 24, 24, 24)
        self.content_layout.setSpacing(20)

        scroll.setWidget(content)
        layout.addWidget(scroll)

        # Load profiles
        QTimer.singleShot(100, self.refresh_profiles)

    def refresh_profiles(self):
        """Refresh all calibration profile cards."""
        # Clear existing
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        try:
            from calibrate_pro.utils.startup_manager import StartupManager

            manager = StartupManager()
            displays = manager.get_all_calibrations().values()

            self.autoload_label.setText("Auto-Apply: Disabled — confirmation required")
            self.autoload_label.setStyleSheet(f"color: {COLORS['warning']};")

            # Create card for each display
            for display in displays:
                card = CalibrationProfileCard(display.display_id)
                self.content_layout.addWidget(card)

            # Add spacer at bottom
            self.content_layout.addStretch()

        except Exception as e:
            error_label = QLabel(f"Error loading profiles: {e}")
            error_label.setStyleSheet(f"color: {COLORS['error']};")
            self.content_layout.addWidget(error_label)
