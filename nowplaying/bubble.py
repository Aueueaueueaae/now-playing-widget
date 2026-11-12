"""Прозрачное стеклянное облачко с обложкой и плавными переходами."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QFontMetrics,
    QGuiApplication,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .app_icons import looks_like_browser_icon, looks_like_source_icon
from .glass import paint_liquid_glass
from .config import (
    DEFAULT_BUBBLE_COLOR,
    DEFAULT_FALLBACK_IMAGE,
    LOG_PATH,
    Settings,
)
from .media import TrackInfo
from .winutil import (
    clamp_to_screens,
    reassert_topmost,
    resource_path,
    virtual_geometry,
)

log = logging.getLogger(__name__)

SHADOW_MARGIN = 30
BASE_PANEL_WIDTH = 392
BASE_FONT_SIZE = 17
RADIUS = 27
STOCK_COVERS_PATH = LOG_PATH.parent / "stock-covers.json"


def _load_stock_hashes() -> set[str]:
    try:
        data = json.loads(STOCK_COVERS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return set()
    except Exception:
        log.debug("Не удалось прочитать кэш стоковых обложек", exc_info=True)
        return set()
    if not isinstance(data, list):
        return set()
    return {str(item) for item in data if isinstance(item, str)}


def _save_stock_hashes(values: set[str]) -> None:
    try:
        STOCK_COVERS_PATH.parent.mkdir(parents=True, exist_ok=True)
        ordered = sorted(values)[-512:]
        STOCK_COVERS_PATH.write_text(
            json.dumps(ordered, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except Exception:
        log.debug("Не удалось сохранить кэш стоковых обложек", exc_info=True)


def ui_font_family() -> str:
    families = set(QFontDatabase.families())
    for name in (
        "Segoe UI Variable Text",
        "Segoe UI Variable Display",
        "Segoe UI",
        "Arial",
    ):
        if name in families:
            return name
    return "Segoe UI"


MIN_BUBBLE_SCALE = 0.20
MAX_BUBBLE_SCALE = 1.60


def bubble_scale(settings: Settings) -> float:
    return max(
        MIN_BUBBLE_SCALE,
        min(MAX_BUBBLE_SCALE, float(settings.bubble_scale)),
    )


def scaled_font_size(settings: Settings) -> int:
    return max(7, int(round(int(settings.font_size) * bubble_scale(settings))))


def scaled_artist_font_size(settings: Settings) -> int:
    return max(
        6,
        int(round(int(settings.artist_font_size) * bubble_scale(settings))),
    )


def art_slot_size(settings: Settings) -> int:
    """Обложка и запасной винил занимают один и тот же слот."""
    return max(18, int(round(int(settings.cover_size) * bubble_scale(settings))))


def panel_padding(settings: Settings) -> tuple[int, int, int, int]:
    scale = bubble_scale(settings)
    return (
        max(6, int(round(18 * scale))),
        max(5, int(round(16 * scale))),
        max(7, int(round(20 * scale))),
        max(5, int(round(16 * scale))),
    )


def panel_spacing(settings: Settings) -> int:
    return max(4, int(round(14 * bubble_scale(settings))))


def panel_size(settings: Settings) -> QSize:
    scale = bubble_scale(settings)
    slot = art_slot_size(settings)
    pad_left, pad_top, pad_right, pad_bottom = panel_padding(settings)
    spacing = panel_spacing(settings)

    base_width = (
        BASE_PANEL_WIDTH
        + (int(settings.font_size) - BASE_FONT_SIZE) * 4.5
        + (int(settings.cover_size) - 64) * 0.9
    )
    base_height = max(94, int(settings.cover_size) + 34)

    width = max(
        int(round(base_width * scale)),
        pad_left + slot + spacing + int(round(150 * scale)) + pad_right,
    )
    height = max(
        int(round(base_height * scale)),
        slot + pad_top + pad_bottom,
    )
    return QSize(width, height)


def title_font(settings: Settings, family: str) -> QFont:
    font = QFont(family)
    font.setPixelSize(scaled_font_size(settings))
    font.setWeight(QFont.Weight.DemiBold)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return font


def artist_font(settings: Settings, family: str) -> QFont:
    font = QFont(family)
    font.setPixelSize(scaled_artist_font_size(settings))
    font.setWeight(QFont.Weight.Medium)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.15)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return font


def text_colors(settings: Settings) -> tuple[QColor, QColor]:
    """Белый текст для цветного стекла; тёмный — только для почти белого."""
    color = QColor(settings.bubble_color or DEFAULT_BUBBLE_COLOR)
    if not color.isValid():
        color = QColor(DEFAULT_BUBBLE_COLOR)
    luminance = (
        0.2126 * color.red() + 0.7152 * color.green() + 0.0722 * color.blue()
    ) / 255.0
    saturation = color.saturationF()
    if luminance > 0.82 and saturation < 0.35:
        return QColor(24, 26, 34, 242), QColor(58, 63, 78, 205)
    return QColor(246, 248, 255, 248), QColor(196, 203, 220, 225)


def panel_radius(size: QSize) -> float:
    """Сильное скругление: облако ближе к овалу/капсуле."""
    return max(20.0, min(46.0, size.height() * 0.46))


def cover_looks_placeholder(pixmap: QPixmap) -> bool:
    """Очень осторожно ловит однотонные заглушки вместо обложек.

    Настоящие минималистичные обложки с текстом обычно имеют много
    переходов на границах букв, поэтому не попадают под пороги.
    """
    try:
        if pixmap.isNull():
            return True
        image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGB32)
        if image.isNull():
            return True
        side = 32
        image = image.scaled(
            side,
            side,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        counts: dict[tuple[int, int, int], int] = {}
        lum = [[0.0] * side for _ in range(side)]
        for y in range(side):
            for x in range(side):
                color = image.pixelColor(x, y)
                key = (color.red() >> 4, color.green() >> 4, color.blue() >> 4)
                counts[key] = counts.get(key, 0) + 1
                lum[y][x] = (
                    0.2126 * color.red()
                    + 0.7152 * color.green()
                    + 0.0722 * color.blue()
                )
        total = side * side
        unique = len(counts)
        dominant = max(counts.values()) / total
        edges = 0.0
        for y in range(side - 1):
            for x in range(side - 1):
                edges += abs(lum[y][x + 1] - lum[y][x])
                edges += abs(lum[y + 1][x] - lum[y][x])
        edges /= 2.0 * (side - 1) * (side - 1)

        if unique <= 14 and dominant >= 0.70 and edges < 7.0:
            return True
        if unique <= 40 and dominant >= 0.50 and edges < 4.0:
            return True
        return False
    except Exception:
        return False


class ElidedLabel(QWidget):
    """QLabel, который сам рисует многоточие и не меняет размер окна."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._text = ""
        self._color = QColor(255, 255, 255)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def setText(self, text: str) -> None:  # noqa: N802
        text = text or ""
        if text == self._text:
            return
        self._text = text
        self.update()

    def text(self) -> str:
        return self._text

    def setTextColor(self, color: QColor) -> None:  # noqa: N802
        self._color = QColor(color)
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        fm = QFontMetrics(self.font())
        return QSize(80, fm.height() + 2)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, QFontMetrics(self.font()).height() + 2)

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setFont(self.font())
        rect = self.rect().adjusted(0, 0, -1, 0)
        fm = QFontMetrics(self.font())
        text = fm.elidedText(self._text, Qt.TextElideMode.ElideRight, rect.width())
        if self._color.lightness() > 128:
            shadow = QColor(0, 0, 0, 120)
        else:
            shadow = QColor(255, 255, 255, 0)
        painter.setPen(shadow)
        painter.drawText(
            rect.translated(1, 1),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            text,
        )
        painter.setPen(self._color)
        painter.drawText(
            rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            text,
        )


