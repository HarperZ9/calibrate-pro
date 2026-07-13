"""Active dark-room theme contract for Calibrate Pro."""

from calibrate_pro import __version__ as APP_VERSION  # noqa: F401 - public compatibility export

APP_NAME = "Calibrate Pro"
APP_ORGANIZATION = "Build Universe"


class C:
    """Application colors for a dim, color-critical Windows workspace."""

    BG = "#0E1014"
    BG_ALT = "#13161C"
    SURFACE = "#191D24"
    SURFACE2 = "#202630"
    BORDER = "#303846"
    BORDER_LT = "#465165"
    TEXT = "#F2F4F7"
    TEXT2 = "#C3CBD8"
    TEXT3 = "#8F9AA9"
    ACCENT = "#37B7A5"
    ACCENT_HI = "#55CEBC"
    ACCENT_TX = "#79E0D1"
    GREEN = "#5DC88C"
    GREEN_HI = "#7ADB9F"
    CYAN = "#6DC8FF"
    YELLOW = "#E1B86A"
    RED = "#E77B78"


_TOKEN_NAMES = (
    "BG",
    "BG_ALT",
    "SURFACE",
    "SURFACE2",
    "BORDER",
    "BORDER_LT",
    "TEXT",
    "TEXT2",
    "TEXT3",
    "ACCENT",
    "ACCENT_HI",
    "ACCENT_TX",
    "GREEN",
    "GREEN_HI",
    "CYAN",
    "YELLOW",
    "RED",
)


def install_build_ui_theme() -> None:
    """Install local tokens before Build UI constructs its widgets."""
    from build_ui import theme as build_theme

    for name in _TOKEN_NAMES:
        setattr(build_theme.C, name, getattr(C, name))


