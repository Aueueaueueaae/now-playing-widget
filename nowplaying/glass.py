"""Liquid glass: общая отрисовка текстуры для облачка и настроек."""

from __future__ import annotations

import random
from functools import lru_cache

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)


@lru_cache(maxsize=4)
def _fine_noise(size: int = 96) -> QPixmap:
    rng = random.Random(20261113)
    data = bytearray(size * size * 4)
    for index in range(0, len(data), 4):
        value = rng.randrange(0, 256)
        alpha = rng.randrange(0, 14)
        data[index] = value
        data[index + 1] = value
        data[index + 2] = value
        data[index + 3] = alpha
    image = QImage(
        bytes(data), size, size, QImage.Format.Format_ARGB32
    ).copy()
    return QPixmap.fromImage(image)


@lru_cache(maxsize=4)
def _cloud_noise(size: int = 18) -> QPixmap:
    rng = random.Random(777)
    data = bytearray(size * size * 4)
    for index in range(0, len(data), 4):
        value = rng.randrange(90, 180)
        alpha = rng.randrange(0, 38)
        data[index] = value
        data[index + 1] = value
        data[index + 2] = value
        data[index + 3] = alpha
    image = QImage(
        bytes(data), size, size, QImage.Format.Format_ARGB32
    ).copy()
    return QPixmap.fromImage(image)


def _inner_path(rect: QRectF, radius: float, inset: float) -> QPainterPath:
    path = QPainterPath()
    adjusted = rect.adjusted(inset, inset, -inset, -inset)
    inner_radius = max(1.0, radius - inset)
    path.addRoundedRect(adjusted, inner_radius, inner_radius)
    return path