class CoverWidget(QWidget):
    """Слот для обложки или запасного винила с центрированной обрезкой."""

    def __init__(self, size: int = 64, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self._scaled: QPixmap | None = None
        self._scaled_key: tuple[int, int, int] | None = None
        self._side = size
        self._image_side = size
        self._circular = False
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_cover(self, pixmap: QPixmap | None) -> None:
        new = pixmap if pixmap is not None and not pixmap.isNull() else None
        if new is self._pixmap:
            return
        if (
            new is not None
            and self._pixmap is not None
            and new.cacheKey() == self._pixmap.cacheKey()
        ):
            return
        self._pixmap = new
        self._scaled = None
        self._scaled_key = None
        self.update()

    def set_side(self, size: int) -> None:
        size = max(16, int(size))
        self._side = size
        self.setFixedSize(size, size)
        self._scaled = None
        self._scaled_key = None
        self.updateGeometry()
        self.update()

    def set_image_side(self, size: int) -> None:
        size = max(16, int(size))
        if size == self._image_side:
            return
        self._image_side = size
        self._scaled = None
        self._scaled_key = None
        self.update()

    def set_circular(self, circular: bool) -> None:
        circular = bool(circular)
        if circular == self._circular:
            return
        self._circular = circular
        self.update()

    def pixmap(self) -> QPixmap | None:
        return self._pixmap

    def _drawn_side(self) -> float:
        return float(max(8, min(self._image_side, self.width(), self.height())))

    def _scaled_cover(self) -> QPixmap | None:
        if self._pixmap is None:
            return None
        dpr = max(1.0, self.devicePixelRatioF())
        side = self._drawn_side()
        target = max(1, int(round(side * dpr)))
        key = (self._pixmap.cacheKey(), target, 1 if self._circular else 0)
        if self._scaled is not None and self._scaled_key == key:
            return self._scaled
        scaled = self._pixmap.scaled(
            target,
            target,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        scaled.setDevicePixelRatio(dpr)
        self._scaled = scaled
        self._scaled_key = key
        return scaled

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
            | QPainter.RenderHint.TextAntialiasing
        )
        side = self._drawn_side()
        x = (self.width() - side) / 2.0
        y = (self.height() - side) / 2.0
        rect = QRectF(x + 0.5, y + 0.5, side - 1.0, side - 1.0)
        radius = min(16.0, rect.height() * 0.24, rect.width() * 0.24)
        path = QPainterPath()
        if self._circular:
            path.addEllipse(rect)
        else:
            path.addRoundedRect(rect, radius, radius)

        if self._pixmap is None:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 13))
            painter.drawPath(path)
            font = QFont(self.font())
            font.setPixelSize(max(14, int(side * 0.38)))
            font.setWeight(QFont.Weight.Medium)
            painter.setFont(font)
            painter.setPen(QColor(255, 255, 255, 96))
            painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), "♪")
        else:
            painter.setClipPath(path)
            scaled = self._scaled_cover()
            if scaled is not None:
                draw_x = (self.width() - scaled.width() / scaled.devicePixelRatio()) / 2.0
                draw_y = (self.height() - scaled.height() / scaled.devicePixelRatio()) / 2.0
                painter.drawPixmap(int(round(draw_x)), int(round(draw_y)), scaled)
            painter.setClipping(False)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 38 if not self._circular else 48), 1.0))
        painter.drawPath(path)


