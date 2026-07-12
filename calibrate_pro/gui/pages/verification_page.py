"""Evidence-labelled ColorChecker and grayscale verification display."""

import hashlib

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from calibrate_pro.gui.theme import COLORS
from calibrate_pro.verification.provenance import EvidenceKind, MetricValue


def _not_measured(unit: str) -> MetricValue:
    return MetricValue(None, unit, EvidenceKind.NOT_MEASURED)


def _estimated_metric(value: object, unit: str, source: str) -> MetricValue:
    if isinstance(value, MetricValue):
        return value
    if type(value) in {int, float}:
        return MetricValue(float(value), unit, EvidenceKind.ESTIMATED, source)
    return _not_measured(unit)


class VerificationPage(QWidget):
    """Verification results with ColorChecker and grayscale display."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        # Header
        header_layout = QHBoxLayout()
        header = QLabel("Calibration Verification")
        header.setStyleSheet("font-size: 20px; font-weight: 600;")
        header_layout.addWidget(header)
        header_layout.addStretch()

        verify_btn = QPushButton("Run Verification")
        verify_btn.setProperty("primary", True)
        verify_btn.clicked.connect(self._run_verification)
        header_layout.addWidget(verify_btn)

        layout.addLayout(header_layout)

        # Tabs for different verification types
        tabs = QTabWidget()

        # ColorChecker Tab
        colorchecker_widget = self._create_colorchecker_tab()
        tabs.addTab(colorchecker_widget, "ColorChecker 24")

        # Grayscale Tab
        grayscale_widget = self._create_grayscale_tab()
        tabs.addTab(grayscale_widget, "Grayscale Ramp")

        # Summary Tab
        summary_widget = self._create_summary_tab()
        tabs.addTab(summary_widget, "Summary")

        layout.addWidget(tabs)

    def _create_colorchecker_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(16)

        # ColorChecker grid
        grid_widget = QWidget()
        grid_layout = QGridLayout(grid_widget)
        grid_layout.setSpacing(4)

        # Reference patch names. No observation is shown before verification.
        patches = [
            "Dark Skin",
            "Light Skin",
            "Blue Sky",
            "Foliage",
            "Blue Flower",
            "Bluish Green",
            "Orange",
            "Purplish Blue",
            "Moderate Red",
            "Purple",
            "Yellow Green",
            "Orange Yellow",
            "Blue",
            "Green",
            "Red",
            "Yellow",
            "Magenta",
            "Cyan",
            "White",
            "Neutral 8",
            "Neutral 6.5",
            "Neutral 5",
            "Neutral 3.5",
            "Black",
        ]

        # Approximate colors for visualization
        colors = [
            "#735244",
            "#c29682",
            "#627a9d",
            "#576c43",
            "#8580b1",
            "#67bdaa",
            "#d67e2c",
            "#505ba6",
            "#c15a63",
            "#5e3c6c",
            "#9dbc40",
            "#e0a32e",
            "#383d96",
            "#469449",
            "#af363c",
            "#e7c71f",
            "#bb5695",
            "#0885a1",
            "#f3f3f2",
            "#c8c8c8",
            "#a0a0a0",
            "#7a7a7a",
            "#555555",
            "#343434",
        ]

        for i, (name, color) in enumerate(zip(patches, colors)):
            row, col = divmod(i, 6)

            patch = QFrame()
            patch.setMinimumSize(80, 70)

            patch.setStyleSheet(f"""
                QFrame {{
                    background-color: {color};
                    border-radius: 6px;
                    border: 2px solid {COLORS["border"]};
                }}
            """)
            patch.setToolTip(f"{name}\nDelta E: Not measured")

            patch_layout = QVBoxLayout(patch)
            patch_layout.setContentsMargins(4, 4, 4, 4)
            patch_layout.addStretch()

            de_label = QLabel("Not measured")
            de_label.setStyleSheet(
                "color: white; font-weight: 700; font-size: 12px; background: rgba(0,0,0,0.5); border-radius: 3px; padding: 2px;"
            )
            de_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            patch_layout.addWidget(de_label)

            grid_layout.addWidget(patch, row, col)

        layout.addWidget(grid_widget)

        # Results summary
        results_layout = QHBoxLayout()

        avg_frame = self._create_result_stat("Average Delta E", "Not measured", COLORS["text_secondary"])
        max_frame = self._create_result_stat("Maximum Delta E", "Not measured", COLORS["text_secondary"])
        grade_frame = self._create_result_stat("Evidence", "Not measured", COLORS["text_secondary"])

        results_layout.addWidget(avg_frame)
        results_layout.addWidget(max_frame)
        results_layout.addWidget(grade_frame)
        results_layout.addStretch()

        layout.addLayout(results_layout)
        layout.addStretch()

        return widget

    def _create_result_stat(self, label: str, value: str, color: str) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(f"background-color: {COLORS['surface']}; border-radius: 8px;")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(20, 12, 20, 12)

        value_label = QLabel(value)
        value_label.setStyleSheet(f"font-size: 20px; font-weight: 700; color: {color};")
        layout.addWidget(value_label)

        label_widget = QLabel(label)
        label_widget.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        layout.addWidget(label_widget)

        return frame

    def _create_grayscale_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(16)

        # Grayscale ramp visualization
        ramp_widget = QWidget()
        ramp_layout = QHBoxLayout(ramp_widget)
        ramp_layout.setSpacing(2)

        for i in range(21):
            level = int(i * 255 / 20)
            gray = f"#{level:02x}{level:02x}{level:02x}"

            patch = QFrame()
            patch.setMinimumSize(40, 100)
            patch.setStyleSheet(f"background-color: {gray}; border-radius: 4px;")
            patch.setToolTip(f"Level {i * 5}%\nRGB: ({level}, {level}, {level})")
            ramp_layout.addWidget(patch)

        layout.addWidget(ramp_widget)

        # Gamma curve info
        info_group = QGroupBox("Grayscale Tracking")
        info_layout = QFormLayout(info_group)

        info_layout.addRow("Target Gamma:", QLabel("2.2 (Power Law)"))
        info_layout.addRow("Measured Gamma:", QLabel("Not measured"))
        info_layout.addRow("Max Deviation:", QLabel("Not measured"))
        info_layout.addRow("RGB Balance:", QLabel("Not measured"))

        layout.addWidget(info_group)
        layout.addStretch()

        return widget

    def _create_summary_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(16)

        # Summary table
        table = QTableWidget()
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(["Metric", "Observed", "Target"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setVisible(False)

        data = [
            ("Average Delta E", "Not measured", "Project target"),
            ("Maximum Delta E", "Not measured", "Project target"),
            ("White Point", "Not measured", "6504K (D65)"),
            ("Peak Luminance", "Not measured", "250 cd/m\u00b2"),
            ("Black Level", "Not measured", "0.1 cd/m\u00b2"),
            ("Contrast Ratio", "Not measured", "2500:1"),
            ("Gamma (avg)", "Not measured", "2.2"),
            ("sRGB Coverage", "Not measured", "Project target"),
            ("DCI-P3 Coverage", "Not measured", "Project target"),
        ]

        table.setRowCount(len(data))
        for row, (metric, measured, target) in enumerate(data):
            table.setItem(row, 0, QTableWidgetItem(metric))
            table.setItem(row, 1, QTableWidgetItem(measured))
            table.setItem(row, 2, QTableWidgetItem(target))

        layout.addWidget(table)

        # Export button
        export_btn = QPushButton("Export Report (PDF)")
        export_btn.setMaximumWidth(200)
        layout.addWidget(export_btn)

        layout.addStretch()
        return widget

    def _run_verification(self):
        """Run sensorless calibration verification using panel database."""
        try:
            from calibrate_pro.panels.database import get_database
            from calibrate_pro.sensorless.neuralux import SensorlessEngine

            # Get panel database
            db = get_database()

            # Get the fallback panel (or detected one in real implementation)
            panel = db.get_fallback()

            # Create engine and verify
            engine = SensorlessEngine()
            engine.current_panel = panel
            result = engine.verify_calibration(panel)

            receipt = hashlib.sha256(repr(panel).encode("utf-8")).hexdigest()
            source = f"panel-characterization:{panel.manufacturer}:{receipt}"
            avg_de = _estimated_metric(result.get("delta_e_avg"), "dE2000", source)
            max_de = _estimated_metric(result.get("delta_e_max"), "dE2000", source)
            result["delta_e_avg"] = avg_de
            result["delta_e_max"] = max_de

            # Show results dialog
            msg = QMessageBox(self)
            msg.setWindowTitle("Verification Results")
            msg.setIcon(QMessageBox.Icon.Information)

            msg.setText("<h3>Calibration Verification Complete</h3>")
            msg.setInformativeText(
                f"<p><b>Average Delta E:</b> {avg_de.display_text()}</p>"
                f"<p><b>Maximum Delta E:</b> {max_de.display_text()}</p>"
                f"<p><b>Evidence source:</b> {source}</p>"
                f"<br/>"
                f"<p style='color: gray'>Panel: {panel.manufacturer} {panel.panel_type}</p>"
            )
            msg.setDetailedText(
                "These metrics are estimates derived from panel characterization, not instrument observations.\n\n"
                "No quality grade is assigned without an approved rubric."
            )

            msg.exec()

            # Store verification data for display update
            self._last_verification = result

        except Exception as e:
            QMessageBox.critical(self, "Verification Error", f"Failed to run verification:\n\n{str(e)}")
