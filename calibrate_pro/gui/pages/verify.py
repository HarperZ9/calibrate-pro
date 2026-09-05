"""Verification results, drawn from what the session answered.

The page shows one predicted verification and says on its face that it is
predicted. It reads no display, opens no sensor, runs no thread of its own and
writes no file. Each of those was here: the page enumerated displays on a timer
300ms after it was built, ran the accuracy model in a ``QThread``, opened a raw
USB device with a vendor unlock key, and wrote a report straight to a path from
a file dialog with no action behind the write.

What is left is drawing. The reference ColorChecker is on screen from the start
so the grid is never blank, figures appear only once an action produced them,
and every figure carries the evidence label the session attached to it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from calibrate_pro.application.assets import ExportBundle
from calibrate_pro.application.outcomes import ActionOutcome
from calibrate_pro.application.prediction import DELTA_E_UNIT
from calibrate_pro.application.results import DetectionSummary, VerificationResult
from calibrate_pro.gui.action_binding import ActionBinder, Operation, SurfaceBinding
from calibrate_pro.gui.app import C, Card, GamutBar, Heading, Stat
from calibrate_pro.gui.widgets.cie_diagram import CIEDiagramWidget
from calibrate_pro.sensorless.neuralux import COLORCHECKER_CLASSIC
from calibrate_pro.verification.provenance import EvidenceKind, MetricValue

#: Offered in the selector when the last detection pass observed no display.
NO_DISPLAY_ITEM = "No display in this session"

#: Under the grid until an action has produced a result.
NOT_RUN_NOTE = "No verification has been run in this session."

#: Beside the chromaticity plot, which draws reference gamuts and nothing else.
CIE_NOTE = "Reference gamuts. This build measures no display primaries."

#: Beside the coverage bars, which no action in this build fills in.
GAMUT_NOTE = "No action in this build reports gamut coverage."


def _not_measured(unit: str) -> MetricValue:
    return MetricValue(None, unit, EvidenceKind.NOT_MEASURED)


def _metric_or_not_measured(value: object, unit: str) -> MetricValue:
    return value if isinstance(value, MetricValue) else _not_measured(unit)


def _metric_colour(metric: MetricValue) -> str:
    """Colour a figure by whether there is one, not by how good it is.

    A verification that reported nothing reads in the same muted colour as the
    label beneath it. Grading the number by threshold here would put a pass or
    fail judgement on the screen that no action in this build makes.
    """
    return C.ACCENT_TX if metric.value is not None else C.TEXT3


# ColorChecker Patch Widget


class ColorPatchWidget(QWidget):
    """
    Single ColorChecker patch: top half reference color, bottom half
    predicted/measured color, Delta E overlay, colored border.
    """

    def __init__(
        self,
        name: str = "",
        ref_srgb: tuple = (0.5, 0.5, 0.5),
        pred_srgb: tuple | None = None,
        delta_e: MetricValue | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._name = name
        self._ref = ref_srgb
        self._pred = pred_srgb
        self._de = delta_e or _not_measured("dE2000")
        if not isinstance(self._de, MetricValue):
            raise TypeError("delta_e must be a MetricValue")
        self.setFixedSize(64, 64)
        self.setToolTip(
            f"{name}\ndE: {self._de.display_text()}\n"
            f"Evidence source: {self._de.source or 'Not measured'}\n"
            f"Ref  sRGB: ({ref_srgb[0]:.3f}, {ref_srgb[1]:.3f}, {ref_srgb[2]:.3f})\n"
            + (
                f"Observed sRGB: ({pred_srgb[0]:.3f}, {pred_srgb[1]:.3f}, {pred_srgb[2]:.3f})"
                if pred_srgb is not None
                else "Observed sRGB: Not measured"
            )
        )

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        border_color = QColor(C.ACCENT_TX if self._de.value is not None else C.BORDER)

        # Border
        p.setPen(QPen(border_color, 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(1, 1, w - 2, h - 2, 4, 4)

        # Top half -- reference color
        ref_color = QColor(
            int(max(0, min(1, self._ref[0])) * 255),
            int(max(0, min(1, self._ref[1])) * 255),
            int(max(0, min(1, self._ref[2])) * 255),
        )
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(ref_color)
        p.drawRoundedRect(3, 3, w - 6, (h - 6) // 2, 2, 2)

        # Bottom half -- predicted color
        pred = self._pred or (0.5, 0.5, 0.5)
        pred_color = QColor(
            int(max(0, min(1, pred[0])) * 255),
            int(max(0, min(1, pred[1])) * 255),
            int(max(0, min(1, pred[2])) * 255),
        )
        p.setBrush(pred_color)
        top_of_bottom = 3 + (h - 6) // 2
        p.drawRoundedRect(3, top_of_bottom, w - 6, h - 3 - top_of_bottom, 2, 2)

        # Delta E text overlay
        p.setPen(QColor(255, 255, 255, 200))
        font = QFont("Segoe UI", 8, QFont.Weight.Bold)
        p.setFont(font)
        text_rect = QRectF(0, 0, float(w), float(h))
        text = "N/M" if self._de.value is None else f"{self._de.value:.1f}"
        p.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, text)

        p.end()


# ColorChecker Grid Widget


class ColorCheckerGrid(QWidget):
    """6x4 grid of ColorChecker patches."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._grid_layout = QGridLayout(self)
        self._grid_layout.setSpacing(4)
        self._grid_layout.setContentsMargins(0, 0, 0, 0)
        self._patches: list[ColorPatchWidget] = []

    def set_results(self, patches: list[dict]):
        """
        Populate the grid from verification results.

        Each dict should have: name, ref_srgb, displayed_srgb (or we approximate),
        delta_e.
        """
        # Clear existing
        for pw in self._patches:
            pw.deleteLater()
        self._patches.clear()

        # The ColorChecker Classic is 6 columns x 4 rows
        cols = 6
        for idx, patch_data in enumerate(patches):
            row = idx // cols
            col = idx % cols

            ref_srgb = patch_data.get("ref_srgb", (0.5, 0.5, 0.5))

            displayed_lab = patch_data.get("displayed_lab")
            pred_srgb = self._lab_to_approx_srgb(displayed_lab) if displayed_lab is not None else None

            de = _metric_or_not_measured(patch_data.get("delta_e"), "dE2000")
            name = patch_data.get("name", f"Patch {idx + 1}")

            pw = ColorPatchWidget(name, ref_srgb, pred_srgb, de, self)
            self._grid_layout.addWidget(pw, row, col)
            self._patches.append(pw)

    @staticmethod
    def _lab_to_approx_srgb(lab: tuple) -> tuple:
        """
        Quick Lab D50 to approximate sRGB for display purposes.
        Uses simplified conversion -- exact results are in the engine.
        """
        try:
            import numpy as np

            from calibrate_pro.core.color_math import D50_WHITE, D65_WHITE, bradford_adapt, lab_to_xyz, xyz_to_srgb

            lab_arr = np.array(lab, dtype=float)
            xyz_d50 = lab_to_xyz(lab_arr, D50_WHITE)
            xyz_d65 = bradford_adapt(xyz_d50, D50_WHITE, D65_WHITE)
            srgb = xyz_to_srgb(xyz_d65)
            srgb = np.clip(srgb, 0, 1)
            return (float(srgb[0]), float(srgb[1]), float(srgb[2]))
        except Exception:
            # Crude fallback
            L = lab[0] if len(lab) > 0 else 50
            v = max(0, min(1, L / 100.0))
            return (v, v, v)


