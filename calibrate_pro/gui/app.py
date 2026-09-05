"""
Calibrate Pro -- Main Application

Clean, professional GUI built for display calibration professionals.
Every widget has proper layout constraints. Every panel resizes correctly.
"""

import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from decimal import Decimal
from functools import partial
from pathlib import Path

from calibrate_pro import __version__ as APP_VERSION
from calibrate_pro.qt_runtime import configure_qt_api

configure_qt_api()

logger = logging.getLogger(__name__)

from calibrate_pro.gui.theme import STYLE, C, install_build_ui_theme

install_build_ui_theme()

from build_ui.widgets import Card, Heading, Sidebar, Stat, StatusDot, ToastNotification
from PySide6.QtCore import (
    QPointF,
    QRectF,
    QSettings,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QKeySequence, QPainter, QPen, QPixmap, QPolygonF, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QSystemTrayIcon,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from calibrate_pro.application.actions import ActionClassification, ActionDisposition, ResolvedAction
from calibrate_pro.application.assets import ExportBundle
from calibrate_pro.application.composition import build_production_service
from calibrate_pro.application.contracts import (
    CharacterizationKind,
    DisplayObservation,
    PanelCharacterization,
)
from calibrate_pro.application.detection import panel_key_from_provenance
from calibrate_pro.application.outcomes import ActionError, ActionOutcome, ActionSuccess
from calibrate_pro.application.results import DetectionSummary, HdrStatus
from calibrate_pro.application.service import FunctionalRecoveryService
from calibrate_pro.gui.action_binding import ActionBinder, refusal_message
from calibrate_pro.verification.provenance import EvidenceKind, MetricValue

APP_NAME = "Calibrate Pro"
APP_ORG = "Build Universe"

#: What a control says when this window narrowed it because the build is a
#: simulated preview. The banner promises no hardware access and no display
#: changes, and this is that same promise stated on the control itself.
PREVIEW_DISABLED_REASON = "Disabled in simulated preview."

#: The View menu's page entries in stack order: the label, its shortcut, and
#: the navigation action the entry stands for.
PAGE_MENU_ENTRIES: tuple[tuple[str, str, str], ...] = (
    ("&Dashboard", "Ctrl+1", "navigation.dashboard"),
    ("&Calibrate", "Ctrl+2", "navigation.calibrate"),
    ("&Verify", "Ctrl+3", "navigation.verify"),
    ("&Profiles", "Ctrl+4", "navigation.profiles"),
    ("DD&C Control", "Ctrl+5", "navigation.ddc"),
    ("&Settings", "Ctrl+6", "navigation.settings"),
)

#: The Export submenu in menu order: the name the session publishes a format
#: under, and the label the entry carries.
EXPORT_MENU_ENTRIES: tuple[tuple[str, str], ...] = (
    ("cube", ".cube (Resolve / dwm_lut)"),
    ("3dlut", ".3dlut (MadVR)"),
    ("png", ".png (ReShade / SpecialK)"),
    ("icc", ".icc (ICC Profile)"),
    ("mpv", "mpv config"),
    ("obs", "OBS LUT"),
)


def refresh_text(refresh_millihz: int) -> str:
    """Render a refresh rate at the precision the observation carries.

    The contract stores millihertz because 59.94 Hz is a real rate that whole
    hertz cannot hold. Trailing zeros are dropped, so an exact 60 Hz reading is
    not dressed up as 60.000.
    """
    hertz = (Decimal(refresh_millihz) / Decimal(1000)).normalize()
    return f"{hertz:f} Hz"


def hdr_text(hdr_enabled: bool | None) -> str:
    """Say what the HDR switch answered, including that it did not answer."""
    if hdr_enabled is None:
        return "not read"
    return "on" if hdr_enabled else "off"


def characterization_text(characterization: PanelCharacterization) -> str:
    """Name where a panel description came from, or say there is none.

    A card showing a panel type with no source would read as a measurement of
    the attached unit. What a detection pass holds is a database match, a
    deliberate generic stand-in, or nothing, and which one it is decides how
    much any number derived from it is worth.
    """
    if characterization.kind is CharacterizationKind.UNKNOWN:
        return "Panel not characterized"
    key = panel_key_from_provenance(characterization)
    if key is not None:
        return f"Panel {key}"
    return f"Panel characterization: {characterization.provenance}"


def chromaticity_point(pair: tuple[str, str] | None) -> tuple[float, float] | None:
    """Convert one contract chromaticity into what the gamut widget draws.

    The contract carries exact decimal strings so that no stage rounds a
    coordinate twice. The widget draws pixels, so the single conversion to
    binary floating point happens here, at the last moment before drawing.
    """
    if pair is None:
        return None
    return (float(pair[0]), float(pair[1]))


def menu_action(menu: QMenu, text: str, parent: QWidget, shortcut: str | None = None) -> QAction:
    """Create one menu entry and hand it back to be bound.

    The entry is deliberately not connected here. Every entry in this window is
    connected by the binder, which is what stops a control from reaching a
    handler the session was never asked about.
    """
    action = QAction(text, parent)
    if shortcut is not None:
        action.setShortcut(QKeySequence(shortcut))
    menu.addAction(action)
    return action


def not_measured_metric(unit: str) -> MetricValue:
    """Return the canonical GUI representation for missing evidence."""
    return MetricValue(None, unit, EvidenceKind.NOT_MEASURED)


def metric_or_not_measured(value: object, unit: str) -> MetricValue:
    """Reject bare numerics at GUI boundaries instead of guessing provenance."""
    return value if isinstance(value, MetricValue) else not_measured_metric(unit)


@dataclass(frozen=True)
class QtDisplaySnapshot:
    """Read-only display facts exposed by Qt, with no display writer handle."""

    index: int
    name: str
    device_name: str
    device_id: str
    monitor_name: str
    manufacturer: str
    model: str
    serial: str
    width: int
    height: int
    refresh_rate: int
    bit_depth: int
    is_primary: bool


def qt_display_snapshots() -> list[QtDisplaySnapshot]:
    """Return basic display observations through Qt's read-only screen API."""
    primary = QApplication.primaryScreen()
    snapshots: list[QtDisplaySnapshot] = []
    for index, screen in enumerate(QApplication.screens()):
        geometry = screen.geometry()
        name = screen.name() or f"Display {index + 1}"
        manufacturer = screen.manufacturer() or "Unknown"
        model = screen.model() or name
        serial = screen.serialNumber() or ""
        snapshots.append(
            QtDisplaySnapshot(
                index=index,
                name=name,
                device_name=name,
                device_id=name,
                monitor_name=name,
                manufacturer=manufacturer,
                model=model,
                serial=serial,
                width=geometry.width(),
                height=geometry.height(),
                refresh_rate=round(screen.refreshRate()),
                bit_depth=screen.depth(),
                is_primary=screen is primary,
            )
        )
    return snapshots


def make_tray_icon(accent_color: str = "#92ad7e") -> QIcon:
    """
    Create a tray icon variant with a specific accent color.

    The accent color tints the calibration arcs, check mark, stand, and
    frame to visually indicate calibration state:
        - Green (#92ad7e): all displays calibrated
        - Yellow (#e0c87a): calibration is stale (>30 days)
        - Gray  (#bfb0a4): no calibration applied
    """
    icon = QIcon()
    for size in [16, 24, 32, 48, 64, 128, 256]:
        pm = QPixmap(size, size)
        pm.fill(QColor(0, 0, 0, 0))

        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        s = size
        m = s * 0.08

        # Monitor body
        body_rect = (m, m, s - 2 * m, s * 0.72)
        p.setPen(QPen(QColor(accent_color), max(1, s * 0.04)))
        p.setBrush(QColor("#f7f3ee"))
        p.drawRoundedRect(
            int(body_rect[0]), int(body_rect[1]), int(body_rect[2]), int(body_rect[3]), s * 0.08, s * 0.08
        )

        # Screen area
        inset = s * 0.14
        screen_x = inset
        screen_y = inset
        screen_w = s - 2 * inset
        screen_h = s * 0.52
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#f0ebe4"))
        p.drawRoundedRect(int(screen_x), int(screen_y), int(screen_w), int(screen_h), s * 0.04, s * 0.04)

        # Single-color calibration arc
        cx = s * 0.5
        cy = s * 0.42
        radius = s * 0.18

        for angle_start in [200, 240, 280]:
            pen = QPen(QColor(accent_color), max(1.5, s * 0.05))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            arc_rect = QRectF(cx - radius, cy - radius, radius * 2, radius * 2)
            p.drawArc(arc_rect, angle_start * 16, 35 * 16)

        # Stand
        stand_top = s * 0.76
        stand_w = s * 0.22
        stand_h = s * 0.08
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(accent_color))
        stand = QPolygonF(
            [
                QPointF(cx - stand_w * 0.4, stand_top),
                QPointF(cx + stand_w * 0.4, stand_top),
                QPointF(cx + stand_w * 0.7, stand_top + stand_h),
                QPointF(cx - stand_w * 0.7, stand_top + stand_h),
            ]
        )
        p.drawPolygon(stand)

        # Base
        base_y = stand_top + stand_h
        base_w = s * 0.30
        p.drawRoundedRect(int(cx - base_w / 2), int(base_y), int(base_w), int(s * 0.04), s * 0.02, s * 0.02)

        # Check mark in accent color
        if size >= 24:
            check_x = screen_x + screen_w * 0.65
            check_y = screen_y + screen_h * 0.55
            check_s = s * 0.14
            pen = QPen(QColor(accent_color), max(1.5, s * 0.04))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.drawLine(
                QPointF(check_x, check_y + check_s * 0.4), QPointF(check_x + check_s * 0.35, check_y + check_s * 0.75)
            )
            p.drawLine(QPointF(check_x + check_s * 0.35, check_y + check_s * 0.75), QPointF(check_x + check_s, check_y))

        p.end()
        icon.addPixmap(pm)

    return icon


