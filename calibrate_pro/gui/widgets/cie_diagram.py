"""
CIE 1931 Chromaticity Diagram Widget

Interactive visualization of the CIE 1931 xy chromaticity space with:
- Spectral locus rendered as a filled horseshoe with approximate sRGB colors
- Gamut triangle overlays (sRGB, display, target)
- Planckian locus (black-body curve) from 2000K to 10000K
- D65 and measured white point markers
- Mouse interaction: hover tooltips, wheel zoom, click-drag pan
"""

from typing import Optional, List, Tuple, Dict
from dataclasses import dataclass, field
import math

from PyQt6.QtWidgets import QWidget, QSizePolicy, QToolTip
from PyQt6.QtCore import Qt, QRectF, QPointF, pyqtSignal, QSize
from PyQt6.QtGui import (
    QPainter, QPen, QBrush, QColor, QPainterPath,
    QPolygonF, QFont, QImage, QPixmap, QMouseEvent, QWheelEvent,
    QTransform
)

from calibrate_pro.gui.app import C


# =============================================================================
# Color Data
# =============================================================================

# CIE 1931 spectral locus: (wavelength_nm, x, y) at every 5nm from 380-780nm
SPECTRAL_LOCUS = [
    (380, 0.1741, 0.0050), (385, 0.1740, 0.0050), (390, 0.1738, 0.0049),
    (395, 0.1736, 0.0049), (400, 0.1733, 0.0048), (405, 0.1730, 0.0048),
    (410, 0.1726, 0.0048), (415, 0.1721, 0.0048), (420, 0.1714, 0.0051),
    (425, 0.1703, 0.0058), (430, 0.1689, 0.0069), (435, 0.1669, 0.0086),
    (440, 0.1644, 0.0109), (445, 0.1611, 0.0138), (450, 0.1566, 0.0177),
    (455, 0.1510, 0.0227), (460, 0.1440, 0.0297), (465, 0.1355, 0.0399),
    (470, 0.1241, 0.0578), (475, 0.1096, 0.0868), (480, 0.0913, 0.1327),
    (485, 0.0687, 0.2007), (490, 0.0454, 0.2950), (495, 0.0235, 0.4127),
    (500, 0.0082, 0.5384), (505, 0.0039, 0.6548), (510, 0.0139, 0.7502),
    (515, 0.0389, 0.8120), (520, 0.0743, 0.8338), (525, 0.1142, 0.8262),
    (530, 0.1547, 0.8059), (535, 0.1929, 0.7816), (540, 0.2296, 0.7543),
    (545, 0.2658, 0.7243), (550, 0.3016, 0.6923), (555, 0.3373, 0.6589),
    (560, 0.3731, 0.6245), (565, 0.4087, 0.5896), (570, 0.4441, 0.5547),
    (575, 0.4788, 0.5202), (580, 0.5125, 0.4866), (585, 0.5448, 0.4544),
    (590, 0.5752, 0.4242), (595, 0.6029, 0.3965), (600, 0.6270, 0.3725),
    (605, 0.6482, 0.3514), (610, 0.6658, 0.3340), (615, 0.6801, 0.3197),
    (620, 0.6915, 0.3083), (625, 0.7006, 0.2993), (630, 0.7079, 0.2920),
    (635, 0.7140, 0.2859), (640, 0.7190, 0.2809), (645, 0.7230, 0.2770),
    (650, 0.7260, 0.2740), (655, 0.7283, 0.2717), (660, 0.7300, 0.2700),
    (665, 0.7311, 0.2689), (670, 0.7320, 0.2680), (675, 0.7327, 0.2673),
    (680, 0.7334, 0.2666), (685, 0.7340, 0.2660), (690, 0.7344, 0.2656),
    (695, 0.7346, 0.2654), (700, 0.7347, 0.2653),
]

# Standard illuminant white points
WHITE_POINTS = {
    "D50": (0.3457, 0.3585),
    "D55": (0.3324, 0.3474),
    "D65": (0.3127, 0.3290),
    "D75": (0.2990, 0.3149),
    "E":   (0.3333, 0.3333),
    "A":   (0.4476, 0.4074),
}

