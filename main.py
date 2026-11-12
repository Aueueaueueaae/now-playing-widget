"""Точка входа. Запускать через pythonw.exe, чтобы не было консоли."""

from __future__ import annotations

import ctypes
import logging
import logging.handlers
import sys
import threading
import traceback

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from nowplaying.app import ApplicationController
from nowplaying.config import APP_NAME, LOG_PATH
from nowplaying.icon import make_icon
from nowplaying.winutil import acquire_single_instance, release_single_instance

log = logging.getLogger(__name__)


def setup_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    file_handler = logging.handlers.RotatingFileHandler(
        LOG_PATH,
        maxBytes=1_000_000,
        backupCount=2,
        encoding="utf-8",
    )
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")
    )
    root.addHandler(file_handler)

    if sys.stderr is not None:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        root.addHandler(stream)


def install_exception_hooks() -> None:
    def handle_exception(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            return
        log.critical(
            "Необработанная ошибка:\n%s",
            "".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
        )

    sys.excepthook = handle_exception

    def handle_thread_exception(args):
        if issubclass(args.exc_type, KeyboardInterrupt):
            return
        log.critical(
            "Необработанная ошибка в потоке %s:\n%s",
            args.thread.name if args.thread else "?",
            "".join(
                traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)
            ),
        )

    threading.excepthook = handle_thread_exception


def main() -> int:
    setup_logging()
    install_exception_hooks()

    if not acquire_single_instance():
        log.info("Виджет уже запущен; второй экземпляр не нужен")
        return 0

    app: QApplication | None = None
    try:
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
        app = QApplication(sys.argv)
        app.setQuitOnLastWindowClosed(False)
        app.setApplicationName(APP_NAME)
        app.setOrganizationName("NowPlayingWidget")
        app.setWindowIcon(make_icon())

        if sys.platform == "win32":
            try:
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                    "NowPlayingWidget.MediaWidget"
                )
            except Exception:
                pass

        controller = ApplicationController(app)
        app.aboutToQuit.connect(controller.shutdown)
        code = app.exec()
        log.info("Приложение завершилось с кодом %s", code)
        return int(code)
    except Exception:
        log.exception("Не удалось запустить приложение")
        return 1
    finally:
        release_single_instance()


if __name__ == "__main__":
    raise SystemExit(main())
