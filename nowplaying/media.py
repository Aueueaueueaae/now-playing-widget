"""Фоновое чтение Windows Media Session (SMTC).

Поток живёт всё время работы приложения. Раз в секунду он смотрит текущую
медиасессию Windows: так виджет работает с Spotify, Яндекс.Музыкой, VK,
браузерами и любым другим плеером, который отдаёт данные системе.
"""

from __future__ import annotations

import asyncio
import ctypes
import hashlib
import logging
import sys
import threading
import time
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"
MAX_COVER_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class TrackInfo:
    has_media: bool = False
    title: str = ""
    artist: str = ""
    album: str = ""
    thumbnail: bytes | None = None
    thumb_hash: bytes = field(default=b"", repr=False)
    is_playing: bool = False
    source: str = ""

    @property
    def display_title(self) -> str:
        return self.title.strip() or "Без названия"


class MediaWatcher(QObject):
    state_changed = Signal(object)
    error = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_async: asyncio.Event | None = None
        self._stop_requested = threading.Event()
        self._lock = threading.Lock()
        self._last_emitted: TrackInfo | None = None
        self._last_error_text = ""
        self._last_error_at = 0.0
        self._thumb_key: tuple[str, str, str, str] | None = None
        self._thumb_attempted: tuple[str, str, str, str] | None = None
        self._thumb_data: bytes | None = None
        self._thumb_hash: bytes = b""

    # ------------------------------------------------------------------ #
    # Публичный интерфейс
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_requested.clear()
        self._thread = threading.Thread(
            target=self._thread_main, name="NowPlaying-SMTC", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_requested.set()
        with self._lock:
            loop = self._loop
            event = self._stop_async
        if loop is not None and event is not None:
            try:
                loop.call_soon_threadsafe(event.set)
            except Exception:
                pass
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=3.0)
            if thread.is_alive():
                log.warning("Поток Media Session не завершился за 3 секунды")

    # ------------------------------------------------------------------ #
    # Поток и asyncio
    # ------------------------------------------------------------------ #

    def _thread_main(self) -> None:
        initialized = False
        try:
            # MTA лучше подходит для WinRT-операций без UI.
            hr = ctypes.windll.ole32.CoInitializeEx(None, 0x0)
            initialized = hr >= 0
        except Exception:
            log.debug("CoInitializeEx не удался", exc_info=True)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        with self._lock:
            self._loop = loop
            self._stop_async = asyncio.Event()
        try:
            loop.run_until_complete(self._run())
        except Exception:
            log.exception("Поток Media Session завершился с ошибкой")
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
            loop.close()
            with self._lock:
                self._loop = None
                self._stop_async = None
            if initialized:
                try:
                    ctypes.windll.ole32.CoUninitialize()
                except Exception:
                    pass

    async def _run(self) -> None:
        manager = None
        backoff = 0.0
        while not self._stop_requested.is_set():
            interval = 1.0
            try:
                if manager is None:
                    manager = await self._get_manager()
                    if manager is None:
                        await self._sleep_or_stop(max(2.0, backoff))
                        backoff = min(backoff + 1.0, 15.0)
                        continue
                    backoff = 0.0

                track, interval = await self._read(manager)
                self._emit(track)
            except Exception:
                log.exception("Ошибка чтения Media Session")
                self._emit(TrackInfo(has_media=False))
                self._notify_error("Не удалось прочитать данные плеера. Жду дальше…")
                manager = None
                await self._sleep_or_stop(max(3.0, backoff))
                backoff = min(backoff + 1.0, 15.0)
                continue

            await self._sleep_or_stop(interval)

    async def _get_manager(self):
        try:
            from winrt.windows.media.control import (
                GlobalSystemMediaTransportControlsSessionManager as Manager,
            )
        except Exception as exc:
            log.exception("WinRT Media Session недоступен")
            self._notify_error("Windows Media Session недоступен на этой системе.")
            self._emit(TrackInfo(has_media=False))
            await self._sleep_or_stop(30.0)
            return None

        try:
            manager = await asyncio.wait_for(Manager.request_async(), timeout=5.0)
            log.info("Media Session подключён")
            return manager
        except Exception:
            log.exception("Не удалось получить Media Session Manager")
            self._notify_error("Windows Media Session пока недоступен. Жду…")
            return None

    async def _read(self, manager) -> tuple[TrackInfo, float]:
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlaybackStatus,
        )

        sessions = []
        try:
            sessions = list(manager.get_sessions() or [])
        except Exception:
            log.debug("Не удалось получить список сессий", exc_info=True)

        current = None
        try:
            current = manager.get_current_session()
        except Exception:
            log.debug("Не удалось получить текущую сессию", exc_info=True)

        session = self._choose_session(current, sessions, PlaybackStatus)
        if session is None:
            return TrackInfo(has_media=False), 2.0

        is_playing = False
        try:
            info = session.get_playback_info()
            is_playing = info.playback_status == PlaybackStatus.PLAYING
        except Exception:
            log.debug("Не удалось получить статус воспроизведения", exc_info=True)

        try:
            props = await asyncio.wait_for(
                session.try_get_media_properties_async(), timeout=2.5
            )
        except asyncio.TimeoutError:
            log.debug("Таймаут получения метаданных")
            return TrackInfo(has_media=True, is_playing=is_playing), 1.4
        except Exception:
            log.debug("Ошибка получения метаданных", exc_info=True)
            return TrackInfo(has_media=True, is_playing=is_playing), 1.4

        title = _clean(props.title)
        artist = _clean(props.artist)
        if not artist:
            artist = _clean(props.album_artist)
        album = _clean(props.album_title)
        try:
            source = str(session.source_app_user_model_id or "")
        except Exception:
            source = ""

        key = (source, title, artist, album)
        if key != self._thumb_key:
            self._thumb_key = key
            self._thumb_attempted = None
            self._thumb_data = None
            self._thumb_hash = b""

        if key != self._thumb_attempted:
            self._thumb_attempted = key
            thumbnail = getattr(props, "thumbnail", None)
            if thumbnail is not None:
                data = await self._read_thumbnail(thumbnail)
                if data:
                    self._thumb_data = data
                    self._thumb_hash = hashlib.blake2b(data, digest_size=8).digest()

        has_any_text = bool(title or artist)
        if not has_any_text:
            return TrackInfo(
                has_media=False,
                source=source,
            ), 1.4

        return (
            TrackInfo(
                has_media=True,
                title=title,
                artist=artist,
                album=album,
                thumbnail=self._thumb_data,
                thumb_hash=self._thumb_hash,
                is_playing=is_playing,
                source=source,
            ),
            0.9 if is_playing else 1.4,
        )

    @staticmethod
    def _choose_session(current, sessions, playback_status):
        if current is not None:
            try:
                if current.get_playback_info().playback_status == playback_status.PLAYING:
                    return current
            except Exception:
                pass

        for session in sessions:
            if session is current:
                continue
            try:
                if session.get_playback_info().playback_status == playback_status.PLAYING:
                    return session
            except Exception:
                continue

        if current is not None:
            return current
        return sessions[0] if sessions else None

    async def _read_thumbnail(self, reference) -> bytes | None:
        stream = None
        reader = None
        try:
            from winrt.windows.storage.streams import DataReader

            stream = await asyncio.wait_for(reference.open_read_async(), timeout=3.0)
            size = int(stream.size)
            if size <= 0 or size > MAX_COVER_BYTES:
                return None
            reader = DataReader(stream)
            await asyncio.wait_for(reader.load_async(size), timeout=3.0)
            buffer = reader.read_buffer(size)
            data = bytes(memoryview(buffer))
            if len(data) != size:
                return None
            return data
        except asyncio.TimeoutError:
            log.debug("Таймаут загрузки обложки")
            return None
        except Exception:
            log.debug("Не удалось прочитать обложку", exc_info=True)
            return None
        finally:
            if reader is not None:
                try:
                    reader.close()
                except Exception:
                    pass
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass

    async def _sleep_or_stop(self, seconds: float) -> None:
        with self._lock:
            event = self._stop_async
        if event is None:
            await asyncio.sleep(seconds)
            return
        try:
            await asyncio.wait_for(event.wait(), timeout=max(0.05, seconds))
        except asyncio.TimeoutError:
            pass

    def _emit(self, track: TrackInfo) -> None:
        if track == self._last_emitted:
            return
        # Небольшая защита от дребезга: обложка сравнивается по хэшу.
        self._last_emitted = track
        try:
            self.state_changed.emit(track)
        except Exception:
            log.exception("Не удалось отправить состояние в UI")

    def _notify_error(self, text: str) -> None:
        now = time.monotonic()
        if text == self._last_error_text and now - self._last_error_at < 60.0:
            return
        self._last_error_text = text
        self._last_error_at = now
        try:
            self.error.emit(text)
        except Exception:
            pass


def _clean(value) -> str:
    if value is None:
        return ""
    return str(value).replace("\x00", "").strip()
