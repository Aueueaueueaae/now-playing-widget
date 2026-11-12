"""Иконки плееров: помогают отличить обложку от логотипа приложения."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from PySide6.QtCore import QFileInfo, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QFileIconProvider

log = logging.getLogger(__name__)

# Источник SMTC -> имена исполняемых файлов.
_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("chrome", ("chrome.exe",)),
    ("chromium", ("chrome.exe",)),
    ("edge", ("msedge.exe",)),
    ("firefox", ("firefox.exe",)),
    ("opera", ("opera.exe",)),
    ("yandex", ("browser.exe",)),
    ("brave", ("brave.exe",)),
    ("vivaldi", ("vivaldi.exe",)),
)

_COMMON_PATHS: dict[str, tuple[str, ...]] = {
    "chrome.exe": (
        r"Google\Chrome\Application\chrome.exe",
        r"Google\Chrome Beta\Application\chrome.exe",
    ),
    "msedge.exe": (r"Microsoft\Edge\Application\msedge.exe",),
    "firefox.exe": (r"Mozilla Firefox\firefox.exe",),
    "opera.exe": (r"Programs\Opera\opera.exe", r"Opera\opera.exe"),
    "browser.exe": (
        r"Yandex\YandexBrowser\Application\browser.exe",
    ),
    "brave.exe": (
        r"BraveSoftware\Brave-Browser\Application\brave.exe",
    ),
    "vivaldi.exe": (r"Vivaldi\Application\vivaldi.exe",),
}

_icon_cache: dict[str, QPixmap | None] = {}
_hue_cache: dict[int, tuple[list[int], int]] = {}
_provider: QFileIconProvider | None = None


def _registry_paths(exe_name: str) -> list[Path]:
    paths: list[Path] = []
    try:
        import winreg
    except Exception:
        return paths
    key_path = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe_name}"
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(
                    root, key_path, 0, winreg.KEY_READ | view
                ) as key:
                    value, _ = winreg.QueryValueEx(key, "")
                    text = str(value).strip().strip('"')
                    if text:
                        paths.append(Path(text))
            except OSError:
                continue
    return paths


def _common_paths(exe_name: str) -> list[Path]:
    roots = (
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramFiles(x86)"),
        os.environ.get("LOCALAPPDATA"),
    )
    paths: list[Path] = []
    for root in roots:
        if not root:
            continue
        for relative in _COMMON_PATHS.get(exe_name, ()):
            paths.append(Path(root) / relative)
    return paths


def _exe_names(source: str) -> tuple[str, ...]:
    text = (source or "").strip().casefold()
    if not text:
        return ()
    if text.endswith(".exe"):
        return (Path(text).name.casefold(),)
    for token, names in _ALIASES:
        if token in text:
            return names
    return ()


def _icon_for_exe(exe_name: str) -> QPixmap | None:
    global _provider
    key = exe_name.casefold()
    if key in _icon_cache:
        return _icon_cache[key]

    exe = None
    for candidate in (
        *_registry_paths(key),
        *_common_paths(key),
    ):
        try:
            if candidate.is_file():
                exe = candidate
                break
        except OSError:
            continue
    if exe is None:
        _icon_cache[key] = None
        return None

    try:
        if _provider is None:
            _provider = QFileIconProvider()
        icon = _provider.icon(QFileInfo(str(exe)))
        pixmap = icon.pixmap(128, 128)
        result = pixmap if not pixmap.isNull() else None
    except Exception:
        log.debug("Не удалось получить иконку %s", exe, exc_info=True)
        result = None
    _icon_cache[key] = result
    return result


def source_icon(source: str) -> QPixmap | None:
    """Иконка приложения-источника, если её удалось найти."""
    for exe_name in _exe_names(source):
        icon = _icon_for_exe(exe_name)
        if icon is not None:
            return icon
    return None


def _is_colored(color) -> bool:
    return (
        color.alpha() > 80
        and color.saturation() > 90
        and color.value() > 60
    )


def _hue_map(pixmap: QPixmap, side: int = 12) -> tuple[list[int], int]:
    cache_key = pixmap.cacheKey()
    cached = _hue_cache.get(cache_key)
    if cached is not None:
        return cached
    # Сначала приводим картинку к 48x48 и обрезаем по цветному содержимому:
    # так логотип с большими полями сравнивается с иконкой без полей.
    work = (
        pixmap.toImage()
        .convertToFormat(QImage.Format.Format_RGBA8888)
        .scaled(
            48,
            48,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    )
    min_x = min_y = 48
    max_x = max_y = -1
    for y in range(48):
        for x in range(48):
            if _is_colored(work.pixelColor(x, y)):
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)

    if max_x >= min_x and max_y >= min_y:
        width = max_x - min_x + 1
        height = max_y - min_y + 1
        side_len = max(width, height) * 1.15
        center_x = (min_x + max_x) / 2.0
        center_y = (min_y + max_y) / 2.0
        left = int(round(center_x - side_len / 2.0))
        top = int(round(center_y - side_len / 2.0))
        crop_w = max(1, min(48 - max(0, left), int(round(side_len))))
        crop_h = max(1, min(48 - max(0, top), int(round(side_len))))
        work = work.copy(max(0, left), max(0, top), crop_w, crop_h)

    work = work.scaled(
        side,
        side,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    buckets: list[int] = []
    colored = 0
    for y in range(side):
        for x in range(side):
            color = work.pixelColor(x, y)
            if _is_colored(color):
                buckets.append(min(5, int(color.hue() / 60)))
                colored += 1
            else:
                buckets.append(-1)
    if len(_hue_cache) > 64:
        _hue_cache.clear()
    _hue_cache[cache_key] = (buckets, colored)
    return buckets, colored


def _same_layout(pixmap: QPixmap, icon: QPixmap) -> bool:
    try:
        cover_map, cover_colored = _hue_map(pixmap)
        icon_map, icon_colored = _hue_map(icon)
    except Exception:
        log.debug("Не удалось сравнить обложку с иконкой плеера", exc_info=True)
        return False

    if min(cover_colored, icon_colored) < 24:
        return False

    both = same = 0
    for cover_bucket, icon_bucket in zip(cover_map, icon_map):
        if cover_bucket >= 0 and icon_bucket >= 0:
            both += 1
            if cover_bucket == icon_bucket:
                same += 1
    if both < 24:
        return False

    similarity = same / both
    coverage_delta = abs(cover_colored - icon_colored) / max(
        cover_colored, icon_colored
    )
    return similarity >= 0.72 and coverage_delta <= 0.55


def looks_like_source_icon(pixmap: QPixmap, source: str) -> bool:
    """Похожа ли картинка на логотип самого плеера (Chrome, Edge и т. п.)."""
    icon = source_icon(source)
    return icon is not None and _same_layout(pixmap, icon)


def looks_like_browser_icon(pixmap: QPixmap) -> bool:
    """Страховка, если AUMID источника не распознан, а логотип — браузерный."""
    seen: set[str] = set()
    for _token, names in _ALIASES:
        for exe_name in names:
            if exe_name in seen:
                continue
            seen.add(exe_name)
            icon = _icon_for_exe(exe_name)
            if icon is not None and _same_layout(pixmap, icon):
                return True
    return False
