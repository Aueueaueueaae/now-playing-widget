"""Проверка игрового режима: окно остаётся видимым, но уезжает за экран."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QPoint, QTimer
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nowplaying.bubble import BubbleWindow  # noqa: E402
from nowplaying.config import Settings  # noqa: E402
from nowplaying.media import TrackInfo  # noqa: E402
from nowplaying.winutil import virtual_geometry  # noqa: E402

THUMB = ROOT / "assets" / "icon.png"


def main() -> int:
    app = QApplication(sys.argv)
    data = THUMB.read_bytes() if THUMB.exists() else None
    track = TrackInfo(
        has_media=True,
        title="Game mode test",
        artist="Now Playing Widget",
        thumbnail=data,
        thumb_hash=b"game-test",
        is_playing=True,
    )

    bubble = BubbleWindow(Settings(font_size=17, opacity=0.9))
    bubble.set_track(track)
    bubble.set_rest_position(QPoint(120, 120))
    bubble.show_bubble(animate=False)

    failures: list[str] = []

    def step_out() -> None:
        bubble.set_game_mode(True)
        virt = virtual_geometry()
        print("offscreen:", bubble.isVisible(), bubble.x(), bubble.y(), "virtual:", virt)
        if not bubble.isVisible():
            failures.append("окно скрылось вместо переноса за экран")
        if bubble.x() > virt.left() - bubble.width():
            failures.append("окно не ушло за левую границу виртуального стола")
        if bubble.rest_position() != QPoint(120, 120):
            failures.append(f"потеряна позиция покоя: {bubble.rest_position()}")

    def step_back() -> None:
        bubble.set_game_mode(False)
        print("restored:", bubble.isVisible(), bubble.x(), bubble.y())
        if not bubble.isVisible():
            failures.append("окно не вернулось после игрового режима")
        if QPoint(bubble.x(), bubble.y()) != QPoint(120, 120):
            failures.append(f"вернулось не туда: {bubble.x()},{bubble.y()}")
        bubble.hide_immediately()
        app.exit(1 if failures else 0)

    QTimer.singleShot(350, step_out)
    QTimer.singleShot(900, step_back)
    code = app.exec()
    for failure in failures:
        print("FAIL:", failure)
    if not failures:
        print("OK: игровой режим корректен")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
