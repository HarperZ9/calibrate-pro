"""Contracts for the active Calibrate Pro dark-room theme."""


def _relative_luminance(hex_color: str) -> float:
    channels = [int(hex_color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast_ratio(first: str, second: str) -> float:
    light, dark = sorted((_relative_luminance(first), _relative_luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def test_active_app_owns_dark_room_theme() -> None:
    import calibrate_pro.gui.app as app
    from calibrate_pro.gui.theme import C, STYLE
    from build_ui import theme as build_theme

    assert app.C is C
    assert app.STYLE is STYLE
    assert build_theme.C.BG == C.BG
    assert build_theme.C.ACCENT == C.ACCENT
    assert C.BG == "#0E1014"
    assert C.SURFACE == "#191D24"
    assert C.TEXT == "#F2F4F7"
    assert C.ACCENT == "#37B7A5"
    assert "#fdf9f5" not in STYLE.lower()
    assert "#d4a0a0" not in STYLE.lower()
    assert "QPushButton:focus" in STYLE
    assert "QPushButton:disabled" in STYLE


def test_dark_room_text_tokens_meet_wcag_aa_contrast() -> None:
    from calibrate_pro.gui.theme import C

    for foreground in (C.TEXT, C.TEXT2, C.TEXT3):
        for background in (C.BG, C.SURFACE):
            assert _contrast_ratio(foreground, background) >= 4.5


def test_style_covers_widgets_used_by_the_active_app() -> None:
    from calibrate_pro.gui.theme import STYLE

    required_widgets = (
        "QMainWindow",
        "QWidget",
        "QMenuBar",
        "QMenu",
        "QStatusBar",
        "QScrollArea",
        "QPushButton",
        "QComboBox",
        "QLineEdit",
        "QSpinBox",
        "QDoubleSpinBox",
        "QSlider",
        "QCheckBox",
        "QRadioButton",
        "QProgressBar",
        "QTabWidget",
        "QTabBar",
        "QTableWidget",
        "QHeaderView",
        "QListWidget",
        "QToolTip",
    )

    assert all(widget in STYLE for widget in required_widgets)