def make_app_icon() -> QIcon:
    """
    Create the application icon programmatically.

    A stylized display monitor with a color calibration arc --
    navy blue frame, olive green check, subtle color band.
    Generated at multiple sizes for crisp rendering at any DPI.
    """
    icon = QIcon()
    for size in [16, 24, 32, 48, 64, 128, 256]:
        pm = QPixmap(size, size)
        pm.fill(QColor(0, 0, 0, 0))  # Transparent

        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        s = size
        m = s * 0.08  # margin

        # Monitor body -- rounded rectangle, warm brown
        body_rect = (m, m, s - 2 * m, s * 0.72)
        p.setPen(QPen(QColor("#b07878"), max(1, s * 0.04)))
        p.setBrush(QColor("#f7f3ee"))
        p.drawRoundedRect(
            int(body_rect[0]), int(body_rect[1]), int(body_rect[2]), int(body_rect[3]), s * 0.08, s * 0.08
        )

        # Screen area -- slightly inset, dark
        inset = s * 0.14
        screen_x = inset
        screen_y = inset
        screen_w = s - 2 * inset
        screen_h = s * 0.52
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#f0ebe4"))
        p.drawRoundedRect(int(screen_x), int(screen_y), int(screen_w), int(screen_h), s * 0.04, s * 0.04)

        # Color calibration arc on screen -- three subtle bands (R, G, B)
        cx = s * 0.5
        cy = s * 0.42
        radius = s * 0.18

        for angle_start, color in [(200, "#d4a0a0"), (240, "#92ad7e"), (280, "#e0c87a")]:
            pen = QPen(QColor(color), max(1.5, s * 0.05))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            # Draw arc segment
            arc_rect = QRectF(cx - radius, cy - radius, radius * 2, radius * 2)
            p.drawArc(arc_rect, angle_start * 16, 35 * 16)

        # Monitor stand -- small trapezoid
        stand_top = s * 0.76
        stand_w = s * 0.22
        stand_h = s * 0.08
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#d4a0a0"))
        stand = QPolygonF(
            [
                QPointF(cx - stand_w * 0.4, stand_top),
                QPointF(cx + stand_w * 0.4, stand_top),
                QPointF(cx + stand_w * 0.7, stand_top + stand_h),
                QPointF(cx - stand_w * 0.7, stand_top + stand_h),
            ]
        )
        p.drawPolygon(stand)

        # Base
        base_y = stand_top + stand_h
        base_w = s * 0.30
        p.drawRoundedRect(int(cx - base_w / 2), int(base_y), int(base_w), int(s * 0.04), s * 0.02, s * 0.02)

        # Small check mark -- olive green, bottom right of screen
        if size >= 24:
            check_x = screen_x + screen_w * 0.65
            check_y = screen_y + screen_h * 0.55
            check_s = s * 0.14
            pen = QPen(QColor("#a3be90"), max(1.5, s * 0.04))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.drawLine(
                QPointF(check_x, check_y + check_s * 0.4), QPointF(check_x + check_s * 0.35, check_y + check_s * 0.75)
            )
            p.drawLine(QPointF(check_x + check_s * 0.35, check_y + check_s * 0.75), QPointF(check_x + check_s, check_y))

        p.end()
        icon.addPixmap(pm)

    return icon


# Calibrate Pro pages list (used for Sidebar construction)

CAL_PAGES = [
    "Dashboard",
    "Calibrate",
    "Verify",
    "Profiles",
    "DDC Control",
    "Settings",
]


# Dashboard Page


class GamutMiniWidget(QWidget):
    """Tiny CIE xy gamut triangle visualization."""

    def __init__(self, red_xy=None, green_xy=None, blue_xy=None, size: int = 64, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._r = red_xy
        self._g = green_xy
        self._b = blue_xy
        self._size = size

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = self._size
        margin = s * 0.1

        def xy_to_px(x, y):
            # Map CIE xy (0-0.8, 0-0.9) to pixel coordinates
            px = margin + (x / 0.8) * (s - 2 * margin)
            py = s - margin - (y / 0.9) * (s - 2 * margin)
            return QPointF(px, py)

        # Background
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(C.SURFACE2))
        p.drawRoundedRect(0, 0, s, s, 4, 4)

        # sRGB reference triangle (dim)
        srgb_pen = QPen(QColor(C.BORDER_LT), 1)
        p.setPen(srgb_pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        srgb = QPolygonF([xy_to_px(0.64, 0.33), xy_to_px(0.30, 0.60), xy_to_px(0.15, 0.06)])
        p.drawPolygon(srgb)

        # Draw an observed/characterized panel gamut only when supplied.
        if self._r is not None and self._g is not None and self._b is not None:
            panel_pen = QPen(QColor(C.ACCENT_TX), 1.5)
            p.setPen(panel_pen)
            panel_fill = QColor(C.ACCENT)
            panel_fill.setAlpha(40)
            p.setBrush(panel_fill)
            panel = QPolygonF([xy_to_px(*self._r), xy_to_px(*self._g), xy_to_px(*self._b)])
            p.drawPolygon(panel)

        # D65 white point dot
        d65 = xy_to_px(0.3127, 0.3290)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(C.TEXT))
        p.drawEllipse(d65, 2, 2)

        p.end()


class GamutBar(QWidget):
    """Compact horizontal gamut coverage bar."""

    def __init__(
        self,
        srgb: MetricValue | None = None,
        p3: MetricValue | None = None,
        bt2020: MetricValue | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("displayGamutBar")
        self.setStyleSheet("background: transparent;")
        self.setFixedHeight(32)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._srgb = metric_or_not_measured(srgb, "%")
        self._p3 = metric_or_not_measured(p3, "%")
        self._bt2020 = metric_or_not_measured(bt2020, "%")
        self.setToolTip(
            "\n".join(
                f"{name}: {metric.display_text(1)}; source: {metric.source or 'Not measured'}"
                for name, metric in (("sRGB", self._srgb), ("P3", self._p3), ("BT.2020", self._bt2020))
            )
        )

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # Three rows of bars
        bar_h = 6
        gap = 3
        y_start = (h - 3 * bar_h - 2 * gap) // 2

        bars = [
            (self._srgb, "sRGB", C.ACCENT_TX),
            (self._p3, "P3", C.CYAN),
            (self._bt2020, "2020", C.TEXT3),
        ]

        label_w = 32
        bar_x = label_w + 4
        bar_w = max(20, w - bar_x - 86)

        for i, (metric, label, color) in enumerate(bars):
            y = y_start + i * (bar_h + gap)

            # Label
            p.setPen(QColor(C.TEXT3))
            p.setFont(QFont("Segoe UI", 7))
            p.drawText(
                0, int(y), label_w, bar_h + 2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, label
            )

            # Track
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(C.SURFACE2))
            p.drawRoundedRect(int(bar_x), int(y), int(bar_w), bar_h, 3, 3)

            # Fill only when evidence carries a value.
            if metric.value is not None:
                fill_w = max(2, bar_w * min(metric.value, 100) / 100)
                p.setBrush(QColor(color))
                p.drawRoundedRect(int(bar_x), int(y), int(fill_w), bar_h, 3, 3)

            # Percentage
            p.setPen(QColor(C.TEXT2))
            p.drawText(
                int(bar_x + bar_w + 4),
                int(y),
                82,
                bar_h + 2,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                f"{metric.value:.0f}% ({metric.evidence.value})" if metric.value is not None else "Not measured",
            )

        p.end()


class DisplayCard(Card):
    """Enhanced display card with gamut diagram, coverage bars, and status."""

    calibrate_clicked = Signal(int)  # emits display index

    def __init__(
        self,
        name: str,
        resolution: str,
        panel_type: str,
        gamut_srgb: MetricValue | None = None,
        gamut_p3: MetricValue | None = None,
        gamut_bt2020: MetricValue | None = None,
        calibrated: bool = False,
        hdr: bool = False,
        cal_age: str = "",
        delta_e: MetricValue | None = None,
        red_xy=None,
        green_xy=None,
        blue_xy=None,
        peak_nits: MetricValue | None = None,
        display_index: int = 0,
        actions_enabled: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self._display_index = display_index
        self.setMinimumHeight(140)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(16)

        # Left: Mini CIE gamut diagram
        gamut_viz = GamutMiniWidget(red_xy, green_xy, blue_xy, size=72)
        layout.addWidget(gamut_viz, alignment=Qt.AlignmentFlag.AlignTop)

        # Center: Info + gamut bars
        center = QVBoxLayout()
        center.setSpacing(6)

        # Name row
        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        name_label = QLabel(name)
        name_label.setObjectName("displayNameLabel")
        name_label.setStyleSheet("background: transparent; font-size: 14px; font-weight: 500;")
        name_row.addWidget(name_label)

        # Tags
        if hdr:
            hdr_tag = QLabel("HDR")
            hdr_tag.setStyleSheet(
                f"background: {C.SURFACE2}; border: 1px solid {C.BORDER}; "
                f"border-radius: 9px; padding: 2px 10px; font-size: 9px; "
                f"color: {C.CYAN}; font-weight: 600;"
            )
            hdr_tag.setFixedHeight(18)
            name_row.addWidget(hdr_tag)
        name_row.addStretch()
        center.addLayout(name_row)

        # Detail line
        detail_parts = [resolution, panel_type]
        peak_luminance = metric_or_not_measured(peak_nits, "nits")
        detail_parts.append(f"Peak luminance: {peak_luminance.display_text(0)}")
        detail = QLabel("  ·  ".join(detail_parts))
        detail.setObjectName("displayDetailLabel")
        detail.setStyleSheet(f"background: transparent; font-size: 11px; color: {C.TEXT2};")
        center.addWidget(detail)

        # Gamut coverage bars
        gamut_bar = GamutBar(gamut_srgb, gamut_p3, gamut_bt2020)
        center.addWidget(gamut_bar)

        layout.addLayout(center, stretch=1)

        # Right: Status column
        right = QVBoxLayout()
        right.setSpacing(6)
        right.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)

        # Delta E badge
        if calibrated:
            delta_metric = metric_or_not_measured(delta_e, "dE2000")
            de_color = C.ACCENT_TX if delta_metric.value is not None else C.TEXT3
            de_badge = QLabel(f"dE {delta_metric.display_text(1)}")
            de_badge.setStyleSheet(
                f"background: {C.SURFACE2}; border: 1px solid {de_color}; "
                f"border-radius: 10px; padding: 4px 12px; font-size: 11px; "
                f"color: {de_color}; font-weight: 600;"
            )
            de_badge.setFixedHeight(26)
            de_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            de_badge.setToolTip(f"Evidence source: {delta_metric.source or 'Not measured'}")
            right.addWidget(de_badge, alignment=Qt.AlignmentFlag.AlignRight)

        # Calibration age
        if cal_age:
            age_label = QLabel(cal_age)
            age_label.setObjectName("displayStatusLabel")
            age_label.setStyleSheet(f"background: transparent; font-size: 10px; color: {C.TEXT3};")
            right.addWidget(age_label, alignment=Qt.AlignmentFlag.AlignRight)
        elif not calibrated:
            uncal = QLabel("Not calibrated")
            uncal.setStyleSheet(f"font-size: 11px; color: {C.TEXT3};")
            right.addWidget(uncal, alignment=Qt.AlignmentFlag.AlignRight)

        right.addStretch()

        # Action button
        self.calibrate_button = QPushButton("Calibrate" if not calibrated else "Recalibrate")
        self.calibrate_button.setProperty("primary", not calibrated and actions_enabled)
        self.calibrate_button.setFixedWidth(110)
        self.calibrate_button.setFixedHeight(32)
        self.calibrate_button.setStyleSheet(
            self.calibrate_button.styleSheet() + "font-size: 11px; border-radius: 10px;"
        )
        self.calibrate_button.setEnabled(actions_enabled)
        if not actions_enabled:
            self.calibrate_button.setToolTip("Disabled in simulated preview")
        self.calibrate_button.clicked.connect(lambda: self.calibrate_clicked.emit(self._display_index))
        right.addWidget(self.calibrate_button, alignment=Qt.AlignmentFlag.AlignRight)

        layout.addLayout(right)


