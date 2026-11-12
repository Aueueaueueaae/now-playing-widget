"""Интеграционный тест: контроллер + окно настроек + сохранение JSON."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="npw-test-"))
os.environ["APPDATA"] = str(TMP / "Roaming")
os.environ["LOCALAPPDATA"] = str(TMP / "Local")

sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from nowplaying.app import ApplicationController  # noqa: E402
from nowplaying.bubble import panel_size  # noqa: E402
from nowplaying.config import SETTINGS_PATH  # noqa: E402
from nowplaying.settings_dialog import SettingsDialog  # noqa: E402

SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
SETTINGS_PATH.write_text(
    json.dumps({"hotkey": "Ctrl+Alt+Shift+F11"}, ensure_ascii=False),
    encoding="utf-8",
)

app = QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)
controller = ApplicationController(app)

saved: dict = {}


def open_first() -> None:
    QTimer.singleShot(0, controller.open_settings_dialog)
    QTimer.singleShot(900, edit_first)


def edit_first() -> None:
    dialog = QApplication.activeModalWidget()
    assert isinstance(dialog, SettingsDialog), type(dialog)
    dialog._title_slider.setValue(22)
    dialog._artist_slider.setValue(15)
    dialog._cover_slider.setValue(100)
    dialog._scale_slider.setValue(120)
    dialog._set_color("#e9e4da")
    dialog._glass_slider.setValue(95)
    dialog._frost_slider.setValue(40)
    dialog._refraction_slider.setValue(90)
    dialog._opacity_slider.setValue(80)
    dialog._fallback_edit.setText(str(ROOT / "assets" / "vinyl-record.png"))
    dialog._preview_timer.stop()
    dialog._emit_preview()
    QTimer.singleShot(300, dialog._on_save)


def verify_saved() -> None:
    data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8-sig"))
    assert data["font_size"] == 22, data
    assert data["artist_font_size"] == 15, data
    assert data["cover_size"] == 100, data
    assert data["bubble_scale"] == 1.2, data
    assert data["bubble_color"] == "#e9e4da", data
    assert data["glass_intensity"] == 0.95, data
    assert data["glass_frost"] == 0.4, data
    assert data["glass_refraction"] == 0.9, data
    assert data["opacity"] == 0.8, data
    assert data["fallback_image"].endswith("vinyl-record.png"), data
    assert controller._bubble.width() == panel_size(controller._settings).width() + 60
    saved.update(data)
    print(
        "save OK:",
        {
            k: data[k]
            for k in ("font_size", "bubble_color", "cover_size", "bubble_scale")
        },
    )
    QTimer.singleShot(0, controller.open_settings_dialog)
    QTimer.singleShot(900, edit_cancel)


def edit_cancel() -> None:
    dialog = QApplication.activeModalWidget()
    assert isinstance(dialog, SettingsDialog), type(dialog)
    dialog._set_color("#ff0000")
    dialog._title_slider.setValue(12)
    dialog._scale_slider.setValue(150)
    dialog._frost_slider.setValue(100)
    dialog._refraction_slider.setValue(10)
    dialog._preview_timer.stop()
    dialog._emit_preview()
    QTimer.singleShot(300, dialog.reject)


def verify_cancel() -> None:
    data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8-sig"))
    assert data["bubble_color"] == saved["bubble_color"], data
    assert data["font_size"] == saved["font_size"], data
    assert data["bubble_scale"] == saved["bubble_scale"], data
    assert data["glass_frost"] == saved["glass_frost"], data
    assert data["glass_refraction"] == saved["glass_refraction"], data
    assert controller._settings.bubble_color == saved["bubble_color"]
    assert controller._settings.bubble_scale == saved["bubble_scale"]
    assert controller._bubble._settings.bubble_color == saved["bubble_color"]
    assert controller._bubble._settings.bubble_scale == saved["bubble_scale"]
    print("cancel OK: настройки и облачко восстановлены")
    controller.shutdown()
    app.quit()


QTimer.singleShot(700, open_first)
QTimer.singleShot(3200, verify_saved)
QTimer.singleShot(5200, verify_cancel)
QTimer.singleShot(9000, lambda: (print("TIMEOUT"), app.quit()))

code = app.exec()
print("exit", code)
raise SystemExit(code)