def paint_liquid_glass(
    painter: QPainter,
    rect: QRectF,
    radius: float,
    color: QColor | str,
    intensity: float,
    opacity: float,
    frost: float = 0.15,
    refraction: float = 0.75,
) -> None:
    """Прозрачное liquid glass: линза, преломление по кромке и блики.

    ``frost`` добавляет матовость, ``refraction`` — толщину и линзовый край,
    ``intensity`` — яркость бликов.
    """
    intensity = max(0.0, min(1.0, float(intensity)))
    opacity = max(0.0, min(1.0, float(opacity)))
    frost = max(0.0, min(1.0, float(frost)))
    refraction = max(0.0, min(1.0, float(refraction)))
    base = QColor(color)
    if not base.isValid():
        base = QColor("#1b2030")

    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    painter.save()
    painter.setClipPath(path)

    width = rect.width()
    height = rect.height()

    # Основа-линза: в центре стекло почти прозрачное, к краям плотнее.
    tint_alpha = int(90 + 80 * opacity)
    frost_alpha = int(55 * frost)
    total_alpha = min(232, tint_alpha + frost_alpha)
    center_alpha = max(16, int(total_alpha * 0.48))
    edge_alpha = min(244, int(total_alpha * 1.12))

    lens = QRadialGradient(
        rect.left() + width * 0.46,
        rect.top() + height * 0.40,
        max(width, height) * 0.78,
    )
    center = base.lighter(114)
    center.setAlpha(center_alpha)
    middle = QColor(base)
    middle.setAlpha(total_alpha)
    edge = base.darker(124)
    edge.setAlpha(edge_alpha)
    lens.setColorAt(0.0, center)
    lens.setColorAt(0.62, middle)
    lens.setColorAt(1.0, edge)
    painter.fillPath(path, lens)

    vertical = QLinearGradient(0, rect.top(), 0, rect.bottom())
    vertical.setColorAt(
        0.0, QColor(255, 255, 255, int(5 + 12 * intensity))
    )
    vertical.setColorAt(0.42, QColor(255, 255, 255, 0))
    vertical.setColorAt(1.0, QColor(0, 0, 0, int(8 + 18 * refraction)))
    painter.fillPath(path, vertical)

    # Мутность: при 0 стекло остаётся прозрачным, при 1 становится матовым.
    if frost > 0.015:
        painter.save()
        painter.setOpacity(min(0.58, 0.05 + 0.5 * frost))
        painter.fillPath(path, QColor(232, 240, 255, 34))
        painter.setOpacity(min(0.35, 0.01 + 0.24 * frost))
        cloud = _cloud_noise()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawPixmap(rect, cloud, QRectF(cloud.rect()))
        painter.setOpacity(min(0.28, 0.01 + 0.12 * frost))
        painter.drawTiledPixmap(rect, _fine_noise())
        painter.restore()

    # Мягкий цветной отсвет — без заливки обложкой.
    glow_color = base.lighter(180)
    glow_color.setAlpha(int(7 + 24 * intensity))
    glow = QRadialGradient(
        rect.left() + width * 0.14,
        rect.top() + height * 0.08,
        max(70.0, width * 0.85),
    )
    glow.setColorAt(0.0, glow_color)
    transparent = QColor(glow_color)
    transparent.setAlpha(0)
    glow.setColorAt(1.0, transparent)
    painter.fillPath(path, glow)

    # Толстая преломляющая полоса у кромки.
    band_width = 2.0 + 7.0 * refraction
    outer = QPainterPath(path)
    inner = QPainterPath()
    inner.addRoundedRect(
        rect.adjusted(
            band_width, band_width, -band_width, -band_width
        ),
        max(1.0, radius - band_width),
        max(1.0, radius - band_width),
    )
    ring = outer.subtracted(inner)
    ring_gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
    ring_gradient.setColorAt(
        0.0, QColor(255, 255, 255, int(10 + 20 * refraction))
    )
    ring_gradient.setColorAt(
        0.38, QColor(255, 255, 255, int(1 + 5 * refraction))
    )
    ring_gradient.setColorAt(
        0.74, QColor(255, 255, 255, int(0 + 2 * refraction))
    )
    caustic = base.lighter(170)
    caustic.setAlpha(int(2 + 8 * refraction))
    ring_gradient.setColorAt(0.90, caustic)
    ring_gradient.setColorAt(
        1.0, QColor(0, 0, 0, int(6 + 18 * refraction))
    )
    painter.fillPath(ring, ring_gradient)

    # Яркая внутренняя линия преломления.
    bright = QLinearGradient(rect.topLeft(), rect.bottomRight())
    bright.setColorAt(
        0.0, QColor(255, 255, 255, int(16 + 28 * refraction))
    )
    bright.setColorAt(0.5, QColor(255, 255, 255, int(3 + 8 * refraction)))
    bright.setColorAt(1.0, QColor(255, 255, 255, int(1 + 4 * refraction)))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QBrush(bright), 1.2 + 0.4 * refraction))
    painter.drawPath(
        _inner_path(rect, radius, max(1.1, band_width * 0.55))
    )

    # Тёмная тень внутри полосы — стекло кажется толстым.
    shadow = QLinearGradient(rect.topLeft(), rect.bottomRight())
    shadow.setColorAt(0.0, QColor(0, 0, 0, 0))
    shadow.setColorAt(0.55, QColor(0, 0, 0, int(4 + 9 * refraction)))
    shadow.setColorAt(1.0, QColor(0, 0, 0, int(18 + 20 * refraction)))
    painter.setPen(QPen(QBrush(shadow), 2.0))
    painter.drawPath(
        _inner_path(rect, radius, band_width + 1.0)
    )

    # Волнистый диагональный блик.
    band_alpha = int(3 + 14 * intensity)
    band = QPainterPath()
    top_y = rect.top() + height * 0.08
    band.moveTo(rect.left() - 8, top_y)
    band.cubicTo(
        rect.left() + width * 0.26,
        rect.top() + height * 0.01,
        rect.left() + width * 0.58,
        rect.top() + height * 0.44,
        rect.right() + 8,
        rect.top() + height * 0.05,
    )
    band.lineTo(rect.right() + 8, rect.top() + height * 0.25)
    band.cubicTo(
        rect.left() + width * 0.58,
        rect.top() + height * 0.55,
        rect.left() + width * 0.26,
        rect.top() + height * 0.16,
        rect.left() - 8,
        top_y + height * 0.16,
    )
    band.closeSubpath()
    band_gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
    band_gradient.setColorAt(0.0, QColor(255, 255, 255, band_alpha))
    band_gradient.setColorAt(0.55, QColor(255, 255, 255, band_alpha // 3))
    band_gradient.setColorAt(1.0, QColor(255, 255, 255, 0))
    painter.fillPath(band, band_gradient)

    # Узкий верхний блик, без молочной пелены.
    sheen = QLinearGradient(
        0, rect.top(), 0, rect.top() + height * 0.38
    )
    sheen.setColorAt(0.0, QColor(255, 255, 255, int(6 + 20 * intensity)))
    sheen.setColorAt(0.5, QColor(255, 255, 255, int(1 + 6 * intensity)))
    sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
    painter.fillPath(path, sheen)

    # Компактный specular в верхнем левом углу.
    specular = QRadialGradient(
        rect.left() + width * 0.18,
        rect.top() + height * 0.02,
        max(38.0, width * 0.30),
    )
    specular.setColorAt(
        0.0, QColor(255, 255, 255, int(8 + 22 * intensity))
    )
    specular.setColorAt(0.45, QColor(255, 255, 255, int(2 + 7 * intensity)))
    specular.setColorAt(1.0, QColor(255, 255, 255, 0))
    painter.fillPath(path, specular)

    # Короткая яркая линия по верхней кромке.
    painter.setPen(
        QPen(
            QColor(255, 255, 255, int(16 + 30 * intensity)),
            1.3,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
        )
    )
    painter.drawLine(
        int(rect.left() + radius * 0.9),
        int(rect.top() + 2.4),
        int(rect.left() + width * 0.55),
        int(rect.top() + 2.4),
    )

    # Тёмное утолщение снизу.
    shade = QLinearGradient(
        0, rect.top() + height * 0.62, 0, rect.bottom()
    )
    shade.setColorAt(0.0, QColor(0, 0, 0, 0))
    shade.setColorAt(1.0, QColor(0, 0, 0, int(10 + 20 * refraction)))
    painter.fillPath(path, shade)

    painter.setClipping(False)

    # Внешняя грань.
    border = QLinearGradient(rect.topLeft(), rect.bottomRight())
    border.setColorAt(
        0.0, QColor(255, 255, 255, int(50 + 50 * intensity))
    )
    border.setColorAt(0.46, QColor(255, 255, 255, int(16 + 22 * intensity)))
    border.setColorAt(1.0, QColor(255, 255, 255, int(8 + 12 * intensity)))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QBrush(border), 1.1 + 0.8 * refraction))
    painter.drawPath(path)

    # Тонкие светлые кромки для объёма.
    for inset, alpha in ((1.2, 30),):
        stroke = _inner_path(rect, radius, inset)
        stroke_gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        stroke_gradient.setColorAt(
            0.0,
            QColor(255, 255, 255, int(alpha * (0.55 + 0.75 * intensity))),
        )
        stroke_gradient.setColorAt(
            0.5, QColor(255, 255, 255, int(alpha * 0.18))
        )
        stroke_gradient.setColorAt(
            1.0, QColor(255, 255, 255, int(alpha * 0.06))
        )
        painter.setPen(QPen(QBrush(stroke_gradient), 1.0))
        painter.drawPath(stroke)

    # Едва заметный хроматический край: холодный сверху, тёплый снизу.
    fringe = QLinearGradient(rect.topLeft(), rect.bottomRight())
    fringe.setColorAt(
        0.0, QColor(175, 230, 255, int(8 + 16 * refraction))
    )
    fringe.setColorAt(0.5, QColor(255, 255, 255, 0))
    fringe.setColorAt(
        1.0, QColor(255, 195, 220, int(8 + 14 * refraction))
    )
    painter.setPen(QPen(QBrush(fringe), 0.9))
    painter.drawPath(_inner_path(rect, radius, 0.9))

    painter.restore()