# Standard color gamuts as (R, G, B) xy tuples
GAMUTS = {
    "sRGB": {
        "R": (0.640, 0.330),
        "G": (0.300, 0.600),
        "B": (0.150, 0.060),
        "W": (0.3127, 0.3290),
    },
    "DCI-P3": {
        "R": (0.680, 0.320),
        "G": (0.265, 0.690),
        "B": (0.150, 0.060),
        "W": (0.3140, 0.3510),
    },
    "Display P3": {
        "R": (0.680, 0.320),
        "G": (0.265, 0.690),
        "B": (0.150, 0.060),
        "W": (0.3127, 0.3290),
    },
    "BT.2020": {
        "R": (0.708, 0.292),
        "G": (0.170, 0.797),
        "B": (0.131, 0.046),
        "W": (0.3127, 0.3290),
    },
    "Adobe RGB": {
        "R": (0.640, 0.330),
        "G": (0.210, 0.710),
        "B": (0.150, 0.060),
        "W": (0.3127, 0.3290),
    },
}


@dataclass
class MeasuredPoint:
    """A measured chromaticity point to display on the diagram."""
    x: float
    y: float
    label: str = ""
    color: str = ""


# =============================================================================
# Planckian Locus Utilities
# =============================================================================

def _planckian_xy(T: float) -> Tuple[float, float]:
    """
    Compute CIE xy chromaticity of a blackbody radiator at temperature T (K).
    Uses the Kang et al. (2002) approximation.
    """
    T2 = T * T
    T3 = T2 * T
    if T <= 4000:
        x = (-0.2661239e9 / T3 - 0.2343589e6 / T2
             + 0.8776956e3 / T + 0.179910)
    elif T <= 7000:
        x = (-4.6070e9 / T3 + 2.9678e6 / T2
             + 0.09911e3 / T + 0.244063)
    else:
        x = (-2.0064e9 / T3 + 1.9018e6 / T2
             - 0.24748e3 / T + 0.237040)

    x2 = x * x
    x3 = x2 * x
    if T <= 2222:
        y = -1.1063814 * x3 - 1.34811020 * x2 + 2.18555832 * x - 0.20219683
    elif T <= 4000:
        y = -0.9549476 * x3 - 1.37418593 * x2 + 2.09137015 * x - 0.16748867
    else:
        y = 3.0817580 * x3 - 5.87338670 * x2 + 3.75112997 * x - 0.37001483

    return (x, y)


def _nearest_cct(cx: float, cy: float) -> Optional[float]:
    """
    Estimate the nearest correlated color temperature for an xy point
    using McCamy's approximation.  Returns None if far from the locus.
    """
    n = (cx - 0.3320) / (0.1858 - cy) if abs(0.1858 - cy) > 1e-6 else 0
    cct = 449.0 * n * n * n + 3525.0 * n * n + 6823.3 * n + 5520.33
    if cct < 1000 or cct > 100000:
        return None
    # Check distance from the locus to decide relevance
    lx, ly = _planckian_xy(max(2000, min(10000, cct)))
    dist = math.hypot(cx - lx, cy - ly)
    if dist > 0.05:
        return None
    return cct


# =============================================================================
# xy to approximate sRGB
# =============================================================================

