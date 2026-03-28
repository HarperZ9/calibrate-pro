"""
Icon Factory - Calibrate Pro

Programmatic icon generation for toolbar, navigation, system tray,
and application branding. No external icon files required.
"""

import math

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QBrush, QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap

from calibrate_pro.gui.theme import COLORS


class IconFactory:
    """Creates icons programmatically for the application."""

    @staticmethod
    def create_icon(draw_func, size: int = 24, color: str = None) -> QIcon:
        """Create an icon from a drawing function."""
        if color is None:
            color = COLORS['text_primary']

        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(color), 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)

        draw_func(painter, size, color)

        painter.end()
        return QIcon(pixmap)

    @staticmethod
    def dashboard(painter: QPainter, size: int, color: str):
        """Dashboard/home icon - grid of squares."""
        m = size * 0.2  # margin
        s = (size - 2*m - 2) / 2  # square size
        painter.setBrush(QBrush(QColor(color)))
        painter.drawRoundedRect(int(m), int(m), int(s), int(s), 2, 2)
        painter.drawRoundedRect(int(m + s + 2), int(m), int(s), int(s), 2, 2)
        painter.drawRoundedRect(int(m), int(m + s + 2), int(s), int(s), 2, 2)
        painter.drawRoundedRect(int(m + s + 2), int(m + s + 2), int(s), int(s), 2, 2)

    @staticmethod
    def calibrate(painter: QPainter, size: int, color: str):
        """Calibration icon - target/crosshair."""
        c = size / 2
        r = size * 0.35
        painter.drawEllipse(QPoint(int(c), int(c)), int(r), int(r))
        painter.drawEllipse(QPoint(int(c), int(c)), int(r * 0.5), int(r * 0.5))
        # Crosshair lines
        painter.drawLine(int(c), int(size * 0.1), int(c), int(size * 0.3))
        painter.drawLine(int(c), int(size * 0.7), int(c), int(size * 0.9))
        painter.drawLine(int(size * 0.1), int(c), int(size * 0.3), int(c))
        painter.drawLine(int(size * 0.7), int(c), int(size * 0.9), int(c))

    @staticmethod
    def verify(painter: QPainter, size: int, color: str):
        """Verification icon - checkmark in circle."""
        c = size / 2
        r = size * 0.38
        painter.drawEllipse(QPoint(int(c), int(c)), int(r), int(r))
        # Checkmark
        path = QPainterPath()
        path.moveTo(size * 0.3, size * 0.5)
        path.lineTo(size * 0.45, size * 0.65)
        path.lineTo(size * 0.7, size * 0.35)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        pen = painter.pen()
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawPath(path)

    @staticmethod
    def profiles(painter: QPainter, size: int, color: str):
        """Profiles icon - stacked documents."""
        m = size * 0.15
        w = size * 0.55
        h = size * 0.65
        # Back document
        painter.drawRoundedRect(int(m + 4), int(m), int(w), int(h), 2, 2)
        # Front document
        painter.setBrush(QBrush(QColor(COLORS['surface'])))
        painter.drawRoundedRect(int(m), int(m + 4), int(w), int(h), 2, 2)
        # Lines on front doc
        painter.drawLine(int(m + 6), int(m + 14), int(m + w - 6), int(m + 14))
        painter.drawLine(int(m + 6), int(m + 22), int(m + w - 6), int(m + 22))

    @staticmethod
    def settings(painter: QPainter, size: int, color: str):
        """Settings icon - gear."""
        c = size / 2
        outer_r = size * 0.4
        inner_r = size * 0.2
        teeth = 8

        path = QPainterPath()
        for i in range(teeth * 2):
            angle = (i * math.pi / teeth) - math.pi / 2
            r = outer_r if i % 2 == 0 else outer_r * 0.75
            x = c + r * math.cos(angle)
            y = c + r * math.sin(angle)
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        path.closeSubpath()

        painter.setBrush(QBrush(QColor(color)))
        painter.drawPath(path)
        # Inner circle (hole)
        painter.setBrush(QBrush(QColor(COLORS['background'])))
        painter.drawEllipse(QPoint(int(c), int(c)), int(inner_r), int(inner_r))

    @staticmethod
    def vcgt_tools(painter: QPainter, size: int, color: str):
        """VCGT Tools icon - curve/graph symbol."""
        margin = size * 0.15
        graph_size = size - 2 * margin

        # Draw axis lines
        painter.setPen(QPen(QColor(color), 1.5))
        # Y axis
        painter.drawLine(int(margin), int(margin), int(margin), int(size - margin))
        # X axis
        painter.drawLine(int(margin), int(size - margin), int(size - margin), int(size - margin))

        # Draw a gamma curve
        path = QPainterPath()
        steps = 20
        for i in range(steps + 1):
            t = i / steps
            x = margin + t * graph_size
            # Simulate gamma curve (power function)
            y = size - margin - (t ** 2.2) * graph_size
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)

        painter.setPen(QPen(QColor(COLORS['accent']), 2))
        painter.drawPath(path)

    @staticmethod
    def app_icon(size: int = 64) -> QIcon:
        """Main application icon - colorful calibration symbol."""
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        c = size / 2
        r = size * 0.42

        # Outer ring gradient
        gradient = QLinearGradient(0, 0, size, size)
        gradient.setColorAt(0, QColor(COLORS['accent']))
        gradient.setColorAt(1, QColor(COLORS['success']))

        painter.setPen(QPen(QBrush(gradient), size * 0.08))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPoint(int(c), int(c)), int(r), int(r))

        # Inner colored segments (RGB)
        inner_r = size * 0.25
        colors = [COLORS['error'], COLORS['success'], COLORS['accent']]
        for i, color in enumerate(colors):
            angle = i * 2 * math.pi / 3 - math.pi / 2
            x = c + inner_r * 0.4 * math.cos(angle)
            y = c + inner_r * 0.4 * math.sin(angle)
            painter.setBrush(QBrush(QColor(color)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPoint(int(x), int(y)), int(inner_r * 0.4), int(inner_r * 0.4))

        painter.end()
        return QIcon(pixmap)

    @staticmethod
    def tray_icon_active(size: int = 32) -> QIcon:
        """System tray icon when color management is active."""
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Green circle with check
        c = size / 2
        painter.setBrush(QBrush(QColor(COLORS['success'])))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPoint(int(c), int(c)), int(size * 0.4), int(size * 0.4))

        # White checkmark
        painter.setPen(QPen(QColor("white"), 2))
        path = QPainterPath()
        path.moveTo(size * 0.3, size * 0.5)
        path.lineTo(size * 0.45, size * 0.65)
        path.lineTo(size * 0.7, size * 0.35)
        painter.drawPath(path)

        painter.end()
        return QIcon(pixmap)

    @staticmethod
    def tray_icon_inactive(size: int = 32) -> QIcon:
        """System tray icon when color management is inactive."""
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Gray circle
        c = size / 2
        painter.setBrush(QBrush(QColor(COLORS['text_disabled'])))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPoint(int(c), int(c)), int(size * 0.4), int(size * 0.4))

        painter.end()
        return QIcon(pixmap)
