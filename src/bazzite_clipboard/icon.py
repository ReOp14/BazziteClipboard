from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


def clipboard_icon(size: int = 64) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    scale = size / 64
    painter.scale(scale, scale)

    body = QPainterPath()
    body.addRoundedRect(QRectF(12, 14, 40, 42), 6, 6)
    painter.fillPath(body, QColor("#3daee9"))

    clip = QPainterPath()
    clip.addRoundedRect(QRectF(22, 8, 20, 12), 3, 3)
    painter.fillPath(clip, QColor("#fcfcfc"))
    painter.setPen(QPen(QColor("#1d99f3"), 1.6))
    painter.drawRoundedRect(QRectF(22, 8, 20, 12), 3, 3)

    painter.setPen(QPen(QColor("#f5f5f5"), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawLine(22, 32, 42, 32)
    painter.drawLine(22, 40, 38, 40)
    painter.drawLine(22, 48, 34, 48)
    painter.end()
    return QIcon(pixmap)
