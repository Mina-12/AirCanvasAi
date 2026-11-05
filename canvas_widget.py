"""Qt canvas view for the persistent OpenCV drawing engine."""

from __future__ import annotations

import cv2

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget

from drawing_engine import DrawingEngine


class CanvasWidget(QWidget):
    def __init__(self, engine: DrawingEngine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.cursor: tuple[int, int] | None = None
        self.setMinimumSize(500, 390)
        self.setObjectName("drawingCanvas")

    def set_cursor(self, point: tuple[int, int] | None) -> None:
        self.cursor = point
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        image = self.engine.image()
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        height, width = rgb.shape[:2]
        qt_image = QImage(rgb.data, width, height, rgb.strides[0], QImage.Format.Format_RGB888).copy()
        target = self.rect().adjusted(8, 8, -8, -8)
        scaled = qt_image.scaled(target.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        left = target.x() + (target.width() - scaled.width()) // 2
        top = target.y() + (target.height() - scaled.height()) // 2
        painter.drawImage(left, top, scaled)
        if self.cursor is not None:
            sx, sy = scaled.width() / self.engine.width, scaled.height() / self.engine.height
            cx, cy = left + round(self.cursor[0] * sx), top + round(self.cursor[1] * sy)
            painter.setPen(QPen(QColor("#00aeca"), 2))
            painter.drawEllipse(cx - 10, cy - 10, 20, 20)
            painter.drawLine(cx - 14, cy, cx + 14, cy)
            painter.drawLine(cx, cy - 14, cx, cy + 14)
        painter.end()