class BubblePanel(QWidget):
    """Стеклянная панель выбранного цвета: блики, преломление, грань."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._opacity = 0.9
        self._intensity = 0.78
        self._frost = 0.15
        self._refraction = 0.75
        self._radius = float(RADIUS)
        self._color = QColor(DEFAULT_BUBBLE_COLOR)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_radius(self, radius: float) -> None:
        self._radius = max(1.0, float(radius))
        self.update()

    def radius(self) -> float:
        return self._radius

    def set_opacity(self, opacity: float) -> None:
        self._opacity = max(0.0, min(1.0, float(opacity)))
        self.update()

    def set_intensity(self, intensity: float) -> None:
        self._intensity = max(0.0, min(1.0, float(intensity)))
        self.update()

    def set_frost(self, frost: float) -> None:
        self._frost = max(0.0, min(1.0, float(frost)))
        self.update()

    def set_refraction(self, refraction: float) -> None:
        self._refraction = max(0.0, min(1.0, float(refraction)))
        self.update()

    def set_color(self, color: QColor | str) -> None:
        parsed = QColor(color)
        if not parsed.isValid():
            parsed = QColor(DEFAULT_BUBBLE_COLOR)
        self._color = parsed
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        paint_liquid_glass(
            painter,
            rect,
            self._radius,
            self._color,
            self._intensity,
            self._opacity,
            self._frost,
            self._refraction,
        )


class BubbleWindow(QWidget):
    position_changed = Signal(object)  # QPoint

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._track: TrackInfo | None = None
        self._content_key: tuple | None = None
        self._content_token = 0
        self._fade_anim: QPropertyAnimation | None = None
        self._content_anim: QPropertyAnimation | None = None
        self._target_visible = False
        self._game_mode = False
        self._offscreen = False
        self._settings_open = False
        self._rest_pos = QPoint(0, 0)
        self._dragging = False
        self._drag_offset = QPoint()
        self._font_family = ui_font_family()
        self._cover_pixmap: QPixmap | None = None
        self._fallback_pixmap: QPixmap | None = None
        self._fallback_key = ""
        self._thumb_history: dict[str, set[tuple[str, str]]] = {}
        self._stock_hashes: set[str] = _load_stock_hashes()

        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setWindowTitle("Now Playing Widget")
        self.setCursor(Qt.CursorShape.OpenHandCursor)

        self._panel = BubblePanel(self)

        root = QVBoxLayout(self)
        root.setContentsMargins(SHADOW_MARGIN, SHADOW_MARGIN, SHADOW_MARGIN, SHADOW_MARGIN)
        root.setSpacing(0)
        root.addWidget(self._panel)

        self._content = QWidget(self._panel)
        self._content.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        content_layout = QHBoxLayout(self._content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(14)
        self._content_layout = content_layout

        self._cover = CoverWidget(64, self._content)
        content_layout.addWidget(self._cover, 0, Qt.AlignmentFlag.AlignVCenter)

        text_host = QWidget(self._content)
        text_host.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        text_layout = QVBoxLayout(text_host)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)
        text_layout.addStretch(1)
        self._artist = ElidedLabel(text_host)
        self._title = ElidedLabel(text_host)
        text_layout.addWidget(self._artist)
        text_layout.addWidget(self._title)
        text_layout.addStretch(1)
        content_layout.addWidget(text_host, 1)

        panel_layout = QHBoxLayout(self._panel)
        panel_layout.setContentsMargins(18, 16, 20, 16)
        panel_layout.setSpacing(0)
        panel_layout.addWidget(self._content)
        self._panel_layout = panel_layout

        self._content_effect = QGraphicsOpacityEffect(self._content)
        self._content_effect.setOpacity(1.0)
        self._content.setGraphicsEffect(self._content_effect)

        self._fade_timer = QTimer(self)
        self._fade_timer.setSingleShot(True)
        self._fade_timer.setInterval(280)
        self._fade_timer.timeout.connect(self._finish_hide_if_needed)

        self._top_timer = QTimer(self)
        self._top_timer.setInterval(3500)
        self._top_timer.timeout.connect(self._keep_on_top)

        self.apply_settings(settings)
        self.hide()

    # ------------------------------------------------------------------ #
    # Фон окна: мягкая тень рисуется только снаружи панели
    # ------------------------------------------------------------------ #

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        panel_rect = QRectF(
            SHADOW_MARGIN,
            SHADOW_MARGIN,
            self._panel.width(),
            self._panel.height(),
        )
        radius = self._panel.radius()
        opacity = max(0.0, min(1.0, float(self._settings.opacity)))
        intensity = max(0.0, min(1.0, float(self._settings.glass_intensity)))
        scale = bubble_scale(self._settings)
        offset = max(2.0, min(9.0, self._settings.font_size * 0.45 * scale))
        spread = max(8.0, (SHADOW_MARGIN - 4) * min(1.0, scale))
        layers = 22

        painter.setPen(Qt.PenStyle.NoPen)
        for index in range(layers, 0, -1):
            grow = spread * (index / layers)
            depth = 1.0 - index / layers
            alpha = int(
                (1.3 + 3.4 * depth**1.5)
                * (0.5 + 0.5 * opacity)
                * (0.8 + 0.35 * intensity)
            )
            if alpha <= 0:
                continue
            rect = panel_rect.adjusted(-grow, -grow + offset, grow, grow + offset)
            painter.setBrush(QColor(0, 0, 0, alpha))
            painter.drawRoundedRect(rect, radius + grow, radius + grow)

        # Вырезаем область панели: иначе тень просвечивает сквозь стекло
        # и превращает полупрозрачную карточку в почти чёрный прямоугольник.
        cut = QPainterPath()
        cut.addRoundedRect(panel_rect, radius, radius)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        painter.setBrush(QColor(0, 0, 0, 255))
        painter.drawPath(cut)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.end()

    # ------------------------------------------------------------------ #
    # Настройки и внешний вид
    # ------------------------------------------------------------------ #

    def apply_settings(self, settings: Settings) -> None:
        self._settings = settings

        self._title.setFont(title_font(settings, self._font_family))
        self._artist.setFont(artist_font(settings, self._font_family))
        title_color, artist_color = text_colors(settings)
        self._title.setTextColor(title_color)
        self._artist.setTextColor(artist_color)

        size = panel_size(settings)
        slot = art_slot_size(settings)
        pad_left, pad_top, pad_right, pad_bottom = panel_padding(settings)
        self._panel_layout.setContentsMargins(
            pad_left, pad_top, pad_right, pad_bottom
        )
        self._content_layout.setSpacing(panel_spacing(settings))
        self._cover.set_side(slot)
        self._panel.set_radius(panel_radius(size))
        self._panel.setFixedSize(size)
        self._panel.set_opacity(settings.opacity)
        self._panel.set_color(settings.bubble_color)
        self._panel.set_intensity(settings.glass_intensity)
        self._panel.set_frost(settings.glass_frost)
        self._panel.set_refraction(settings.glass_refraction)
        self.setFixedSize(size.width() + SHADOW_MARGIN * 2, size.height() + SHADOW_MARGIN * 2)

        self._ensure_fallback()
        self._update_art()

        if self.isVisible() and not self._offscreen:
            self._move_rest_position(self._rest_pos)
        self.update()

    def _ensure_fallback(self) -> None:
        wanted = (self._settings.fallback_image or DEFAULT_FALLBACK_IMAGE).strip()
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
        log.info(
            "Запасная картинка: %s (%s)",
            candidate,
            "загружена" if self._fallback_pixmap is not None else "не найдена",
        )

    def _update_art(self) -> None:
        side = art_slot_size(self._settings)
        if self._cover_pixmap is not None:
            self._cover.set_circular(False)
            self._cover.set_image_side(side)
            self._cover.set_cover(self._cover_pixmap)
        else:
            self._cover.set_circular(True)
            self._cover.set_image_side(side)
            self._cover.set_cover(self._fallback_pixmap)

    # ------------------------------------------------------------------ #
    # Трек и анимация содержимого
    # ------------------------------------------------------------------ #

    def set_track(self, track: TrackInfo) -> None:
        new_key = (track.title, track.artist, track.album, track.thumb_hash)
        content_changed = new_key != self._content_key
        self._track = track
        if not content_changed:
            return

        self._content_key = new_key
        if not self.isVisible():
            self._apply_content(track)
            self._content_effect.setOpacity(1.0)
            return
        self._crossfade(track)

    def _crossfade(self, track: TrackInfo) -> None:
        self._content_token += 1
        token = self._content_token
        if self._content_anim is not None:
            self._content_anim.stop()

        # Если содержимое ещё проявляется после появления окна — просто обновляем.
        current = self._content_effect.opacity()
        if current < 0.985:
            self._apply_content(track)
            self._content_effect.setOpacity(1.0)
            return

        anim = QPropertyAnimation(self._content_effect, b"opacity", self)
        anim.setDuration(110)
        anim.setStartValue(current)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(lambda: self._content_midpoint(token, track))
        self._content_anim = anim
        anim.start()

    def _content_midpoint(self, token: int, track: TrackInfo) -> None:
        if token != self._content_token:
            return
        self._apply_content(track)
        anim = QPropertyAnimation(self._content_effect, b"opacity", self)
        anim.setDuration(220)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(lambda: self._content_finished(token))
        self._content_anim = anim
        anim.start()

    def _content_finished(self, token: int) -> None:
        if token == self._content_token:
            self._content_effect.setOpacity(1.0)

    def _apply_content(self, track: TrackInfo) -> None:
        self._title.setText(track.display_title)
        self._artist.setText(track.artist)
        self._artist.setVisible(bool(track.artist))

        pixmap = QPixmap()
        loaded = bool(track.thumbnail) and pixmap.loadFromData(track.thumbnail or b"")
        if loaded and not pixmap.isNull():
            if self._is_stock_thumbnail(pixmap, track):
                self._cover_pixmap = None
            else:
                self._cover_pixmap = pixmap
        else:
            self._cover_pixmap = None

        self._update_art()

    def _is_stock_thumbnail(self, pixmap: QPixmap, track: TrackInfo) -> bool:
        """Отличает обложку трека от заглушки плеера."""
        if looks_like_source_icon(
            pixmap, track.source
        ) or looks_like_browser_icon(pixmap):
            log.debug("Логотип плеера заменён винилом (%s)", track.source)
            return True

        hash_key = bytes(track.thumb_hash).hex()
        if hash_key:
            owner = (
                track.artist.strip().casefold(),
                (track.album.strip() or track.title.strip()).casefold(),
            )
            owners = self._thumb_history.setdefault(hash_key, set())
            owners.add(owner)
            if len(owners) >= 2 and hash_key not in self._stock_hashes:
                # Одна и та же картинка у разных исполнителей/альбомов —
                # это точно стоковая заглушка, а не обложка альбома.
                self._stock_hashes.add(hash_key)
                _save_stock_hashes(self._stock_hashes)
                log.info("Стоковая обложка плеера заменена винилом")
            if hash_key in self._stock_hashes:
                return True
            if len(self._thumb_history) > 256:
                self._thumb_history.clear()

        return cover_looks_placeholder(pixmap)

    # ------------------------------------------------------------------ #
    # Появление/исчезновение
    # ------------------------------------------------------------------ #

    def show_bubble(self, animate: bool = True) -> None:
        self._target_visible = True
        self._fade_timer.stop()
        if self._content_effect.opacity() < 0.999:
            self._content_effect.setOpacity(1.0)
        if self._offscreen or self._game_mode:
            self._move_offscreen()
        else:
            self._move_rest_position(self._rest_pos)

        was_visible = self.isVisible()
        if not was_visible:
            log.info(
                "Показ облачка: %s,%s%s",
                self.x(),
                self.y(),
                " (за экраном)" if self._offscreen else "",
            )
            self.setWindowOpacity(0.0)
            self.show()
            self.raise_()
        else:
            self.raise_()

        if animate:
            self._animate_opacity(1.0, 260)
        else:
            if self._fade_anim is not None:
                self._fade_anim.stop()
            self.setWindowOpacity(1.0)
        if not self._game_mode:
            self._keep_on_top()
            if not self._settings_open:
                self._top_timer.start()

    def set_settings_open(self, opened: bool) -> None:
        """Пока открыто окно настроек, не перекрываем его облачком."""
        self._settings_open = bool(opened)
        if self._settings_open:
            self._top_timer.stop()
        elif self.isVisible() and not self._game_mode:
            self._keep_on_top()
            self._top_timer.start()

    def _keep_on_top(self) -> None:
        if (
            not self.isVisible()
            or self._game_mode
            or self._offscreen
            or self._settings_open
        ):
            return
        try:
            reassert_topmost(int(self.winId()))
        except Exception:
            pass

    def hide_bubble(self, animate: bool = True) -> None:
        self._target_visible = False
        self._fade_timer.stop()
        self._top_timer.stop()
        if not self.isVisible():
            self.hide()
            return
        if animate:
            self._animate_opacity(0.0, 240)
            self._fade_timer.start()
        else:
            if self._fade_anim is not None:
                self._fade_anim.stop()
            self.hide()
            self.setWindowOpacity(1.0)

    def hide_immediately(self) -> None:
        self._target_visible = False
        self._fade_timer.stop()
        self._top_timer.stop()
        if self._fade_anim is not None:
            self._fade_anim.stop()
        if self._content_anim is not None:
            self._content_anim.stop()
        self._content_effect.setOpacity(1.0)
        self.hide()
        self.setWindowOpacity(1.0)

    def _animate_opacity(self, target: float, duration: int) -> None:
        if self._fade_anim is not None:
            self._fade_anim.stop()
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(duration)
        anim.setStartValue(self.windowOpacity())
        anim.setEndValue(target)
        anim.setEasingCurve(
            QEasingCurve.Type.OutCubic if target > 0.5 else QEasingCurve.Type.InCubic
        )
        anim.finished.connect(self._finish_hide_if_needed)
        self._fade_anim = anim
        anim.start()

    def _finish_hide_if_needed(self) -> None:
        if not self._target_visible:
            self._content_effect.setOpacity(1.0)
            self.hide()
            self.setWindowOpacity(1.0)
            self._top_timer.stop()

    # ------------------------------------------------------------------ #
    # Игровой режим: увести за пределы рабочего стола, оставив окно живым
    # ------------------------------------------------------------------ #

    def set_game_mode(self, active: bool) -> None:
        active = bool(active)
        if active == self._game_mode:
            return
        self._game_mode = active
        if active:
            self._top_timer.stop()
            if not self._offscreen:
                if self.isVisible():
                    self._rest_pos = QPoint(self.x(), self.y())
                self._move_offscreen()
        else:
            self._offscreen = False
            if self.isVisible():
                self._move_rest_position(self._rest_pos)
                self._keep_on_top()
                if not self._game_mode:
                    self._top_timer.start()

    @property
    def game_mode(self) -> bool:
        return self._game_mode

    def _move_offscreen(self) -> None:
        if self.isVisible() and not self._offscreen:
            self._rest_pos = QPoint(self.x(), self.y())
        self._offscreen = True
        virtual = virtual_geometry()
        x = virtual.left() - self.width() - 320
        y = virtual.top() + 40
        self.move(x, y)

    def rest_position(self) -> QPoint:
        if self._offscreen:
            return QPoint(self._rest_pos)
        return QPoint(self.x(), self.y())

    def cover_pixmap(self) -> QPixmap | None:
        return self._cover_pixmap

    def set_rest_position(self, point: QPoint) -> None:
        self._rest_pos = QPoint(point)
        if not self._offscreen and not self._game_mode:
            self._move_rest_position(self._rest_pos)

    def _move_rest_position(self, point: QPoint) -> None:
        rect = QRect(point, self.size())
        clamped = clamp_to_screens(rect, min_visible=36)
        self._rest_pos = clamped.topLeft()
        self.move(self._rest_pos)

    # ------------------------------------------------------------------ #
    # Перетаскивание
    # ------------------------------------------------------------------ #

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if (
            self._game_mode
            or event.button() != Qt.MouseButton.LeftButton
        ):
            return super().mousePressEvent(event)
        self._dragging = True
        self._drag_offset = (
            event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        )
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._dragging and event.buttons() & Qt.MouseButton.LeftButton:
            new_pos = event.globalPosition().toPoint() - self._drag_offset
            self._rest_pos = new_pos
            self.move(new_pos)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._dragging and event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            rect = QRect(QPoint(self.x(), self.y()), self.size())
            clamped = clamp_to_screens(rect, min_visible=36)
            self._rest_pos = clamped.topLeft()
            self.move(self._rest_pos)
            self.position_changed.emit(QPoint(self._rest_pos))
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        # Окно не должно закрываться само; выход делает приложение.
        event.ignore()



