"""Пересобирает assets/icon.png и assets/icon.ico из векторного рисунка."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QGuiApplication  # noqa: E402

from nowplaying.icon import render_icon, save_png  # noqa: E402


def main() -> int:
    app = QGuiApplication(sys.argv)  # noqa: F841
    assets = ROOT / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    save_png(assets / "icon.png", 256)

    try:
        from PIL import Image
    except ImportError:
        print("Pillow не установлен — ICO не создан (PNG готов).")
        return 0

    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    with tempfile.TemporaryDirectory() as tmp:
        paths = []
        for size in sizes:
            path = Path(tmp) / f"icon-{size}.png"
            render_icon(size).save(str(path), "PNG")
            paths.append(path)
        images = [Image.open(p).convert("RGBA") for p in paths]
        largest = images[-1]
        largest.save(
            assets / "icon.ico",
            format="ICO",
            sizes=[(s, s) for s in sizes],
        )
    print(f"Готово: {assets / 'icon.png'} и {assets / 'icon.ico'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
