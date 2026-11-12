"""Компактное окно настроек с живым превью."""

from __future__ import annotations

import copy
import logging
import os
import subprocess
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QIcon,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .bubble import (
    BubblePanel,
    CoverWidget,
    ElidedLabel,
    art_slot_size,
    artist_font,
    art_slot_size,
    panel_padding,
    panel_radius,
    panel_size,
    panel_spacing,
    text_colors,
    title_font,
    ui_font_family,
)
from .config import (
    DEFAULT_BUBBLE_COLOR,
    DEFAULT_FALLBACK_IMAGE,
    DEFAULT_HOTKEY,
    Settings,
    normalize_color,
    normalize_process_name,
)
from .glass import paint_liquid_glass
from .winutil import parse_hotkey, resource_path

log = logging.getLogger(__name__)

SAMPLE_ARTIST = "Исполнитель"
SAMPLE_TITLE = "Название трека"
GLASS_MARGIN = 22
GLASS_RADIUS = 24

GLASS_STYLESHEET = """
#glassSettings {
    background: transparent;
}
#glassSettings QLabel {
    color: #eef2fb;
    background: transparent;
}
#glassSettings QPushButton {
    color: #eef2fb;
    background: rgba(255, 255, 255, 0.08);
    border: 1px solid rgba(255, 255, 255, 0.14);
    border-radius: 10px;
    padding: 6px 14px;
}
#glassSettings QPushButton:hover {
    background: rgba(255, 255, 255, 0.14);
}
#glassSettings QPushButton:pressed {
    background: rgba(255, 255, 255, 0.05);
}
#glassSettings QPushButton:default {
    border: 1px solid rgba(206, 102, 255, 0.75);
}
#glassSettings QToolButton {
    color: #e6ebf8;
    background: transparent;
    border: none;
    padding: 4px 6px;
}
#glassSettings QToolButton:hover {
    background: rgba(255, 255, 255, 0.08);
    border-radius: 8px;
}
#glassSettings QToolButton#closeButton {
    color: rgba(255, 255, 255, 0.72);
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.10);
    border-radius: 13px;
    font-size: 12pt;
}
#glassSettings QToolButton#closeButton:hover {
    color: white;
    background: rgba(255, 90, 100, 0.55);
    border-color: rgba(255, 160, 165, 0.55);
}
#glassSettings QSlider::groove:horizontal {
    height: 6px;
    border-radius: 3px;
    background: rgba(255, 255, 255, 0.12);
}
#glassSettings QSlider::sub-page:horizontal {
    background: rgba(206, 102, 255, 0.62);
    border-radius: 3px;
}
#glassSettings QSlider::handle:horizontal {
    width: 16px;
    height: 16px;
    margin: -5px 0;
    border-radius: 8px;
    background: #CE66FF;
    border: 1px solid rgba(255, 255, 255, 0.55);
}
#glassSettings QLineEdit,
#glassSettings QKeySequenceEdit,
#glassSettings QSpinBox,
#glassSettings QDoubleSpinBox {
    color: #eef2fb;
    background: rgba(0, 0, 0, 0.24);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 8px;
    padding: 4px 8px;
    selection-background-color: rgba(206, 102, 255, 0.55);
}
#glassSettings QLineEdit:focus,
#glassSettings QKeySequenceEdit:focus,
#glassSettings QSpinBox:focus,
#glassSettings QDoubleSpinBox:focus {
    border-color: rgba(206, 102, 255, 0.65);
}
#glassSettings QCheckBox {
    color: #e8edf9;
    spacing: 8px;
}
#glassSettings QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 5px;
    border: 1px solid rgba(255, 255, 255, 0.32);
    background: rgba(0, 0, 0, 0.22);
}
#glassSettings QCheckBox::indicator:checked {
    background: #CE66FF;
    border-color: rgba(235, 196, 255, 0.85);
}
#glassSettings QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 2px 0;
}
#glassSettings QScrollBar::handle:vertical {
    background: rgba(255, 255, 255, 0.20);
    border-radius: 4px;
    min-height: 24px;
}
#glassSettings QScrollBar::add-line:vertical,
#glassSettings QScrollBar::sub-line:vertical {
    height: 0;
}
#glassSettings QToolTip {
    color: #eef2fb;
    background: #202430;
    border: 1px solid rgba(255, 255, 255, 0.18);
    padding: 4px;
}
"""


