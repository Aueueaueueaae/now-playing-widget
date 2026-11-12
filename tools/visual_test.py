"""Визуальный тест стекла, цветов, размеров и запасного винила."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import (
    QBuffer,
    QByteArray,
    QIODevice,
    QPoint,
    QTimer,
    Qt,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import QApplication, QWidget

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nowplaying.bubble import BubbleWindow  # noqa: E402
from nowplaying.config import Settings  # noqa: E402
from nowplaying.media import TrackInfo  # noqa: E402

OUT = ROOT / "tools" / "out"
OUT.mkdir(parents=True, exist_ok=True)


class Backdrop(QWidget):
    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setGeometry(0, 0, 1080, 760)

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        gradient = QLinearGradient(0, 0, 1080, 760)
        gradient.setColorAt(0, QColor("#f6d365"))
        gradient.setColorAt(0.45, QColor("#fda085"))
        gradient.setColorAt(1, QColor("#5ee7df"))
        painter.fillRect(self.rect(), gradient)
        for cx, cy, radius, color in (
            (200, 150, 120, "#ff5f6d"),
            (820, 120, 150, "#4facfe"),
            (450, 620, 180, "#43e97b"),
            (950, 480, 100, "#fa709a"),
        ):
            radial = QRadialGradient(cx, cy, radius)
            colored = QColor(color)
            colored.setAlpha(220)
            radial.setColorAt(0, colored)
            radial.setColorAt(1, QColor(255, 255, 255, 0))
            painter.setBrush(radial)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPoint(cx, cy), radius, radius)
        painter.setPen(QColor(30, 30, 30, 170))
        for i in range(19):
            painter.drawText(
                20,
                30 + i * 40,
                "GLASS BLUR TEST ABCDEFGHIJKLMNOPQRSTUVWXYZ 0123456789",
            )


def make_cover_bytes() -> bytes:
    pixmap = QPixmap(400, 400)
    painter = QPainter(pixmap)
    gradient = QLinearGradient(0, 0, 400, 400)
    gradient.setColorAt(0.0, QColor("#f857a6"))
    gradient.setColorAt(0.5, QColor("#5865f2"))
    gradient.setColorAt(1.0, QColor("#31e6c9"))
    painter.fillRect(pixmap.rect(), gradient)
    painter.setPen(QColor(255, 255, 255, 220))
    font = QFont("Segoe UI")
    font.setPixelSize(58)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(
        pixmap.rect(),
        int(Qt.AlignmentFlag.AlignCenter),
        "ALBUM",
    )
    painter.end()
    buffer = QBuffer()
    data = QByteArray()
    buffer.setBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    pixmap.save(buffer, "PNG")
    buffer.close()
    return bytes(data)


def main() -> int:
    app = QApplication(sys.argv)
    backdrop = Backdrop()
    backdrop.show()
    backdrop.raise_()
    backdrop.activateWindow()

    data = make_cover_bytes()
    cover_track = TrackInfo(
        has_media=True,
        title="Midnight Drive (Extended Mix) — A Very Long Track Title That Must Be Elided",
        artist="Test Artist With A Rather Long Name",
        album="Album",
        thumbnail=data,
        thumb_hash=b"cover-test",
        is_playing=True,
    )
    no_cover_track = TrackInfo(
        has_media=True,
        title="Трек без обложки",
        artist="Неизвестный исполнитель",
        album="",
        thumbnail=b"",
        thumb_hash=b"",
        is_playing=True,
    )

    cases = (
        (Settings(), cover_track, 20),
        (
            Settings(
                bubble_color="#e9e4da",
                glass_intensity=1.0,
                opacity=0.86,
                font_size=22,
                artist_font_size=15,
                cover_size=112,
            ),
            cover_track,
            240,
        ),
        (
            Settings(
                bubble_color="#123044",
                glass_intensity=0.95,
                font_size=19,
                artist_font_size=13,
                cover_size=104,
            ),
            no_cover_track,
            470,
        ),
    )

    bubbles = []
    for settings, track, y in cases:
        bubble = BubbleWindow(settings)
        bubble.set_track(track)
        bubble.set_rest_position(QPoint(50, y))
        bubble.show_bubble(animate=False)
        bubbles.append(bubble)

    for bubble in bubbles:
        bubble.raise_()

    def shot() -> None:
        for index, bubble in enumerate(bubbles):
            print(
                "bubble",
                index,
                bubble.isVisible(),
                bubble.geometry().getRect(),
                bubble.windowOpacity(),
                bubble._cover_pixmap is not None,
            )
            bubble.grab().save(str(OUT / f"bubble-{index}.png"))
        screen = app.primaryScreen()
        image = screen.grabWindow(0, 0, 0, 1080, 760)
        image.save(str(OUT / "glass-test.png"))
        for bubble in bubbles:
            bubble.hide_immediately()
        backdrop.hide()
        app.exit(0)

    QTimer.singleShot(1800, shot)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
