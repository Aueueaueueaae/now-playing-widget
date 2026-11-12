"""Иконка приложения без внешних картинок."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QIcon,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)


def render_icon(size: int) -> QImage:
    size = max(8, int(size))
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    s = float(size)
    margin = s * 0.035
    body = QRectF(margin, margin, s - margin * 2, s - margin * 2)
    radius = s * 0.24

    body_path = QPainterPath()
    body_path.addRoundedRect(body, radius, radius)

    gradient = QLinearGradient(body.left(), body.top(), body.right(), body.bottom())
    gradient.setColorAt(0.0, QColor(91, 108, 255))
    gradient.setColorAt(0.55, QColor(124, 92, 246))
    gradient.setColorAt(1.0, QColor(184, 78, 218))
    painter.fillPath(body_path, gradient)

    # Верхний блик.
    sheen = QLinearGradient(body.left(), body.top(), body.left(), body.bottom())
    sheen.setColorAt(0.0, QColor(255, 255, 255, 52))
    sheen.setColorAt(0.55, QColor(255, 255, 255, 0))
    painter.fillPath(body_path, sheen)

    # Облачко.
    cloud = QPainterPath()
    cloud.addRoundedRect(
        QRectF(s * 0.19, s * 0.45, s * 0.62, s * 0.29),
        s * 0.145,
        s * 0.145,
    )
    for cx, cy, r in (
        (0.34, 0.50, 0.145),
        (0.49, 0.41, 0.185),
        (0.64, 0.50, 0.145),
    ):
        circle = QPainterPath()
        circle.addEllipse(QRectF(s * (cx - r), s * (cy - r), s * r * 2, s * r * 2))
        cloud = cloud.united(circle)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(255, 255, 255, 246))
    painter.drawPath(cloud)

    # Три тёмные полоски-эквалайзер внутри облака.
    if size >= 20:
        bar_color = QColor(63, 61, 160, 220)
        painter.setBrush(bar_color)
        painter.setPen(QPen(bar_color, max(1.0, s * 0.012)))
        bar_w = s * 0.038
        bar_radius = bar_w / 2
        base_y = s * 0.635
        for dx, height in ((0.445, 0.085), (0.481, 0.135), (0.517, 0.105)):
            r = QRectF(s * dx, base_y - s * height, bar_w, s * height)
            painter.drawRoundedRect(r, bar_radius, bar_radius)

    # Тонкая грань.
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor(255, 255, 255, 42), max(0.7, s * 0.006)))
    painter.drawPath(body_path)

    painter.end()
    return image


def make_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 20, 24, 32, 40, 48, 64, 128, 256):
        pixmap = QPixmap.fromImage(render_icon(size))
        icon.addPixmap(pixmap)
    return icon


def save_png(path: Path, size: int = 256) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    render_icon(size).save(str(path), "PNG")