class GlassTitleBar(QWidget):
    """Заголовок безрамочного окна: перетаскивание и кнопка закрытия."""

    def __init__(self, title: str, dialog: QDialog) -> None:
        super().__init__(dialog)
        self._drag_offset: QPoint | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        label = QLabel(title, self)
        label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        label.setStyleSheet(
            "color: #f3f6fe; font-size: 15pt; font-weight: 600;"
        )
        close = QToolButton(self)
        close.setObjectName("closeButton")
        close.setText("✕")
        close.setFixedSize(26, 26)
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(dialog.reject)
        layout.addWidget(label)
        layout.addStretch(1)
        layout.addWidget(close)
        self.setFixedHeight(34)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            window = self.window()
            handle = window.windowHandle()
            try:
                if handle is not None and handle.startSystemMove():
                    event.accept()
                    return
            except Exception:
                pass
            self._drag_offset = (
                event.globalPosition().toPoint()
                - window.frameGeometry().topLeft()
            )
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if (
            self._drag_offset is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            self.window().move(
                event.globalPosition().toPoint() - self._drag_offset
            )
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_offset = None
        super().mouseReleaseEvent(event)


def hint_label(text: str, parent: QWidget | None = None) -> QLabel:
    """Приглушённая подсказка на тёмном стекле."""
    label = QLabel(text, parent)
    label.setWordWrap(True)
    label.setStyleSheet("color: rgba(214, 222, 241, 0.60);")
    return label


class TransparentViewport(QWidget):
    """Viewport прокрутки без собственной заливки — видно стекло окна."""

    def paintEvent(self, event) -> None:  # noqa: N802
        # Намеренно ничего не рисуем: фоном служит liquid glass диалога.
        del event


class TransparentBody(QWidget):
    """Контейнер настроек без фоновой заливки."""

    def paintEvent(self, event) -> None:  # noqa: N802
        del event


class GlassScrollArea(QScrollArea):
    """Область прокрутки без фоновой заливки: видно liquid glass окна."""

    def paintEvent(self, event) -> None:  # noqa: N802
        del event


class GlassGroupBox(QGroupBox):
    """Карточка настроек: полупрозрачная подложка и заголовок внутри."""

    def __init__(self, title: str, parent: QWidget) -> None:
        super().__init__(title, parent)
        self.setAutoFillBackground(False)
        self.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground, True
        )

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
        )
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, 14, 14)

        painter.fillPath(path, QColor(8, 12, 20, 105))
        painter.save()
        painter.setClipPath(path)
        sheen = QLinearGradient(0, rect.top(), 0, rect.top() + 46)
        sheen.setColorAt(0.0, QColor(255, 255, 255, 18))
        sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillRect(
            QRectF(rect.left(), rect.top(), rect.width(), 46), sheen
        )
        painter.restore()

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 54), 1.0))
        painter.drawPath(path)

        font = QFont(self.font())
        font.setPixelSize(12)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor(225, 232, 248, 185))
        painter.drawText(
            QRectF(14, 5, max(10.0, rect.width() - 28), 18),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            self.title(),
        )


def glass_group(title: str, parent: QWidget) -> QGroupBox:
    return GlassGroupBox(title, parent)


# --------------------------------------------------------------------------- #
# Превью
# --------------------------------------------------------------------------- #

