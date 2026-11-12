"""Небольшие обёртки над Win32, которые нужны виджету."""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QAbstractNativeEventFilter, QByteArray, QRect
from PySide6.QtGui import QGuiApplication, QScreen
from PySide6.QtWidgets import QApplication

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"


def resource_path(relative: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    candidate = base / relative
    if candidate.exists():
        return candidate
    # В exe относительный путь может указывать на файл рядом с программой,
    # например свою картинку для треков без обложки.
    if getattr(sys, "frozen", False):
        beside = Path(sys.executable).resolve().parent / relative
        if beside.exists():
            return beside
    return candidate


# --------------------------------------------------------------------------- #
# Topmost
# --------------------------------------------------------------------------- #

def reassert_topmost(hwnd: int) -> None:
    """Поднимает окно над другими topmost-окнами, не забирая фокус."""
    if not IS_WINDOWS:
        return
    try:
        HWND_TOPMOST = wintypes.HWND(-1)
        SWP_NOSIZE = 0x0001
        SWP_NOMOVE = 0x0002
        SWP_NOACTIVATE = 0x0010
        ctypes.windll.user32.SetWindowPos(
            wintypes.HWND(hwnd),
            HWND_TOPMOST,
            0,
            0,
            0,
            0,
            SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE,
        )
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Один экземпляр приложения
# --------------------------------------------------------------------------- #

_MUTEX_HANDLE: int | None = None


def acquire_single_instance() -> bool:
    global _MUTEX_HANDLE
    if not IS_WINDOWS:
        return True
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        handle = kernel32.CreateMutexW(None, False, "Local\\NowPlayingWidget.SingleInstance")
        if not handle:
            return True
        if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            kernel32.CloseHandle(handle)
            return False
        _MUTEX_HANDLE = int(handle)
        return True
    except Exception:
        log.exception("Не удалось создать мьютекс")
        return True


def release_single_instance() -> None:
    global _MUTEX_HANDLE
    if _MUTEX_HANDLE and IS_WINDOWS:
        try:
            ctypes.windll.kernel32.CloseHandle(_MUTEX_HANDLE)
        except Exception:
            pass
    _MUTEX_HANDLE = None


# --------------------------------------------------------------------------- #
# Глобальная горячая клавиша
# --------------------------------------------------------------------------- #

if IS_WINDOWS:
    WM_HOTKEY = 0x0312
    MOD_ALT = 0x0001
    MOD_CONTROL = 0x0002
    MOD_SHIFT = 0x0004
    MOD_WIN = 0x0008
    MOD_NOREPEAT = 0x4000

    _VK_NAMES: dict[str, int] = {
        "backspace": 0x08,
        "tab": 0x09,
        "enter": 0x0D,
        "return": 0x0D,
        "pause": 0x13,
        "capslock": 0x14,
        "esc": 0x1B,
        "escape": 0x1B,
        "space": 0x20,
        "pageup": 0x21,
        "pagedown": 0x22,
        "end": 0x23,
        "home": 0x24,
        "left": 0x25,
        "up": 0x26,
        "right": 0x27,
        "down": 0x28,
        "printscreen": 0x2C,
        "insert": 0x2D,
        "delete": 0x2E,
        "num0": 0x60,
        "num1": 0x61,
        "num2": 0x62,
        "num3": 0x63,
        "num4": 0x64,
        "num5": 0x65,
        "num6": 0x66,
        "num7": 0x67,
        "num8": 0x68,
        "num9": 0x69,
        "num*": 0x6A,
        "num+": 0x6B,
        "num-": 0x6D,
        "num.": 0x6E,
        "num/": 0x6F,
    }
    for _i in range(1, 25):
        _VK_NAMES[f"f{_i}"] = 0x6F + _i


def parse_hotkey(text: str) -> tuple[int, int] | None:
    """'Ctrl+Alt+M' -> (MOD_CONTROL|MOD_ALT, VK_M)."""
    if not IS_WINDOWS or not text:
        return None
    parts = [p.strip().lower() for p in text.split("+") if p.strip()]
    if not parts:
        return None
    mods = 0
    key = ""
    for part in parts:
        if part in {"ctrl", "control"}:
            mods |= MOD_CONTROL
        elif part in {"alt", "option"}:
            mods |= MOD_ALT
        elif part == "shift":
            mods |= MOD_SHIFT
        elif part in {"win", "windows", "cmd", "meta", "super"}:
            mods |= MOD_WIN
        else:
            key = part

    if not key:
        return None
    if len(key) == 1 and ("a" <= key <= "z" or "0" <= key <= "9"):
        vk = ord(key.upper())
    elif len(key) == 1 and ("а" <= key <= "я" or "ё" == key):
        # RegisterHotKey работает с виртуальными клавишами, а не с буквами.
        # Для кириллицы используем соответствующую латинскую раскладку.
        mapping = {
            "й": "Q", "ц": "W", "у": "E", "к": "R", "е": "T", "н": "Y", "г": "U",
            "ш": "I", "щ": "O", "з": "P", "х": "[", "ъ": "]", "ф": "A", "ы": "S",
            "в": "D", "а": "F", "п": "G", "р": "H", "о": "J", "л": "K", "д": "L",
            "ж": ";", "э": "'", "я": "Z", "ч": "X", "с": "C", "м": "V", "и": "B",
            "т": "N", "ь": "M", "б": ",", "ю": ".", "ё": "`",
        }
        latin = mapping.get(key)
        if not latin:
            return None
        vk = ord(latin)
    elif key in _VK_NAMES:
        vk = _VK_NAMES[key]
    else:
        return None
    return mods, vk


class HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, callback: Callable[[], None]) -> None:
        super().__init__()
        self.callback = callback
        self._id = 0x4E50
        self._registered = False
        self._last_text = ""

    def register(self, text: str) -> bool:
        if not IS_WINDOWS:
            return False
        self.unregister()
        parsed = parse_hotkey(text)
        if parsed is None:
            log.warning("Не удалось разобрать горячую клавишу: %r", text)
            return False
        mods, vk = parsed
        try:
            ok = bool(
                ctypes.windll.user32.RegisterHotKey(
                    None, self._id, mods | MOD_NOREPEAT, vk
                )
            )
        except Exception:
            log.exception("Ошибка RegisterHotKey")
            ok = False
        self._registered = ok
        self._last_text = text
        if not ok:
            log.warning("Горячая клавиша %s уже занята или не поддерживается", text)
        return ok

    def unregister(self) -> None:
        if not IS_WINDOWS or not self._registered:
            return
        try:
            ctypes.windll.user32.UnregisterHotKey(None, self._id)
        except Exception:
            pass
        self._registered = False

    def nativeEventFilter(self, eventType: QByteArray, message: int):  # noqa: N802
        if not IS_WINDOWS:
            return False, 0
        try:
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and int(msg.wParam) == self._id:
                self.callback()
                return True, 0
        except Exception:
            pass
        return False, 0


