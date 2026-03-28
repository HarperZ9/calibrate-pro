"""
Main Application Window - Calibrate Pro Professional GUI

Assembles the navigation shell around extracted page components.
"""

import sys
from pathlib import Path

from PyQt6.QtCore import QSettings, QSize, Qt, QTimer
from PyQt6.QtGui import QAction, QFont, QGuiApplication
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSizePolicy,
    QStackedWidget,
    QSystemTrayIcon,
    QToolBar,
    QToolButton,
    QWidget,
)

from calibrate_pro.gui.icons import IconFactory
from calibrate_pro.gui.pages.calibration_page import CalibrationPage
from calibrate_pro.gui.pages.color_control_page import SoftwareColorControlPage
from calibrate_pro.gui.pages.dashboard_page import DashboardPage
from calibrate_pro.gui.pages.ddc_control_page import DDCControlPage
from calibrate_pro.gui.pages.profiles_page import ProfilesPage
from calibrate_pro.gui.pages.settings_page import SettingsPage
from calibrate_pro.gui.pages.vcgt_tools_page import VCGTToolsPage
from calibrate_pro.gui.pages.verification_page import VerificationPage
from calibrate_pro.gui.theme import (
    APP_NAME,
    APP_ORGANIZATION,
    APP_VERSION,
    COLORS,
    DARK_STYLESHEET,
)
from calibrate_pro.gui.workers import ColorManagementStatus