class BubblePreview(QWidget):
    """Мини-копия облачка из тех же виджетов, что и настоящее окно."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = Settings()
        self._cover_pixmap: QPixmap | None = None
        self._fallback_pixmap: QPixmap | None = None
        self._fallback_key = ""
        self._family = ui_font_family()

        self._panel = BubblePanel(self)
        layout = QHBoxLayout(self._panel)
        layout.setContentsMargins(18, 16, 20, 16)
        layout.setSpacing(14)
        self._layout = layout

        self._cover = CoverWidget(64, self._panel)
        layout.addWidget(self._cover, 0, Qt.AlignmentFlag.AlignVCenter)

        text_host = QWidget(self._panel)
        text_layout = QVBoxLayout(text_host)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)
        text_layout.addStretch(1)
        self._artist = ElidedLabel(text_host)
        self._artist.setText(SAMPLE_ARTIST)
        self._title = ElidedLabel(text_host)
        self._title.setText(SAMPLE_TITLE)
        text_layout.addWidget(self._artist)
        text_layout.addWidget(self._title)
        text_layout.addStretch(1)
        layout.addWidget(text_host, 1)

        self._load_sample_cover()
        self._load_fallback(self._settings.fallback_image)
        self._refresh()

    def _load_sample_cover(self) -> None:
        pixmap = QPixmap(str(resource_path("assets/icon.png")))
        self._cover_pixmap = pixmap if not pixmap.isNull() else None

    def _load_fallback(self, path: str) -> None:
        wanted = (path or DEFAULT_FALLBACK_IMAGE).strip()
        if wanted == self._fallback_key:
            return
        self._fallback_key = wanted
        candidate = Path(wanted)
        if not candidate.is_absolute():
            candidate = resource_path(wanted)
        pixmap = QPixmap(str(candidate))
        if pixmap.isNull():
            pixmap = QPixmap(str(resource_path(DEFAULT_FALLBACK_IMAGE)))
        self._fallback_pixmap = pixmap if not pixmap.isNull() else None
        self._refresh_art()

    def update_settings(self, settings: Settings) -> None:
        self._settings = settings
        self._load_fallback(settings.fallback_image)
        self._refresh()

    def _refresh(self) -> None:
        settings = self._settings
        size = panel_size(settings)
        pad_left, pad_top, pad_right, pad_bottom = panel_padding(settings)
        self._layout.setContentsMargins(
            pad_left, pad_top, pad_right, pad_bottom
        )
        self._layout.setSpacing(panel_spacing(settings))
        self._panel.set_radius(panel_radius(size))
        self._panel.setFixedSize(size)
        self.setFixedSize(size)

        self._panel.set_color(settings.bubble_color)
        self._panel.set_intensity(settings.glass_intensity)
        self._panel.set_frost(settings.glass_frost)
        self._panel.set_refraction(settings.glass_refraction)
        self._panel.set_opacity(settings.opacity)

        self._title.setFont(title_font(settings, self._family))
        self._artist.setFont(artist_font(settings, self._family))
        title_color, artist_color = text_colors(settings)
        self._title.setTextColor(title_color)
        self._artist.setTextColor(artist_color)

        self._cover.set_side(art_slot_size(settings))
        self._refresh_art()
        self.updateGeometry()
        self.adjustSize()

    def _refresh_art(self) -> None:
        side = art_slot_size(self._settings)
        if self._cover_pixmap is None:
            self._cover.set_circular(True)
            self._cover.set_image_side(side)
            self._cover.set_cover(self._fallback_pixmap)
        else:
            self._cover.set_circular(False)
            self._cover.set_image_side(side)
            self._cover.set_cover(self._cover_pixmap)


class PreviewCanvas(QWidget):
    """Цветная подложка + отрисованное облачко, вписанное в размер окна."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._preview = BubblePreview(self)
        self._preview.hide()
        self._panel_pixmap: QPixmap | None = None
        self.setFixedHeight(168)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )

    def update_settings(self, settings: Settings) -> None:
        self._preview.update_settings(settings)
        self._preview.ensurePolished()
        size = self._preview.size()
        pixmap = QPixmap(size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        self._preview.render(painter, QPoint(0, 0))
        painter.end()
        self._panel_pixmap = pixmap
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        clip = QPainterPath()
        clip.addRoundedRect(rect, 14, 14)
        painter.setClipPath(clip)

        gradient = QLinearGradient(0, 0, rect.width(), rect.height())
        gradient.setColorAt(0.0, QColor(38, 54, 110))
        gradient.setColorAt(0.5, QColor(74, 52, 118))
        gradient.setColorAt(1.0, QColor(128, 58, 96))
        painter.fillRect(rect, gradient)

        blobs = (
            (QColor(84, 170, 255, 150), 0.18, 0.20, 0.62),
            (QColor(255, 120, 190, 120), 0.86, 0.24, 0.55),
            (QColor(120, 255, 214, 90), 0.62, 0.92, 0.60),
        )
        for color, cx, cy, size in blobs:
            radius = max(rect.width(), rect.height()) * size
            glow = QRadialGradient(
                rect.width() * cx, rect.height() * cy, radius
            )
            glow.setColorAt(0.0, color)
            faded = QColor(color)
            faded.setAlpha(0)
            glow.setColorAt(1.0, faded)
            painter.fillRect(rect, glow)

        painter.setClipping(False)

        if self._panel_pixmap is not None:
            available = rect.adjusted(18, 18, -18, -18).size()
            source = self._panel_pixmap
            if (
                source.width() <= available.width()
                and source.height() <= available.height()
            ):
                scaled = source
            else:
                scaled = source.scaled(
                    available.toSize(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            x = rect.left() + (rect.width() - scaled.width()) / 2.0
            y = rect.top() + (rect.height() - scaled.height()) / 2.0

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 52))
            painter.drawRoundedRect(
                QRectF(x, y + 4, scaled.width(), scaled.height()),
                18,
                18,
            )
            painter.drawPixmap(int(round(x)), int(round(y)), scaled)


# --------------------------------------------------------------------------- #
# Диалог
# --------------------------------------------------------------------------- #

class SettingsDialog(QDialog):
    """Главные настройки сверху, всё остальное — в «Дополнительно»."""

    preview_changed = Signal(object)  # Settings

    def __init__(
        self, settings: Settings, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._original = copy.deepcopy(settings)
        self._settings = copy.deepcopy(settings)
        self._family = ui_font_family()
        self._suppress_preview = True
        self._color_value = normalize_color(
            settings.bubble_color, DEFAULT_BUBBLE_COLOR
        )

        self.setObjectName("glassSettings")
        self.setWindowTitle("Настройки облачка")
        icon_path = resource_path("assets/icon.ico")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setMinimumWidth(560)

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(60)
        self._preview_timer.timeout.connect(self._emit_preview)

        self.setStyleSheet(GLASS_STYLESHEET)
        self._build_ui()
        self._load_controls()
        self._connect_signals()
        self._suppress_preview = False
        self._emit_preview()
        self._fit_to_screen()

    # ------------------------------------------------------------------ #
    # Интерфейс
    # ------------------------------------------------------------------ #

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
        )
        panel = QRectF(self.rect()).adjusted(
            GLASS_MARGIN, GLASS_MARGIN, -GLASS_MARGIN, -GLASS_MARGIN
        )

        painter.setPen(Qt.PenStyle.NoPen)
        for index in range(16, 0, -1):
            grow = 10.0 * index / 16.0
            depth = 1.0 - index / 16.0
            alpha = int(1.5 + 3.5 * depth**1.4)
            painter.setBrush(QColor(0, 0, 0, alpha))
            painter.drawRoundedRect(
                panel.adjusted(-grow, -grow + 3, grow, grow + 3),
                GLASS_RADIUS + grow,
                GLASS_RADIUS + grow,
            )

        cut = QPainterPath()
        cut.addRoundedRect(panel, GLASS_RADIUS, GLASS_RADIUS)
        painter.setCompositionMode(
            QPainter.CompositionMode.CompositionMode_Clear
        )
        painter.setBrush(QColor(0, 0, 0, 255))
        painter.drawPath(cut)
        painter.setCompositionMode(
            QPainter.CompositionMode.CompositionMode_SourceOver
        )
        paint_liquid_glass(
            painter,
            panel,
            GLASS_RADIUS,
            QColor("#0a0e18"),
            0.90,
            0.95,
            0.45,
            0.85,
        )
        # Затемнённая шапка, чтобы заголовок читался на любом фоне.
        painter.save()
        header_clip = QPainterPath()
        header_clip.addRoundedRect(panel, GLASS_RADIUS, GLASS_RADIUS)
        painter.setClipPath(header_clip)
        header = QLinearGradient(0, panel.top(), 0, panel.top() + 88)
        header.setColorAt(0.0, QColor(6, 9, 16, 130))
        header.setColorAt(1.0, QColor(6, 9, 16, 0))
        painter.fillRect(
            QRectF(panel.left(), panel.top(), panel.width(), 88),
            header,
        )
        painter.restore()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            GLASS_MARGIN + 18,
            GLASS_MARGIN + 12,
            GLASS_MARGIN + 18,
            GLASS_MARGIN + 14,
        )
        outer.setSpacing(10)

        outer.addWidget(GlassTitleBar("Настройки", self))
        outer.addWidget(
            hint_label("Изменения сразу видны на облачке — можно не сохранять.")
        )

        body = TransparentBody(self)
        body.setObjectName("scrollBody")
        body.setAutoFillBackground(False)
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(10)

        self._preview_canvas = PreviewCanvas(body)
        body_layout.addWidget(self._preview_canvas)

        body_layout.addWidget(self._build_main_group(body))
        body_layout.addWidget(self._build_color_row(body))

        self._advanced_open = False
        self._advanced_toggle = QToolButton(body)
        self._advanced_toggle.setAutoRaise(True)
        self._advanced_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self._advanced_toggle.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self._advanced_toggle.setText("Дополнительно")
        self._advanced_toggle.clicked.connect(self._toggle_advanced)
        body_layout.addWidget(self._advanced_toggle, 0, Qt.AlignmentFlag.AlignLeft)

        self._advanced = self._build_advanced(body)
        self._advanced.setVisible(False)
        body_layout.addWidget(self._advanced)
        body_layout.addStretch(1)

        self._scroll = GlassScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._scroll.setAutoFillBackground(False)
        self._scroll.setAttribute(
            Qt.WidgetAttribute.WA_NoSystemBackground, True
        )
        viewport = TransparentViewport(self._scroll)
        viewport.setAutoFillBackground(False)
        viewport.setAttribute(
            Qt.WidgetAttribute.WA_NoSystemBackground, True
        )
        self._scroll.setViewport(viewport)
        self._scroll.setWidget(body)
        body.setAutoFillBackground(False)
        body.setAttribute(
            Qt.WidgetAttribute.WA_NoSystemBackground, True
        )
        body.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground, True
        )
        outer.addWidget(self._scroll, 1)

        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        reset_button = QPushButton("Сбросить", self)
        reset_button.clicked.connect(self._on_reset)
        json_button = QPushButton("Открыть JSON…", self)
        json_button.setToolTip(
            "Для продвинутых: полный файл настроек в блокноте."
        )
        json_button.clicked.connect(self._on_open_json)
        save_button = QPushButton("Сохранить", self)
        save_button.setDefault(True)
        save_button.clicked.connect(self._on_save)
        cancel_button = QPushButton("Отмена", self)
        cancel_button.clicked.connect(self.reject)

        bottom.addWidget(reset_button)
        bottom.addWidget(json_button)
        bottom.addStretch(1)
        bottom.addWidget(save_button)
        bottom.addWidget(cancel_button)
        outer.addLayout(bottom)

    def _build_main_group(self, parent: QWidget) -> QWidget:
        box = glass_group("Основное", parent)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(12, 30, 12, 12)
        layout.setSpacing(8)

        self._artist_slider, self._artist_value, artist_row = self._slider_row(
            box, "Исполнитель", 8, 28
        )
        self._title_slider, self._title_value, title_row = self._slider_row(
            box, "Название трека", 11, 32
        )
        self._cover_slider, self._cover_value, cover_row = self._slider_row(
            box, "Обложка", 40, 140
        )
        self._scale_slider, self._scale_value, scale_row = self._slider_row(
            box, "Размер облака", 20, 160
        )
        layout.addWidget(artist_row)
        layout.addWidget(title_row)
        layout.addWidget(cover_row)
        layout.addWidget(scale_row)

        self._size_label = hint_label("", box)
        self._size_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self._size_label)
        return box

    def _build_color_row(self, parent: QWidget) -> QWidget:
        box = glass_group("Цвет облака", parent)
        layout = QHBoxLayout(box)
        layout.setContentsMargins(12, 30, 12, 10)
        layout.setSpacing(10)

        self._color_button = QPushButton(box)
        self._color_button.setFixedSize(44, 28)
        self._color_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._color_button.clicked.connect(self._pick_color)

        self._color_label = QLabel(box)
        self._color_label.setMinimumWidth(74)

        palette_button = QPushButton("Палитра…", box)
        palette_button.clicked.connect(self._pick_color)

        layout.addWidget(self._color_button)
        layout.addWidget(self._color_label)
        layout.addStretch(1)
        layout.addWidget(palette_button)
        return box

    def _build_advanced(self, parent: QWidget) -> QWidget:
        host = QWidget(parent)
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        glass_box = glass_group("Стекло", host)
        glass_layout = QVBoxLayout(glass_box)
        glass_layout.setContentsMargins(12, 30, 12, 10)
        glass_layout.setSpacing(8)
        self._glass_slider, self._glass_value, glass_row = self._slider_row(
            glass_box, "Блик", 0, 100
        )
        self._frost_slider, self._frost_value, frost_row = self._slider_row(
            glass_box, "Мутность", 0, 100
        )
        (
            self._refraction_slider,
            self._refraction_value,
            refraction_row,
        ) = self._slider_row(glass_box, "Преломление", 0, 100)
        self._opacity_slider, self._opacity_value, opacity_row = self._slider_row(
            glass_box, "Тонировка", 30, 100
        )
        glass_layout.addWidget(glass_row)
        glass_layout.addWidget(frost_row)
        glass_layout.addWidget(refraction_row)
        glass_layout.addWidget(opacity_row)
        layout.addWidget(glass_box)

        image_box = glass_group("Картинка без обложки", host)
        image_layout = QVBoxLayout(image_box)
        image_layout.setContentsMargins(12, 30, 12, 10)
        image_layout.setSpacing(8)
        image_row = QHBoxLayout()
        self._fallback_edit = QLineEdit(image_box)
        self._fallback_edit.setPlaceholderText(DEFAULT_FALLBACK_IMAGE)
        browse = QPushButton("Обзор…", image_box)
        browse.clicked.connect(self._pick_fallback_image)
        reset_image = QPushButton("Сброс", image_box)
        reset_image.clicked.connect(
            lambda: self._fallback_edit.setText(DEFAULT_FALLBACK_IMAGE)
        )
        image_row.addWidget(self._fallback_edit, 1)
        image_row.addWidget(browse)
        image_row.addWidget(reset_image)
        image_layout.addLayout(image_row)
        image_layout.addWidget(
            hint_label(
                "Показывается автоматически, если обложки нет или плеер "
                "прислал свою заглушку.",
                image_box,
            )
        )
        layout.addWidget(image_box)

        behavior_box = glass_group("Поведение", host)
        behavior_layout = QGridLayout(behavior_box)
        behavior_layout.setContentsMargins(12, 30, 12, 10)
        behavior_layout.setHorizontalSpacing(10)
        behavior_layout.setVerticalSpacing(8)
        behavior_layout.addWidget(QLabel("Скрыть после паузы:", behavior_box), 0, 0)
        self._pause_delay = QDoubleSpinBox(behavior_box)
        self._pause_delay.setRange(0.0, 60.0)
        self._pause_delay.setSingleStep(0.5)
        self._pause_delay.setDecimals(1)
        self._pause_delay.setSuffix(" с")
        behavior_layout.addWidget(self._pause_delay, 0, 1)
        behavior_layout.setColumnStretch(2, 1)

        self._autostart = QCheckBox("Запускать с Windows", behavior_box)
        self._detect_games = QCheckBox(
            "Прятать в полноэкранных играх", behavior_box
        )
        behavior_layout.addWidget(self._autostart, 1, 0, 1, 3)
        behavior_layout.addWidget(self._detect_games, 2, 0, 1, 3)
        behavior_layout.addWidget(
            QLabel("Не считать играми:", behavior_box), 3, 0
        )
        self._ignore_processes = QLineEdit(behavior_box)
        self._ignore_processes.setPlaceholderText("chrome.exe, obs64.exe")
        behavior_layout.addWidget(self._ignore_processes, 3, 1, 1, 2)
        layout.addWidget(behavior_box)

        hotkey_box = glass_group("Горячая клавиша", host)
        hotkey_layout = QHBoxLayout(hotkey_box)
        hotkey_layout.setContentsMargins(12, 30, 12, 10)
        self._hotkey_edit = QKeySequenceEdit(hotkey_box)
        try:
            self._hotkey_edit.setMaximumSequenceLength(1)
        except AttributeError:
            pass
        default_button = QPushButton("По умолчанию", hotkey_box)
        default_button.clicked.connect(
            lambda: self._hotkey_edit.setKeySequence(
                QKeySequence(DEFAULT_HOTKEY)
            )
        )
        hotkey_layout.addWidget(self._hotkey_edit, 1)
        hotkey_layout.addWidget(default_button)
        layout.addWidget(hotkey_box)
        layout.addWidget(
            hint_label(
                "Нужен модификатор Ctrl, Alt, Shift или Win. "
                f"По умолчанию {DEFAULT_HOTKEY}.",
                host,
            )
        )
        return host

    def _slider_row(
        self, parent: QWidget, text: str, minimum: int, maximum: int
    ) -> tuple[QSlider, QLabel, QWidget]:
        host = QWidget(parent)
        layout = QHBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        label = QLabel(text, host)
        label.setMinimumWidth(128)
        slider = QSlider(Qt.Orientation.Horizontal, host)
        slider.setRange(minimum, maximum)
        value = QLabel("", host)
        value.setFixedWidth(48)
        value.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        layout.addWidget(label)
        layout.addWidget(slider, 1)
        layout.addWidget(value)
        return slider, value, host

    # ------------------------------------------------------------------ #
    # Значения
    # ------------------------------------------------------------------ #

    def _load_controls(self) -> None:
        settings = self._settings
        self._artist_slider.setValue(int(settings.artist_font_size))
        self._title_slider.setValue(int(settings.font_size))
        self._cover_slider.setValue(int(settings.cover_size))
        self._scale_slider.setValue(round(float(settings.bubble_scale) * 100))
        self._glass_slider.setValue(round(settings.glass_intensity * 100))
        self._frost_slider.setValue(round(settings.glass_frost * 100))
        self._refraction_slider.setValue(
            round(settings.glass_refraction * 100)
        )
        self._opacity_slider.setValue(round(settings.opacity * 100))
        self._fallback_edit.setText(settings.fallback_image)
        self._fallback_edit.setCursorPosition(0)
        self._pause_delay.setValue(float(settings.pause_hide_delay_sec))
        self._autostart.setChecked(bool(settings.autostart))
        self._detect_games.setChecked(bool(settings.detect_games))
        self._ignore_processes.setText(
            ", ".join(settings.ignore_fullscreen_processes)
        )
        self._hotkey_edit.setKeySequence(QKeySequence(settings.hotkey))
        self._set_color(settings.bubble_color, emit=False)
        self._update_value_labels()

    def _connect_signals(self) -> None:
        for widget in (
            self._artist_slider,
            self._title_slider,
            self._cover_slider,
            self._scale_slider,
            self._glass_slider,
            self._frost_slider,
            self._refraction_slider,
            self._opacity_slider,
            self._pause_delay,
        ):
            widget.valueChanged.connect(self._schedule_preview)
        self._autostart.toggled.connect(self._schedule_preview)
        self._detect_games.toggled.connect(self._schedule_preview)
        self._ignore_processes.textChanged.connect(self._schedule_preview)
        self._fallback_edit.textChanged.connect(self._schedule_preview)
        self._hotkey_edit.keySequenceChanged.connect(self._schedule_preview)

    def _set_color(self, value: str, emit: bool = True) -> None:
        color = normalize_color(value, DEFAULT_BUBBLE_COLOR)
        self._color_value = color
        self._color_label.setText(color)
        self._color_button.setStyleSheet(
            "QPushButton { border-radius: 7px; border: 1px solid rgba(0,0,0,0.35);"
            f" background: {color}; }}"
            "QPushButton:hover { border: 2px solid palette(highlight); }"
        )
        if emit:
            self._schedule_preview()

    def _pick_color(self) -> None:
        current = QColor(self._color_value)
        if not current.isValid():
            current = QColor(DEFAULT_BUBBLE_COLOR)
        chosen = QColorDialog.getColor(current, self, "Цвет облака")
        if chosen.isValid():
            self._set_color(chosen.name())

    def _pick_fallback_image(self) -> None:
        current = Path(self._fallback_edit.text())
        if current.is_file():
            start_dir = current.parent
        else:
            start_dir = Path.home() / "Pictures"
            if not start_dir.exists():
                start_dir = Path.home()
        path, _filter = QFileDialog.getOpenFileName(
            self,
            "Картинка для треков без обложки",
            str(start_dir),
            "Картинки (*.png *.jpg *.jpeg *.webp *.bmp);;Все файлы (*.*)",
        )
        if path:
            self._fallback_edit.setText(path)
            self._fallback_edit.setCursorPosition(0)

    def _update_value_labels(self) -> None:
        self._artist_value.setText(f"{self._artist_slider.value()} px")
        self._title_value.setText(f"{self._title_slider.value()} px")
        self._cover_value.setText(f"{self._cover_slider.value()} px")
        self._scale_value.setText(f"{self._scale_slider.value()}%")
        self._glass_value.setText(f"{self._glass_slider.value()}%")
        self._frost_value.setText(f"{self._frost_slider.value()}%")
        self._refraction_value.setText(
            f"{self._refraction_slider.value()}%"
        )
        self._opacity_value.setText(f"{self._opacity_slider.value()}%")
        settings = self._collect_preview()
        size = panel_size(settings)
        self._size_label.setText(
            f"Ширина × высота: {size.width()} × {size.height()} px"
        )

    def _collect_preview(self) -> Settings:
        """Настройки из ползунков без учёта полей, которые не влияют на размер."""
        settings = copy.deepcopy(self._settings)
        settings.artist_font_size = self._artist_slider.value()
        settings.font_size = self._title_slider.value()
        settings.cover_size = self._cover_slider.value()
        settings.bubble_scale = self._scale_slider.value() / 100.0
        settings.bubble_color = self._color_value
        return settings

    def _collect(self) -> Settings:
        settings = self._collect_preview()
        settings.glass_intensity = self._glass_slider.value() / 100.0
        settings.glass_frost = self._frost_slider.value() / 100.0
        settings.glass_refraction = self._refraction_slider.value() / 100.0
        settings.opacity = self._opacity_slider.value() / 100.0
        settings.fallback_image = (
            self._fallback_edit.text().strip() or DEFAULT_FALLBACK_IMAGE
        )
        settings.pause_hide_delay_sec = self._pause_delay.value()
        settings.autostart = self._autostart.isChecked()
        settings.detect_games = self._detect_games.isChecked()
        raw = self._ignore_processes.text().replace(";", ",").split(",")
        clean: list[str] = []
        for item in raw:
            value = normalize_process_name(item)
            if value and value not in clean:
                clean.append(value)
        settings.ignore_fullscreen_processes = tuple(clean)

        sequence = self._hotkey_edit.keySequence().toString(
            QKeySequence.SequenceFormat.PortableText
        )
        settings.hotkey = sequence.strip() or DEFAULT_HOTKEY
        return settings

    def _schedule_preview(self, *_args) -> None:
        if self._suppress_preview:
            return
        self._update_value_labels()
        self._preview_timer.start()

    def _emit_preview(self) -> None:
        self._settings = self._collect()
        self._preview_canvas.update_settings(self._settings)
        self.preview_changed.emit(copy.deepcopy(self._settings))

    # ------------------------------------------------------------------ #
    # Кнопки и поведение
    # ------------------------------------------------------------------ #

    def _toggle_advanced(self) -> None:
        self._set_advanced_open(not self._advanced_open)

    def _set_advanced_open(self, opened: bool) -> None:
        self._advanced_open = bool(opened)
        self._advanced.setVisible(self._advanced_open)
        self._advanced_toggle.setArrowType(
            Qt.ArrowType.DownArrow
            if self._advanced_open
            else Qt.ArrowType.RightArrow
        )
        if self._advanced_open:
            QTimer.singleShot(50, self._reveal_advanced)

    def _reveal_advanced(self) -> None:
        self._scroll.ensureWidgetVisible(self._advanced, 0, 12)
        bar = self._scroll.verticalScrollBar()
        bar.setValue(max(bar.minimum(), bar.value() - 36))

    def _message_box(
        self,
        title: str,
        text: str,
        *,
        question: bool = False,
        warning: bool = False,
    ) -> int:
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(text)
        box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        box.setStyleSheet(
            "QMessageBox { background: #1b202b; }"
            "QMessageBox QLabel { color: #eef2fb; }"
            "QMessageBox QPushButton {"
            " color: #eef2fb; background: rgba(255,255,255,0.12);"
            " border: 1px solid rgba(255,255,255,0.22);"
            " border-radius: 8px; padding: 5px 16px; min-width: 72px; }"
            "QMessageBox QPushButton:hover {"
            " background: rgba(255,255,255,0.20); }"
        )
        if question:
            box.setIcon(QMessageBox.Icon.Question)
            box.setStandardButtons(
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No
            )
            box.setDefaultButton(QMessageBox.StandardButton.No)
        else:
            box.setIcon(
                QMessageBox.Icon.Warning
                if warning
                else QMessageBox.Icon.Information
            )
            box.setStandardButtons(QMessageBox.StandardButton.Ok)
        return int(box.exec())

    def _on_save(self) -> None:
        settings = self._collect()
        if not parse_hotkey(settings.hotkey) or "+" not in settings.hotkey:
            self._message_box(
                "Горячая клавиша",
                "Не удалось распознать комбинацию. Нужен хотя бы один "
                "модификатор (Ctrl, Alt, Shift, Win) и обычная клавиша.\n\n"
                f"Сейчас указано: {settings.hotkey or 'ничего'}",
                warning=True,
            )
            self._set_advanced_open(True)
            QTimer.singleShot(
                60,
                lambda: self._scroll.ensureWidgetVisible(self._hotkey_edit),
            )
            self._hotkey_edit.setFocus()
            return
        self._settings = settings
        self.accept()

    def _on_reset(self) -> None:
        answer = self._message_box(
            "Сбросить настройки",
            "Вернуть внешний вид и поведение к значениям по умолчанию?",
            question=True,
        )
        if answer != int(QMessageBox.StandardButton.Yes):
            return
        defaults = replace(
            Settings(), position=copy.deepcopy(self._original.position)
        )
        self._settings = defaults
        self._load_controls()
        self._emit_preview()

    def _on_open_json(self) -> None:
        from .config import SETTINGS_PATH

        path = SETTINGS_PATH
        try:
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}\n", encoding="utf-8")
            os.startfile(str(path))  # type: ignore[attr-defined]
        except Exception:
            try:
                subprocess.Popen(["notepad.exe", str(path)])
            except Exception:
                log.exception("Не удалось открыть файл настроек")
                self._message_box(
                    "Файл настроек",
                    f"Не удалось открыть файл:\n{path}",
                    warning=True,
                )

    def _fit_to_screen(self) -> None:
        """Не даём окну вырасти выше экрана: лишнее прокручивается."""
        body = self._scroll.widget()
        content_height = body.sizeHint().height() if body is not None else 0
        wanted_height = max(560, content_height + 190)
        screen = QGuiApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else None
        if available is None:
            self.resize(560, wanted_height)
            return
        width = min(560, available.width() - 40)
        height = min(wanted_height, available.height() - 60)
        self.resize(width, height)
        self.move(available.center() - self.rect().center())

    def result_settings(self) -> Settings:
        return copy.deepcopy(self._settings)

    def original_settings(self) -> Settings:
        return copy.deepcopy(self._original)