# Grayscale Tracking Chart Widget


class GrayscaleTrackingChart(QWidget):
    """
    Interactive gamma/EOTF tracking chart rendered with QPainter.

    Displays:
      - Target gamma curve (e.g. 2.2 or BT.1886) as a smooth thin line
      - Measured luminance points as colored dots (green/yellow/red by dE)
      - Optional per-channel R/G/B tracking lines
      - Grid at 10% intervals with axis labels
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 250)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Data
        self._steps: list[float] = []
        self._target_gamma: float = 2.2
        self._measured: list[float] = []
        self._per_channel: dict[str, list[float]] | None = None
        self._delta_es: list[MetricValue] = []
        self._evidence_source: str | None = None

    def set_data(
        self,
        steps: list[float],
        target_gamma: float,
        measured_luminances: list[float],
        per_channel: dict[str, list[float]] | None = None,
        delta_es: list[MetricValue] | None = None,
        evidence_source: str | None = None,
    ):
        """
        Populate the chart.

        Args:
            steps: list of float (0.0-1.0) signal levels.
            target_gamma: float (2.2 for sRGB, 2.4 for BT.1886).
            measured_luminances: list of float (normalized 0-1).
            per_channel: optional dict with 'red', 'green', 'blue' lists
                         of normalized luminances.
            delta_es: optional evidence-labelled per-step Delta E values.
            evidence_source: receipt for observed luminance/channel values.
        """
        self._steps = list(steps)
        self._target_gamma = target_gamma
        self._evidence_source = evidence_source.strip() if evidence_source and evidence_source.strip() else None
        self._measured = list(measured_luminances) if self._evidence_source else []
        self._per_channel = per_channel if self._evidence_source else None
        self._delta_es = [metric for metric in (delta_es or []) if isinstance(metric, MetricValue)]
        self.setToolTip(f"Evidence source: {self._evidence_source or 'Not measured'}")

        self.update()

    # Painting

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()

        # Chart margins
        margin_l = 48
        margin_r = 16
        margin_t = 32
        margin_b = 36

        chart_x = margin_l
        chart_y = margin_t
        chart_w = w - margin_l - margin_r
        chart_h = h - margin_t - margin_b

        if chart_w < 20 or chart_h < 20:
            p.end()
            return

        # Background fill
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(C.SURFACE))
        p.drawRoundedRect(0, 0, w, h, 10, 10)

        # Title
        p.setPen(QColor(C.TEXT))
        title_font = QFont("Segoe UI", 11, QFont.Weight.DemiBold)
        p.setFont(title_font)
        p.drawText(
            QRectF(0, 4, float(w), float(margin_t - 4)),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            "Grayscale Tracking",
        )

        # Helper: map normalized (0-1) data coords to pixel coords
        def to_px(nx: float, ny: float) -> QPointF:
            px = chart_x + nx * chart_w
            py = chart_y + chart_h - ny * chart_h
            return QPointF(px, py)

        # --- Grid lines at 10% intervals ---
        grid_pen = QPen(QColor(C.BORDER), 1, Qt.PenStyle.SolidLine)
        p.setPen(grid_pen)
        axis_font = QFont("Segoe UI", 7)
        p.setFont(axis_font)

        for i in range(11):
            frac = i / 10.0
            # Vertical grid line
            vx = chart_x + frac * chart_w
            p.setPen(grid_pen)
            p.drawLine(QPointF(vx, chart_y), QPointF(vx, chart_y + chart_h))
            # X-axis label
            p.setPen(QColor(C.TEXT3))
            p.drawText(
                QRectF(vx - 16, chart_y + chart_h + 4, 32, 16),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                f"{int(frac * 100)}",
            )

            # Horizontal grid line
            hy = chart_y + chart_h - frac * chart_h
            p.setPen(grid_pen)
            p.drawLine(QPointF(chart_x, hy), QPointF(chart_x + chart_w, hy))
            # Y-axis label
            p.setPen(QColor(C.TEXT3))
            p.drawText(
                QRectF(0, hy - 8, margin_l - 6, 16),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"{frac:.1f}",
            )

        # Axis titles
        p.setPen(QColor(C.TEXT2))
        small_font = QFont("Segoe UI", 8)
        p.setFont(small_font)
        p.drawText(
            QRectF(chart_x, chart_y + chart_h + 18, chart_w, 16),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            "Input Signal Level (%)",
        )

        # Y-axis title (drawn rotated)
        p.save()
        p.translate(12, chart_y + chart_h / 2)
        p.rotate(-90)
        p.drawText(
            QRectF(-chart_h / 2, -8, chart_h, 16),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            "Output Luminance",
        )
        p.restore()

        # --- Target gamma curve ---
        gamma = self._target_gamma if self._target_gamma > 0 else 2.2
        curve_path = QPainterPath()
        num_seg = 100
        for seg in range(num_seg + 1):
            nx = seg / float(num_seg)
            ny = nx**gamma
            pt = to_px(nx, ny)
            if seg == 0:
                curve_path.moveTo(pt)
            else:
                curve_path.lineTo(pt)

        target_pen = QPen(QColor(C.TEXT3), 1.5, Qt.PenStyle.SolidLine)
        p.setPen(target_pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(curve_path)

        # --- Per-channel lines (R, G, B) ---
        if self._per_channel and self._steps:
            channel_colors = {
                "red": "#d08888",
                "green": "#92ad7e",
                "blue": "#95b3ba",
            }
            for ch_name, ch_color in channel_colors.items():
                ch_data = self._per_channel.get(ch_name, [])
                if len(ch_data) < 2:
                    continue
                ch_path = QPainterPath()
                for i, s in enumerate(self._steps):
                    if i >= len(ch_data):
                        break
                    pt = to_px(s, ch_data[i])
                    if i == 0:
                        ch_path.moveTo(pt)
                    else:
                        ch_path.lineTo(pt)
                ch_pen = QPen(QColor(ch_color), 1.2, Qt.PenStyle.SolidLine)
                p.setPen(ch_pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPath(ch_path)

        # --- Measured points as colored dots ---
        if self._steps and self._measured:
            for i, s in enumerate(self._steps):
                if i >= len(self._measured):
                    break
                meas_y = self._measured[i]
                metric = self._delta_es[i] if i < len(self._delta_es) else _not_measured("dE2000")
                dot_color = QColor(C.ACCENT_TX if metric.value is not None else C.TEXT3)

                pt = to_px(s, meas_y)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(dot_color)
                p.drawEllipse(pt, 4.0, 4.0)

        # --- Chart border ---
        border_pen = QPen(QColor(C.BORDER), 1)
        p.setPen(border_pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(QRectF(chart_x, chart_y, chart_w, chart_h))

        # --- Legend ---
        legend_font = QFont("Segoe UI", 7)
        p.setFont(legend_font)
        lx = chart_x + 8
        ly = chart_y + 8
        legend_items = [
            (C.TEXT3, f"Target (gamma {gamma:.1f})"),
            (C.ACCENT_TX, "Observed (receipt required)"),
        ]
        for color_str, label in legend_items:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(color_str))
            p.drawEllipse(QPointF(lx + 4, ly + 5), 3, 3)
            p.setPen(QColor(C.TEXT2))
            p.drawText(QRectF(lx + 12, ly, 120, 12), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)
            ly += 14

        p.end()


# Gamut Coverage Bars Widget


class GamutCoverageSection(QWidget):
    """Three labeled gamut coverage bars: sRGB, P3, BT.2020."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._srgb = _not_measured("%")
        self._p3 = _not_measured("%")
        self._bt2020 = _not_measured("%")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        heading = QLabel("Gamut Coverage")
        heading.setStyleSheet(f"font-size: 13px; font-weight: 500; color: {C.TEXT};")
        layout.addWidget(heading)

        self._bar = GamutBar(self._srgb, self._p3, self._bt2020)
        self._bar.setFixedHeight(40)
        layout.addWidget(self._bar)

    def set_values(self, srgb: MetricValue, p3: MetricValue, bt2020: MetricValue):
        self._srgb = _metric_or_not_measured(srgb, "%")
        self._p3 = _metric_or_not_measured(p3, "%")
        self._bt2020 = _metric_or_not_measured(bt2020, "%")
        # Replace bar widget with updated values
        old_bar = self._bar
        self._bar = GamutBar(self._srgb, self._p3, self._bt2020)
        self._bar.setFixedHeight(40)
        self.layout().replaceWidget(old_bar, self._bar)
        old_bar.deleteLater()


