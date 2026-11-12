"""Быстрый визуальный тест компактного окна настроек."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from nowplaying.config import Settings  # noqa: E402
from nowplaying.settings_dialog import SettingsDialog  # noqa: E402

OUT = ROOT / "tools" / "out"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> int:
    app = QApplication(sys.argv)
    dialog = SettingsDialog(Settings())
    dialog.show()

    def first_shot() -> None:
        dialog.grab().save(str(OUT / "settings_compact_default.png"))

        dialog._title_slider.setValue(24)
        dialog._artist_slider.setValue(16)
        dialog._cover_slider.setValue(112)
        dialog._scale_slider.setValue(125)
        dialog._set_color("#e9e4da")
        dialog._preview_timer.stop()
        dialog._emit_preview()
        QTimer.singleShot(220, custom_shot)

    def custom_shot() -> None:
        dialog.grab().save(str(OUT / "settings_compact_custom.png"))
        dialog._set_color("#123044")
        dialog._title_slider.setValue(18)
        dialog._artist_slider.setValue(12)
        dialog._cover_slider.setValue(84)
        dialog._scale_slider.setValue(100)
        dialog._set_advanced_open(True)
        dialog._preview_timer.stop()
        dialog._emit_preview()
        QTimer.singleShot(260, advanced_shot)

    def advanced_shot() -> None:
        dialog.grab().save(str(OUT / "settings_compact_advanced.png"))
        settings = dialog.result_settings()
        print("dialog:", dialog.width(), dialog.height())
        print("artist/title:", settings.artist_font_size, settings.font_size)
        print("cover/scale:", settings.cover_size, settings.bubble_scale)
        print("color:", settings.bubble_color)
        dialog.reject()
        app.quit()

    QTimer.singleShot(700, first_shot)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
