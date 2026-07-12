"""
Verify Page -- Calibration verification with ColorChecker grid and stats.

Shows a 6x4 ColorChecker grid, evidence-labelled Delta E statistics, and
gamut coverage. Runs verification in a QThread.
"""

import hashlib
import traceback
from html import escape
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from calibrate_pro.gui.app import C, Card, GamutBar, Heading, Stat, qt_display_snapshots
from calibrate_pro.gui.widgets.cie_diagram import CIEDiagramWidget
from calibrate_pro.verification.provenance import EvidenceKind, MetricValue


def _not_measured(unit: str) -> MetricValue:
    return MetricValue(None, unit, EvidenceKind.NOT_MEASURED)


def _metric_or_not_measured(value: object, unit: str) -> MetricValue:
    return value if isinstance(value, MetricValue) else _not_measured(unit)


def _estimated_metric(value: object, unit: str, source: str) -> MetricValue:
    if isinstance(value, MetricValue):
        return value
    if type(value) in {int, float}:
        return MetricValue(float(value), unit, EvidenceKind.ESTIMATED, source)
    return _not_measured(unit)


# Worker Thread


class VerifyWorker(QThread):
    """Runs SensorlessEngine.verify_calibration() off the main thread."""

    finished = Signal(bool, object)  # success, results dict or error string
    progress = Signal(int, int)  # current patch index, total patches

    def __init__(self, display_index: int = 0, display_name: str = "Generic Display", parent=None):
        super().__init__(parent)
        self.display_index = display_index
        self.display_name = display_name

    def run(self):
        try:
            from calibrate_pro.panels.database import PanelDatabase
            from calibrate_pro.sensorless.neuralux import SensorlessEngine

            self.progress.emit(0, 24)

            db = PanelDatabase()
            panel = db.find_panel(self.display_name) or db.get_fallback()

            self.progress.emit(2, 24)

            engine = SensorlessEngine()
            engine.current_panel = panel

            # Inject a progress callback if the engine supports it
            original_verify = engine.verify_calibration
            _self = self

            def verify_with_progress(panel_arg):
                result = original_verify(panel_arg)
                # Emit progress for each patch as they complete
                patches = result.get("patches", [])
                for i in range(len(patches)):
                    _self.progress.emit(i + 1, max(len(patches), 24))
                return result

            results = verify_with_progress(panel)
            receipt = hashlib.sha256(repr(panel).encode("utf-8")).hexdigest()
            source = f"panel-characterization:{panel.name}:{receipt}"
            for key in ("delta_e_avg", "delta_e_max", "cam16_delta_e_avg", "cam16_delta_e_max"):
                results[key] = _estimated_metric(results.get(key), "dE2000", source)
            for patch in results.get("patches", []):
                if isinstance(patch, dict):
                    patch["delta_e"] = _estimated_metric(patch.get("delta_e"), "dE2000", source)
                    patch["cam16_delta_e"] = _estimated_metric(patch.get("cam16_delta_e"), "CAM16-UCS dE", source)
            gamut = results.get("gamut_coverage")
            if isinstance(gamut, dict):
                for key in ("srgb_pct", "dci_p3_pct", "bt2020_pct"):
                    gamut[key] = _estimated_metric(gamut.get(key), "%", source)
            results.pop("grade", None)
            results["evidence_source"] = source
            results["accuracy_note"] = "Estimated from panel characterization; not instrument measured."

            # Attach panel primaries so the GUI can populate the CIE diagram
            try:
                prims = panel.native_primaries
                results["display_primaries"] = {
                    "R": (prims.red.x, prims.red.y),
                    "G": (prims.green.x, prims.green.y),
                    "B": (prims.blue.x, prims.blue.y),
                    "W": (prims.white.x, prims.white.y),
                }
            except Exception:
                pass

            self.progress.emit(24, 24)
            self.finished.emit(True, results)

        except Exception as exc:
            tb = traceback.format_exc()
            self.finished.emit(False, f"{exc}\n{tb}")


