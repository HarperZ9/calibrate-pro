"""
Verification Page - ColorChecker results and grayscale verification display.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
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

        # ColorChecker patch names and simulated Delta E values
        patches = [
            ("Dark Skin", 0.69),
            ("Light Skin", 0.39),
            ("Blue Sky", 0.44),
            ("Foliage", 0.62),
            ("Blue Flower", 0.41),
            ("Bluish Green", 0.42),
            ("Orange", 0.83),
            ("Purplish Blue", 0.42),
            ("Moderate Red", 0.30),
            ("Purple", 1.03),
            ("Yellow Green", 0.57),
            ("Orange Yellow", 0.78),
            ("Blue", 0.80),
            ("Green", 0.60),
            ("Red", 0.72),
            ("Yellow", 0.48),
            ("Magenta", 0.37),
            ("Cyan", 2.93),
            ("White", 0.09),
            ("Neutral 8", 0.32),
            ("Neutral 6.5", 0.48),
            ("Neutral 5", 0.32),
            ("Neutral 3.5", 0.32),
            ("Black", 1.15),
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

        for i, ((name, de), color) in enumerate(zip(patches, colors)):
            row, col = divmod(i, 6)

            patch = QFrame()
            patch.setMinimumSize(80, 70)

            de_color = COLORS["success"] if de < 1 else COLORS["warning"] if de < 2 else COLORS["error"]

            patch.setStyleSheet(f"""
                QFrame {{
                    background-color: {color};
                    border-radius: 6px;
                    border: 2px solid {de_color};
                }}
            """)
            patch.setToolTip(f"{name}\nDelta E: {de:.2f}")

            patch_layout = QVBoxLayout(patch)
            patch_layout.setContentsMargins(4, 4, 4, 4)
            patch_layout.addStretch()

            de_label = QLabel(f"{de:.2f}")
            de_label.setStyleSheet(
                "color: white; font-weight: 700; font-size: 12px; background: rgba(0,0,0,0.5); border-radius: 3px; padding: 2px;"
            )
            de_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            patch_layout.addWidget(de_label)

            grid_layout.addWidget(patch, row, col)

        layout.addWidget(grid_widget)

        # Results summary
        results_layout = QHBoxLayout()

        avg_frame = self._create_result_stat("Average Delta E", "0.65", COLORS["success"])
        max_frame = self._create_result_stat("Maximum Delta E", "2.93", COLORS["warning"])
        grade_frame = self._create_result_stat("Grade", "Professional", COLORS["accent"])

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
        info_layout.addRow("Measured Gamma:", QLabel("2.198 (avg)"))
        info_layout.addRow("Max Deviation:", QLabel("0.8% at 20%"))
        info_layout.addRow("RGB Balance:", QLabel("< 0.5% deviation"))

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
        table.setHorizontalHeaderLabels(["Metric", "Measured", "Target"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setVisible(False)

        data = [
            ("Average Delta E", "0.65", "< 1.0"),
            ("Maximum Delta E", "2.93", "< 3.0"),
            ("White Point", "6498K", "6504K (D65)"),
            ("Peak Luminance", "248 cd/m\u00b2", "250 cd/m\u00b2"),
            ("Black Level", "0.098 cd/m\u00b2", "0.1 cd/m\u00b2"),
            ("Contrast Ratio", "2531:1", "2500:1"),
            ("Gamma (avg)", "2.198", "2.2"),
            ("sRGB Coverage", "100%", "100%"),
            ("DCI-P3 Coverage", "99.2%", ">95%"),
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

            # Update UI with results
            avg_de = result.get("delta_e_avg", 0.0)
            max_de = result.get("delta_e_max", 0.0)
            grade = result.get("grade", "Unknown")

            # Show results dialog
            msg = QMessageBox(self)
            msg.setWindowTitle("Verification Results")
            msg.setIcon(QMessageBox.Icon.Information)

            grade_color = COLORS["success"] if avg_de < 1.0 else COLORS["warning"] if avg_de < 2.0 else COLORS["error"]

            msg.setText("<h3>Calibration Verification Complete</h3>")
            msg.setInformativeText(
                f"<p><b>Average Delta E:</b> <span style='color: {grade_color}'>{avg_de:.2f}</span></p>"
                f"<p><b>Maximum Delta E:</b> {max_de:.2f}</p>"
                f"<p><b>Quality Grade:</b> {grade}</p>"
                f"<br/>"
                f"<p style='color: gray'>Panel: {panel.manufacturer} {panel.panel_type}</p>"
            )

            if avg_de < 1.0:
                msg.setDetailedText(
                    "Excellent calibration quality!\n\n"
                    "Your display is calibrated to professional standards with Delta E < 1.0. "
                    "This level of accuracy is suitable for professional color-critical work."
                )
            elif avg_de < 2.0:
                msg.setDetailedText(
                    "Good calibration quality.\n\n"
                    "Your display is calibrated to high consumer standards. "
                    "Color accuracy is suitable for most photo editing and content creation."
                )
            else:
                msg.setDetailedText(
                    "Calibration could be improved.\n\n"
                    "Consider re-running calibration or adjusting monitor settings. "
                    "The current accuracy may show visible color differences in critical work."
                )

            msg.exec()

            # Store verification data for display update
            self._last_verification = result

        except Exception as e:
            QMessageBox.critical(self, "Verification Error", f"Failed to run verification:\n\n{str(e)}")
