"""Настройки приложения и их безопасное хранение."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

APP_NAME = "NowPlayingWidget"
APP_TITLE = "Сейчас играет"

SETTINGS_DIR = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_NAME
SETTINGS_PATH = SETTINGS_DIR / "settings.json"
LOG_PATH = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / APP_NAME / "widget.log"

DEFAULT_FONT_SIZE = 17
DEFAULT_ARTIST_FONT_SIZE = 12
DEFAULT_COVER_SIZE = 64
DEFAULT_BUBBLE_SCALE = 1.0
DEFAULT_OPACITY = 0.90
DEFAULT_GLASS_INTENSITY = 0.78
DEFAULT_GLASS_FROST = 0.15
DEFAULT_GLASS_REFRACTION = 0.75
DEFAULT_BUBBLE_COLOR = "#1b2030"
DEFAULT_FALLBACK_IMAGE = "assets/vinyl-record.png"
DEFAULT_PAUSE_DELAY = 3.0
DEFAULT_HOTKEY = "Ctrl+Alt+Shift+M"


@dataclass(frozen=True)
class Position:
    screen: str = ""
    x: int = 0
    y: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"screen": self.screen, "x": int(self.x), "y": int(self.y)}


@dataclass
class Settings:
    font_size: int = DEFAULT_FONT_SIZE
    artist_font_size: int = DEFAULT_ARTIST_FONT_SIZE
    cover_size: int = DEFAULT_COVER_SIZE
    bubble_scale: float = DEFAULT_BUBBLE_SCALE
    fallback_image: str = DEFAULT_FALLBACK_IMAGE
    bubble_color: str = DEFAULT_BUBBLE_COLOR
    glass_intensity: float = DEFAULT_GLASS_INTENSITY
    glass_frost: float = DEFAULT_GLASS_FROST
    glass_refraction: float = DEFAULT_GLASS_REFRACTION
    opacity: float = DEFAULT_OPACITY
    pause_hide_delay_sec: float = DEFAULT_PAUSE_DELAY
    autostart: bool = False
    hotkey: str = DEFAULT_HOTKEY
    detect_games: bool = True
    ignore_fullscreen_processes: tuple[str, ...] = field(default_factory=tuple)
    position: Position | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "font_size": int(self.font_size),
            "artist_font_size": int(self.artist_font_size),
            "cover_size": int(self.cover_size),
            "bubble_scale": round(float(self.bubble_scale), 3),
            "fallback_image": self.fallback_image,
            "bubble_color": self.bubble_color,
            "glass_intensity": round(float(self.glass_intensity), 3),
            "glass_frost": round(float(self.glass_frost), 3),
            "glass_refraction": round(float(self.glass_refraction), 3),
            "opacity": round(float(self.opacity), 3),
            "pause_hide_delay_sec": round(float(self.pause_hide_delay_sec), 2),
            "autostart": bool(self.autostart),
            "hotkey": self.hotkey,
            "detect_games": bool(self.detect_games),
            "ignore_fullscreen_processes": list(self.ignore_fullscreen_processes),
            "position": self.position.to_dict() if self.position else None,
        }


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _as_int(raw: Any, default: int, low: int, high: int) -> int:
    try:
        return int(_clamp(float(raw), low, high))
    except (TypeError, ValueError):
        return default


def _as_float(raw: Any, default: float, low: float, high: float) -> float:
    try:
        return float(_clamp(float(raw), low, high))
    except (TypeError, ValueError):
        return default


def _as_bool(raw: Any, default: bool) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "on", "да"}
    return default


def normalize_color(raw: Any, default: str = DEFAULT_BUBBLE_COLOR) -> str:
    """Приводит '#RGB' или '#RRGGBB' к нижнему регистру '#rrggbb'."""
    text = str(raw or "").strip()
    if not text:
        return default
    if not text.startswith("#"):
        text = "#" + text
    if len(text) == 4:
        text = "#" + "".join(ch * 2 for ch in text[1:])
    if len(text) != 7:
        return default
    try:
        int(text[1:], 16)
    except ValueError:
        return default
    return text.lower()


def normalize_process_name(raw: str) -> str:
    value = raw.strip().lower()
    if not value:
        return ""
    return value if value.endswith(".exe") else value + ".exe"


def _parse_position(raw: Any) -> Position | None:
    if not isinstance(raw, dict):
        return None
    try:
        x = int(raw["x"])
        y = int(raw["y"])
    except (KeyError, TypeError, ValueError):
        return None
    screen = str(raw.get("screen") or "")
    return Position(screen=screen, x=x, y=y)


class ConfigStore:
    """Читает JSON, чинит значения и не затирает сломанный файл."""

    def __init__(self, path: Path = SETTINGS_PATH) -> None:
        self.path = path
        self.settings = Settings()
        self.writable = True
        self.last_load_ok = True

    def load(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.settings = Settings()
            self.writable = True
            self.last_load_ok = True
            self.save()
            return True

        try:
            raw = json.loads(self.path.read_text(encoding="utf-8-sig"))
            if not isinstance(raw, dict):
                raise ValueError("корень JSON должен быть объектом")
        except Exception:
            log.exception("Не удалось прочитать %s", self.path)
            self.writable = False
            self.last_load_ok = False
            return False

        ignored = raw.get("ignore_fullscreen_processes", [])
        if isinstance(ignored, str):
            ignored = [ignored]
        if not isinstance(ignored, list):
            ignored = []
        clean_ignored: list[str] = []
        for item in ignored:
            if not isinstance(item, str):
                continue
            value = normalize_process_name(item)
            if not value or value in clean_ignored:
                continue
            clean_ignored.append(value)

        fallback_image = str(raw.get("fallback_image") or DEFAULT_FALLBACK_IMAGE).strip()
        if not fallback_image:
            fallback_image = DEFAULT_FALLBACK_IMAGE

        self.settings = Settings(
            font_size=_as_int(raw.get("font_size"), DEFAULT_FONT_SIZE, 11, 32),
            artist_font_size=_as_int(
                raw.get("artist_font_size"), DEFAULT_ARTIST_FONT_SIZE, 8, 28
            ),
            cover_size=_as_int(raw.get("cover_size"), DEFAULT_COVER_SIZE, 40, 140),
            bubble_scale=_as_float(
                raw.get("bubble_scale"), DEFAULT_BUBBLE_SCALE, 0.2, 1.6
            ),
            fallback_image=fallback_image,
            bubble_color=normalize_color(raw.get("bubble_color"), DEFAULT_BUBBLE_COLOR),
            glass_intensity=_as_float(
                raw.get("glass_intensity"), DEFAULT_GLASS_INTENSITY, 0.0, 1.0
            ),
            glass_frost=_as_float(
                raw.get("glass_frost"), DEFAULT_GLASS_FROST, 0.0, 1.0
            ),
            glass_refraction=_as_float(
                raw.get("glass_refraction"), DEFAULT_GLASS_REFRACTION, 0.0, 1.0
            ),
            opacity=_as_float(raw.get("opacity"), DEFAULT_OPACITY, 0.30, 1.0),
            pause_hide_delay_sec=_as_float(
                raw.get("pause_hide_delay_sec"), DEFAULT_PAUSE_DELAY, 0.0, 60.0
            ),
            autostart=_as_bool(raw.get("autostart"), False),
            hotkey=str(raw.get("hotkey") or DEFAULT_HOTKEY).strip() or DEFAULT_HOTKEY,
            detect_games=_as_bool(raw.get("detect_games"), True),
            ignore_fullscreen_processes=tuple(clean_ignored),
            position=_parse_position(raw.get("position")),
        )
        self.writable = True
        self.last_load_ok = True
        return True

    def save(self) -> bool:
        if not self.writable:
            return False
        text = json.dumps(self.settings.to_dict(), ensure_ascii=False, indent=2) + "\n"
        tmp = self.path.with_name(self.path.name + ".tmp")
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp.write_text(text, encoding="utf-8", newline="\n")
                os.replace(tmp, self.path)
                return True
            except PermissionError as exc:
                # Файл может быть на мгновение занят редактором или антивирусом.
                last_error = exc
                time.sleep(0.04 * (attempt + 1))
            except Exception as exc:
                last_error = exc
                break
        try:
            self.path.write_text(text, encoding="utf-8", newline="\n")
            return True
        except Exception:
            if last_error is not None:
                log.error(
                    "Не удалось сохранить настройки в %s",
                    self.path,
                    exc_info=(
                        type(last_error),
                        last_error,
                        last_error.__traceback__,
                    ),
                )
            else:
                log.exception("Не удалось сохранить настройки в %s", self.path)
            return False

    def set_position(self, position: Position) -> None:
        self.settings.position = position
        self.save()
