"""Автозапуск через HKCU\\...\\Run — без прав администратора."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

log = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APPROVED_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
VALUE_NAME = "NowPlayingWidget"


def _app_command() -> str:
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable)
        return f'"{exe}" --autostart'

    pythonw = Path(sys.executable).with_name("pythonw.exe")
    interpreter = pythonw if pythonw.exists() else Path(sys.executable)
    main_py = Path(__file__).resolve().parent.parent / "main.py"
    return f'"{interpreter}" "{main_py}" --autostart'


def _read_command() -> str | None:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return str(value)
    except FileNotFoundError:
        return None
    except OSError:
        log.exception("Не удалось прочитать запись автозапуска")
        return None


def is_registered() -> bool:
    return _read_command() is not None


def set_enabled(enabled: bool) -> bool:
    """Включает/выключает автозапуск. Возвращает True при успехе."""
    try:
        import winreg

        if enabled:
            command = _app_command()
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command)
            # Если пользователь выключал запись через Диспетчер задач,
            # удаление отметки снова делает её активной.
            try:
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER, APPROVED_KEY, 0, winreg.KEY_SET_VALUE
                ) as approved:
                    winreg.DeleteValue(approved, VALUE_NAME)
            except FileNotFoundError:
                pass
            return True

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, VALUE_NAME)
        except FileNotFoundError:
            pass
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, APPROVED_KEY, 0, winreg.KEY_SET_VALUE
            ) as approved:
                winreg.DeleteValue(approved, VALUE_NAME)
        except FileNotFoundError:
            pass
        return True
    except Exception:
        log.exception("Не удалось изменить автозапуск")
        return False


def sync(enabled: bool) -> None:
    """Чинит путь при переносе exe и убирает старую запись при выключении."""
    current = _read_command()
    if enabled:
        desired = _app_command()
        if current != desired:
            set_enabled(True)
    elif current is not None:
        set_enabled(False)