class MainWindow(QMainWindow):
    """Main application window for Calibrate Pro."""

    def __init__(self):
        super().__init__()
        self.settings = QSettings(APP_ORGANIZATION, APP_NAME)
        self.cm_status = ColorManagementStatus()
        self._setup_window()
        self._setup_menubar()
        self._setup_toolbar()
        self._setup_central_widget()
        self._setup_statusbar()
        self._setup_system_tray()
        self._restore_geometry()
        self._load_color_management_state()

    def _setup_window(self):
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.setMinimumSize(1100, 700)
        self.setStyleSheet(DARK_STYLESHEET)
        self.setWindowIcon(IconFactory.app_icon())

    def _setup_menubar(self):
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("&File")
        file_menu.addAction(QAction("&New Calibration...", self, shortcut="Ctrl+N", triggered=self._new_calibration))
        file_menu.addAction(QAction("&Open Profile...", self, shortcut="Ctrl+O", triggered=self._open_profile))
        file_menu.addSeparator()
        file_menu.addAction(QAction("&Save Profile...", self, shortcut="Ctrl+S", triggered=self._save_profile))

        export_menu = file_menu.addMenu("Export LUT")
        for label, fmt in [
            (".cube (Resolve/dwm_lut)", "cube"),
            (".3dlut (MadVR)", "3dlut"),
            (".png (ReShade/SpecialK)", "png"),
            (".icc (ICC v4 Profile)", "icc"),
            ("mpv config", "mpv"),
            ("OBS LUT", "obs"),
        ]:
            act = QAction(label, self)
            act.triggered.connect(lambda checked, f=fmt: self._export_lut(f))
            export_menu.addAction(act)

        file_menu.addSeparator()
        file_menu.addAction(QAction("E&xit", self, shortcut="Alt+F4", triggered=self.close))

        # Display menu
        display_menu = menubar.addMenu("&Display")
        display_menu.addAction(QAction("&Detect Displays", self, triggered=self._detect_displays))
        display_menu.addSeparator()
        display_menu.addAction(QAction("&Install Profile...", self, triggered=self._install_profile))
        display_menu.addAction(QAction("&Reset Gamma", self, triggered=self._reset_gamma))

        # Tools menu
        tools_menu = menubar.addMenu("&Tools")
        tools_menu.addAction(QAction("&Test Patterns...", self, triggered=self._show_test_patterns))
        tools_menu.addAction(QAction("&LUT Preview...", self, triggered=lambda: self.central_stack.setCurrentIndex(4)))
        tools_menu.addSeparator()
        tools_menu.addAction(QAction("&ACES Pipeline...", self))
        tools_menu.addAction(QAction("&HDR Analysis...", self))

        # Help menu
        help_menu = menubar.addMenu("&Help")
        help_menu.addAction(QAction("&Documentation", self))
        help_menu.addSeparator()
        help_menu.addAction(QAction("&About", self, triggered=self._show_about))

    def _setup_toolbar(self):
        toolbar = QToolBar("Navigation")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(20, 20))
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)

        icon_funcs = [
            IconFactory.dashboard,
            IconFactory.calibrate,
            IconFactory.verify,
            IconFactory.profiles,
            IconFactory.vcgt_tools,
            IconFactory.calibrate,
            IconFactory.settings,
            IconFactory.settings,
        ]

        buttons = [
            ("Dashboard", 0),
            ("Calibrate", 1),
            ("Verify", 2),
            ("Profiles", 3),
            ("VCGT Tools", 4),
            ("Color Control", 5),
            ("DDC Control", 6),
            ("Settings", 7),
        ]

        for (text, index), icon_func in zip(buttons, icon_funcs):
            btn = QToolButton()
            btn.setText(text)
            btn.setIcon(IconFactory.create_icon(icon_func, 20))
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, i=index: self.central_stack.setCurrentIndex(i))
            self.nav_group.addButton(btn)
            toolbar.addWidget(btn)

            if index == 0:
                btn.setChecked(True)

        toolbar.addWidget(QWidget())
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)

        self.toolbar_cm_status = QLabel()
        self.toolbar_cm_status.setStyleSheet(f"""
            QLabel {{
                background-color: {COLORS['surface']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 11px;
            }}
        """)
        toolbar.addWidget(self.toolbar_cm_status)
        self._update_toolbar_cm_status()

    def _setup_central_widget(self):
        self.central_stack = QStackedWidget()
        self.setCentralWidget(self.central_stack)

        self.dashboard_page = DashboardPage(cm_status=self.cm_status)
        self.central_stack.addWidget(self.dashboard_page)
        self.central_stack.addWidget(CalibrationPage())
        self.central_stack.addWidget(VerificationPage())
        self.profiles_page = ProfilesPage()
        self.central_stack.addWidget(self.profiles_page)
        self.central_stack.addWidget(VCGTToolsPage())
        self.color_control_page = SoftwareColorControlPage()
        self.central_stack.addWidget(self.color_control_page)
        self.ddc_control_page = DDCControlPage()
        self.central_stack.addWidget(self.ddc_control_page)
        self.central_stack.addWidget(SettingsPage())

    def _setup_statusbar(self):
        status_bar = self.statusBar()
        self.status_label = QLabel("Ready")
        status_bar.addWidget(self.status_label, 1)

        self.statusbar_cm_indicator = QLabel()
        self.statusbar_cm_indicator.setStyleSheet(f"color: {COLORS['text_secondary']};")
        status_bar.addPermanentWidget(self.statusbar_cm_indicator)

        self.display_indicator = QLabel()
        self.display_indicator.setStyleSheet(f"color: {COLORS['text_secondary']};")
        status_bar.addPermanentWidget(self.display_indicator)

        QTimer.singleShot(500, self._detect_displays)

    def _setup_system_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        self.tray_icon = QSystemTrayIcon(self)
        self._update_tray_icon()

        tray_menu = QMenu()

        self.tray_status_action = QAction("Color Management: Inactive", self)
        self.tray_status_action.setEnabled(False)
        tray_menu.addAction(self.tray_status_action)
        tray_menu.addSeparator()

        show_action = QAction("Show Window", self)
        show_action.triggered.connect(self._show_from_tray)
        tray_menu.addAction(show_action)

        tray_menu.addSeparator()

        self.tray_lut_action = QAction("Disable LUT", self)
        self.tray_lut_action.triggered.connect(self._toggle_lut_from_tray)
        tray_menu.addAction(self.tray_lut_action)

        reload_action = QAction("Reload Profile", self)
        reload_action.triggered.connect(self._reload_color_management)
        tray_menu.addAction(reload_action)

        tray_menu.addSeparator()

        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self._quit_application)
        tray_menu.addAction(exit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._tray_activated)
        self.tray_icon.show()

        self._update_tray_status()

    def _update_tray_icon(self):
        if self.cm_status.is_active():
            self.tray_icon.setIcon(IconFactory.tray_icon_active())
        else:
            self.tray_icon.setIcon(IconFactory.tray_icon_inactive())

    def _update_tray_status(self):
        if hasattr(self, 'tray_status_action'):
            if self.cm_status.is_active():
                self.tray_status_action.setText(f"Active: {self.cm_status.get_status_text()}")
                self.tray_lut_action.setText("Disable LUT")
            else:
                self.tray_status_action.setText("Color Management: Inactive")
                self.tray_lut_action.setText("Enable LUT")

    def _update_toolbar_cm_status(self):
        if self.cm_status.is_active():
            status_text = self.cm_status.get_status_text()
            color = COLORS['success']
        else:
            status_text = "No CM active"
            color = COLORS['text_disabled']

        self.toolbar_cm_status.setText(f"  {status_text}")
        self.toolbar_cm_status.setStyleSheet(f"""
            QLabel {{
                background-color: {COLORS['surface']};
                border: 1px solid {color};
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 11px;
                color: {color};
            }}
        """)

        if hasattr(self, 'statusbar_cm_indicator'):
            self.statusbar_cm_indicator.setText(status_text)

    def _load_color_management_state(self):
        last_profile = self.settings.value("cm/last_icc_profile", "")
        last_lut = self.settings.value("cm/last_lut", "")
        last_lut_method = self.settings.value("cm/last_lut_method", "dwm_lut")

        if last_profile and Path(last_profile).exists():
            self.cm_status.set_icc_profile("primary", last_profile)

        if last_lut and Path(last_lut).exists():
            self.cm_status.set_lut("primary", last_lut, last_lut_method)

        if not self.cm_status.is_active():
            demo_profile = Path.home() / "Documents" / "Calibrate Pro" / "Profiles" / "Calibrate_Pro_PG27UCDM.icc"
            demo_lut = Path.home() / "Documents" / "Calibrate Pro" / "LUTs" / "PG27UCDM_sRGB.cube"
            if demo_profile.exists():
                self.cm_status.set_icc_profile("primary", str(demo_profile))
            if demo_lut.exists():
                self.cm_status.set_lut("primary", str(demo_lut), "dwm_lut")

        self._refresh_all_cm_displays()

    def _refresh_all_cm_displays(self):
        self._update_toolbar_cm_status()
        if hasattr(self, 'tray_icon'):
            self._update_tray_icon()
            self._update_tray_status()
        if hasattr(self, 'dashboard_page'):
            self.dashboard_page.update_cm_status()

    def _show_from_tray(self):
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_from_tray()

    def _toggle_lut_from_tray(self):
        if self.cm_status.active_lut:
            self.settings.setValue("cm/disabled_lut", self.cm_status.active_lut)
            self.cm_status.clear_lut("primary")
            self.status_label.setText("LUT disabled")
        else:
            saved_lut = self.settings.value("cm/disabled_lut", "")
            if saved_lut and Path(saved_lut).exists():
                self.cm_status.set_lut("primary", saved_lut)
                self.status_label.setText(f"LUT enabled: {Path(saved_lut).stem}")
        self._refresh_all_cm_displays()

    def _reload_color_management(self):
        self._load_color_management_state()
        self.status_label.setText("Color management reloaded")

    def _quit_application(self):
        if self.cm_status.active_icc_profile:
            self.settings.setValue("cm/last_icc_profile", self.cm_status.active_icc_profile)
        if self.cm_status.active_lut:
            self.settings.setValue("cm/last_lut", self.cm_status.active_lut)
            self.settings.setValue("cm/last_lut_method", self.cm_status.lut_method)

        self.settings.setValue("geometry", self.saveGeometry())

        if hasattr(self, 'tray_icon'):
            self.tray_icon.hide()

        QApplication.quit()

    def _restore_geometry(self):
        geometry = self.settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        else:
            screen = QGuiApplication.primaryScreen()
            if screen:
                sg = screen.availableGeometry()
                self.move(sg.x() + (sg.width() - self.width()) // 2,
                          sg.y() + (sg.height() - self.height()) // 2)

    def closeEvent(self, event):
        minimize_to_tray = self.settings.value("general/minimize_to_tray", True, type=bool)

        if minimize_to_tray and hasattr(self, 'tray_icon') and self.tray_icon.isVisible():
            event.ignore()
            self.hide()
            self.tray_icon.showMessage(
                APP_NAME,
                "Running in background. Right-click tray icon for options.",
                QSystemTrayIcon.MessageIcon.Information,
                2000
            )
        else:
            self._quit_application()
            event.accept()

    def _detect_displays(self):
        displays = QGuiApplication.screens()
        if displays:
            primary = displays[0]
            g = primary.geometry()
            self.display_indicator.setText(f"{primary.name()} - {g.width()}x{g.height()} @ {primary.refreshRate():.0f}Hz")
            self.status_label.setText(f"Detected {len(displays)} display(s)")

    def _new_calibration(self):
        self.central_stack.setCurrentIndex(1)

    def _open_profile(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Profile", "",
            "Calibration Files (*.icc *.cube *.3dlut);;ICC Profiles (*.icc);;3D LUTs (*.cube *.3dlut);;All Files (*)")
        if path:
            self.status_label.setText(f"Loaded: {path}")

    def _save_profile(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Profile", "",
            "ICC Profile (*.icc);;3D LUT (*.cube);;All Files (*)")
        if path:
            self.status_label.setText(f"Saved: {path}")

    def _export_lut(self, fmt):
        extensions = {
            "cube": "3D LUT (*.cube)",
            "3dlut": "MadVR LUT (*.3dlut)",
            "png": "ReShade/SpecialK PNG (*.png)",
            "icc": "ICC Profile (*.icc)",
            "mpv": "mpv Config (*.conf)",
            "obs": "OBS LUT (*.cube)",
        }
        path, _ = QFileDialog.getSaveFileName(
            self, f"Export {fmt.upper()}", "", extensions.get(fmt, "All Files (*)"))
        if path:
            self.status_label.setText(f"Exported: {path}")

    def _install_profile(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Install ICC Profile", "", "ICC Profiles (*.icc *.icm)")
        if path:
            try:
                from calibrate_pro.panels.detection import install_profile
                install_profile(path)
                self.status_label.setText(f"Installed: {path}")
                QMessageBox.information(self, "Profile Installed", f"ICC profile installed:\n{path}")
            except (ImportError, OSError) as e:
                QMessageBox.warning(self, "Install Failed", str(e))

    def _reset_gamma(self):
        try:
            from calibrate_pro.lut_system.dwm_lut import remove_lut
            from calibrate_pro.panels.detection import enumerate_displays, reset_gamma_ramp
            displays = enumerate_displays()
            for i, d in enumerate(displays):
                reset_gamma_ramp(d.device_name)
                try:
                    remove_lut(i)
                except OSError:
                    pass
            self.cm_status.clear()
            self._refresh_all_cm_displays()
            self.status_label.setText("Gamma reset to default")
        except (ImportError, OSError) as e:
            QMessageBox.warning(self, "Reset Failed", str(e))

    def _show_test_patterns(self):
        try:
            from calibrate_pro.patterns.display import show_patterns
            show_patterns()
        except (ImportError, OSError) as e:
            QMessageBox.warning(self, "Test Patterns", str(e))

    def _show_about(self):
        QMessageBox.about(self, f"About {APP_NAME}",
            f"<h2>{APP_NAME}</h2>"
            f"<p>Version {APP_VERSION}</p>"
            f"<p>Professional display calibration suite with:</p>"
            f"<ul>"
            f"<li>Sensorless calibration</li>"
            f"<li>Hardware colorimeter support</li>"
            f"<li>System-wide 3D LUT (dwm_lut)</li>"
            f"<li>Full HDR calibration suite</li>"
            f"</ul>"
            f"<p>2024 {APP_ORGANIZATION}</p>")


def run_application():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(APP_ORGANIZATION)
    app.setFont(QFont("Segoe UI", 10))

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(run_application())
