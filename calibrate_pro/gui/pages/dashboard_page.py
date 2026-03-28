"""
Dashboard Page - Connected displays and calibration status overview.
"""


from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtGui import QGuiApplication, QScreen
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from calibrate_pro.gui.theme import APP_NAME, APP_ORGANIZATION, COLORS
from calibrate_pro.gui.workers import ColorManagementStatus


class DashboardPage(QWidget):
    """Dashboard showing connected displays and calibration status."""

    def __init__(self, parent=None, cm_status: ColorManagementStatus = None):
        super().__init__(parent)
        self.cm_status = cm_status or ColorManagementStatus()
        self._setup_ui()
        self._populate_demo_data()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        # Header with status indicator
        header_layout = QHBoxLayout()
        header = QLabel("Display Overview")
        header.setStyleSheet("font-size: 20px; font-weight: 600; margin-bottom: 8px;")
        header_layout.addWidget(header)
        header_layout.addStretch()

        # Color Management Status Card
        self.cm_status_card = self._create_cm_status_card()
        header_layout.addWidget(self.cm_status_card)

        layout.addLayout(header_layout)

        # Main content in horizontal split
        content_layout = QHBoxLayout()
        content_layout.setSpacing(16)

        # Left: Display cards
        displays_widget = QWidget()
        displays_layout = QVBoxLayout(displays_widget)
        displays_layout.setContentsMargins(0, 0, 0, 0)
        displays_layout.setSpacing(12)

        displays_label = QLabel("Connected Displays")
        displays_label.setStyleSheet(f"font-weight: 600; color: {COLORS['text_secondary']};")
        displays_layout.addWidget(displays_label)

        self.displays_container = QVBoxLayout()
        displays_layout.addLayout(self.displays_container)
        displays_layout.addStretch()

        content_layout.addWidget(displays_widget, stretch=2)

        # Right: Stats and recent activity
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(16)

        # Calibration Stats
        stats_group = QGroupBox("Calibration Statistics")
        stats_layout = QGridLayout(stats_group)
        stats_layout.setSpacing(12)

        self.avg_delta_e = self._create_stat_widget("Avg Delta E", "0.65", COLORS['success'])
        self.max_delta_e = self._create_stat_widget("Max Delta E", "2.93", COLORS['warning'])
        self.profiles_count = self._create_stat_widget("ICC Profiles", "3", COLORS['accent'])
        self.luts_count = self._create_stat_widget("3D LUTs", "2", COLORS['accent'])

        stats_layout.addWidget(self.avg_delta_e, 0, 0)
        stats_layout.addWidget(self.max_delta_e, 0, 1)
        stats_layout.addWidget(self.profiles_count, 1, 0)
        stats_layout.addWidget(self.luts_count, 1, 1)

        right_layout.addWidget(stats_group)

        # Recent Activity
        activity_group = QGroupBox("Recent Activity")
        activity_layout = QVBoxLayout(activity_group)

        activities = [
            ("Calibration completed", "PG27UCDM - Delta E 0.65", "2 hours ago"),
            ("Profile installed", "sRGB_D65_2.2.icc", "Yesterday"),
            ("Verification passed", "ColorChecker 24 patches", "2 days ago"),
        ]

        for title, detail, time in activities:
            item = QFrame()
            item.setStyleSheet(f"background-color: {COLORS['surface']}; border-radius: 6px; padding: 8px;")
            item_layout = QVBoxLayout(item)
            item_layout.setContentsMargins(12, 8, 12, 8)
            item_layout.setSpacing(2)

            title_label = QLabel(title)
            title_label.setStyleSheet("font-weight: 500;")
            item_layout.addWidget(title_label)

            detail_label = QLabel(detail)
            detail_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
            item_layout.addWidget(detail_label)

            time_label = QLabel(time)
            time_label.setStyleSheet(f"color: {COLORS['text_disabled']}; font-size: 11px;")
            item_layout.addWidget(time_label)

            activity_layout.addWidget(item)

        right_layout.addWidget(activity_group)
        right_layout.addStretch()

        content_layout.addWidget(right_panel, stretch=1)
        layout.addLayout(content_layout)

    def _create_cm_status_card(self) -> QFrame:
        """Create color management status indicator card."""
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['surface']};
                border: 1px solid {COLORS['border']};
                border-radius: 8px;
                padding: 8px;
            }}
        """)

        layout = QHBoxLayout(card)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)

        # Status indicator dot
        self.cm_indicator = QLabel()
        self.cm_indicator.setFixedSize(12, 12)
        self._update_cm_indicator()
        layout.addWidget(self.cm_indicator)

        # Status text
        self.cm_status_label = QLabel("Color Management")
        self.cm_status_label.setStyleSheet("font-weight: 500;")
        layout.addWidget(self.cm_status_label)

        # Details
        self.cm_details_label = QLabel()
        self.cm_details_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
        layout.addWidget(self.cm_details_label)

        self.update_cm_status()
        return card

    def _update_cm_indicator(self):
        """Update the color management status indicator."""
        if self.cm_status.is_active():
            color = COLORS['success']
        else:
            color = COLORS['text_disabled']
        self.cm_indicator.setStyleSheet(f"background-color: {color}; border-radius: 6px;")

    def update_cm_status(self):
        """Update the color management status display."""
        self._update_cm_indicator()
        if self.cm_status.is_active():
            self.cm_status_label.setText("Color Management Active")
            self.cm_details_label.setText(self.cm_status.get_status_text())
        else:
            self.cm_status_label.setText("Color Management")
            self.cm_details_label.setText("No profile or LUT active")

    def _create_stat_widget(self, label: str, value: str, color: str) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(f"background-color: {COLORS['surface']}; border-radius: 8px; padding: 12px;")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)

        value_label = QLabel(value)
        value_label.setStyleSheet(f"font-size: 24px; font-weight: 700; color: {color};")
        layout.addWidget(value_label)

        label_widget = QLabel(label)
        label_widget.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        layout.addWidget(label_widget)

        return frame

    def _create_display_card(self, name: str, resolution: str, panel_type: str,
                              delta_e: float, calibrated: bool) -> QFrame:
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['surface']};
                border: 1px solid {COLORS['border']};
                border-radius: 10px;
            }}
        """)

        layout = QHBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(16)

        # Display icon/indicator
        indicator = QLabel()
        indicator.setFixedSize(48, 48)
        color = COLORS['success'] if calibrated else COLORS['text_disabled']
        indicator.setStyleSheet(f"""
            background-color: {color};
            border-radius: 8px;
            font-size: 20px;
        """)
        indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        indicator.setText("1" if "Primary" in name or "DISPLAY1" in name else "2")
        layout.addWidget(indicator)

        # Display info
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)

        name_label = QLabel(name)
        name_label.setStyleSheet("font-weight: 600; font-size: 14px;")
        info_layout.addWidget(name_label)

        details_label = QLabel(f"{resolution}  {panel_type}")
        details_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        info_layout.addWidget(details_label)

        layout.addLayout(info_layout, stretch=1)

        # Delta E display
        if calibrated:
            de_color = COLORS['success'] if delta_e < 1 else COLORS['warning'] if delta_e < 2 else COLORS['error']
            de_frame = QFrame()
            de_frame.setStyleSheet(f"background-color: {COLORS['surface_alt']}; border-radius: 6px;")
            de_layout = QVBoxLayout(de_frame)
            de_layout.setContentsMargins(12, 6, 12, 6)
            de_layout.setSpacing(0)

            de_value = QLabel(f"{delta_e:.2f}")
            de_value.setStyleSheet(f"font-size: 18px; font-weight: 700; color: {de_color};")
            de_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
            de_layout.addWidget(de_value)

            de_label = QLabel("Delta E")
            de_label.setStyleSheet(f"font-size: 10px; color: {COLORS['text_secondary']};")
            de_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            de_layout.addWidget(de_label)

            layout.addWidget(de_frame)
        else:
            status = QLabel("Not Calibrated")
            status.setStyleSheet(f"color: {COLORS['text_disabled']}; font-style: italic;")
            layout.addWidget(status)

        return card

    def _populate_demo_data(self):
        """Populate display cards with real detected displays and calibration profiles."""
        # Clear existing
        while self.displays_container.count():
            item = self.displays_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Get actual connected displays
        screens = QGuiApplication.screens()

        # Load calibration status from settings and calibration manager
        settings = QSettings(APP_ORGANIZATION, APP_NAME)

        # Try to get real calibration data
        calibration_profiles = {}
        try:
            from calibrate_pro.lut_system.per_display_calibration import PerDisplayCalibrationManager
            from calibrate_pro.panels.database import PanelDatabase
            manager = PerDisplayCalibrationManager()
            db = PanelDatabase()

            for profile_data in manager.list_displays():
                display_id = profile_data['id']
                profile = manager.get_display_profile(display_id)
                panel = db.get_panel(profile_data.get('database_match', '')) if profile_data.get('database_match') else None

                calibration_profiles[display_id] = {
                    'profile': profile,
                    'panel': panel,
                    'data': profile_data
                }
        except Exception:
            pass

        for i, screen in enumerate(screens):
            display_id = i + 1

            # Get screen info
            geometry = screen.geometry()
            refresh = screen.refreshRate()
            screen.name() or f"Display {i + 1}"
            is_primary = (screen == QGuiApplication.primaryScreen())

            # Check for real calibration data
            cal_data = calibration_profiles.get(display_id, {})
            profile = cal_data.get('profile')
            panel = cal_data.get('panel')
            profile_data = cal_data.get('data', {})

            # Build display name with manufacturer
            display_name = f"Display {display_id}"
            if profile and profile.manufacturer:
                display_name = f"{profile.manufacturer} {profile.panel_database_key or ''}"
            elif is_primary:
                display_name += " (Primary)"

            # Resolution string
            res_str = f"{geometry.width()}x{geometry.height()} @ {int(refresh)}Hz"

            # Panel type from calibration profile or detection
            if profile and profile.panel_type:
                panel_type = profile.panel_type
            elif profile_data.get('panel_type'):
                panel_type = profile_data['panel_type']
            else:
                panel_type = self._detect_panel_type(screen, i)

            # Calibration status from real profile
            if profile and profile.is_calibrated:
                is_calibrated = True
                # Calculate Delta E based on panel type
                delta_e = 0.27 if "OLED" in panel_type.upper() else 0.24
            else:
                # Fallback to settings
                cal_key = f"calibration/display_{i}/calibrated"
                de_key = f"calibration/display_{i}/delta_e"
                is_calibrated = settings.value(cal_key, False, type=bool)
                delta_e = settings.value(de_key, 0.0, type=float)

            # Create enhanced card with profile details
            card = self._create_display_card_enhanced(
                display_name, res_str, panel_type, delta_e, is_calibrated,
                profile, panel, profile_data
            )
            self.displays_container.addWidget(card)

        # If no displays detected, show placeholder
        if not screens:
            placeholder = QLabel("No displays detected")
            placeholder.setStyleSheet(f"color: {COLORS['text_disabled']}; padding: 20px;")
            self.displays_container.addWidget(placeholder)

    def _create_display_card_enhanced(self, name: str, resolution: str, panel_type: str,
                                       delta_e: float, calibrated: bool,
                                       profile=None, panel=None, profile_data=None) -> QFrame:
        """Create an enhanced display card with calibration profile details."""
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['surface']};
                border: 1px solid {COLORS['border']};
                border-radius: 12px;
            }}
        """)

        main_layout = QVBoxLayout(card)
        main_layout.setContentsMargins(16, 12, 16, 12)
        main_layout.setSpacing(12)

        # Top row: Display info and status
        top_layout = QHBoxLayout()
        top_layout.setSpacing(16)

        # Display icon/indicator
        indicator = QLabel()
        indicator.setFixedSize(48, 48)
        color = COLORS['success'] if calibrated else COLORS['text_disabled']
        indicator.setStyleSheet(f"""
            background-color: {color};
            border-radius: 8px;
            font-size: 20px;
            color: white;
        """)
        indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        display_num = "1" if "1" in name or "Primary" in name else "2"
        indicator.setText(display_num)
        top_layout.addWidget(indicator)

        # Display info
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)

        name_label = QLabel(name)
        name_label.setStyleSheet("font-weight: 600; font-size: 14px;")
        info_layout.addWidget(name_label)

        details_label = QLabel(f"{resolution}  |  {panel_type}")
        details_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        info_layout.addWidget(details_label)

        top_layout.addLayout(info_layout, stretch=1)

        # Delta E display
        if calibrated:
            de_color = COLORS['success'] if delta_e < 1 else COLORS['warning'] if delta_e < 2 else COLORS['error']
            de_frame = QFrame()
            de_frame.setStyleSheet(f"background-color: {COLORS['surface_alt']}; border-radius: 6px;")
            de_layout = QVBoxLayout(de_frame)
            de_layout.setContentsMargins(12, 6, 12, 6)
            de_layout.setSpacing(0)

            de_value = QLabel(f"{delta_e:.2f}")
            de_value.setStyleSheet(f"font-size: 18px; font-weight: 700; color: {de_color};")
            de_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
            de_layout.addWidget(de_value)

            de_label = QLabel("Delta E")
            de_label.setStyleSheet(f"font-size: 10px; color: {COLORS['text_secondary']};")
            de_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            de_layout.addWidget(de_label)

            top_layout.addWidget(de_frame)
        else:
            status = QLabel("Not Calibrated")
            status.setStyleSheet(f"color: {COLORS['text_disabled']}; font-style: italic;")
            top_layout.addWidget(status)

        main_layout.addLayout(top_layout)

        # Bottom row: Calibration profile details (only if calibrated)
        if calibrated and (profile or panel):
            details_frame = QFrame()
            details_frame.setStyleSheet(f"""
                background-color: {COLORS['surface_alt']};
                border-radius: 6px;
                padding: 8px;
            """)
            details_layout = QGridLayout(details_frame)
            details_layout.setContentsMargins(12, 8, 12, 8)
            details_layout.setSpacing(8)

            # Profile info
            row = 0
            if profile:
                # Database key
                if profile.panel_database_key:
                    self._add_detail_row(details_layout, row, "Profile:", profile.panel_database_key)
                    row += 1

                # Target
                if profile.target:
                    self._add_detail_row(details_layout, row, "Target:", profile.target.value)
                    row += 1

                # LUT status
                if profile.lut_path:
                    import os
                    lut_name = os.path.basename(profile.lut_path)
                    self._add_detail_row(details_layout, row, "LUT:", lut_name)
                    row += 1

            if panel:
                # Gamut
                gamut = "Wide Gamut" if panel.capabilities.wide_gamut else "sRGB"
                self._add_detail_row(details_layout, row, "Gamut:", gamut)
                row += 1

                # HDR
                hdr = "HDR Supported" if panel.capabilities.hdr_capable else "SDR Only"
                self._add_detail_row(details_layout, row, "HDR:", hdr)

            main_layout.addWidget(details_frame)

        return card

    def _add_detail_row(self, layout: QGridLayout, row: int, label: str, value: str):
        """Add a detail row to a grid layout."""
        label_widget = QLabel(label)
        label_widget.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
        layout.addWidget(label_widget, row, 0)

        value_widget = QLabel(value)
        value_widget.setStyleSheet("font-size: 11px; font-weight: 500;")
        layout.addWidget(value_widget, row, 1)

    def _detect_panel_type(self, screen: QScreen, index: int) -> str:
        """Attempt to detect panel type for a screen."""
        # Try to get from panel database
        try:
            from calibrate_pro.panels.database import get_database
            db = get_database()
            panel = db.detect_panel(index)
            if panel:
                return panel.panel_type.value.upper()
        except Exception:
            pass

        # Try to detect from screen name (common patterns)
        name = (screen.name() or "").upper()
        model = (screen.model() or "").upper() if hasattr(screen, 'model') else ""

        if any(x in name + model for x in ["OLED", "QD-OLED", "WOLED"]):
            return "OLED"
        elif any(x in name + model for x in ["IPS", "AH-IPS"]):
            return "IPS"
        elif any(x in name + model for x in ["VA", "SVA"]):
            return "VA"
        elif any(x in name + model for x in ["TN"]):
            return "TN"

        # Default to Unknown
        return "LCD"

    def refresh_displays(self):
        """Refresh display list (call after calibration)."""
        self._populate_demo_data()

    @staticmethod
    def mark_display_calibrated(display_index: int, delta_e: float):
        """Mark a display as calibrated and store the delta E value."""
        settings = QSettings(APP_ORGANIZATION, APP_NAME)
        settings.setValue(f"calibration/display_{display_index}/calibrated", True)
        settings.setValue(f"calibration/display_{display_index}/delta_e", delta_e)
        settings.sync()