STYLE = f"""
QMainWindow {{
    background-color: {C.BG};
}}
QWidget {{
    background-color: {C.BG};
    color: {C.TEXT};
    font-family: "Segoe UI Variable", "Segoe UI", sans-serif;
    font-size: 13px;
}}
QMenuBar {{
    background-color: {C.BG_ALT};
    border-bottom: 1px solid {C.BORDER};
    padding: 4px;
}}
QMenuBar::item {{ padding: 6px 10px; border-radius: 4px; background: transparent; }}
QMenuBar::item:selected {{ background-color: {C.SURFACE2}; color: {C.TEXT}; }}
QMenu {{
    background-color: {C.SURFACE};
    border: 1px solid {C.BORDER_LT};
    border-radius: 6px;
    padding: 4px;
}}
QMenu::item {{ padding: 7px 28px 7px 12px; border-radius: 4px; }}
QMenu::item:selected {{ background-color: {C.ACCENT}; color: {C.BG}; }}
QMenu::item:disabled {{ color: {C.TEXT3}; }}
QMenu::separator {{ height: 1px; background-color: {C.BORDER}; margin: 4px 8px; }}
QStatusBar {{
    background-color: {C.BG_ALT};
    color: {C.TEXT2};
    border-top: 1px solid {C.BORDER};
}}
QScrollArea {{ background-color: {C.BG}; border: none; }}
QScrollArea > QWidget > QWidget {{ background-color: {C.BG}; }}
QPushButton {{
    background-color: {C.SURFACE2};
    color: {C.TEXT};
    border: 1px solid {C.BORDER_LT};
    border-radius: 6px;
    padding: 7px 14px;
}}
QPushButton:hover {{ background-color: {C.BORDER}; border-color: {C.ACCENT}; }}
QPushButton:focus {{ border: 1px solid {C.ACCENT_HI}; }}
QPushButton:pressed, QPushButton:checked {{ background-color: {C.ACCENT}; color: {C.BG}; }}
QPushButton:disabled {{ background-color: {C.SURFACE}; color: {C.TEXT3}; border-color: {C.BORDER}; }}
QPushButton[primary="true"] {{ background-color: {C.ACCENT}; color: {C.BG}; border-color: {C.ACCENT}; }}
QPushButton[primary="true"]:hover {{ background-color: {C.ACCENT_HI}; border-color: {C.ACCENT_HI}; }}
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {{
    background-color: {C.SURFACE};
    color: {C.TEXT};
    border: 1px solid {C.BORDER_LT};
    border-radius: 4px;
    padding: 6px 8px;
    selection-background-color: {C.ACCENT};
    selection-color: {C.BG};
}}
QComboBox:hover, QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover {{ border-color: {C.ACCENT}; }}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {C.ACCENT_HI}; }}
QComboBox:disabled, QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
    background-color: {C.BG_ALT}; color: {C.TEXT3}; border-color: {C.BORDER};
}}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{
    background-color: {C.SURFACE}; color: {C.TEXT}; border: 1px solid {C.BORDER_LT};
    selection-background-color: {C.ACCENT}; selection-color: {C.BG};
}}
QSlider::groove:horizontal {{ background-color: {C.BORDER}; height: 4px; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background-color: {C.ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background-color: {C.ACCENT}; border: 1px solid {C.ACCENT_HI};
    width: 14px; margin: -5px 0; border-radius: 7px;
}}
QSlider::handle:horizontal:hover, QSlider::handle:horizontal:pressed {{ background-color: {C.ACCENT_HI}; }}
QSlider::handle:horizontal:disabled {{ background-color: {C.TEXT3}; border-color: {C.BORDER_LT}; }}
QCheckBox, QRadioButton {{ color: {C.TEXT}; spacing: 7px; }}
QCheckBox:disabled, QRadioButton:disabled {{ color: {C.TEXT3}; }}
QCheckBox:focus, QRadioButton:focus {{ color: {C.ACCENT_TX}; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px; height: 16px; background-color: {C.SURFACE}; border: 1px solid {C.BORDER_LT};
}}
QCheckBox::indicator {{ border-radius: 4px; }}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {C.ACCENT}; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background-color: {C.ACCENT}; border-color: {C.ACCENT_HI};
}}
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{
    background-color: {C.BG_ALT}; border-color: {C.BORDER};
}}
QProgressBar {{
    background-color: {C.SURFACE}; color: {C.TEXT2}; border: 1px solid {C.BORDER};
    border-radius: 5px; min-height: 10px; text-align: center;
}}
QProgressBar::chunk {{ background-color: {C.ACCENT}; border-radius: 4px; }}
QTabWidget::pane {{ background-color: {C.SURFACE}; border: 1px solid {C.BORDER}; border-radius: 6px; }}
QTabBar::tab {{
    background-color: {C.BG_ALT}; color: {C.TEXT2}; border: 1px solid {C.BORDER};
    border-bottom: none; border-top-left-radius: 5px; border-top-right-radius: 5px;
    padding: 7px 12px; margin-right: 2px;
}}
QTabBar::tab:hover {{ color: {C.TEXT}; border-color: {C.ACCENT}; }}
QTabBar::tab:selected {{ background-color: {C.SURFACE}; color: {C.ACCENT_TX}; border-color: {C.ACCENT}; }}
QTabBar::tab:disabled {{ color: {C.TEXT3}; border-color: {C.BORDER}; }}
QTableWidget, QListWidget {{
    background-color: {C.SURFACE}; alternate-background-color: {C.SURFACE2};
    color: {C.TEXT}; border: 1px solid {C.BORDER}; border-radius: 4px;
    gridline-color: {C.BORDER}; outline: none;
}}
QTableWidget::item, QListWidget::item {{ padding: 6px; }}
QTableWidget::item:selected, QListWidget::item:selected {{ background-color: {C.ACCENT}; color: {C.BG}; }}
QTableWidget:focus, QListWidget:focus {{ border-color: {C.ACCENT_HI}; }}
QHeaderView::section {{
    background-color: {C.SURFACE2}; color: {C.TEXT2}; border: none;
    border-bottom: 1px solid {C.BORDER_LT}; border-right: 1px solid {C.BORDER}; padding: 7px;
}}
QToolTip {{
    background-color: {C.SURFACE2}; color: {C.TEXT}; border: 1px solid {C.BORDER_LT};
    border-radius: 4px; padding: 5px;
}}
"""


# Preserve the established GUI public surface while making the new tokens active.
COLORS = {
    "background": C.BG,
    "background_alt": C.BG_ALT,
    "surface": C.SURFACE,
    "surface_alt": C.SURFACE2,
    "border": C.BORDER,
    "text_primary": C.TEXT,
    "text_secondary": C.TEXT2,
    "text_disabled": C.TEXT3,
    "accent": C.ACCENT,
    "accent_hover": C.ACCENT_HI,
    "accent_pressed": C.ACCENT,
    "success": C.GREEN,
    "warning": C.YELLOW,
    "error": C.RED,
    "info": C.CYAN,
    "measured": C.CYAN,
    "target": C.ACCENT_TX,
    "delta_good": C.GREEN,
    "delta_warn": C.YELLOW,
    "delta_bad": C.RED,
}
DARK_STYLESHEET = STYLE
