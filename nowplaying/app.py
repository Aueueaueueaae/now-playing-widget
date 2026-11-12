"""Сборка приложения: трей, горячая клавиша, медиа и игровое состояние."""

from __future__ import annotations

import copy
import logging
import os
import subprocess
import time

from PySide6.QtCore import QFileSystemWatcher, QObject, QPoint, QRect, QTimer, Qt
from PySide6.QtGui import QAction, QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QMenu,
    QMessageBox,
    QSystemTrayIcon,
)

from . import autostart
from .bubble import BubbleWindow
from .config import APP_TITLE, ConfigStore, Position
from .game_detect import GameWatcher
from .icon import make_icon
from .media import MediaWatcher, TrackInfo
from .settings_dialog import SettingsDialog
from .winutil import (
    HotkeyFilter,
    clamp_to_screens,
    default_position,
    nearest_screen,
    release_single_instance,
    resource_path,
    screen_by_name,
)

log = logging.getLogger(__name__)


class ApplicationController(QObject):
    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        self.app = app
        self._shutting_down = False
        self._user_visible = True
        self._game_active = False
        self._has_media = False
        self._is_playing = False
        self._pause_expired = False
        self._last_track: TrackInfo | None = None
        self._last_notice: dict[str, float] = {}
        self._settings_dialog: SettingsDialog | None = None

        self._config = ConfigStore()
        loaded_ok = self._config.load()
        self._settings = self._config.settings

        self._pause_timer = QTimer(self)
        self._pause_timer.setSingleShot(True)
        self._pause_timer.setTimerType(Qt.TimerType.CoarseTimer)
        self._pause_timer.timeout.connect(self._on_pause_timeout)

        self._bubble = BubbleWindow(self._settings)
        self._bubble.position_changed.connect(self._on_bubble_moved)
        self._restore_initial_position()

        self._build_tray()
        if not loaded_ok:
            QTimer.singleShot(
                800,
                lambda: self._notify(
                    "Файл настроек содержит ошибку. Использую значения по умолчанию; "
                    f"проверьте {self._config.path}"
                ),
            )
        else:
            autostart.sync(self._settings.autostart)

        self._media = MediaWatcher(self)
        self._media.state_changed.connect(self._on_media_state)
        self._media.error.connect(self._on_media_error)

        self._games = GameWatcher(self)
        self._games.update_config(
            self._settings.detect_games, self._settings.ignore_fullscreen_processes
        )
        self._games.changed.connect(self._on_game_changed)

        self._hotkey = HotkeyFilter(self.toggle_visibility)
        self.app.installNativeEventFilter(self._hotkey)
        if not self._hotkey.register(self._settings.hotkey):
            QTimer.singleShot(
                900,
                lambda: self._notify(
                    f"Не удалось назначить горячую клавишу {self._settings.hotkey}. "
                    "Измените её в настройках."
                ),
            )

        self._watch_config()
        self._update_tray_tooltip()
        self._update_visibility_action()
        QTimer.singleShot(0, self._media.start)
        log.info("Виджет запущен; настройки: %s", self._config.path)

    # ------------------------------------------------------------------ #
    # Трей
    # ------------------------------------------------------------------ #

    def _build_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            log.error("Системный трей недоступен")
            QMessageBox.critical(
                None,
                APP_TITLE,
                "Системный трей Windows недоступен. Виджет не сможет работать незаметно.",
            )
            raise RuntimeError("system tray unavailable")

        icon_path = resource_path("assets/icon.ico")
        icon: QIcon
        if icon_path.exists():
            icon = QIcon(str(icon_path))
            if icon.isNull():
                icon = make_icon()
        else:
            icon = make_icon()

        self._tray = QSystemTrayIcon(icon, self)
        self._tray.setToolTip(APP_TITLE)

        self._menu = QMenu()
        self._action_visibility = QAction("Скрыть облачко", self._menu)
        self._action_visibility.triggered.connect(self.toggle_visibility)

        self._action_autostart = QAction("Автозапуск с Windows", self._menu)
        self._action_autostart.setCheckable(True)
        self._action_autostart.setChecked(bool(self._settings.autostart))
        self._action_autostart.toggled.connect(self._on_autostart_toggled)

        action_settings = QAction("Настройки…", self._menu)
        action_settings.triggered.connect(self.open_settings_dialog)

        action_json = QAction("Файл настроек (JSON)…", self._menu)
        action_json.triggered.connect(self.open_settings)

        action_quit = QAction("Выход", self._menu)
        action_quit.triggered.connect(self.quit)

        self._menu.addAction(self._action_visibility)
        self._menu.addSeparator()
        self._menu.addAction(self._action_autostart)
        self._menu.addAction(action_settings)
        self._menu.addAction(action_json)
        self._menu.addSeparator()
        self._menu.addAction(action_quit)

        self._tray.setContextMenu(self._menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # Только одиночный клик: при двойном клике Windows присылает ещё и
        # DoubleClick, из-за чего видимость переключалась бы дважды.
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_visibility()

    def _update_visibility_action(self) -> None:
        if not hasattr(self, "_action_visibility"):
            return
        self._action_visibility.setText(
            "Скрыть облачко" if self._user_visible else "Показать облачко"
        )

    def _update_tray_tooltip(self) -> None:
        if not hasattr(self, "_tray"):
            return
        if self._last_track and self._has_media:
            artist = self._last_track.artist.strip()
            title = self._last_track.display_title
            text = f"{artist} — {title}" if artist else title
            if len(text) > 70:
                text = text[:67] + "…"
            self._tray.setToolTip(f"{APP_TITLE}\n{text}")
        else:
            self._tray.setToolTip(f"{APP_TITLE} — ожидание музыки")

    def _notify(self, text: str, key: str = "generic", interval: float = 5.0) -> None:
        now = time.monotonic()
        if now - self._last_notice.get(key, 0.0) < interval:
            return
        self._last_notice[key] = now
        log.info("Уведомление: %s", text)
        if hasattr(self, "_tray") and self._tray.isVisible():
            self._tray.showMessage(APP_TITLE, text, QSystemTrayIcon.MessageIcon.Information, 5000)

    # ------------------------------------------------------------------ #
    # Медиа и видимость
    # ------------------------------------------------------------------ #

    def _on_media_state(self, track: TrackInfo) -> None:
        self._last_track = track
        has_media = bool(track.has_media and (track.title or track.artist))
        was_playing = self._is_playing
        self._has_media = has_media
        self._is_playing = bool(has_media and track.is_playing)

        if not has_media:
            self._pause_timer.stop()
            self._pause_expired = False
            if self._user_visible:
                self._bubble.hide_bubble(animate=True)
            self._update_tray_tooltip()
            return

        self._bubble.set_track(track)

        if self._is_playing:
            self._pause_timer.stop()
            self._pause_expired = False
            if self._user_visible:
                self._bubble.show_bubble(animate=True)
        elif was_playing and self._user_visible:
            self._start_pause_timer()

        self._update_tray_tooltip()

    def _start_pause_timer(self) -> None:
        delay = max(0.0, float(self._settings.pause_hide_delay_sec))
        self._pause_timer.start(max(0, int(round(delay * 1000))))

    def _on_pause_timeout(self) -> None:
        self._pause_expired = True
        if self._user_visible:
            self._bubble.hide_bubble(animate=True)

    def toggle_visibility(self) -> None:
        if self._shutting_down:
            return
        self._user_visible = not self._user_visible
        log.info("Облачко %s пользователем", "показано" if self._user_visible else "скрыто")
        if self._user_visible:
            self._pause_timer.stop()
            self._pause_expired = False
            if self._has_media and self._last_track is not None:
                self._bubble.set_track(self._last_track)
                self._bubble.show_bubble(animate=True)
        else:
            self._pause_timer.stop()
            self._bubble.hide_bubble(animate=True)
        self._update_visibility_action()

    # ------------------------------------------------------------------ #
    # Игровой режим
    # ------------------------------------------------------------------ #

    def _on_game_changed(self, active: bool, exe: str) -> None:
        self._game_active = bool(active)
        self._bubble.set_game_mode(self._game_active)
        if not self._game_active:
            if self._user_visible and self._is_playing and not self._bubble.isVisible():
                self._bubble.show_bubble(animate=False)
        self._update_tray_tooltip()
        if active:
            log.debug("Включён игровой режим (%s)", exe)

    # ------------------------------------------------------------------ #
    # Настройки
    # ------------------------------------------------------------------ #

    def _restore_initial_position(self) -> None:
        position = self._settings.position
        if position is not None:
            point = QPoint(position.x, position.y)
            rect = QRect(point, self._bubble.size())
            clamped = clamp_to_screens(rect, min_visible=36)
            screen = screen_by_name(position.screen) or nearest_screen(clamped.center())
            if screen is None:
                screen, default_rect = default_position(self._bubble.size())
                clamped = default_rect
            self._bubble.set_rest_position(clamped.topLeft())
            return

        _screen, rect = default_position(self._bubble.size())
        self._bubble.set_rest_position(rect.topLeft())

    def _on_bubble_moved(self, point: QPoint) -> None:
        log.info("Облачко перемещено: %s, %s", point.x(), point.y())
        self._persist_position(point)

    def _persist_position(self, point: QPoint | None = None) -> None:
        if not self._config.writable:
            return
        point = QPoint(point) if point is not None else self._bubble.rest_position()
        center = point + QPoint(self._bubble.width() // 2, self._bubble.height() // 2)
        screen = QGuiApplication.screenAt(center) or nearest_screen(center)
        name = screen.name() if screen is not None else ""
        position = Position(screen=name, x=point.x(), y=point.y())
        if position == self._settings.position:
            return
        self._settings.position = position
        if self._config.save():
            self._rearm_file_watcher()

    def _apply_settings(self, old) -> None:
        new = self._config.settings
        self._settings = new

        if new.hotkey != old.hotkey:
            if not self._hotkey.register(new.hotkey):
                self._notify(
                    f"Не удалось назначить горячую клавишу {new.hotkey}. "
                    "Возможно, она занята.",
                    key="hotkey",
                    interval=10.0,
                )

        if new.autostart != old.autostart:
            if autostart.set_enabled(new.autostart):
                self._action_autostart.blockSignals(True)
                self._action_autostart.setChecked(new.autostart)
                self._action_autostart.blockSignals(False)
            else:
                self._notify("Не удалось изменить автозапуск Windows.", key="autostart")
                new.autostart = old.autostart
                self._config.save()

        self._games.update_config(new.detect_games, new.ignore_fullscreen_processes)
        self._bubble.apply_settings(new)

        if new.position != old.position and new.position is not None:
            self._bubble.set_rest_position(QPoint(new.position.x, new.position.y))

        if self._pause_timer.isActive() and new.pause_hide_delay_sec != old.pause_hide_delay_sec:
            self._start_pause_timer()

        self._action_autostart.blockSignals(True)
        self._action_autostart.setChecked(bool(new.autostart))
        self._action_autostart.blockSignals(False)
        self._update_tray_tooltip()

    def _watch_config(self) -> None:
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_config_file_changed)
        self._reload_timer = QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(250)
        self._reload_timer.timeout.connect(self._reload_config)
        self._rearm_file_watcher()

    def _rearm_file_watcher(self) -> None:
        if not hasattr(self, "_watcher"):
            return
        path = str(self._config.path)
        if path not in self._watcher.files():
            try:
                self._watcher.addPath(path)
            except Exception:
                log.debug("Не удалось поставить файл настроек на наблюдение", exc_info=True)

    def _on_config_file_changed(self, _path: str) -> None:
        self._reload_timer.start()

    def _reload_config(self) -> None:
        if self._shutting_down:
            return
        old = self._config.settings
        ok = self._config.load()
        self._rearm_file_watcher()
        if not ok:
            self._notify(
                "В файле настроек ошибка. Работаю со старыми значениями.",
                key="bad_config",
                interval=20.0,
            )
            return
        try:
            new = self._config.settings
            if new != old:
                self._apply_settings(old)
                log.info("Настройки перезагружены")
        except Exception:
            log.exception("Не удалось применить настройки")

    def _on_autostart_toggled(self, checked: bool) -> None:
        if not autostart.set_enabled(checked):
            self._action_autostart.blockSignals(True)
            self._action_autostart.setChecked(not checked)
            self._action_autostart.blockSignals(False)
            self._notify("Не удалось изменить автозапуск Windows.", key="autostart")
            return
        self._settings.autostart = bool(checked)
        self._config.save()
        self._rearm_file_watcher()

    def open_settings_dialog(self) -> None:
        if self._shutting_down:
            return
        if self._settings_dialog is not None:
            self._settings_dialog.raise_()
            self._settings_dialog.activateWindow()
            return

        original = copy.deepcopy(self._config.settings)
        dialog = SettingsDialog(self._config.settings)
        self._settings_dialog = dialog
        dialog.preview_changed.connect(self._apply_preview)
        self._bubble.set_settings_open(True)
        try:
            result = dialog.exec()
        except Exception:
            log.exception("Ошибка окна настроек")
            result = QDialog.DialogCode.Rejected
        finally:
            self._settings_dialog = None
            self._bubble.set_settings_open(False)

        if result == QDialog.DialogCode.Accepted:
            self._commit_settings(dialog.result_settings(), original)
        else:
            # Отмена: возвращаем облачко к сохранённому виду.
            self._apply_preview(original)

    def _apply_preview(self, settings) -> None:
        try:
            self._bubble.apply_settings(copy.deepcopy(settings))
        except Exception:
            log.exception("Не удалось показать превью настроек")

    def _commit_settings(self, new, old) -> None:
        if new.hotkey != old.hotkey:
            if not self._hotkey.register(new.hotkey):
                new.hotkey = old.hotkey
                self._hotkey.register(old.hotkey)
                self._notify(
                    "Эта горячая клавиша занята. Оставил прежнюю комбинацию.",
                    key="hotkey",
                    interval=10.0,
                )

        self._config.settings = copy.deepcopy(new)
        if self._config.save():
            self._rearm_file_watcher()
        else:
            self._notify(
                "Не удалось сохранить настройки. Проверьте папку "
                f"{self._config.path.parent}",
                key="save_error",
            )
        self._apply_settings(old)
        log.info("Настройки сохранены через окно настроек")

    def open_settings(self) -> None:
        path = self._config.path
        if not path.exists():
            self._config.save()
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]
        except Exception:
            try:
                subprocess.Popen(["notepad.exe", str(path)])
            except Exception:
                log.exception("Не удалось открыть файл настроек")
                self._notify(f"Не удалось открыть файл настроек: {path}")

    # ------------------------------------------------------------------ #
    # Ошибки и завершение
    # ------------------------------------------------------------------ #

    def _on_media_error(self, text: str) -> None:
        log.warning("Media Session: %s", text)
        self._notify(text, key="media_error", interval=120.0)

    def quit(self) -> None:
        self.app.quit()

    def shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        log.info("Завершение работы")
        try:
            if self._config.writable:
                self._persist_position()
        except Exception:
            log.exception("Не удалось сохранить позицию")
        try:
            self._reload_timer.stop()
        except Exception:
            pass
        try:
            self._watcher.removePaths(self._watcher.files())
        except Exception:
            pass
        try:
            self._media.stop()
        except Exception:
            log.exception("Ошибка остановки Media Session")
        try:
            self._games.stop()
        except Exception:
            pass
        try:
            self._hotkey.unregister()
            self.app.removeNativeEventFilter(self._hotkey)
        except Exception:
            pass
        try:
            self._pause_timer.stop()
            self._bubble.hide_immediately()
            self._tray.hide()
        except Exception:
            pass
        release_single_instance()