# Verify Page


class VerifyPage(QWidget):
    """Verification results, rendered from what the session performed.

    Nothing here decides what is available. The selector, both run buttons and
    the export button each stand for a declared action, and the resolver
    supplies whether each is offered and the sentence a refused one shows. The
    page used to write that sentence itself, and one of the things it wrote was
    that measured verification was available whenever a sensor was plugged in,
    which the session refuses in every state.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._displays: list[tuple[str, str]] = []
        self._binder: ActionBinder | None = None
        self._display_binding: SurfaceBinding | None = None
        self._select_display: Callable[[str], ActionOutcome[Any]] | None = None
        self._build()
        self.render_reference_grid()

    # -- construction -------------------------------------------------------

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)

        content = QWidget()
        self._layout = QVBoxLayout(content)
        self._layout.setContentsMargins(32, 28, 32, 28)
        self._layout.setSpacing(20)

        self._layout.addWidget(Heading("Verification"))
        self._layout.addWidget(self._build_display_card())

        body_row = QHBoxLayout()
        body_row.setSpacing(24)
        body_row.addLayout(self._build_grid_column(), stretch=3)
        body_row.addWidget(self._build_evidence_card(), stretch=0)
        self._layout.addLayout(body_row)

        self._layout.addWidget(Heading("Grayscale Tracking", level=2))
        self._layout.addWidget(self._build_grayscale_card())
        self._layout.addLayout(self._build_button_row())

        self._export_label = QLabel("")
        self._export_label.setWordWrap(True)
        self._export_label.setStyleSheet(f"font-size: 11px; color: {C.TEXT3};")
        self._layout.addWidget(self._export_label)

        self._layout.addStretch()
        scroll.setWidget(content)

    def _build_display_card(self) -> QWidget:
        card, layout = Card.with_layout(QHBoxLayout, margins=(16, 12, 16, 12))
        label = QLabel("Display")
        label.setStyleSheet(f"font-size: 12px; color: {C.TEXT2}; font-weight: 500;")
        layout.addWidget(label)

        self._display_combo = QComboBox()
        self._display_combo.setMinimumWidth(280)
        self._display_combo.setStyleSheet(f"""
            QComboBox {{
                background: {C.SURFACE2};
                border: 1px solid {C.BORDER};
                border-radius: 6px;
                padding: 6px 12px;
                color: {C.TEXT};
                font-size: 13px;
            }}
            QComboBox::drop-down {{
                border: none;
                width: 24px;
            }}
            QComboBox QAbstractItemView {{
                background: {C.SURFACE};
                border: 1px solid {C.BORDER};
                color: {C.TEXT};
                selection-background-color: {C.ACCENT};
            }}
        """)
        self._display_combo.currentIndexChanged.connect(self._on_display_changed)
        layout.addWidget(self._display_combo, stretch=1)
        return card

    def _build_grid_column(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(12)

        heading = QLabel("ColorChecker Classic")
        heading.setStyleSheet(f"font-size: 14px; font-weight: 500; color: {C.TEXT};")
        column.addWidget(heading)

        description = QLabel("Top: reference  |  Bottom: predicted  |  Center: evidence-labelled Delta E")
        description.setStyleSheet(f"font-size: 11px; color: {C.TEXT3};")
        column.addWidget(description)

        self._checker_grid = ColorCheckerGrid()
        column.addWidget(self._checker_grid)

        self._method_label = QLabel(NOT_RUN_NOTE)
        self._method_label.setWordWrap(True)
        self._method_label.setStyleSheet(f"font-size: 11px; color: {C.TEXT3}; font-style: italic;")
        column.addWidget(self._method_label)

        column.addStretch()
        return column

    def _build_evidence_card(self) -> QWidget:
        card, layout = Card.with_layout(QVBoxLayout, margins=(20, 16, 20, 16), spacing=16)
        card.setMinimumWidth(260)
        card.setMaximumWidth(360)
        card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

        heading = QLabel("Evidence")
        heading.setStyleSheet(f"font-size: 14px; font-weight: 500; color: {C.TEXT};")
        layout.addWidget(heading)

        self._stat_avg_de = Stat("Average Delta E", "Not measured")
        layout.addWidget(self._stat_avg_de)
        self._stat_max_de = Stat("Maximum Delta E", "Not measured")
        layout.addWidget(self._stat_max_de)
        self._stat_evidence = Stat("Evidence source", "Not measured")
        layout.addWidget(self._stat_evidence)

        layout.addWidget(self._separator())
        self._gamut_section = GamutCoverageSection()
        layout.addWidget(self._gamut_section)
        layout.addWidget(self._note(GAMUT_NOTE))

        layout.addWidget(self._separator())
        cie_heading = QLabel("CIE 1931 Chromaticity")
        cie_heading.setStyleSheet(f"font-size: 13px; font-weight: 500; color: {C.TEXT};")
        layout.addWidget(cie_heading)

        self._cie_diagram = CIEDiagramWidget()
        self._cie_diagram.setMinimumSize(240, 240)
        self._cie_diagram.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self._cie_diagram, stretch=1)
        layout.addWidget(self._note(CIE_NOTE))

        layout.addStretch()
        return card

    def _build_grayscale_card(self) -> QWidget:
        card, layout = Card.with_layout(QVBoxLayout, margins=(16, 12, 16, 12), spacing=8)
        self._gs_chart = GrayscaleTrackingChart()
        self._gs_chart.setMinimumHeight(280)
        layout.addWidget(self._gs_chart)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(24)
        self._gs_avg_label = QLabel("Avg grayscale dE: Not measured")
        self._gs_max_label = QLabel("Max grayscale dE: Not measured")
        for label in (self._gs_avg_label, self._gs_max_label):
            label.setStyleSheet(f"font-size: 12px; color: {C.TEXT2}; font-weight: 500;")
            stats_row.addWidget(label)
        stats_row.addStretch()
        layout.addLayout(stats_row)
        return card

    def _build_button_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addStretch()
        self._btn_verify = self._button("Run Verification", 200, primary=True)
        self._btn_measured = self._button("Run Measured Verification", 240)
        self._btn_export = self._button("Export Report", 160)
        for button in (self._btn_verify, self._btn_measured, self._btn_export):
            row.addWidget(button)
        row.addStretch()
        return row

    def _button(self, text: str, width: int, *, primary: bool = False) -> QPushButton:
        """Build one action button, disabled until the binder renders it.

        Every button here waits for the resolver. Starting enabled would offer
        an action for the moment between construction and the first refresh,
        which is long enough for a click.
        """
        button = QPushButton(text)
        button.setProperty("primary", primary)
        button.setFixedHeight(40)
        button.setFixedWidth(width)
        background = C.GREEN if primary else C.SURFACE
        border = C.GREEN_HI if primary else C.BORDER
        hover = f"background: {C.GREEN_HI};" if primary else f"border-color: {C.ACCENT}; background: {C.SURFACE2};"
        button.setStyleSheet(f"""
            QPushButton {{
                background: {background};
                border: 1px solid {border};
                border-radius: 8px;
                color: {C.TEXT};
                font-size: 14px;
                font-weight: {"600" if primary else "500"};
            }}
            QPushButton:hover {{ {hover} }}
            QPushButton:disabled {{
                background: {C.SURFACE2};
                border-color: {C.BORDER};
                color: {C.TEXT3};
            }}
        """)
        button.setEnabled(False)
        return button

    @staticmethod
    def _separator() -> QFrame:
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {C.BORDER};")
        return line

    @staticmethod
    def _note(text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet(f"font-size: 10px; color: {C.TEXT3};")
        return label

    # -- binding ------------------------------------------------------------

    def bind_actions(
        self,
        binder: ActionBinder,
        *,
        select_display: Callable[[str], ActionOutcome[Any]],
        run_sensorless: Operation,
        run_measured: Operation,
        save_report: Operation,
    ) -> None:
        """Hand every control here to the action it stands for.

        The measured button is bound to an action this build has no handler
        for. That is the point: what appears on it is the manifest's reason for
        holding measured verification closed, in place of the availability
        claim the page used to make after finding a sensor on the bus.

        The save button opens no dialog. Saving requires an output directory
        that has already been configured and checked, which is a separate
        action with its own record, so a save here writes only where the
        session has already accepted. Until one is configured the button
        carries the resolver's sentence saying so.
        """
        self._binder = binder
        self._select_display = select_display
        self._display_binding = binder.bind(
            "workflow.select_display",
            self._display_combo,
            self._selected_display,
            hides=False,
            connect=False,
        )
        binder.bind(
            "verification.sensorless",
            self._btn_verify,
            run_sensorless,
            on_success=self.render_verification,
            hides=False,
        )
        binder.bind("verification.measured", self._btn_measured, run_measured, hides=False)
        binder.bind(
            "report.save",
            self._btn_export,
            save_report,
            on_success=self._render_export,
            hides=False,
        )

    def _selected_display(self) -> ActionOutcome[Any] | None:
        """Adopt whichever display the selector is on, if it is on one."""
        select = self._select_display
        index = self._display_combo.currentIndex()
        if select is None or not (0 <= index < len(self._displays)):
            return None
        return select(self._displays[index][1])

    def _on_display_changed(self, index: int) -> None:
        """Ask the session to adopt the display the operator picked."""
        _ = index
        binder, binding = self._binder, self._display_binding
        if binder is not None and binding is not None:
            binder.invoke(binding)

    # -- rendering ----------------------------------------------------------

    def render_session(self, summary: DetectionSummary) -> None:
        """List the displays one detection pass observed, and only those.

        Repopulating moves the current index, so the signal is blocked while it
        happens. Without that, redrawing this page after a detection pass would
        re-select a display, and selecting one drops everything downstream of
        it, including a plan the operator had already generated.
        """
        combo = self._display_combo
        blocked = combo.blockSignals(True)
        try:
            combo.clear()
            self._displays = [
                (display.safe_label, display.platform_display_id) for display in summary.dashboard.displays
            ]
            if not self._displays:
                combo.addItem(NO_DISPLAY_ITEM)
                return
            for label, _display_id in self._displays:
                combo.addItem(label)
        finally:
            combo.blockSignals(blocked)

    def render_reference_grid(self) -> None:
        """Show the ColorChecker references with no delta against them.

        These are the targets the model compares to, so the grid is populated
        before anything has been run and carries no figure while it is. That is
        the state the page opens in and returns to when a verification reports
        that it covered nothing.
        """
        self._checker_grid.set_results(
            [
                {
                    "name": patch.name,
                    "ref_srgb": patch.srgb,
                    "delta_e": _not_measured(DELTA_E_UNIT),
                }
                for patch in COLORCHECKER_CLASSIC
            ]
        )
        self._show_unmeasured_grayscale()

    def render_verification(self, result: VerificationResult) -> None:
        """Show one session verification, including what it did not cover."""
        if result.patches:
            self._checker_grid.set_results(
                [
                    {
                        "name": patch.name,
                        "ref_srgb": patch.reference_srgb,
                        "displayed_lab": patch.displayed_lab,
                        "delta_e": patch.delta_e,
                    }
                    for patch in result.patches
                ]
            )
        else:
            self.render_reference_grid()

        average, maximum = result.average_delta_e, result.maximum_delta_e
        self._stat_avg_de.set_value(average.display_text(), _metric_colour(average))
        self._stat_max_de.set_value(maximum.display_text(), _metric_colour(maximum))
        self._stat_evidence.set_value(average.source or "Not measured", C.TEXT)
        self._method_label.setText(result.limitation or self._predicted_note(result))

    @staticmethod
    def _predicted_note(result: VerificationResult) -> str:
        """State what produced the figures, by name, next to the figures."""
        model = result.average_delta_e.source or "an unnamed model"
        return (
            f"Predicted by {model} from the plan this session generated. "
            f"No display was measured and no sensor was read."
        )

    def _render_export(self, bundle: ExportBundle) -> None:
        """Name what the export wrote, taken from the manifest sealing it."""
        self._export_label.setText(
            f"Wrote {len(bundle.assets)} file(s) to {bundle.directory}, sealed by {bundle.manifest_filename}."
        )

    def _show_unmeasured_grayscale(self) -> None:
        """Show only the requested target curve before evidence exists."""
        steps = [i / 10.0 for i in range(11)]
        self._gs_chart.set_data(steps, 2.2, [])
        self._gs_avg_label.setText("Avg grayscale dE: Not measured")
        self._gs_max_label.setText("Max grayscale dE: Not measured")