class NativeVerifyWorker(QThread):
    """Runs native ColorChecker verification using i1Display3 USB HID."""

    finished = Signal(bool, object)
    log_line = Signal(str)
    progress = Signal(str, float)

    def __init__(self, display_index: int = 0, parent=None):
        super().__init__(parent)
        self.display_index = display_index

    def run(self):
        try:
            import struct
            import time

            import hid
            import numpy as np

            OLED_MATRIX = np.array(
                [
                    [0.03836831, -0.02175997, 0.01696057],
                    [0.01449629, 0.01611903, 0.00057150],
                    [-0.00004481, 0.00035042, 0.08032401],
                ]
            )

            M_MASK = 0xFFFFFFFF

            # Open and unlock sensor
            self.log_line.emit("Opening i1Display3...")
            device = hid.device()
            device.open(0x0765, 0x5020)

            # Unlock (NEC OEM key)
            k0, k1 = 0xA9119479, 0x5B168761
            cmd = bytearray(65)
            cmd[0] = 0
            cmd[1] = 0x99
            device.write(cmd)
            time.sleep(0.2)
            c = bytes(device.read(64, timeout_ms=3000))
            sc = bytearray(8)
            for i in range(8):
                sc[i] = c[3] ^ c[35 + i]
            ci0 = (sc[3] << 24) + (sc[0] << 16) + (sc[4] << 8) + sc[6]
            ci1 = (sc[1] << 24) + (sc[7] << 16) + (sc[2] << 8) + sc[5]
            nk0, nk1 = (-k0) & M_MASK, (-k1) & M_MASK
            co = [(nk0 - ci1) & M_MASK, (nk1 - ci0) & M_MASK, (ci1 * nk0) & M_MASK, (ci0 * nk1) & M_MASK]
            s = sum(sc)
            for sh in [0, 8, 16, 24]:
                s += (nk0 >> sh) & 0xFF
                s += (nk1 >> sh) & 0xFF
            s0, s1 = s & 0xFF, (s >> 8) & 0xFF
            sr = bytearray(16)
            sr[0] = (((co[0] >> 16) & 0xFF) + s0) & 0xFF
            sr[1] = (((co[2] >> 8) & 0xFF) - s1) & 0xFF
            sr[2] = ((co[3] & 0xFF) + s1) & 0xFF
            sr[3] = (((co[1] >> 16) & 0xFF) + s0) & 0xFF
            sr[4] = (((co[2] >> 16) & 0xFF) - s1) & 0xFF
            sr[5] = (((co[3] >> 16) & 0xFF) - s0) & 0xFF
            sr[6] = (((co[1] >> 24) & 0xFF) - s0) & 0xFF
            sr[7] = ((co[0] & 0xFF) - s1) & 0xFF
            sr[8] = (((co[3] >> 8) & 0xFF) + s0) & 0xFF
            sr[9] = (((co[2] >> 24) & 0xFF) - s1) & 0xFF
            sr[10] = (((co[0] >> 8) & 0xFF) + s0) & 0xFF
            sr[11] = (((co[1] >> 8) & 0xFF) - s1) & 0xFF
            sr[12] = ((co[1] & 0xFF) + s1) & 0xFF
            sr[13] = (((co[3] >> 24) & 0xFF) + s1) & 0xFF
            sr[14] = ((co[2] & 0xFF) + s0) & 0xFF
            sr[15] = (((co[0] >> 24) & 0xFF) - s0) & 0xFF
            rb = bytearray(65)
            rb[0] = 0
            rb[1] = 0x9A
            for i in range(16):
                rb[25 + i] = c[2] ^ sr[i]
            device.write(rb)
            time.sleep(0.3)
            device.read(64, timeout_ms=3000)

            self.log_line.emit("Sensor unlocked. Place sensor against display.")
            self.log_line.emit("Measurement requires a fullscreen patch window.")
            self.log_line.emit("Using CLI: calibrate-pro native-calibrate --verify")

            # Measure white for normalization
            self.progress.emit("Measuring white reference...", 0.0)
            intclks = int(1.0 * 12000000)
            cmd2 = bytearray(65)
            cmd2[0] = 0x00
            cmd2[1] = 0x01
            struct.pack_into("<I", cmd2, 2, intclks)
            device.write(cmd2)
            resp = device.read(64, timeout_ms=4000)
            if resp and resp[0] == 0x00 and resp[1] == 0x01:
                rv = struct.unpack("<I", bytes(resp[2:6]))[0]
                gv = struct.unpack("<I", bytes(resp[6:10]))[0]
                bv = struct.unpack("<I", bytes(resp[10:14]))[0]
                t = intclks / 12000000.0
                freq = np.array([0.5 * (rv + 0.5) / t, 0.5 * (gv + 0.5) / t, 0.5 * (bv + 0.5) / t])
                white_xyz = OLED_MATRIX @ freq
                white_Y = white_xyz[1]
            else:
                device.close()
                self.finished.emit(False, "Failed to measure white reference")
                return

            self.log_line.emit(f"White Y = {white_Y:.1f} cd/m2")

            receipt = hashlib.sha256(bytes(resp) + white_xyz.tobytes()).hexdigest()
            source = f"instrument:i1display3:{receipt}"

            # A white reading is not a ColorChecker verification. Keep Delta E
            # explicitly unmeasured while retaining the observed luminance.
            results = {
                "patches": [],
                "delta_e_avg": _not_measured("dE2000"),
                "delta_e_max": _not_measured("dE2000"),
                "method": "native_measured",
                "white_luminance": MetricValue(white_Y, "cd/m²", EvidenceKind.MEASURED, source),
                "evidence_source": source,
            }

            # Note: full patch measurement needs fullscreen window
            # For now, report the white measurement and sensor status
            self.log_line.emit("Sensor connected and measuring.")
            self.log_line.emit(f"White luminance: {white_Y:.1f} cd/m2")
            self.log_line.emit(f"White xy: ({white_xyz[0] / sum(white_xyz):.4f}, {white_xyz[1] / sum(white_xyz):.4f})")

            device.close()
            self.finished.emit(True, results)

        except Exception as exc:
            tb = traceback.format_exc()
            self.finished.emit(False, f"Native verify error: {exc}\n{tb}")


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
    """Verification results page with ColorChecker grid, stats, and gamut bars."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: VerifyWorker | None = None
        self._last_results: dict | None = None
        self._displays = []
        self._build()
        QTimer.singleShot(300, self._detect_displays)

    # Build UI

    def _build(self):
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

        # --- Header ---
        self._layout.addWidget(Heading("Verification"))

        # --- Display selector ---
        disp_card, disp_lay = Card.with_layout(QHBoxLayout, margins=(16, 12, 16, 12))
        disp_label = QLabel("Display")
        disp_label.setStyleSheet(f"font-size: 12px; color: {C.TEXT2}; font-weight: 500;")
        disp_lay.addWidget(disp_label)

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
        disp_lay.addWidget(self._display_combo, stretch=1)
        self._layout.addWidget(disp_card)

        # --- Main content: grid on left, stats on right ---
        body_row = QHBoxLayout()
        body_row.setSpacing(24)

        # Left: ColorChecker grid
        left_col = QVBoxLayout()
        left_col.setSpacing(12)

        grid_heading = QLabel("ColorChecker Classic")
        grid_heading.setStyleSheet(f"font-size: 14px; font-weight: 500; color: {C.TEXT};")
        left_col.addWidget(grid_heading)

        grid_desc = QLabel("Top: reference  |  Bottom: observed/estimated  |  Center: evidence-labelled Delta E")
        grid_desc.setStyleSheet(f"font-size: 11px; color: {C.TEXT3};")
        left_col.addWidget(grid_desc)

        self._checker_grid = ColorCheckerGrid()
        left_col.addWidget(self._checker_grid)

        # Prediction label
        self._method_label = QLabel("Evidence: Not measured")
        self._method_label.setStyleSheet(f"font-size: 11px; color: {C.TEXT3}; font-style: italic;")
        left_col.addWidget(self._method_label)

        left_col.addStretch()
        body_row.addLayout(left_col, stretch=3)

        # Right: Stats panel
        right_card, right_lay = Card.with_layout(QVBoxLayout, margins=(20, 16, 20, 16), spacing=16)
        right_card.setMinimumWidth(260)
        right_card.setMaximumWidth(360)
        right_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

        stats_heading = QLabel("Evidence")
        stats_heading.setStyleSheet(f"font-size: 14px; font-weight: 500; color: {C.TEXT};")
        right_lay.addWidget(stats_heading)

        self._stat_avg_de = Stat("Average Delta E", "Not measured")
        right_lay.addWidget(self._stat_avg_de)

        self._stat_max_de = Stat("Maximum Delta E", "Not measured")
        right_lay.addWidget(self._stat_max_de)

        self._stat_evidence = Stat("Evidence source", "Not measured")
        right_lay.addWidget(self._stat_evidence)

        # Separator
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {C.BORDER};")
        right_lay.addWidget(sep)

        # Gamut coverage
        self._gamut_section = GamutCoverageSection()
        right_lay.addWidget(self._gamut_section)

        # CIE 1931 Chromaticity Diagram
        sep2 = QFrame()
        sep2.setFixedHeight(1)
        sep2.setStyleSheet(f"background: {C.BORDER};")
        right_lay.addWidget(sep2)

        cie_heading = QLabel("CIE 1931 Chromaticity")
        cie_heading.setStyleSheet(f"font-size: 13px; font-weight: 500; color: {C.TEXT};")
        right_lay.addWidget(cie_heading)

        self._cie_diagram = CIEDiagramWidget()
        self._cie_diagram.setMinimumSize(240, 240)
        self._cie_diagram.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        right_lay.addWidget(self._cie_diagram, stretch=1)

        right_lay.addStretch()
        body_row.addWidget(right_card, stretch=0)

        self._layout.addLayout(body_row)

        # --- Grayscale Tracking Chart ---
        self._layout.addWidget(Heading("Grayscale Tracking", level=2))

        gs_card, gs_lay = Card.with_layout(QVBoxLayout, margins=(16, 12, 16, 12), spacing=8)
        self._gs_chart = GrayscaleTrackingChart()
        self._gs_chart.setMinimumHeight(280)
        gs_lay.addWidget(self._gs_chart)

        # Stats row below the chart
        gs_stats_row = QHBoxLayout()
        gs_stats_row.setSpacing(24)

        self._gs_avg_label = QLabel("Avg grayscale dE: --")
        self._gs_avg_label.setStyleSheet(f"font-size: 12px; color: {C.TEXT2}; font-weight: 500;")
        gs_stats_row.addWidget(self._gs_avg_label)

        self._gs_max_label = QLabel("Max grayscale dE: --")
        self._gs_max_label.setStyleSheet(f"font-size: 12px; color: {C.TEXT2}; font-weight: 500;")
        gs_stats_row.addWidget(self._gs_max_label)

        gs_stats_row.addStretch()
        gs_lay.addLayout(gs_stats_row)

        self._layout.addWidget(gs_card)

        # --- Buttons row ---
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._btn_verify = QPushButton("Run Verification")
        self._btn_verify.setProperty("primary", True)
        self._btn_verify.setFixedHeight(40)
        self._btn_verify.setFixedWidth(200)
        self._btn_verify.setStyleSheet(f"""
            QPushButton {{
                background: {C.GREEN};
                border: 1px solid {C.GREEN_HI};
                border-radius: 8px;
                color: {C.TEXT};
                font-size: 14px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background: {C.GREEN_HI};
            }}
            QPushButton:disabled {{
                background: {C.SURFACE2};
                border-color: {C.BORDER};
                color: {C.TEXT3};
            }}
        """)
        self._btn_verify.clicked.connect(self._run_verification)
        btn_row.addWidget(self._btn_verify)

        self._btn_export = QPushButton("Export Report")
        self._btn_export.setFixedHeight(40)
        self._btn_export.setFixedWidth(160)
        self._btn_export.setStyleSheet(f"""
            QPushButton {{
                background: {C.SURFACE};
                border: 1px solid {C.BORDER};
                border-radius: 8px;
                color: {C.TEXT};
                font-size: 14px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                border-color: {C.ACCENT};
                background: {C.SURFACE2};
            }}
            QPushButton:disabled {{
                background: {C.SURFACE2};
                border-color: {C.BORDER};
                color: {C.TEXT3};
            }}
        """)
        self._btn_export.setEnabled(False)
        self._btn_export.clicked.connect(self._export_report)
        btn_row.addWidget(self._btn_export)

        btn_row.addStretch()
        self._layout.addLayout(btn_row)

        # --- Progress section (hidden until verifying) ---
        self._progress_card = Card()
        prog_lay = QVBoxLayout(self._progress_card)
        prog_lay.setContentsMargins(20, 16, 20, 16)
        prog_lay.setSpacing(10)

        self._step_label = QLabel("Ready")
        self._step_label.setStyleSheet(f"font-size: 13px; font-weight: 500; color: {C.ACCENT_TX};")
        prog_lay.addWidget(self._step_label)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 24)
        self._progress_bar.setValue(0)
        self._progress_bar.setFixedHeight(8)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background: {C.SURFACE2};
                border: none;
                border-radius: 4px;
            }}
            QProgressBar::chunk {{
                background: {C.GREEN};
                border-radius: 4px;
            }}
        """)
        prog_lay.addWidget(self._progress_bar)

        self._progress_card.setVisible(False)
        self._layout.addWidget(self._progress_card)

        # --- Error label ---
        self._error_label = QLabel("")
        self._error_label.setWordWrap(True)
        self._error_label.setStyleSheet(f"color: {C.RED}; font-size: 12px;")
        self._error_label.setVisible(False)
        self._layout.addWidget(self._error_label)

        self._layout.addStretch()
        scroll.setWidget(content)

        # Seed the grid with default ColorChecker patches (no delta E yet)
        self._seed_default_grid()

    # Seed default grid

    def _seed_default_grid(self):
        """Show the ColorChecker with reference colors and dashes before verification."""
        try:
            from calibrate_pro.sensorless.neuralux import COLORCHECKER_CLASSIC

            patches = []
            for cp in COLORCHECKER_CLASSIC:
                patches.append(
                    {
                        "name": cp.name,
                        "ref_srgb": cp.srgb,
                        "ref_lab": cp.lab_d50,
                        "delta_e": _not_measured("dE2000"),
                    }
                )
            self._checker_grid.set_results(patches)
        except Exception:
            pass

        self._show_unmeasured_grayscale()

    def _show_unmeasured_grayscale(self):
        """Show only the requested target curve before evidence exists."""
        steps = [i / 10.0 for i in range(11)]
        self._gs_chart.set_data(steps, 2.2, [])
        self._gs_avg_label.setText("Avg grayscale dE: Not measured")
        self._gs_max_label.setText("Max grayscale dE: Not measured")

    # Display Detection

    def _detect_displays(self):
        self._display_combo.clear()
        try:
            self._displays = qt_display_snapshots()
            for i, d in enumerate(self._displays):
                name = d.name
                res = f"{d.width}x{d.height}"
                self._display_combo.addItem(f"{i + 1}. {name}  ({res})")
        except Exception as exc:
            self._display_combo.addItem("Display detection unavailable")
            self._show_error(f"Could not detect displays: {exc}")

        # Detect sensor
        self._sensor_detected = False
        try:
            from calibrate_pro.hardware.i1d3_native import I1D3Driver

            devices = I1D3Driver.find_devices()
            self._sensor_detected = bool(devices)
        except Exception:
            pass

        if self._sensor_detected:
            self._method_label.setText("Sensor detected - measured verification available")
            self._method_label.setStyleSheet(f"font-size: 11px; color: {C.GREEN_HI}; font-style: italic;")

    # Verification

    def _run_verification(self):
        if self._worker is not None and self._worker.isRunning():
            return

        self._hide_error()
        self._btn_verify.setText("Verifying...")
        self._btn_verify.setEnabled(False)
        self._btn_export.setEnabled(False)
        self._progress_card.setVisible(True)
        self._progress_bar.setValue(0)
        self._step_label.setText("Starting verification...")
        self._step_label.setStyleSheet(f"font-size: 13px; font-weight: 500; color: {C.ACCENT_TX};")

        display_index = max(0, self._display_combo.currentIndex())
        display_name = (
            self._displays[display_index].name
            if hasattr(self, "_displays") and display_index < len(self._displays)
            else "Generic Display"
        )
        self._worker = VerifyWorker(display_index, display_name)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_progress(self, current: int, total: int):
        self._progress_bar.setMaximum(total)
        self._progress_bar.setValue(current)
        self._step_label.setText(f"Verifying patch {current}/{total}...")

    def _on_finished(self, success: bool, data):
        self._btn_verify.setEnabled(True)
        self._btn_verify.setText("Run Verification")

        if not success:
            self._show_error(str(data))
            self._progress_card.setVisible(False)
            self._worker = None
            return

        # Show completed progress
        self._step_label.setText("Verification complete")
        self._step_label.setStyleSheet(f"font-size: 13px; font-weight: 500; color: {C.GREEN_HI};")
        self._progress_bar.setValue(self._progress_bar.maximum())

        results = data
        self._last_results = results
        self._btn_export.setEnabled(True)
        try:
            self._populate_results(results)
        except Exception as exc:
            self._show_error(f"Error displaying results: {exc}")

        self._worker = None

    def _populate_results(self, results: dict):
        """Fill the UI with verification data."""
        patches = results.get("patches", [])

        # Populate the ColorChecker grid
        self._checker_grid.set_results(patches)

        avg_de = _metric_or_not_measured(results.get("delta_e_avg"), "dE2000")
        max_de = _metric_or_not_measured(results.get("delta_e_max"), "dE2000")
        avg_color = C.ACCENT_TX if avg_de.value is not None else C.TEXT3
        max_color = C.ACCENT_TX if max_de.value is not None else C.TEXT3
        self._stat_avg_de.set_value(avg_de.display_text(), avg_color)
        self._stat_max_de.set_value(max_de.display_text(), max_color)
        source = avg_de.source or max_de.source or results.get("evidence_source")
        self._stat_evidence.set_value(str(source or "Not measured"), C.TEXT3)

        method = results.get("method", "")
        if avg_de.evidence is EvidenceKind.MEASURED or method == "native_measured":
            sensor_name = results.get("sensor_name", "i1Display3")
            method_text = f"Measured ({sensor_name})"
        elif avg_de.evidence is EvidenceKind.ESTIMATED:
            method_text = "Estimated (panel characterization)"
        else:
            method_text = "Not measured"
        self._method_label.setText(f"{method_text} \u2014 {avg_de.display_text()}; source: {source or 'Not measured'}")
        self._method_label.setStyleSheet(f"font-size: 11px; color: {avg_color}; font-style: italic;")

        # Gamut coverage
        gamut = results.get("gamut_coverage", {})
        srgb_pct = _metric_or_not_measured(gamut.get("srgb_pct") if isinstance(gamut, dict) else None, "%")
        p3_pct = _metric_or_not_measured(gamut.get("dci_p3_pct") if isinstance(gamut, dict) else None, "%")
        bt2020_pct = _metric_or_not_measured(gamut.get("bt2020_pct") if isinstance(gamut, dict) else None, "%")
        self._gamut_section.set_values(srgb_pct, p3_pct, bt2020_pct)

        # CIE 1931 chromaticity diagram -- populate with display primaries
        dp = results.get("display_primaries")
        if dp:
            self._cie_diagram.set_display_gamut(dp["R"], dp["G"], dp["B"], dp.get("W"))

        gs_data = results.get("grayscale")
        if isinstance(gs_data, dict) and source:
            gs_des = [
                metric
                for raw in gs_data.get("delta_es", [])
                if (metric := _metric_or_not_measured(raw, "dE2000")).value is not None
            ]
            self._gs_chart.set_data(
                gs_data.get("steps", []),
                gs_data.get("target_gamma", 2.2),
                gs_data.get("measured", []),
                per_channel=gs_data.get("per_channel"),
                delta_es=gs_des,
                evidence_source=str(source),
            )
        else:
            self._show_unmeasured_grayscale()
            gs_des = []

        if gs_des:
            values = [metric.value for metric in gs_des if metric.value is not None]
            evidence = gs_des[0].evidence
            gs_avg = MetricValue(sum(values) / len(values), "dE2000", evidence, str(source))
            gs_max = MetricValue(max(values), "dE2000", evidence, str(source))
            self._gs_avg_label.setText(f"Avg grayscale dE: {gs_avg.display_text()}")
            self._gs_max_label.setText(f"Max grayscale dE: {gs_max.display_text()}")

    # Export Report

    def _build_html_report(self, results: dict) -> str:
        """Build a self-contained HTML report string from verification results."""
        avg_de = _metric_or_not_measured(results.get("delta_e_avg"), "dE2000")
        max_de = _metric_or_not_measured(results.get("delta_e_max"), "dE2000")
        method = str(results.get("method") or "Not measured")
        patches = results.get("patches", [])
        evidence_source = avg_de.source or max_de.source or results.get("evidence_source")

        lines = [
            "<!DOCTYPE html><html><head>",
            "<meta charset='utf-8'>",
            "<title>Calibrate Pro - Verification Report</title>",
            "<style>",
            "  body { font-family: 'Segoe UI', sans-serif; margin: 40px; "
            "         background: #fdf9f5; color: #443933; }",
            "  h1 { color: #b07878; }",
            "  table { border-collapse: collapse; margin-top: 16px; }",
            "  th, td { border: 1px solid #ede4da; padding: 6px 14px;             text-align: left; }",
            "  th { background: #faf5f0; }",
            "  @media print { body { background: white; } }",
            "</style></head><body>",
            "<h1>Calibrate Pro - Verification Report</h1>",
            f"<p><strong>Method:</strong> {escape(method)}</p>",
            f"<p><strong>Average Delta E:</strong> {escape(avg_de.display_text())}</p>",
            f"<p><strong>Maximum Delta E:</strong> {escape(max_de.display_text())}</p>",
            f"<p><strong>Evidence source:</strong> {escape(str(evidence_source or 'Not measured'))}</p>",
            "<p>No quality grade is assigned without an approved rubric.</p>",
        ]
        if patches:
            lines.append("<h2>Patch Results</h2>")
            lines.append("<table><tr><th>Patch</th><th>Delta E</th><th>Evidence source</th></tr>")
            for p in patches:
                if not isinstance(p, dict):
                    continue
                de = _metric_or_not_measured(p.get("delta_e"), "dE2000")
                name = escape(str(p.get("name") or "Unnamed patch"))
                source = escape(str(de.source or "Not measured"))
                lines.append(f"<tr><td>{name}</td><td>{escape(de.display_text())}</td><td>{source}</td></tr>")
            lines.append("</table>")
        lines.append("</body></html>")
        return "\n".join(lines)

    def _export_report(self):
        """Export verification results as HTML, PDF, or text report."""
        if not self._last_results:
            return

        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export Verification Report",
            "verification_report.html",
            "HTML Report (*.html);;PDF Report (*.pdf);;Text Report (*.txt)",
        )
        if not path:
            return

        results = self._last_results

        try:
            is_pdf = path.lower().endswith(".pdf")

            if is_pdf:
                # Build HTML content, then convert to PDF
                html_content = self._build_html_report(results)

                from calibrate_pro.verification.pdf_export import export_report_pdf

                success = export_report_pdf(html_content, path)

                if success:
                    # Check if the PDF was actually created (WebEngine path)
                    # or if we fell back to browser
                    if Path(path).exists():
                        QMessageBox.information(self, "Report Exported", f"PDF report saved to:\n{path}")
                    else:
                        html_fallback = Path(path).with_suffix(".html")
                        QMessageBox.information(
                            self,
                            "Report Exported",
                            f"PDF export requires a browser.\n\n"
                            f"The HTML report has been opened in your browser.\n"
                            f"Use your browser's Print > Save as PDF to create "
                            f"the PDF.\n\n"
                            f"HTML saved at:\n{html_fallback}",
                        )
                else:
                    QMessageBox.warning(self, "Export Error", "Could not export PDF. Please try HTML format instead.")
                return

            # Non-PDF export uses the same evidence-aware rendering as the UI.
            if path.endswith(".html"):
                content = self._build_html_report(results)
            else:
                avg_de = _metric_or_not_measured(results.get("delta_e_avg"), "dE2000")
                max_de = _metric_or_not_measured(results.get("delta_e_max"), "dE2000")
                method = str(results.get("method") or "Not measured")
                patches = results.get("patches", [])
                evidence_source = avg_de.source or max_de.source or results.get("evidence_source")

                lines = [
                    "Calibrate Pro - Verification Report",
                    "=" * 40,
                    f"Method:          {method}",
                    f"Average Delta E: {avg_de.display_text()}",
                    f"Maximum Delta E: {max_de.display_text()}",
                    f"Evidence source: {evidence_source or 'Not measured'}",
                    "Quality grade:   Not assigned (no approved rubric)",
                    "",
                ]
                if patches:
                    lines.append("Patch Results:")
                    lines.append("-" * 30)
                    for p in patches:
                        if not isinstance(p, dict):
                            continue
                        name = str(p.get("name") or "Unnamed patch")
                        de = _metric_or_not_measured(p.get("delta_e"), "dE2000")
                        lines.append(f"  {name:20s}  {de.display_text()}  source: {de.source or 'Not measured'}")
                content = "\n".join(lines)

            Path(path).write_text(content, encoding="utf-8")

        except Exception as exc:
            QMessageBox.warning(self, "Export Error", str(exc))
            return

        if not path.lower().endswith(".pdf"):
            QMessageBox.information(self, "Report Exported", f"Verification report saved to:\n{path}")

    # Helpers

    def _show_error(self, msg: str):
        self._error_label.setText(msg)
        self._error_label.setVisible(True)

    def _hide_error(self):
        self._error_label.setText("")
        self._error_label.setVisible(False)