def _xy_to_srgb(cx: float, cy: float) -> Tuple[int, int, int]:
    """
    Convert CIE xy chromaticity (at Y=1) to approximate sRGB (0-255).
    This is for rendering purposes only, not colorimetrically exact.
    """
    if cy < 1e-6:
        return (0, 0, 0)
    Y = 1.0
    X = (cx / cy) * Y
    Z = ((1.0 - cx - cy) / cy) * Y

    # XYZ to linear sRGB (D65)
    r =  3.2406 * X - 1.5372 * Y - 0.4986 * Z
    g = -0.9689 * X + 1.8758 * Y + 0.0415 * Z
    b =  0.0557 * X - 0.2040 * Y + 1.0570 * Z

    def gamma(v):
        v = max(0.0, v)
        if v <= 0.0031308:
            return 12.92 * v
        return 1.055 * (v ** (1.0 / 2.4)) - 0.055

    r, g, b = gamma(r), gamma(g), gamma(b)
    mx = max(r, g, b)
    if mx > 1.0:
        r, g, b = r / mx, g / mx, b / mx

    return (
        max(0, min(255, int(r * 255 + 0.5))),
        max(0, min(255, int(g * 255 + 0.5))),
        max(0, min(255, int(b * 255 + 0.5))),
    )


def _is_inside_locus(cx: float, cy: float) -> bool:
    """Quick test — is (cx, cy) inside the spectral locus horseshoe?"""
    poly = [(x, y) for _, x, y in SPECTRAL_LOCUS]
    n = len(poly)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > cy) != (yj > cy)) and (cx < (xj - xi) * (cy - yi) / (yj - yi + 1e-15) + xi):
            inside = not inside
        j = i
    return inside


# =============================================================================
# CIE 1931 Chromaticity Diagram Widget
# =============================================================================

