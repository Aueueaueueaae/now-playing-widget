"""Определение полноэкранной игры по активному окну.

Полноэкранный/безрамочный вариант — самое частое, что используют игры.
Мы намеренно не сканируем все процессы и не читаем память: проверяется только
окно на переднем плане. Это дёшево и не требует никаких прав.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
from ctypes import wintypes
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"

# Процессы, которые не считаем играми, даже если окно развёрнуто на весь экран.
# Это браузеры (F11), оболочка Windows, OBS и программы для созвонов.
DEFAULT_IGNORED = frozenset(
    {
        "explorer.exe",
        "shellhost.exe",
        "searchhost.exe",
        "startmenuexperiencehost.exe",
        "shellexperiencehost.exe",
        "textinputhost.exe",
        "systemsettings.exe",
        "lockapp.exe",
        "dwm.exe",
        "taskmgr.exe",
        "obs.exe",
        "obs32.exe",
        "obs64.exe",
        "chrome.exe",
        "msedge.exe",
        "msedgewebview2.exe",
        "firefox.exe",
        "brave.exe",
        "opera.exe",
        "opera_gx.exe",
        "vivaldi.exe",
        "yandex.exe",
        "browser.exe",
        "chromium.exe",
        "librewolf.exe",
        "waterfox.exe",
        "arc.exe",
        "discord.exe",
        "zoom.exe",
        "teams.exe",
        "ms-teams.exe",
        "code.exe",
        "code - insiders.exe",
    }
)

IGNORED_CLASSES = frozenset(
    {
        "Progman",
        "WorkerW",
        "Shell_TrayWnd",
        "Shell_SecondaryTrayWnd",
        "Windows.UI.Core.CoreWindow",
        "MultitaskingViewFrame",
        "ForegroundStaging",
    }
)

GWL_STYLE = -16
WS_MAXIMIZE = 0x01000000
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
DWMWA_CLOAKED = 14
MONITOR_DEFAULTTONEAREST = 2
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

QUNS_BUSY = 2
QUNS_RUNNING_D3D_FULL_SCREEN = 3
QUNS_PRESENTATION_MODE = 4


@dataclass(frozen=True)
class FullscreenApp:
    hwnd: int
    pid: int
    exe: str
    title: str
    exclusive: bool


if IS_WINDOWS:
    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", RECT),
            ("rcWork", RECT),
            ("dwFlags", wintypes.DWORD),
        ]


def _winapi():
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    shell32 = ctypes.windll.shell32
    dwmapi = ctypes.windll.dwmapi

    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsIconic.restype = wintypes.BOOL
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.MonitorFromWindow.restype = wintypes.HANDLE
    user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]
    user32.GetMonitorInfoW.restype = wintypes.BOOL

    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    dwmapi.DwmGetWindowAttribute.argtypes = [
        wintypes.HWND,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long

    shell32.SHQueryUserNotificationState.argtypes = [ctypes.POINTER(ctypes.c_int)]
    shell32.SHQueryUserNotificationState.restype = ctypes.c_long

    return user32, kernel32, shell32, dwmapi


if IS_WINDOWS:
    _USER32, _KERNEL32, _SHELL32, _DWMAPI = _winapi()


def _process_exe(pid: int) -> str:
    if not pid:
        return ""
    handle = _KERNEL32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buf))
        if _KERNEL32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value).lower()
        return ""
    finally:
        _KERNEL32.CloseHandle(handle)


def _window_text(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(512)
    _USER32.GetWindowTextW(hwnd, buf, len(buf))
    return buf.value.strip()


def _window_class(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    _USER32.GetClassNameW(hwnd, buf, len(buf))
    return buf.value


def _is_cloaked(hwnd: int) -> bool:
    value = wintypes.DWORD(0)
    try:
        result = _DWMAPI.DwmGetWindowAttribute(
            hwnd, DWMWA_CLOAKED, ctypes.byref(value), ctypes.sizeof(value)
        )
        return result == 0 and value.value != 0
    except Exception:
        return False


def _fullscreen_state() -> int:
    state = ctypes.c_int(0)
    try:
        if _SHELL32.SHQueryUserNotificationState(ctypes.byref(state)) == 0:
            return int(state.value)
    except Exception:
        pass
    return 0


def _rect_covers_monitor(rect: RECT, monitor: RECT, tolerance: int = 4) -> bool:
    return (
        rect.left <= monitor.left + tolerance
        and rect.top <= monitor.top + tolerance
        and rect.right >= monitor.right - tolerance
        and rect.bottom >= monitor.bottom - tolerance
    )


def detect_fullscreen_app(
    own_pid: int | None = None,
    extra_ignored: tuple[str, ...] | list[str] = (),
) -> FullscreenApp | None:
    """Возвращает описание полноэкранного приложения или None."""
    if not IS_WINDOWS:
        return None

    own_pid = own_pid or os.getpid()
    ignored = DEFAULT_IGNORED | {_norm_name(x) for x in extra_ignored if x}

    hwnd = int(_USER32.GetForegroundWindow() or 0)
    if not hwnd:
        return None
    if not _USER32.IsWindowVisible(hwnd) or _USER32.IsIconic(hwnd):
        return None
    if _is_cloaked(hwnd):
        return None

    class_name = _window_class(hwnd)
    if class_name in IGNORED_CLASSES:
        return None

    pid = wintypes.DWORD()
    _USER32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value or int(pid.value) == int(own_pid):
        return None

    exe = _process_exe(int(pid.value))
    if not exe or exe in ignored:
        return None

    rect = RECT()
    if not _USER32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    if rect.right - rect.left < 200 or rect.bottom - rect.top < 200:
        return None

    monitor_handle = _USER32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    if not monitor_handle:
        return None
    monitor = MONITORINFO()
    monitor.cbSize = ctypes.sizeof(MONITORINFO)
    if not _USER32.GetMonitorInfoW(monitor_handle, ctypes.byref(monitor)):
        return None

    covers_monitor = _rect_covers_monitor(rect, monitor.rcMonitor)
    notification_state = _fullscreen_state() if covers_monitor else 0
    exclusive = notification_state in (
        QUNS_BUSY,
        QUNS_RUNNING_D3D_FULL_SCREEN,
        QUNS_PRESENTATION_MODE,
    )

    if not covers_monitor:
        return None

    style = int(_USER32.GetWindowLongW(hwnd, GWL_STYLE))

    # Развёрнутое на весь экран обычное окно при скрытой панели задач — ещё не игра.
    # Безрамочные игры не имеют заголовка/толстой рамки; эксклюзивный режим
    # дополнительно подтверждается через оболочку Windows.
    framed = bool(style & WS_CAPTION) and bool(style & WS_THICKFRAME)
    if framed and not exclusive:
        return None

    return FullscreenApp(
        hwnd=hwnd,
        pid=int(pid.value),
        exe=exe,
        title=_window_text(hwnd),
        exclusive=exclusive,
    )


def _norm_name(name: str) -> str:
    value = name.strip().lower()
    return value if value.endswith(".exe") else value + ".exe"


class GameWatcher(QObject):
    """Опрашивает передний план с гистерезисом, чтобы не мигать при alt-tab."""

    changed = Signal(bool, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.enabled = True
        self.ignore: tuple[str, ...] = ()
        self.active = False
        self._misses = 0
        self._last_exe = ""
        self._timer = QTimer(self)
        self._timer.setInterval(800)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        QTimer.singleShot(500, self._tick)

    def update_config(self, enabled: bool, ignore: tuple[str, ...]) -> None:
        self.enabled = bool(enabled)
        self.ignore = tuple(ignore)
        if not self.enabled and self.active:
            self.active = False
            self._misses = 0
            self.changed.emit(False, "")

    def _tick(self) -> None:
        if not self.enabled:
            return
        app = detect_fullscreen_app(os.getpid(), self.ignore)
        if app is not None:
            self._misses = 0
            if not self.active:
                self.active = True
                self._last_exe = app.exe
                log.info("Полноэкранное приложение: %s | %s", app.exe, app.title[:120])
                self.changed.emit(True, app.exe)
            return

        if self.active:
            self._misses += 1
            # Два спокойных замера подряд — выходим из игрового режима.
            if self._misses >= 2:
                self.active = False
                self._misses = 0
                log.info("Полноэкранное приложение закрыто или свёрнуто")
                self.changed.emit(False, "")

    def stop(self) -> None:
        self._timer.stop()