# --------------------------------------------------------------------------- #
# Геометрия экранов
# --------------------------------------------------------------------------- #

def virtual_geometry() -> QRect:
    screens = QGuiApplication.screens()
    if not screens:
        return QRect(0, 0, 1920, 1080)
    rect = QRect(screens[0].geometry())
    for screen in screens[1:]:
        rect = rect.united(screen.geometry())
    return rect


def screen_by_name(name: str) -> QScreen | None:
    if not name:
        return None
    for screen in QGuiApplication.screens():
        if screen.name() == name:
            return screen
    return None


def nearest_screen(point) -> QScreen | None:
    screens = QGuiApplication.screens()
    if not screens:
        return None
    for screen in screens:
        if screen.geometry().contains(point):
            return screen

    def distance(screen: QScreen) -> int:
        delta = screen.geometry().center() - point
        return abs(delta.x()) + abs(delta.y())

    return min(screens, key=distance)


def clamp_to_screens(rect: QRect, min_visible: int = 36) -> QRect:
    """Не даёт полностью потерять облачко за краями мониторов."""
    screens = QGuiApplication.screens()
    if not screens:
        return rect
    best: tuple[int, QRect] | None = None
    for screen in screens:
        g = screen.geometry()
        candidate = QRect(rect)
        if candidate.left() > g.right() - min_visible:
            candidate.moveLeft(g.right() - min_visible)
        if candidate.right() < g.left() + min_visible:
            candidate.moveRight(g.left() + min_visible)
        if candidate.top() > g.bottom() - min_visible:
            candidate.moveTop(g.bottom() - min_visible)
        if candidate.bottom() < g.top() + min_visible:
            candidate.moveBottom(g.top() + min_visible)
        overlap_w = max(0, min(candidate.right(), g.right()) - max(candidate.left(), g.left()))
        overlap_h = max(0, min(candidate.bottom(), g.bottom()) - max(candidate.top(), g.top()))
        score = overlap_w * overlap_h
        if best is None or score > best[0]:
            best = (score, candidate)
    return best[1] if best else rect


def default_position(size) -> tuple[QScreen, QRect]:
    app = QApplication.instance()
    screen = app.primaryScreen() if app else None
    if screen is None:
        from PySide6.QtGui import QGuiApplication as QGA

        screen = QGA.primaryScreen()
    area = screen.availableGeometry()
    x = area.right() - size.width() - 28
    y = area.top() + 44
    return screen, QRect(x, y, size.width(), size.height())
