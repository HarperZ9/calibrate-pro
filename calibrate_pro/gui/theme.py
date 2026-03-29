"""
Theme Constants and Stylesheet - Calibrate Pro

Application identity constants, color palette, and the dark theme stylesheet
optimized for display calibration environments.
"""

# Application Constants

APP_NAME = "Calibrate Pro"
APP_VERSION = "1.0.0"
APP_ORGANIZATION = "Quanta Universe"

# Dark theme colors optimized for calibration environment
COLORS = {
    "background": "#1a1a1a",
    "background_alt": "#242424",
    "surface": "#2d2d2d",
    "surface_alt": "#383838",
    "border": "#404040",
    "text_primary": "#e0e0e0",
    "text_secondary": "#a0a0a0",
    "text_disabled": "#606060",
    "accent": "#4a9eff",
    "accent_hover": "#6bb3ff",
    "accent_pressed": "#3a8eef",
    "success": "#4caf50",
    "warning": "#ff9800",
    "error": "#f44336",
    "info": "#2196f3",
    "measured": "#00bcd4",
    "target": "#ff5722",
    "delta_good": "#4caf50",
    "delta_warn": "#ff9800",
    "delta_bad": "#f44336",
}


# Dark Theme Stylesheet

DARK_STYLESHEET = f"""
QMainWindow {{ background-color: {COLORS["background"]}; }}
QWidget {{ background-color: {COLORS["background"]}; color: {COLORS["text_primary"]}; font-family: "Segoe UI", sans-serif; font-size: 13px; }}
QMenuBar {{ background-color: {COLORS["surface"]}; border-bottom: 1px solid {COLORS["border"]}; padding: 4px; }}
QMenuBar::item {{ background-color: transparent; padding: 6px 12px; border-radius: 4px; }}
QMenuBar::item:selected {{ background-color: {COLORS["surface_alt"]}; }}
QMenu {{ background-color: {COLORS["surface"]}; border: 1px solid {COLORS["border"]}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 8px 32px 8px 16px; border-radius: 4px; }}
QMenu::item:selected {{ background-color: {COLORS["accent"]}; }}
QMenu::separator {{ height: 1px; background-color: {COLORS["border"]}; margin: 4px 8px; }}
QToolBar {{ background-color: {COLORS["surface"]}; border: none; border-bottom: 1px solid {COLORS["border"]}; padding: 4px; spacing: 4px; }}
QToolButton {{ background-color: transparent; border: none; border-radius: 4px; padding: 6px 12px; color: {COLORS["text_primary"]}; }}
QToolButton:hover {{ background-color: {COLORS["surface_alt"]}; }}
QToolButton:checked {{ background-color: {COLORS["accent"]}; color: white; }}
QPushButton {{ background-color: {COLORS["surface_alt"]}; border: 1px solid {COLORS["border"]}; border-radius: 6px; padding: 8px 16px; font-weight: 500; }}
QPushButton:hover {{ background-color: {COLORS["accent"]}; border-color: {COLORS["accent"]}; }}
QPushButton:disabled {{ background-color: {COLORS["surface"]}; color: {COLORS["text_disabled"]}; }}
QPushButton[primary="true"] {{ background-color: {COLORS["accent"]}; border-color: {COLORS["accent"]}; color: white; }}
QGroupBox {{ border: 1px solid {COLORS["border"]}; border-radius: 8px; margin-top: 12px; padding: 12px; padding-top: 24px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left; left: 12px; padding: 0 6px; color: {COLORS["text_secondary"]}; }}
QTabWidget::pane {{ border: 1px solid {COLORS["border"]}; border-radius: 8px; background-color: {COLORS["surface"]}; }}
QTabBar::tab {{ background-color: {COLORS["background_alt"]}; border: 1px solid {COLORS["border"]}; border-bottom: none; border-top-left-radius: 6px; border-top-right-radius: 6px; padding: 8px 16px; margin-right: 2px; }}
QTabBar::tab:selected {{ background-color: {COLORS["surface"]}; }}
QComboBox {{ background-color: {COLORS["surface_alt"]}; border: 1px solid {COLORS["border"]}; border-radius: 4px; padding: 6px 12px; min-width: 120px; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: none; border-left: 4px solid transparent; border-right: 4px solid transparent; border-top: 6px solid {COLORS["text_secondary"]}; }}
QComboBox QAbstractItemView {{ background-color: {COLORS["surface"]}; border: 1px solid {COLORS["border"]}; selection-background-color: {COLORS["accent"]}; }}
QSpinBox, QDoubleSpinBox {{ background-color: {COLORS["surface_alt"]}; border: 1px solid {COLORS["border"]}; border-radius: 4px; padding: 6px; }}
QSlider::groove:horizontal {{ background-color: {COLORS["surface_alt"]}; height: 6px; border-radius: 3px; }}
QSlider::handle:horizontal {{ background-color: {COLORS["accent"]}; width: 16px; height: 16px; margin: -5px 0; border-radius: 8px; }}
QSlider::sub-page:horizontal {{ background-color: {COLORS["accent"]}; border-radius: 3px; }}
QTableWidget {{ background-color: {COLORS["surface"]}; border: 1px solid {COLORS["border"]}; border-radius: 4px; gridline-color: {COLORS["border"]}; }}
QTableWidget::item {{ padding: 8px; }}
QTableWidget::item:selected {{ background-color: {COLORS["accent"]}; }}
QHeaderView::section {{ background-color: {COLORS["surface_alt"]}; border: none; border-bottom: 1px solid {COLORS["border"]}; padding: 8px; font-weight: 600; }}
QListWidget {{ background-color: {COLORS["surface"]}; border: 1px solid {COLORS["border"]}; border-radius: 4px; }}
QListWidget::item {{ padding: 8px; border-bottom: 1px solid {COLORS["border"]}; }}
QListWidget::item:selected {{ background-color: {COLORS["accent"]}; }}
QLineEdit {{ background-color: {COLORS["surface_alt"]}; border: 1px solid {COLORS["border"]}; border-radius: 4px; padding: 8px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 4px; border: 1px solid {COLORS["border"]}; background-color: {COLORS["surface_alt"]}; }}
QCheckBox::indicator:checked {{ background-color: {COLORS["accent"]}; border-color: {COLORS["accent"]}; }}
QRadioButton::indicator {{ width: 18px; height: 18px; border-radius: 9px; border: 1px solid {COLORS["border"]}; background-color: {COLORS["surface_alt"]}; }}
QRadioButton::indicator:checked {{ background-color: {COLORS["accent"]}; border-color: {COLORS["accent"]}; }}
QProgressBar {{ background-color: {COLORS["surface"]}; border: none; border-radius: 4px; height: 8px; }}
QProgressBar::chunk {{ background-color: {COLORS["accent"]}; border-radius: 4px; }}
QScrollBar:vertical {{ background-color: {COLORS["background"]}; width: 10px; border-radius: 5px; }}
QScrollBar::handle:vertical {{ background-color: {COLORS["surface_alt"]}; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
QStatusBar {{ background-color: {COLORS["surface"]}; border-top: 1px solid {COLORS["border"]}; }}
QLabel {{ background-color: transparent; }}
"""