class SensorCard(Card):
    """Card showing colorimeter status."""

    def __init__(self, connected: bool = False, name: str = "", parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(60)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(12)

        dot = StatusDot(C.GREEN if connected else C.TEXT3, 8)
        layout.addWidget(dot)

        if connected:
            text = QLabel(f"Colorimeter: {name}")
            text.setStyleSheet(f"font-size: 12px; color: {C.GREEN_HI};")
        else:
            text = QLabel("No colorimeter detected")
            text.setStyleSheet(f"font-size: 12px; color: {C.TEXT3};")
        layout.addWidget(text, stretch=1)


class LiveSensorCard(Card):
    """Live colorimeter readout with auto-updating XYZ, luminance, CCT."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(90)
        self._driver = None
        self._timer = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        # Header
        header = QHBoxLayout()
        self._title = QLabel("Colorimeter -- Live Readout")
        self._title.setStyleSheet(f"font-size: 12px; font-weight: 500; color: {C.GREEN_HI};")
        header.addWidget(self._title)
        header.addStretch()

        self._toggle_btn = QPushButton("Start")
        self._toggle_btn.setFixedSize(60, 24)
        self._toggle_btn.setStyleSheet("font-size: 10px; padding: 2px 8px;")
        self._toggle_btn.clicked.connect(self._toggle_live)
        header.addWidget(self._toggle_btn)
        layout.addLayout(header)

        # Readout row
        readings = QHBoxLayout()
        readings.setSpacing(24)

        self._lum_stat = Stat("Luminance", "--", C.TEXT)
        self._cct_stat = Stat("CCT", "--", C.TEXT)
        self._xyz_label = QLabel("X -- Y -- Z --")
        self._xyz_label.setStyleSheet(
            f"font-size: 11px; color: {C.TEXT2}; font-family: 'Cascadia Code', 'Consolas', monospace;"
        )

        readings.addWidget(self._lum_stat)
        readings.addWidget(self._cct_stat)
        readings.addWidget(self._xyz_label, stretch=1)
        layout.addLayout(readings)

        self._running = False

    def _toggle_live(self):
        if self._running:
            self._stop_live()
        else:
            self._start_live()

    def _start_live(self):
        try:
            from calibrate_pro.hardware.i1d3_native import I1D3Driver

            self._driver = I1D3Driver()
            if not self._driver.open():
                self._title.setText("Colorimeter -- Failed to open")
                self._title.setStyleSheet(f"font-size: 12px; font-weight: 500; color: {C.RED};")
                return

            self._running = True
            self._toggle_btn.setText("Stop")
            self._title.setText("Colorimeter -- Live")

            self._timer = QTimer()
            self._timer.timeout.connect(self._take_reading)
            self._timer.start(800)  # Read every 800ms

        except (ImportError, OSError, RuntimeError) as e:
            self._title.setText(f"Error: {e}")

    def _stop_live(self):
        self._running = False
        if self._timer:
            self._timer.stop()
            self._timer = None
        if self._driver:
            self._driver.close()
            self._driver = None
        self._toggle_btn.setText("Start")
        self._title.setText("Colorimeter -- Stopped")
        self._title.setStyleSheet(f"font-size: 12px; font-weight: 500; color: {C.TEXT2};")

    def _take_reading(self):
        if not self._driver or not self._running:
            return
        try:
            m = self._driver.measure(integration_time=0.5)
            if m and (m.X > 0 or m.Y > 0 or m.Z > 0):
                self._lum_stat.set_value(f"{m.luminance:.1f}", C.TEXT)
                self._cct_stat.set_value(f"{m.cct:.0f}K" if m.cct > 1000 else "--", C.TEXT)
                self._xyz_label.setText(f"X {m.X:.2f}   Y {m.Y:.2f}   Z {m.Z:.2f}")
            else:
                self._xyz_label.setText("No light detected")
        except (OSError, RuntimeError):
            self._xyz_label.setText("Read error")


# Add Display Profile Dialog


class AddDisplayDialog(QDialog):
    """Dialog for adding display profiles via EDID auto-detect or JSON import."""

    display_added = Signal()  # emitted when a profile is added

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Display Profile")
        self.setMinimumSize(520, 460)
        self.setStyleSheet(
            f"QDialog {{ background: {C.BG}; }}"
            f"QTabWidget::pane {{ border: 1px solid {C.BORDER}; border-radius: 10px; "
            f"  background: {C.SURFACE}; padding: 12px; }}"
            f"QTabBar::tab {{ background: {C.SURFACE2}; border: 1px solid {C.BORDER}; "
            f"  border-top-left-radius: 8px; border-top-right-radius: 8px; "
            f"  padding: 8px 20px; margin-right: 2px; font-size: 12px; color: {C.TEXT}; }}"
            f"QTabBar::tab:selected {{ background: {C.SURFACE}; border-bottom-color: {C.SURFACE}; "
            f"  font-weight: 600; color: {C.ACCENT_TX}; }}"
            f"QTabBar::tab:hover {{ background: {C.SURFACE}; }}"
            f"QLabel {{ color: {C.TEXT}; }}"
            f"QComboBox {{ background: {C.SURFACE}; border: 1px solid {C.BORDER}; "
            f"  border-radius: 8px; padding: 6px 12px; font-size: 12px; }}"
            f"QComboBox:hover {{ border-color: {C.ACCENT}; }}"
            f"QComboBox::drop-down {{ border: none; width: 24px; }}"
        )
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        heading = QLabel("Add Display Profile")
        heading.setStyleSheet(f"font-size: 18px; font-weight: 500; color: {C.TEXT};")
        layout.addWidget(heading)

        tabs = QTabWidget()
        tabs.addTab(self._build_edid_tab(), "Auto-detect from EDID")
        tabs.addTab(self._build_import_tab(), "Import from file")
        layout.addWidget(tabs)

    # EDID auto-detect tab
    def _build_edid_tab(self):
        tab = QWidget()
        vbox = QVBoxLayout(tab)
        vbox.setContentsMargins(8, 12, 8, 8)
        vbox.setSpacing(12)

        desc = QLabel(
            "Detect connected displays via EDID and create panel profiles\nfrom their reported chromaticity data."
        )
        desc.setStyleSheet(f"font-size: 11px; color: {C.TEXT2}; line-height: 1.4;")
        desc.setWordWrap(True)
        vbox.addWidget(desc)

        # Display selector
        self._edid_combo = QComboBox()
        self._edid_combo.setFixedHeight(34)
        self._edid_combo.currentIndexChanged.connect(self._on_edid_display_changed)
        vbox.addWidget(self._edid_combo)

        # Info card
        info_card = QFrame()
        info_card.setStyleSheet(
            f"QFrame {{ background: {C.SURFACE2}; border: 1px solid {C.BORDER}; border-radius: 10px; padding: 12px; }}"
        )
        info_layout = QVBoxLayout(info_card)
        info_layout.setSpacing(6)

        self._edid_info_label = QLabel("Click 'Scan Displays' to detect connected monitors.")
        self._edid_info_label.setStyleSheet(f"font-size: 11px; color: {C.TEXT2};")
        self._edid_info_label.setWordWrap(True)
        info_layout.addWidget(self._edid_info_label)

        # Primaries display
        self._primaries_label = QLabel("")
        self._primaries_label.setStyleSheet(f"font-size: 11px; color: {C.TEXT}; font-family: 'Consolas', monospace;")
        self._primaries_label.setWordWrap(True)
        info_layout.addWidget(self._primaries_label)

        vbox.addWidget(info_card)

        # Panel type and gamma overrides
        override_form = QFormLayout()
        override_form.setSpacing(10)
        override_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        type_label = QLabel("Panel type")
        type_label.setStyleSheet(f"font-size: 12px; color: {C.TEXT};")
        self._panel_type_combo = QComboBox()
        self._panel_type_combo.addItems(["Auto", "QD-OLED", "WOLED", "IPS", "VA", "Mini-LED", "TN"])
        self._panel_type_combo.setFixedHeight(32)
        override_form.addRow(type_label, self._panel_type_combo)

        gamma_label = QLabel("Gamma")
        gamma_label.setStyleSheet(f"font-size: 12px; color: {C.TEXT};")
        self._gamma_combo = QComboBox()
        self._gamma_combo.addItems(["2.2 (standard)", "2.4 (VA / cinema)", "2.0", "1.8", "sRGB (2.2 + linear toe)"])
        self._gamma_combo.setFixedHeight(32)
        override_form.addRow(gamma_label, self._gamma_combo)

        vbox.addLayout(override_form)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        scan_btn = QPushButton("Scan Displays")
        scan_btn.setFixedHeight(34)
        scan_btn.setStyleSheet(
            f"QPushButton {{ background: {C.SURFACE}; border: 1px solid {C.BORDER}; "
            f"border-radius: 10px; font-size: 12px; padding: 6px 18px; }}"
            f"QPushButton:hover {{ border-color: {C.ACCENT}; background: {C.SURFACE2}; }}"
        )
        scan_btn.clicked.connect(self._scan_displays)
        btn_row.addWidget(scan_btn)

        btn_row.addStretch()

        self._create_btn = QPushButton("Create Profile")
        self._create_btn.setFixedHeight(34)
        self._create_btn.setProperty("primary", True)
        self._create_btn.setStyleSheet(
            f"QPushButton {{ background: {C.ACCENT}; border: none; color: white; "
            f"font-weight: 600; border-radius: 10px; font-size: 12px; padding: 6px 22px; }}"
            f"QPushButton:hover {{ background: {C.ACCENT_HI}; }}"
            f"QPushButton:disabled {{ background: {C.BORDER}; color: {C.TEXT3}; }}"
        )
        self._create_btn.setEnabled(False)
        self._create_btn.clicked.connect(self._create_edid_profile)
        btn_row.addWidget(self._create_btn)

        vbox.addLayout(btn_row)
        vbox.addStretch()

        # Internal state
        self._scanned_displays = []
        self._scanned_edid_data = []

        return tab

    # Import-from-file tab
    def _build_import_tab(self):
        tab = QWidget()
        vbox = QVBoxLayout(tab)
        vbox.setContentsMargins(8, 12, 8, 8)
        vbox.setSpacing(12)

        desc = QLabel(
            "Import a community .json panel profile into the database.\n"
            "Panel profiles contain chromaticity, gamma, and capability data."
        )
        desc.setStyleSheet(f"font-size: 11px; color: {C.TEXT2}; line-height: 1.4;")
        desc.setWordWrap(True)
        vbox.addWidget(desc)

        # File path display
        self._import_path_label = QLabel("No file selected")
        self._import_path_label.setStyleSheet(
            f"font-size: 11px; color: {C.TEXT3}; padding: 8px; "
            f"background: {C.SURFACE2}; border: 1px solid {C.BORDER}; border-radius: 8px;"
        )
        self._import_path_label.setWordWrap(True)
        vbox.addWidget(self._import_path_label)

        # Preview area
        self._import_preview = QLabel("")
        self._import_preview.setStyleSheet(
            f"font-size: 11px; color: {C.TEXT}; font-family: 'Consolas', monospace; "
            f"padding: 8px; background: {C.SURFACE2}; border: 1px solid {C.BORDER}; "
            f"border-radius: 8px;"
        )
        self._import_preview.setWordWrap(True)
        self._import_preview.setMinimumHeight(80)
        self._import_preview.hide()
        vbox.addWidget(self._import_preview)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        browse_btn = QPushButton("Browse...")
        browse_btn.setFixedHeight(34)
        browse_btn.setStyleSheet(
            f"QPushButton {{ background: {C.SURFACE}; border: 1px solid {C.BORDER}; "
            f"border-radius: 10px; font-size: 12px; padding: 6px 18px; }}"
            f"QPushButton:hover {{ border-color: {C.ACCENT}; background: {C.SURFACE2}; }}"
        )
        browse_btn.clicked.connect(self._browse_import_file)
        btn_row.addWidget(browse_btn)

        btn_row.addStretch()

        self._import_btn = QPushButton("Import Profile")
        self._import_btn.setFixedHeight(34)
        self._import_btn.setProperty("primary", True)
        self._import_btn.setStyleSheet(
            f"QPushButton {{ background: {C.ACCENT}; border: none; color: white; "
            f"font-weight: 600; border-radius: 10px; font-size: 12px; padding: 6px 22px; }}"
            f"QPushButton:hover {{ background: {C.ACCENT_HI}; }}"
            f"QPushButton:disabled {{ background: {C.BORDER}; color: {C.TEXT3}; }}"
        )
        self._import_btn.setEnabled(False)
        self._import_btn.clicked.connect(self._import_profile)
        btn_row.addWidget(self._import_btn)

        vbox.addLayout(btn_row)
        vbox.addStretch()

        self._import_file_path = None

        return tab

    # EDID scanning logic
    def _scan_displays(self):
        """Scan for connected displays not already in the panel database."""
        try:
            displays = qt_display_snapshots()

            self._edid_combo.clear()
            self._scanned_displays = []
            self._scanned_edid_data = []

            for i, display in enumerate(displays):
                name = display.name
                panel = None

                # Qt deliberately exposes no EDID bytes. Keep inferred color
                # characteristics empty instead of importing a writer-capable
                # legacy module merely to read them.
                edid_chromaticity = None
                edid_gamma = 2.2

                in_db = "  [in database]" if panel else "  [unknown]"
                res = f"{display.width}x{display.height}"
                self._edid_combo.addItem(f"{name}  ({res}){in_db}")

                self._scanned_displays.append(
                    {
                        "display": display,
                        "name": name,
                        "index": i,
                        "in_database": panel is not None,
                        "panel": panel,
                        "edid_chromaticity": edid_chromaticity,
                        "edid_gamma": edid_gamma,
                        "manufacturer": display.manufacturer or "Unknown",
                    }
                )
                self._scanned_edid_data.append(edid_chromaticity)

            if not displays:
                self._edid_info_label.setText("No displays detected.")
                self._create_btn.setEnabled(False)
            else:
                self._on_edid_display_changed(0)

        except (ImportError, OSError, AttributeError, KeyError) as e:
            self._edid_info_label.setText(f"Error scanning displays: {e}")
            self._create_btn.setEnabled(False)

    def _on_edid_display_changed(self, index):
        """Update info panel when a different display is selected."""
        if index < 0 or index >= len(self._scanned_displays):
            return

        info = self._scanned_displays[index]
        chrom = info["edid_chromaticity"]

        if info["in_database"]:
            panel = info["panel"]
            self._edid_info_label.setText(
                f"This display is already in the database as:\n{panel.name}  ({panel.panel_type})"
            )
            self._edid_info_label.setStyleSheet(f"font-size: 11px; color: {C.GREEN};")
            self._create_btn.setEnabled(False)
            if chrom:
                self._primaries_label.setText(
                    f"R({chrom['red'][0]:.4f}, {chrom['red'][1]:.4f})  "
                    f"G({chrom['green'][0]:.4f}, {chrom['green'][1]:.4f})  "
                    f"B({chrom['blue'][0]:.4f}, {chrom['blue'][1]:.4f})\n"
                    f"White({chrom['white'][0]:.4f}, {chrom['white'][1]:.4f})"
                )
            else:
                self._primaries_label.setText("")
        elif chrom:
            # Calculate approximate gamut coverage
            r, g, b = chrom["red"], chrom["green"], chrom["blue"]
            is_wide = r[0] > 0.66 or g[1] > 0.65
            gamut_desc = "Wide gamut (P3+)" if is_wide else "sRGB-class"

            self._edid_info_label.setText(
                f"EDID chromaticity detected - ready to create profile.\n"
                f"Gamut: {gamut_desc}   |   Gamma: {info['edid_gamma']:.1f}"
            )
            self._edid_info_label.setStyleSheet(f"font-size: 11px; color: {C.TEXT};")
            self._primaries_label.setText(
                f"R({r[0]:.4f}, {r[1]:.4f})  "
                f"G({g[0]:.4f}, {g[1]:.4f})  "
                f"B({b[0]:.4f}, {b[1]:.4f})\n"
                f"White({chrom['white'][0]:.4f}, {chrom['white'][1]:.4f})"
            )
            self._create_btn.setEnabled(True)
        else:
            self._edid_info_label.setText(
                "No EDID chromaticity data available for this display.\nA generic sRGB profile will be used."
            )
            self._edid_info_label.setStyleSheet(f"font-size: 11px; color: {C.YELLOW};")
            self._primaries_label.setText("")
            self._create_btn.setEnabled(False)

    def _create_edid_profile(self):
        """Create a panel profile from the selected display's EDID data."""
        index = self._edid_combo.currentIndex()
        if index < 0 or index >= len(self._scanned_displays):
            return

        info = self._scanned_displays[index]
        chrom = info["edid_chromaticity"]
        if not chrom:
            return

        # Resolve gamma override
        gamma_text = self._gamma_combo.currentText()
        if gamma_text.startswith("2.4"):
            gamma = 2.4
        elif gamma_text.startswith("2.0"):
            gamma = 2.0
        elif gamma_text.startswith("1.8"):
            gamma = 1.8
        else:
            gamma = info["edid_gamma"]

        # Resolve panel type override
        panel_type_text = self._panel_type_combo.currentText()

        try:
            from calibrate_pro.panels.database import DDCRecommendations, PanelDatabase, create_from_edid

            panel = create_from_edid(
                edid_chromaticity=chrom,
                monitor_name=info["name"],
                manufacturer=info["manufacturer"],
                gamma=gamma,
            )

            # Override panel type if user selected one
            if panel_type_text != "Auto":
                panel.panel_type = panel_type_text

            # Add generic DDC recommendations
            if panel.ddc is None:
                panel.ddc = DDCRecommendations(
                    notes=f"Auto-generated defaults for {info['name']}. "
                    "Adjust picture mode and color preset in your monitor's OSD "
                    "for best DDC/CI control."
                )

            # Save to profiles directory
            db = PanelDatabase()
            safe_name = info["name"].replace(" ", "_").replace("/", "_").replace("\\", "_")
            key = safe_name or f"EDID_Display_{index}"
            db.add_panel(key, panel)
            filepath = db.save_panel(key, f"{safe_name.lower()}.json")

            QMessageBox.information(
                self,
                "Profile Created",
                f"Panel profile created successfully.\n\n"
                f"Name: {info['name']}\n"
                f"Type: {panel.panel_type}\n"
                f"Gamma: {gamma}\n"
                f"Saved to: {filepath}",
            )

            self.display_added.emit()
            self.accept()

        except (ImportError, OSError, KeyError, ValueError) as e:
            QMessageBox.warning(self, "Error", f"Failed to create profile:\n{e}")

    # File import logic
    def _browse_import_file(self):
        """Open file dialog to select a .json panel profile."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Panel Profile", "", "JSON Panel Profiles (*.json);;All Files (*)"
        )
        if not path:
            return

        self._import_file_path = path
        self._import_path_label.setText(path)
        self._import_path_label.setStyleSheet(
            f"font-size: 11px; color: {C.TEXT}; padding: 8px; "
            f"background: {C.SURFACE2}; border: 1px solid {C.BORDER}; border-radius: 8px;"
        )

        # Preview the file
        try:
            import json

            with open(path, encoding="utf-8") as f:
                data = json.load(f)

            if isinstance(data, list):
                count = len(data)
                names = [d.get("display_name", d.get("model_pattern", "?")) for d in data[:5]]
                preview = f"{count} panel profile(s):\n" + "\n".join(f"  - {n}" for n in names)
                if count > 5:
                    preview += f"\n  ... and {count - 5} more"
            else:
                mfg = data.get("manufacturer", "?")
                name = data.get("display_name", data.get("model_pattern", "?"))
                ptype = data.get("panel_type", "?")
                preview = f"Manufacturer: {mfg}\nDisplay: {name}\nPanel type: {ptype}"

            self._import_preview.setText(preview)
            self._import_preview.show()
            self._import_btn.setEnabled(True)

        except (OSError, json.JSONDecodeError, ValueError, KeyError) as e:
            self._import_preview.setText(f"Error reading file: {e}")
            self._import_preview.show()
            self._import_btn.setEnabled(False)

    def _import_profile(self):
        """Import the selected JSON file into the panel database."""
        if not self._import_file_path:
            return

        try:
            import json
            import shutil

            from calibrate_pro.panels.database import PanelCharacterization, PanelDatabase

            with open(self._import_file_path, encoding="utf-8") as f:
                data = json.load(f)

            db = PanelDatabase()
            profiles_dir = db.profiles_dir
            profiles_dir.mkdir(parents=True, exist_ok=True)

            # Copy the file into the profiles directory
            dest = profiles_dir / Path(self._import_file_path).name
            if dest.exists():
                reply = QMessageBox.question(
                    self,
                    "File Exists",
                    f"{dest.name} already exists. Overwrite?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return

            shutil.copy2(self._import_file_path, dest)

            # Load and validate the profiles
            if isinstance(data, list):
                count = len(data)
                for panel_data in data:
                    panel = PanelCharacterization.from_dict(panel_data)
                    key = panel.model_pattern.split("|")[0]
                    db.add_panel(key, panel)
            else:
                panel = PanelCharacterization.from_dict(data)
                key = panel.model_pattern.split("|")[0]
                db.add_panel(key, panel)
                count = 1

            QMessageBox.information(
                self,
                "Import Successful",
                f"Imported {count} panel profile(s) from:\n{Path(self._import_file_path).name}\n\nSaved to: {dest}",
            )

            self.display_added.emit()
            self.accept()

        except (ImportError, OSError, json.JSONDecodeError, ValueError, KeyError) as e:
            QMessageBox.warning(self, "Import Error", f"Failed to import profile:\n{e}")


class DashboardPage(QWidget):
    """The displays this session observed, and nothing it did not observe.

    The page renders one detection summary. It enumerates no displays and opens
    no colorimeter of its own, because a card built from a second reading would
    describe machine state that no action performed and no journal entry
    covers. State this process owns rather than reads off the machine, the
    calibration guard and the startup registration, is supplied by the window
    that started those services.
    """

    navigate_to_calibrate = Signal(int)  # emits display index

    #: What a stat says when the window running this page never read it.
    NOT_READ = "Not read"

    def __init__(
        self,
        parent=None,
        preview_mode: bool = False,
        program_state: Callable[[], tuple[tuple[str, str], tuple[str, str]]] | None = None,
    ):
        super().__init__(parent)
        self.preview_mode = preview_mode
        self.preview_populated = False
        self.preview_metrics: tuple[MetricValue, ...] = ()
        self.observed: DetectionSummary | None = None
        self._program_state = program_state
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(24)

        # Header
        header_row = QHBoxLayout()
        header_row.addWidget(Heading("Displays"))
        header_row.addStretch()

        # Refresh runs the session's detection action, bound by the window that
        # owns this page. It is not connected to a redraw here, because a card
        # redrawn with no pass behind it would show an older observation under
        # a button that promises a newer one.
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setFixedHeight(32)
        header_row.addWidget(self.refresh_btn)

        self.add_display_btn = QPushButton("Add Display Profile")
        self.add_display_btn.setFixedHeight(32)
        self.add_display_btn.setStyleSheet(
            f"QPushButton {{ background: {C.SURFACE}; border: 1px solid {C.ACCENT}; "
            f"border-radius: 10px; font-size: 12px; padding: 6px 16px; color: {C.ACCENT_TX}; }}"
            f"QPushButton:hover {{ background: {C.SURFACE2}; border-color: {C.ACCENT_HI}; }}"
            f"QPushButton:disabled {{ background: {C.SURFACE}; border-color: {C.BORDER}; color: {C.TEXT3}; }}"
        )
        self.add_display_btn.clicked.connect(self._show_add_display_dialog)
        self.add_display_btn.setEnabled(not self.preview_mode)
        if self.preview_mode:
            self.add_display_btn.setToolTip("Disabled in simulated preview")
        header_row.addWidget(self.add_display_btn)

        # Enabled state, visibility, and tooltip belong to the binder in the
        # window that owns this page, which reads them from the session rather
        # than from this widget's idea of what the build can do.
        self.calibrate_all_btn = QPushButton("Calibrate All")
        self.calibrate_all_btn.setFixedHeight(32)
        self.calibrate_all_btn.setProperty("primary", not self.preview_mode)
        self.calibrate_all_btn.setEnabled(False)
        header_row.addWidget(self.calibrate_all_btn)

        layout.addLayout(header_row)

        # Display cards container
        self._cards_layout = QVBoxLayout()
        self._cards_layout.setSpacing(12)
        layout.addLayout(self._cards_layout)

        # Sensor status
        self._sensor_layout = QVBoxLayout()
        layout.addLayout(self._sensor_layout)

        # Stats row
        stats_row = QHBoxLayout()
        stats_row.setSpacing(24)
        self._stat_panels = Stat("Panel Profiles", "--")
        self._stat_sensor = Stat("Sensor", "--")
        self._stat_lut = Stat("Active LUT", "--")
        self._stat_guard = Stat("Guard", "--")
        self._stat_startup = Stat("Auto-Start", "--")
        stats_row.addWidget(self._stat_panels)
        stats_row.addWidget(self._stat_sensor)
        stats_row.addWidget(self._stat_lut)
        stats_row.addWidget(self._stat_guard)
        stats_row.addWidget(self._stat_startup)
        stats_row.addStretch()
        layout.addLayout(stats_row)

        layout.addStretch()
        scroll.setWidget(content)

        if self.preview_mode:
            QTimer.singleShot(0, self._populate)
        else:
            self._populate()

    def render_session(self, summary: DetectionSummary) -> None:
        """Show exactly what one detection pass observed, replacing the last."""
        self.observed = summary
        self._populate()

    def _populate(self) -> None:
        """Redraw the page from what it already holds, reading nothing new."""
        self._clear(self._cards_layout)
        self._clear(self._sensor_layout)
        if self.preview_mode:
            self._populate_preview()
            return
        self._populate_observed()

    @staticmethod
    def _clear(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _populate_observed(self) -> None:
        """Render the stored summary, or say plainly that there is not one."""
        self._populate_panel_count()
        self._populate_program_state()
        # Applying a DWM LUT now requires a separately confirmed plan.
        self._stat_lut.set_value("Confirmation required", C.TEXT3)

        summary = self.observed
        if summary is None:
            self._cards_layout.addWidget(self._notice("No detection pass has run in this session."))
            self._stat_sensor.set_value(self.NOT_READ, C.TEXT3)
            return

        for index, observation in enumerate(summary.dashboard.displays):
            card = self._display_card(index, observation)
            card.calibrate_clicked.connect(self.navigate_to_calibrate.emit)
            self._cards_layout.addWidget(card)
        for display_id, reason in summary.rejected:
            self._cards_layout.addWidget(self._notice(f"Not usable: {display_id} · {reason}"))
        if not summary.dashboard.displays:
            self._cards_layout.addWidget(self._notice("The last detection pass found no usable display."))
        self._populate_sensor(summary)

    def _display_card(self, index: int, observation: DisplayObservation) -> DisplayCard:
        """Build one card from one observation, claiming nothing more.

        Every colorimetric metric is Not measured, because a detection pass
        reads geometry and capability and never reads light. The primaries come
        from the panel characterization the pass matched, which describes a
        product rather than the unit on the desk.
        """
        characterization = observation.characterization
        return DisplayCard(
            observation.safe_label,
            f"{observation.width_px}x{observation.height_px} @ {refresh_text(observation.refresh_millihz)}",
            characterization_text(characterization),
            gamut_srgb=not_measured_metric("%"),
            gamut_p3=not_measured_metric("%"),
            gamut_bt2020=not_measured_metric("%"),
            calibrated=False,
            hdr=observation.hdr_enabled is True,
            cal_age=f"Calibration: Not measured · HDR: {hdr_text(observation.hdr_enabled)}",
            delta_e=not_measured_metric("dE2000"),
            red_xy=chromaticity_point(characterization.red_xy),
            green_xy=chromaticity_point(characterization.green_xy),
            blue_xy=chromaticity_point(characterization.blue_xy),
            peak_nits=not_measured_metric("nits"),
            display_index=index,
        )

    def _populate_sensor(self, summary: DetectionSummary) -> None:
        """Report the colorimeter exactly as the detection pass found it.

        The pass answers whether a supported sensor was present, not which
        product it was. Opening the device again here to recover a product
        string would put a second, unjournaled instrument read behind a label
        the session never produced. The live readout is offered only when the
        pass found a sensor, and it reads the device only when asked to.
        """
        available = any(display.capabilities.sensor_available for display in summary.dashboard.displays)
        self._sensor_layout.addWidget(SensorCard(available, "present"))
        if available:
            self._live_sensor = LiveSensorCard()
            self._sensor_layout.addWidget(self._live_sensor)
        self._stat_sensor.set_value(*(("Present", C.GREEN_HI) if available else ("Not detected", C.TEXT3)))

    def _populate_panel_count(self) -> None:
        """Count the bundled panel records, which is a read of a local file."""
        try:
            from calibrate_pro.panels.database import PanelDatabase

            self._stat_panels.set_value(str(len(PanelDatabase().list_panels())))
        except (ImportError, OSError, ValueError) as exc:
            logger.debug("Could not read the panel database: %s", exc)
            self._stat_panels.set_value("Unavailable", C.TEXT3)

    def _populate_program_state(self) -> None:
        """Show what the window knows about its services, or that it knows nothing."""
        if self._program_state is None:
            self._stat_guard.set_value(self.NOT_READ, C.TEXT3)
            self._stat_startup.set_value(self.NOT_READ, C.TEXT3)
            return
        guard, startup = self._program_state()
        self._stat_guard.set_value(*guard)
        self._stat_startup.set_value(*startup)

    def _notice(self, text: str) -> QLabel:
        """Render one line the page states rather than one it observed."""
        label = QLabel(text)
        label.setObjectName("dashboardNotice")
        label.setWordWrap(True)
        label.setStyleSheet(f"background: transparent; color: {C.TEXT3}; font-size: 12px;")
        return label

    def _populate_preview(self) -> None:
        """Populate only from the bundled fixture without consulting machine state."""
        from calibrate_pro.gui.preview import PreviewSnapshotProvider

        displays = PreviewSnapshotProvider().snapshots()
        metrics: list[MetricValue] = []
        for display in displays:
            snapshot = display.snapshot
            metrics.extend(display.metrics)
            card = DisplayCard(
                snapshot.name,
                display.resolution,
                display.panel_type,
                gamut_srgb=display.gamut_srgb,
                gamut_p3=display.gamut_p3,
                gamut_bt2020=display.gamut_bt2020,
                calibrated=False,
                hdr=False,
                cal_age="Calibration: Not measured",
                delta_e=display.delta_e,
                peak_nits=display.peak_luminance,
                display_index=snapshot.index,
                actions_enabled=False,
            )
            self._cards_layout.addWidget(card)

        evidence_card, evidence_layout = Card.with_layout(spacing=4)
        evidence_label = QLabel(
            "Preview evidence · simulated values use the bundled public fixture · colorimeter: Not measured"
        )
        evidence_label.setObjectName("previewEvidenceLabel")
        evidence_label.setStyleSheet(f"background: transparent; color: {C.TEXT2}; font-size: 11px;")
        evidence_layout.addWidget(evidence_label)
        self._sensor_layout.addWidget(evidence_card)

        self.preview_metrics = tuple(metrics)
        self._stat_panels.set_value(f"{len(displays)} simulated", C.ACCENT_TX)
        self._stat_sensor.set_value("Not measured", C.TEXT3)
        self._stat_lut.set_value("Not measured", C.TEXT3)
        self._stat_guard.set_value("Disabled in preview", C.TEXT3)
        self._stat_startup.set_value("Not measured", C.TEXT3)
        self.preview_populated = True

    def _show_add_display_dialog(self):
        """Show the Add Display Profile dialog."""
        dialog = AddDisplayDialog(self)
        dialog.display_added.connect(self._populate)
        dialog.exec()


# Placeholder Pages (to be rebuilt individually)


class PlaceholderPage(QWidget):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.addWidget(Heading(title))
        layout.addWidget(QLabel("This page is being rebuilt."))
        layout.addStretch()


class PreviewModePage(QWidget):
    """Safe page surface used when action-heavy workflows are unavailable."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(16)
        layout.addWidget(Heading(title))
        message = QLabel(
            "Simulated preview keeps this workflow visible but inactive.\n"
            "No hardware access, profile writes, startup changes, exports, or display changes are available."
        )
        message.setWordWrap(True)
        message.setStyleSheet(f"color: {C.TEXT2}; font-size: 12px;")
        layout.addWidget(message)
        layout.addStretch()


# Main Window


class CalibrateProWindow(QMainWindow):
    """Main application window."""

    def __init__(
        self,
        preview_mode: bool = False,
        service: FunctionalRecoveryService | None = None,
    ):
        """Build the window around one session service.

        The service is injectable so a test can drive this window against a
        composition that touches no hardware. Building the production one costs
        nothing on its own: it wires a detector and a generator and reads no
        display until an action asks it to.
        """
        super().__init__()
        self.preview_mode = preview_mode
        self.service = service if service is not None else build_production_service()
        self._binder = ActionBinder(
            self.service,
            report=self.show_toast,
            restrict=self._preview_restriction if preview_mode else None,
        )
        self.settings = QSettings(APP_ORG, APP_NAME)
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.setMinimumSize(900, 600)
        self.resize(1200, 800)
        self.setStyleSheet(STYLE)
        self._app_icon = make_app_icon()
        self.setWindowIcon(self._app_icon)

        # Declared before the pages are built. The dashboard asks the window
        # what its services are doing while it draws its first frame, and a
        # window that has not started them yet answers that it has not read
        # them rather than raising.
        self._guard = None
        self._startup = None

        self._build_menubar()
        self._build_central()
        self._build_statusbar()
        self._setup_shortcuts()

        if self.preview_mode:
            self._status.setText("Simulated preview · hardware and display changes disabled")
        else:
            self._build_tray()
            self._restore_geometry()
            self._start_services()
            self._update_tray_state()

            # Periodic tray state refresh (every 60 seconds)
            self._tray_timer = QTimer(self)
            self._tray_timer.timeout.connect(self._update_tray_state)
            self._tray_timer.start(60_000)

            self._prime_session()
            QTimer.singleShot(500, self._check_first_run)

    # --- Action policy for this surface ---

    def _preview_restriction(self, resolved: ResolvedAction) -> ResolvedAction:
        """Narrow every action that reaches past the interface.

        The preview banner promises no hardware access and no display changes.
        This keeps that promise per control: reading a display is refused here
        even though the session would allow it, because the promise covers
        reads. A narrowing can only make an answer stricter, so this can never
        offer something the session itself would refuse.
        """
        if self.service.classification(resolved.action_id) is ActionClassification.UI_ONLY:
            return resolved
        return replace(
            resolved,
            disposition=ActionDisposition.DISABLED,
            reason=PREVIEW_DISABLED_REASON,
        )

    def _prime_session(self) -> None:
        """Detect once at startup so the menu describes a real session.

        Every control is rendered from session state. Without this the window
        would open showing a menu resolved against an empty session, and the
        HDR entry would answer from a detection pass that never ran.
        """
        self._detect_displays()
        self._binder.refresh()

    # --- Background Services ---

    def _start_services(self):
        """Start calibration guard and other background services."""
        import logging

        logger = logging.getLogger(__name__)

        try:
            from calibrate_pro.utils.startup_manager import StartupManager

            # Constructing this creates the application config directory, so it
            # happens once here rather than every time a page redraws.
            self._startup = StartupManager()
        except (ImportError, OSError) as exc:
            logger.debug("StartupManager not available: %s", exc)

        try:
            from calibrate_pro.services.calibration_guard import CalibrationGuard, GuardedDisplay

            def on_restore(display_name, reason):
                self.show_toast(
                    f"Restored calibration for {display_name} ({reason})",
                    level="success",
                )

            guard = CalibrationGuard(check_interval=15.0, on_restore=on_restore)

            # Guard is monitor-only. Qt supplies identity without opening any
            # writer-capable monitor or gamma-ramp handle.
            for display in qt_display_snapshots():
                guard.guard_display(
                    GuardedDisplay(
                        device_name=display.device_name,
                        display_name=display.name,
                    )
                )

            guard.start()
            self._guard = guard
            logger.info("CalibrationGuard started (checking every 15s)")

        except (ImportError, OSError, RuntimeError) as e:
            logger.debug("CalibrationGuard not started: %s", e)

    def show_toast(self, message: str, level: str = "info"):
        """Show a toast notification in the bottom-right corner of the window.

        Args:
            message: The text to display.
            level: One of "info", "success", or "warning".
        """
        toast = ToastNotification(message, level, parent=self)
        # Position in bottom-right of the window
        margin = 16
        x = self.width() - toast.width() - margin
        y = self.height() - toast.height() - margin
        toast.move(x, y)
        toast.slide_in()

    def _stop_services(self):
        """Stop background services."""
        if self._guard:
            self._guard.stop()
            self._guard = None

    # --- First-Run Wizard ---

    def _check_first_run(self):
        """Show welcome wizard on first launch."""
        if self.settings.value("first_run_completed", False, type=bool):
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Welcome to Calibrate Pro")
        dialog.setFixedSize(500, 400)
        dialog.setStyleSheet(f"""
            QDialog {{
                background: {C.BG};
                border-radius: 16px;
            }}
            QLabel {{
                background: transparent;
            }}
        """)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(36, 32, 36, 28)
        layout.setSpacing(16)

        # Title
        title = QLabel("Welcome to Calibrate Pro")
        title.setStyleSheet(f"font-size: 22px; font-weight: 600; color: {C.ACCENT_TX};")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # Description
        desc = QLabel("Professional display calibration for Windows and macOS")
        desc.setStyleSheet(f"font-size: 13px; color: {C.TEXT2};")
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(desc)

        layout.addSpacing(8)

        # Detected displays
        displays_heading = QLabel("Detected Displays")
        displays_heading.setStyleSheet(f"font-size: 14px; font-weight: 500; color: {C.TEXT};")
        layout.addWidget(displays_heading)

        try:
            displays = qt_display_snapshots()
            if displays:
                for d in displays:
                    name = d.name
                    res = f"{d.width}x{d.height} @ {d.refresh_rate}Hz"
                    row = QHBoxLayout()
                    dot = StatusDot(C.GREEN, 8)
                    row.addWidget(dot)
                    lbl = QLabel(f"{name}  ({res})")
                    lbl.setStyleSheet(f"font-size: 12px; color: {C.TEXT};")
                    row.addWidget(lbl, stretch=1)
                    layout.addLayout(row)
            else:
                no_disp = QLabel("No displays detected")
                no_disp.setStyleSheet(f"font-size: 12px; color: {C.TEXT3};")
                layout.addWidget(no_disp)
        except (ImportError, OSError):
            no_disp = QLabel("Could not enumerate displays")
            no_disp.setStyleSheet(f"font-size: 12px; color: {C.TEXT3};")
            layout.addWidget(no_disp)

        layout.addSpacing(4)

        # Sensor status
        sensor_text = "No colorimeter \u2014 sensorless mode available"
        sensor_color = C.TEXT3
        try:
            from calibrate_pro.hardware.i1d3_native import I1D3Driver

            devices = I1D3Driver.find_devices()
            if devices:
                sensor_name = devices[0].get("product", "i1Display3")
                sensor_text = f"Colorimeter detected: {sensor_name}"
                sensor_color = C.GREEN_HI
        except (ImportError, OSError, RuntimeError):
            pass

        sensor_row = QHBoxLayout()
        sensor_dot = StatusDot(sensor_color, 8)
        sensor_row.addWidget(sensor_dot)
        sensor_lbl = QLabel(sensor_text)
        sensor_lbl.setStyleSheet(f"font-size: 12px; color: {sensor_color};")
        sensor_row.addWidget(sensor_lbl, stretch=1)
        layout.addLayout(sensor_row)

        layout.addStretch()

        # Get Started button
        get_started = QPushButton("Get Started")
        get_started.setProperty("primary", True)
        get_started.setFixedHeight(38)
        get_started.setCursor(Qt.CursorShape.PointingHandCursor)
        get_started.clicked.connect(dialog.accept)
        layout.addWidget(get_started)

        dialog.exec()
        self.settings.setValue("first_run_completed", True)

    # --- Keyboard Shortcuts ---

    def _setup_shortcuts(self):
        """Register keyboard shortcuts not already attached to menu actions.

        Menu-based shortcuts (Ctrl+1..6, Ctrl+Shift+C, F5) are set in
        _build_menubar via QAction.setShortcut so they appear in the menus.
        This method adds only the non-menu shortcuts.
        """
        # Escape -- Minimize to tray or minimize window
        sc_escape = QShortcut(QKeySequence("Escape"), self)
        sc_escape.activated.connect(self._escape_action)

    def _shortcut_switch_page(self, index: int):
        """Switch to a page by index and update sidebar."""
        self._switch_page(index)
        self.sidebar._on_click(index)

    def _escape_action(self):
        """Minimize to tray if available, otherwise minimize window."""
        if hasattr(self, "_tray") and self._tray.isVisible():
            self.hide()
        else:
            self.showMinimized()

    # --- Menu Bar ---

    def _build_menubar(self):
        """Build the menu bar, binding every entry to the action it stands for.

        No entry decides for itself whether it is available. Each one is handed
        to the binder, which asks the session and renders that answer, so a menu
        can never offer something the session would turn down.
        """
        mb = self.menuBar()
        self._build_file_menu(mb.addMenu("&File"))
        self._build_view_menu(mb.addMenu("&View"))
        self._build_display_menu(mb.addMenu("&Display"))
        self._build_tools_menu(mb.addMenu("&Tools"))
        self._binder.bind(
            "help.about",
            menu_action(mb.addMenu("&Help"), "&About", self),
            partial(self.service.perform_ui, "help.about", self._about),
        )

    def _build_file_menu(self, menu: QMenu) -> None:
        self._binder.bind(
            "calibration.all",
            menu_action(menu, "&Calibrate All", self, "Ctrl+Shift+C"),
            partial(self.service.unhandled, "calibration.all"),
        )
        menu.addSeparator()

        export = menu.addMenu("&Export")
        for export_name, label in EXPORT_MENU_ENTRIES:
            self._binder.bind(
                f"export.active.{export_name}",
                menu_action(export, label, self),
                partial(self._export_format, export_name),
                on_success=self._report_export,
            )

        menu.addSeparator()
        self._binder.bind(
            "application.exit",
            menu_action(menu, "E&xit", self, "Alt+F4"),
            partial(self.service.perform_ui, "application.exit", self.close),
        )

    def _build_view_menu(self, menu: QMenu) -> None:
        for index, (label, shortcut, action_id) in enumerate(PAGE_MENU_ENTRIES):
            self._binder.bind(
                action_id,
                menu_action(menu, label, self, shortcut),
                partial(
                    self.service.perform_ui,
                    action_id,
                    partial(self._shortcut_switch_page, index),
                ),
            )
        menu.addSeparator()
        self._bind_detect(menu_action(menu, "&Refresh Dashboard", self, "F5"))

    def _build_display_menu(self, menu: QMenu) -> None:
        self._bind_detect(menu_action(menu, "&Detect Displays", self))
        self._binder.bind(
            "display.restore_defaults",
            menu_action(menu, "&Restore Defaults", self),
            partial(self.service.unhandled, "display.restore_defaults"),
        )
        menu.addSeparator()
        self._binder.bind(
            "profile.install",
            menu_action(menu, "&Install ICC Profile...", self),
            partial(self.service.unhandled, "profile.install"),
        )

    def _build_tools_menu(self, menu: QMenu) -> None:
        self._binder.bind(
            "patterns.open",
            menu_action(menu, "&Test Patterns", self),
            partial(self.service.unhandled, "patterns.open"),
        )
        self._binder.bind(
            "display.hdr_status",
            menu_action(menu, "&HDR Status", self),
            self.service.hdr_status,
            on_success=self._show_hdr_status,
        )

    def _bind_detect(self, control: QAction) -> None:
        """Bind one more entry to the single detection action.

        Two menus offer detection. Both run the same action and are rendered
        from the same answer, so they cannot disagree about whether it is
        available or about what it found.
        """
        self._binder.bind(
            "display.detect",
            control,
            self._detect_displays,
            on_success=self._report_detection,
        )

    # --- Central Widget ---

    def _build_central(self):
        central = QWidget()
        outer_layout = QVBoxLayout(central)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        if self.preview_mode:
            self.preview_banner = QLabel(
                "Simulated preview · bundled public fixture · no hardware access · no display changes"
            )
            self.preview_banner.setObjectName("previewBanner")
            self.preview_banner.setFixedHeight(38)
            self.preview_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.preview_banner.setStyleSheet(
                f"background: {C.SURFACE2}; color: {C.ACCENT_TX}; "
                f"border-bottom: 1px solid {C.ACCENT}; font-weight: 600; padding: 8px 16px;"
            )
            outer_layout.addWidget(self.preview_banner)

        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        outer_layout.addLayout(main_layout, stretch=1)

        # Sidebar
        self.sidebar = Sidebar(CAL_PAGES, app_name=APP_NAME, app_version=APP_VERSION)
        self.sidebar.page_changed.connect(self._switch_page)
        main_layout.addWidget(self.sidebar)

        # Page stack
        self.stack = QStackedWidget()
        self.stack.setStyleSheet(f"background: {C.BG};")

        self.dashboard = DashboardPage(
            preview_mode=self.preview_mode,
            program_state=self._program_state,
        )
        self.dashboard.navigate_to_calibrate.connect(self._navigate_to_calibrate)
        self._bind_detect(self.dashboard.refresh_btn)
        self._binder.bind(
            "calibration.all",
            self.dashboard.calibrate_all_btn,
            partial(self.service.unhandled, "calibration.all"),
        )
        self.stack.addWidget(self.dashboard)  # 0

        if self.preview_mode:
            for title in CAL_PAGES[1:]:
                self.stack.addWidget(PreviewModePage(title))
        else:
            # Calibrate page
            try:
                from calibrate_pro.gui.pages.calibrate import CalibratePage

                cal_page = CalibratePage()
                cal_page.calibration_completed.connect(self._update_tray_state)
                self.stack.addWidget(cal_page)  # 1
            except (ImportError, AttributeError) as e:
                logger.warning("Failed to load CalibratePage: %s", e)
                self.stack.addWidget(PlaceholderPage("Calibrate"))  # 1

            # Verify page
            try:
                from calibrate_pro.gui.pages.verify import VerifyPage

                self.verify_page = VerifyPage()
                self.verify_page.bind_actions(
                    self._binder,
                    select_display=self.service.select_display,
                    run_sensorless=self.service.verify,
                    run_measured=partial(self.service.unhandled, "verification.measured"),
                    save_report=self.service.export,
                )
                self.stack.addWidget(self.verify_page)  # 2
            except (ImportError, TypeError) as e:
                logger.warning("Failed to load VerifyPage: %s", e)
                self.stack.addWidget(PlaceholderPage("Verify"))  # 2
            # Profiles page
            try:
                from calibrate_pro.gui.pages.profiles import ProfilesPage

                self.stack.addWidget(ProfilesPage())  # 3
            except ImportError as e:
                logger.warning("Failed to load ProfilesPage: %s", e)
                self.stack.addWidget(PlaceholderPage("Profiles"))  # 3

            # DDC Control page
            try:
                from calibrate_pro.gui.pages.ddc_control import DDCControlPage

                self.ddc = DDCControlPage()
                self.ddc.bind_actions(self._binder, self.service.unhandled)
                self.stack.addWidget(self.ddc)  # 4
            except (ImportError, RuntimeError) as e:
                logger.warning("Failed to load DDCControlPage: %s", e)
                self.stack.addWidget(PlaceholderPage("DDC Control"))  # 4

            # Settings page
            try:
                from calibrate_pro.gui.pages.settings import SettingsPage

                self.settings_page = SettingsPage()
                self.settings_page.bind_actions(
                    self._binder,
                    set_output_directory=self.service.set_export_directory,
                )
                self.stack.addWidget(self.settings_page)  # 5
            except (ImportError, OSError) as e:
                logger.warning("Failed to load SettingsPage: %s", e)
                self.stack.addWidget(PlaceholderPage("Settings"))  # 5

        main_layout.addWidget(self.stack, stretch=1)
        self.setCentralWidget(central)

    # --- Status Bar ---

    def _build_statusbar(self):
        sb = self.statusBar()
        self._status = QLabel("Ready")
        sb.addWidget(self._status, 1)

    # --- System Tray ---

    def _build_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        self._tray = QSystemTrayIcon(self)
        self._tray.setIcon(self._app_icon)
        self._tray.setToolTip(f"{APP_NAME} -- Display Calibration")

        menu = QMenu()
        menu.setStyleSheet(STYLE)

        self._binder.bind(
            "window.show",
            menu_action(menu, "Show Window", self),
            partial(self.service.perform_ui, "window.show", self._show_window),
        )

        menu.addSeparator()

        self._binder.bind(
            "calibration.all",
            menu_action(menu, "Calibrate All Displays", self),
            partial(self.service.unhandled, "calibration.all"),
        )
        self._binder.bind(
            "display.restore_defaults",
            menu_action(menu, "Restore Defaults", self),
            partial(self.service.unhandled, "display.restore_defaults"),
        )

        menu.addSeparator()

        # --- Switch Profile submenu ---
        self._profile_submenu = menu.addMenu("Switch Profile")
        self._rebuild_profile_submenu()

        menu.addSeparator()

        self._binder.bind(
            "application.exit",
            menu_action(menu, "Exit", self),
            partial(self.service.perform_ui, "application.exit", self._quit),
        )

        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._tray_clicked)
        self._tray.show()

    def _tray_clicked(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.isVisible():
                self.hide()
            else:
                self.showNormal()
                self.activateWindow()

    def _update_tray_state(self):
        """Check calibration status across all displays and update the tray icon/tooltip."""
        if not hasattr(self, "_tray"):
            return

        try:
            from datetime import datetime

            from calibrate_pro.utils.startup_manager import StartupManager

            mgr = StartupManager()
            displays = qt_display_snapshots()

            calibrated_count = 0
            stale_count = 0
            total = len(displays)
            per_display_status = []

            for i, d in enumerate(displays):
                name = d.name
                cal = mgr.get_display_calibration(i)
                if cal and cal.lut_path and Path(cal.lut_path).exists():
                    # Check age
                    is_stale = False
                    if cal.last_calibrated:
                        try:
                            cal_dt = datetime.fromisoformat(cal.last_calibrated)
                            age_days = (datetime.now() - cal_dt).days
                            if age_days > 30:
                                is_stale = True
                        except (ValueError, TypeError):
                            pass
                    if is_stale:
                        stale_count += 1
                        per_display_status.append(f"{name}: stale")
                    else:
                        calibrated_count += 1
                        per_display_status.append(f"{name}: calibrated")
                else:
                    per_display_status.append(f"{name}: not calibrated")

            # Determine icon color and tooltip
            if total == 0:
                icon_color = C.TEXT3
                tooltip = f"{APP_NAME} - No displays detected"
            elif calibrated_count == total:
                icon_color = C.GREEN
                tooltip = f"{APP_NAME} - All displays calibrated"
            elif (
                stale_count > 0 and (calibrated_count + stale_count) == total or calibrated_count > 0 or stale_count > 0
            ):
                icon_color = C.YELLOW
                tooltip = f"{APP_NAME} - {', '.join(per_display_status)}"
            else:
                icon_color = C.TEXT3
                tooltip = f"{APP_NAME} - No calibration applied"

            self._tray.setIcon(make_tray_icon(icon_color))
            self._tray.setToolTip(tooltip)

        except (ImportError, OSError, AttributeError) as e:
            logger.debug("Could not update tray state: %s", e)
            # Fall back to default icon
            self._tray.setIcon(make_tray_icon(C.TEXT3))
            self._tray.setToolTip(f"{APP_NAME} - Display Calibration")

    def _rebuild_profile_submenu(self):
        """Populate the tray 'Switch Profile' submenu with available profiles."""
        if not hasattr(self, "_profile_submenu"):
            return
        self._profile_submenu.clear()

        cal_dir = Path.home() / "Documents" / "Calibrate Pro" / "Calibrations"
        if not cal_dir.exists():
            no_act = QAction("No profiles found", self)
            no_act.setEnabled(False)
            self._profile_submenu.addAction(no_act)
            return

        # Find all .cube files
        cube_files = sorted(cal_dir.glob("*.cube"))
        if not cube_files:
            no_act = QAction("No profiles found", self)
            no_act.setEnabled(False)
            self._profile_submenu.addAction(no_act)
            return

        # Determine currently active profile stem
        active_stem = None
        try:
            from calibrate_pro.utils.startup_manager import StartupManager

            mgr = StartupManager()
            cal = mgr.get_display_calibration(0)
            if cal and cal.lut_path:
                active_stem = Path(cal.lut_path).stem
        except (ImportError, OSError, AttributeError):
            pass

        for cube in cube_files:
            name = cube.stem.replace("_", " ").replace("-", " \u2014 ", 1)
            act = QAction(name, self)
            act.setCheckable(True)
            if active_stem and cube.stem == active_stem:
                act.setChecked(True)
            act.triggered.connect(lambda checked, p=str(cube): self._apply_tray_profile(p))
            self._profile_submenu.addAction(act)

    def _apply_tray_profile(self, cube_path: str):
        """Stage a calibration profile selection without changing display state."""
        profile_name = Path(cube_path).stem.replace("_", " ")
        self.show_toast(
            f"Preview selected: {profile_name}. Open Calibrate to review and confirm.",
            level="info",
        )

    def _quit(self):
        self._stop_services()
        if hasattr(self, "_tray_timer"):
            self._tray_timer.stop()
        if hasattr(self, "_tray"):
            self._tray.hide()
        QApplication.quit()

    # --- Actions ---

    def _switch_page(self, index: int):
        """Switch page with a subtle opacity fade transition."""
        if index == self.stack.currentIndex():
            return
        target = self.stack.widget(index)
        if target:
            try:
                from PySide6.QtCore import QEasingCurve, QPropertyAnimation
                from PySide6.QtWidgets import QGraphicsOpacityEffect

                effect = QGraphicsOpacityEffect(target)
                target.setGraphicsEffect(effect)
                effect.setOpacity(0.3)
                self.stack.setCurrentIndex(index)

                anim = QPropertyAnimation(effect, b"opacity")
                anim.setDuration(150)
                anim.setStartValue(0.3)
                anim.setEndValue(1.0)
                anim.setEasingCurve(QEasingCurve.Type.OutCubic)
                anim.finished.connect(lambda: target.setGraphicsEffect(None))
                self._page_anim = anim  # prevent GC
                anim.start()
            except (AttributeError, RuntimeError):
                self.stack.setCurrentIndex(index)
        else:
            self.stack.setCurrentIndex(index)

    def _navigate_to_calibrate(self, display_index: int) -> None:
        """Open the Calibrate page for one display, through the session.

        The card that emits this is not a bound control, so a refusal is
        reported here rather than by the binder.
        """
        outcome = self.service.perform_ui("navigation.calibrate", lambda: self._open_calibrate(display_index))
        if isinstance(outcome, ActionError):
            self.show_toast(refusal_message(outcome), "warning")

    def _open_calibrate(self, display_index: int) -> None:
        """Switch to the Calibrate page and pre-select the given display."""
        self._shortcut_switch_page(1)
        cal_page = self.stack.widget(1)
        if hasattr(cal_page, "display_combo") and display_index < cal_page.display_combo.count():
            cal_page.display_combo.setCurrentIndex(display_index)

    def _show_window(self) -> None:
        """Bring the window forward from the tray."""
        self.showNormal()
        self.activateWindow()

    # --- Bound action handlers ---

    def _detect_displays(self) -> ActionOutcome[DetectionSummary]:
        """Run the session's detection pass, then repaint what renders it.

        The pages are refreshed only after the action succeeded. A refused
        detection leaves them showing the last state the session actually
        observed, rather than a newer reading nothing recorded. The DDC page is
        optional because its import is allowed to fail into a placeholder.
        """
        outcome = self.service.detect()
        if isinstance(outcome, ActionSuccess):
            pages = (self.dashboard, getattr(self, "ddc", None), getattr(self, "verify_page", None))
            for page in pages:
                if page is not None:
                    page.render_session(outcome.value)
        return outcome

    def _program_state(self) -> tuple[tuple[str, str], tuple[str, str]]:
        """Report the two services this process runs, for the dashboard to show.

        Both are read here rather than by the page, so redrawing a card never
        reaches the registry and never creates the application config
        directory. A window whose services never started answers that it did
        not read them, rather than reporting a disabled state it never checked.
        """
        guard = self._guard
        if guard is not None and guard.is_running:
            restores = guard.restore_count
            guard_state = (f"Active ({restores} restores)" if restores else "Active", C.GREEN_HI)
        else:
            guard_state = ("Inactive", C.TEXT3)
        startup = self._startup
        if startup is None:
            return guard_state, (DashboardPage.NOT_READ, C.TEXT3)
        if startup.is_startup_enabled():
            return guard_state, ("Enabled", C.GREEN_HI)
        return guard_state, ("Disabled", C.TEXT3)

    def _report_detection(self, summary: DetectionSummary) -> None:
        """Say what the pass found, including the displays it turned down."""
        text = f"{len(summary.dashboard.displays)} display(s) detected"
        rejected = len(summary.rejected)
        if rejected:
            text = f"{text}, {rejected} not usable"
        self._status.setText(text)

    def _export_format(self, export_name: str) -> "ActionOutcome[ExportBundle] | None":
        """Publish one generated format into a directory the operator chooses.

        The dialog asks for a directory rather than a filename. A single-format
        export writes the asset together with a manifest sealing it, so what
        lands on disk is a small directory, and naming a file would describe
        something the export does not produce.

        Choosing the directory is its own journaled action and its refusal is
        returned unchanged, so an export is never reported against a directory
        the session rejected. Closing the dialog reports nothing at all.
        """
        directory = QFileDialog.getExistingDirectory(self, f"Export {export_name} into folder")
        if not directory:
            return None
        chosen = self.service.set_export_directory(directory)
        if isinstance(chosen, ActionError):
            return chosen
        return self.service.export_format(export_name)

    def _report_export(self, bundle: ExportBundle) -> None:
        """Name what was written, taken from the manifest that seals it."""
        self._status.setText(
            f"Exported {len(bundle.assets)} file(s) to {bundle.directory} ({bundle.manifest_filename})"
        )

    def _show_hdr_status(self, status: HdrStatus) -> None:
        """Show the HDR switch positions the last detection pass observed.

        A display whose switch was never read says so. Rendering an unanswered
        query as SDR would turn a missing observation into an observed value.
        """
        lines = "\n".join(f"{entry.safe_label}: {entry.summary}" for entry in status.displays)
        QMessageBox.information(
            self,
            "HDR Status",
            f"{lines or 'No displays in this session.'}\n\nObserved {status.observed_utc}",
        )

    def _about(self):
        QMessageBox.about(
            self,
            "About Calibrate Pro",
            f"<h2>{APP_NAME}</h2>"
            f"<p>Version {APP_VERSION}</p>"
            f"<p>Professional sensorless display calibration<br>"
            f"with native colorimeter support.</p>"
            f"<p>Color science: Oklab, JzAzBz, CAM16, PQ/HLG, ACES</p>"
            f"<p>&copy; 2022-2026 Zain Dana Harper</p>",
        )

    # --- Geometry persistence ---

    def _restore_geometry(self):
        geo = self.settings.value("window/geometry")
        if geo:
            self.restoreGeometry(geo)

    def closeEvent(self, event):
        if not self.preview_mode:
            self.settings.setValue("window/geometry", self.saveGeometry())
        # Minimize to tray instead of closing
        if hasattr(self, "_tray") and self._tray.isVisible():
            event.ignore()
            self.hide()
            self._tray.showMessage(
                APP_NAME,
                "Running in the background. Right-click tray icon to exit.",
                QSystemTrayIcon.MessageIcon.Information,
                2000,
            )
        else:
            event.accept()


# Entry Point


def launch():
    """Launch the Calibrate Pro GUI."""
    # Windows taskbar icon fix -- set app user model ID
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("build.calibratepro.1")
    except (AttributeError, OSError):
        pass

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_ORG)
    app.setWindowIcon(make_app_icon())

    window = CalibrateProWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(launch())