class CIEDiagramWidget(QWidget):
    """
    Interactive CIE 1931 xy chromaticity diagram.

    Features:
        - Full-color horseshoe fill (approximate sRGB rendering)
        - sRGB reference triangle (dashed), display gamut (solid),
          target gamut (dotted)
        - Planckian locus 2000K-10000K
        - D65 and measured white-point markers
        - Hover tooltip with xy and nearest CCT
        - Mouse-wheel zoom and click-drag pan
    """

    point_clicked = pyqtSignal(float, float)

    # Default view window in xy space
    _DEFAULT_X0, _DEFAULT_X1 = -0.02, 0.82
    _DEFAULT_Y0, _DEFAULT_Y1 = -0.02, 0.88

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self.setMinimumSize(350, 350)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)

        # View bounds (mutable for zoom / pan)
        self._vx0 = self._DEFAULT_X0
        self._vx1 = self._DEFAULT_X1
        self._vy0 = self._DEFAULT_Y0
        self._vy1 = self._DEFAULT_Y1

        # Cached chromaticity background image
        self._bg_cache: Optional[QImage] = None
        self._bg_cache_size: Optional[QSize] = None
        self._bg_cache_view: Optional[Tuple] = None

        # Overlays
        self._display_gamut: Optional[Tuple] = None   # (r_xy, g_xy, b_xy)
        self._display_wp: Optional[Tuple] = None       # white point xy
        self._target_gamut: Optional[Tuple] = None     # (r_xy, g_xy, b_xy)
        self._measured_points: List[MeasuredPoint] = []

        # Pan state
        self._panning = False
        self._pan_start_pos: Optional[QPointF] = None
        self._pan_start_view: Optional[Tuple] = None

        # Margin around the plot area (px)
        self._margin = 38

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_display_gamut(
        self,
        r_xy: Tuple[float, float],
        g_xy: Tuple[float, float],
        b_xy: Tuple[float, float],
        w_xy: Optional[Tuple[float, float]] = None,
    ):
        """Set the measured display gamut triangle and optional white point."""
        self._display_gamut = (r_xy, g_xy, b_xy)
        self._display_wp = w_xy
        self.update()

    def set_target_gamut(
        self,
        r_xy: Tuple[float, float] = (0.640, 0.330),
        g_xy: Tuple[float, float] = (0.300, 0.600),
        b_xy: Tuple[float, float] = (0.150, 0.060),
    ):
        """Set the target gamut triangle overlay (defaults to sRGB)."""
        self._target_gamut = (r_xy, g_xy, b_xy)
        self.update()

    def set_measured_points(self, points: List[Tuple[float, float, str]]):
        """Set measured chromaticity points as list of (x, y, label)."""
        self._measured_points = [
            MeasuredPoint(x, y, label) for x, y, label in points
        ]
        self.update()

    def reset_view(self):
        """Reset zoom and pan to the default view."""
        self._vx0 = self._DEFAULT_X0
        self._vx1 = self._DEFAULT_X1
        self._vy0 = self._DEFAULT_Y0
        self._vy1 = self._DEFAULT_Y1
        self._invalidate_bg()
        self.update()

    # ------------------------------------------------------------------
    # Coordinate conversion
    # ------------------------------------------------------------------

    def _plot_rect(self) -> QRectF:
        """Return the pixel rectangle for the plot area."""
        m = self._margin
        return QRectF(m, m, self.width() - 2 * m, self.height() - 2 * m)

    def _xy_to_px(self, x: float, y: float) -> QPointF:
        """CIE xy -> widget pixel coords."""
        r = self._plot_rect()
        px = r.left() + (x - self._vx0) / (self._vx1 - self._vx0) * r.width()
        py = r.bottom() - (y - self._vy0) / (self._vy1 - self._vy0) * r.height()
        return QPointF(px, py)

    def _px_to_xy(self, px: float, py: float) -> Tuple[float, float]:
        """Widget pixel coords -> CIE xy."""
        r = self._plot_rect()
        x = self._vx0 + (px - r.left()) / r.width() * (self._vx1 - self._vx0)
        y = self._vy0 + (r.bottom() - py) / r.height() * (self._vy1 - self._vy0)
        return (x, y)

    # ------------------------------------------------------------------
    # Background rendering (chromaticity fill)
    # ------------------------------------------------------------------

    def _invalidate_bg(self):
        self._bg_cache = None

    def _render_background(self) -> QImage:
        """Render the chromaticity horseshoe as a QImage with approximate sRGB colors."""
        w, h = self.width(), self.height()
        img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(QColor(0, 0, 0, 0))

        r = self._plot_rect()
        step = max(2, int(min(r.width(), r.height()) / 180))

        for py_i in range(int(r.top()), int(r.bottom()), step):
            for px_i in range(int(r.left()), int(r.right()), step):
                cx, cy = self._px_to_xy(px_i + step / 2, py_i + step / 2)
                if cx < -0.01 or cy < -0.01 or cx > 0.85 or cy > 0.90:
                    continue
                if not _is_inside_locus(cx, cy):
                    continue
                sr, sg, sb = _xy_to_srgb(cx, cy)
                color = QColor(sr, sg, sb, 200)
                for dy in range(step):
                    for dx in range(step):
                        xi = px_i + dx
                        yi = py_i + dy
                        if 0 <= xi < w and 0 <= yi < h:
                            img.setPixelColor(xi, yi, color)

        return img

    def _ensure_bg(self):
        """Build the background cache if stale."""
        sz = self.size()
        view = (self._vx0, self._vx1, self._vy0, self._vy1)
        if (self._bg_cache is not None
                and self._bg_cache_size == sz
                and self._bg_cache_view == view):
            return
        self._bg_cache = self._render_background()
        self._bg_cache_size = QSize(sz)
        self._bg_cache_view = view

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Card-style background
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(C.SURFACE))
        p.drawRoundedRect(self.rect(), 12, 12)

        # Chromaticity fill
        self._ensure_bg()
        if self._bg_cache:
            p.drawImage(0, 0, self._bg_cache)

        # Grid
        self._paint_grid(p)

        # Spectral locus outline
        self._paint_spectral_locus(p)

        # Planckian locus
        self._paint_planckian_locus(p)

        # sRGB reference triangle (thin dashed)
        self._paint_srgb_triangle(p)

        # Target gamut (dotted green)
        if self._target_gamut:
            self._paint_gamut_triangle(
                p, self._target_gamut,
                color=QColor(C.GREEN),
                width=1.5,
                style=Qt.PenStyle.DotLine,
            )

        # Display gamut (solid accent)
        if self._display_gamut:
            self._paint_gamut_triangle(
                p, self._display_gamut,
                color=QColor(C.ACCENT),
                width=2.0,
                style=Qt.PenStyle.SolidLine,
                fill_alpha=25,
            )

        # White point markers
        self._paint_white_points(p)

        # Measured points
        self._paint_measured_points(p)

        # Axis labels
        self._paint_axis_labels(p)

        p.end()

    # -- Grid ---------------------------------------------------------------

    def _paint_grid(self, p: QPainter):
        pen = QPen(QColor(C.BORDER), 1, Qt.PenStyle.DotLine)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)

        step = 0.1
        x = 0.0
        while x <= 0.8 + 1e-6:
            if self._vx0 <= x <= self._vx1:
                p1 = self._xy_to_px(x, max(0, self._vy0))
                p2 = self._xy_to_px(x, min(0.9, self._vy1))
                p.drawLine(p1, p2)
            x += step

        y = 0.0
        while y <= 0.9 + 1e-6:
            if self._vy0 <= y <= self._vy1:
                p1 = self._xy_to_px(max(0, self._vx0), y)
                p2 = self._xy_to_px(min(0.8, self._vx1), y)
                p.drawLine(p1, p2)
            y += step

    # -- Spectral locus -----------------------------------------------------

    def _paint_spectral_locus(self, p: QPainter):
        path = QPainterPath()
        first = True
        for wl, x, y in SPECTRAL_LOCUS:
            pt = self._xy_to_px(x, y)
            if first:
                path.moveTo(pt)
                first = False
            else:
                path.lineTo(pt)
        # Close with the purple line
        path.lineTo(self._xy_to_px(SPECTRAL_LOCUS[0][1], SPECTRAL_LOCUS[0][2]))

        p.setPen(QPen(QColor(C.TEXT2), 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

        # Wavelength labels at key points
        p.setFont(QFont("Segoe UI", 7))
        p.setPen(QColor(C.TEXT3))
        for wl, x, y in SPECTRAL_LOCUS:
            if wl in (380, 460, 480, 500, 520, 540, 560, 580, 600, 620, 700):
                pt = self._xy_to_px(x, y)
                # Offset label slightly outward from the curve center
                cx, cy_c = 0.33, 0.33
                dx = x - cx
                dy = y - cy_c
                d = max(0.001, math.hypot(dx, dy))
                off = 12
                lx = pt.x() + dx / d * off
                ly = pt.y() - dy / d * off
                p.drawText(int(lx) - 10, int(ly) - 4, 28, 14,
                           Qt.AlignmentFlag.AlignCenter, f"{wl}")

    # -- Planckian locus ----------------------------------------------------

    def _paint_planckian_locus(self, p: QPainter):
        path = QPainterPath()
        first = True
        temp_labels = [2000, 3000, 4000, 5000, 6500, 8000, 10000]
        label_pts: List[Tuple[QPointF, int]] = []

        for T in range(2000, 10001, 50):
            x, y = _planckian_xy(T)
            if not (0 < x < 0.8 and 0 < y < 0.9):
                continue
            pt = self._xy_to_px(x, y)
            if first:
                path.moveTo(pt)
                first = False
            else:
                path.lineTo(pt)

            # Collect label positions
            for tl in temp_labels:
                if abs(T - tl) < 26:
                    label_pts.append((pt, tl))
                    temp_labels.remove(tl)
                    break

        pen = QPen(QColor(C.TEXT3), 1.2)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

        # Temperature labels
        p.setFont(QFont("Segoe UI", 6))
        p.setPen(QColor(C.TEXT3))
        for pt, tval in label_pts:
            label = f"{tval}K"
            p.drawText(int(pt.x()) + 4, int(pt.y()) - 3, label)

    # -- Gamut triangles ----------------------------------------------------

    def _paint_srgb_triangle(self, p: QPainter):
        """sRGB reference triangle — thin dashed line in TEXT3."""
        gamut = GAMUTS["sRGB"]
        pts = [
            self._xy_to_px(*gamut["R"]),
            self._xy_to_px(*gamut["G"]),
            self._xy_to_px(*gamut["B"]),
        ]
        pen = QPen(QColor(C.TEXT3), 1.0, Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPolygon(QPolygonF(pts))

        # Label vertices
        p.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
        p.setPen(QColor(C.TEXT3))
        offsets = [(6, 8), (-14, -6), (-6, 14)]
        for i, (label, off) in enumerate(zip(["R", "G", "B"], offsets)):
            p.drawText(int(pts[i].x()) + off[0],
                       int(pts[i].y()) + off[1], label)

    def _paint_gamut_triangle(
        self, p: QPainter,
        gamut: Tuple,
        color: QColor,
        width: float = 2.0,
        style=Qt.PenStyle.SolidLine,
        fill_alpha: int = 0,
    ):
        r_xy, g_xy, b_xy = gamut
        pts = [
            self._xy_to_px(*r_xy),
            self._xy_to_px(*g_xy),
            self._xy_to_px(*b_xy),
        ]
        poly = QPolygonF(pts)

        if fill_alpha > 0:
            fc = QColor(color)
            fc.setAlpha(fill_alpha)
            p.setBrush(QBrush(fc))
        else:
            p.setBrush(Qt.BrushStyle.NoBrush)

        pen = QPen(color, width, style)
        p.setPen(pen)
        p.drawPolygon(poly)

    # -- White point markers ------------------------------------------------

    def _paint_white_points(self, p: QPainter):
        # D65 reference — labeled dot
        d65 = WHITE_POINTS["D65"]
        pt = self._xy_to_px(*d65)
        p.setPen(QPen(QColor(C.TEXT), 1.5))
        p.setBrush(QColor(C.TEXT))
        p.drawEllipse(pt, 3, 3)
        p.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
        p.setPen(QColor(C.TEXT))
        p.drawText(int(pt.x()) + 6, int(pt.y()) + 4, "D65")

        # Measured white point — small cross / diamond
        if self._display_wp:
            wp = self._xy_to_px(*self._display_wp)
            sz = 5
            pen = QPen(QColor(C.ACCENT_TX), 2.0)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            # Diamond
            diamond = QPolygonF([
                QPointF(wp.x(), wp.y() - sz),
                QPointF(wp.x() + sz, wp.y()),
                QPointF(wp.x(), wp.y() + sz),
                QPointF(wp.x() - sz, wp.y()),
            ])
            p.drawPolygon(diamond)
            # Label
            p.setFont(QFont("Segoe UI", 7))
            p.setPen(QColor(C.ACCENT_TX))
            p.drawText(int(wp.x()) + 8, int(wp.y()) + 4, "WP")

    # -- Measured points ----------------------------------------------------

    def _paint_measured_points(self, p: QPainter):
        for mp in self._measured_points:
            pt = self._xy_to_px(mp.x, mp.y)
            c = QColor(mp.color) if mp.color else QColor(C.CYAN)
            p.setPen(QPen(c.darker(120), 1))
            p.setBrush(QBrush(c))
            p.drawEllipse(pt, 4, 4)
            if mp.label:
                p.setFont(QFont("Segoe UI", 7))
                p.setPen(c)
                p.drawText(int(pt.x()) + 6, int(pt.y()) + 4, mp.label)

    # -- Axis labels --------------------------------------------------------

    def _paint_axis_labels(self, p: QPainter):
        p.setFont(QFont("Segoe UI", 8))
        p.setPen(QColor(C.TEXT2))

        # X axis tick labels
        step = 0.1
        x = 0.0
        while x <= 0.8 + 1e-6:
            if self._vx0 <= x <= self._vx1:
                pt = self._xy_to_px(x, self._vy0)
                p.drawText(int(pt.x()) - 12, int(pt.y()) + 4, 24, 16,
                           Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                           f"{x:.1f}")
            x += step

        # Y axis tick labels
        y = 0.0
        while y <= 0.9 + 1e-6:
            if self._vy0 <= y <= self._vy1:
                pt = self._xy_to_px(self._vx0, y)
                p.drawText(int(pt.x()) - 34, int(pt.y()) - 8, 30, 16,
                           Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                           f"{y:.1f}")
            y += step

        # Axis titles
        p.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        p.setPen(QColor(C.TEXT2))
        r = self._plot_rect()
        p.drawText(int(r.center().x()) - 5, int(r.bottom()) + 26, "x")
        p.save()
        p.translate(10, int(r.center().y()) + 5)
        p.rotate(-90)
        p.drawText(0, 0, "y")
        p.restore()

    # ------------------------------------------------------------------
    # Mouse interaction
    # ------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._panning = True
            self._pan_start_pos = event.position()
            self._pan_start_view = (self._vx0, self._vx1, self._vy0, self._vy1)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif event.button() == Qt.MouseButton.MiddleButton:
            self.reset_view()

    def mouseMoveEvent(self, event: QMouseEvent):  # noqa: N802
        pos = event.position()
        if self._panning and self._pan_start_pos and self._pan_start_view:
            dx_px = pos.x() - self._pan_start_pos.x()
            dy_px = pos.y() - self._pan_start_pos.y()
            r = self._plot_rect()
            vw = self._pan_start_view[1] - self._pan_start_view[0]
            vh = self._pan_start_view[3] - self._pan_start_view[2]
            dx_xy = -dx_px / r.width() * vw
            dy_xy = dy_px / r.height() * vh
            self._vx0 = self._pan_start_view[0] + dx_xy
            self._vx1 = self._pan_start_view[1] + dx_xy
            self._vy0 = self._pan_start_view[2] + dy_xy
            self._vy1 = self._pan_start_view[3] + dy_xy
            self._invalidate_bg()
            self.update()
        else:
            # Hover tooltip
            cx, cy = self._px_to_xy(pos.x(), pos.y())
            if _is_inside_locus(cx, cy):
                cct = _nearest_cct(cx, cy)
                tip = f"x={cx:.4f}  y={cy:.4f}"
                if cct is not None:
                    tip += f"\n~{cct:.0f} K"
                QToolTip.showText(event.globalPosition().toPoint(), tip, self)
            else:
                QToolTip.hideText()

    def mouseReleaseEvent(self, event: QMouseEvent):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            if self._panning:
                # If barely moved, treat as a click
                if self._pan_start_pos:
                    d = (event.position() - self._pan_start_pos)
                    if d.manhattanLength() < 4:
                        cx, cy = self._px_to_xy(event.position().x(),
                                                event.position().y())
                        self.point_clicked.emit(cx, cy)
            self._panning = False
            self._pan_start_pos = None
            self._pan_start_view = None
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def wheelEvent(self, event: QWheelEvent):  # noqa: N802
        """Zoom in / out centred on the cursor position."""
        angle = event.angleDelta().y()
        if angle == 0:
            return
        factor = 0.85 if angle > 0 else 1.0 / 0.85

        # Cursor position in xy space as the zoom anchor
        pos = event.position()
        ax, ay = self._px_to_xy(pos.x(), pos.y())

        # Scale the view bounds around the anchor
        self._vx0 = ax + (self._vx0 - ax) * factor
        self._vx1 = ax + (self._vx1 - ax) * factor
        self._vy0 = ay + (self._vy0 - ay) * factor
        self._vy1 = ay + (self._vy1 - ay) * factor

        # Clamp zoom limits
        vw = self._vx1 - self._vx0
        vh = self._vy1 - self._vy0
        if vw < 0.02 or vh < 0.02:
            # Too zoomed in
            return
        if vw > 2.0 or vh > 2.0:
            self.reset_view()
            return

        self._invalidate_bg()
        self.update()

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        """Double-click resets the view."""
        self.reset_view()

    def resizeEvent(self, event):  # noqa: N802
        self._invalidate_bg()
        super().resizeEvent(event)

    def sizeHint(self):  # noqa: N802
        return QSize(400, 400)
