"""Почти невидимое полноэкранное окно для проверки игрового детектора."""

from __future__ import annotations

import ctypes
import sys

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QWidget

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080


class FullscreenProbe(QWidget):
    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        screen = QApplication.primaryScreen()
        self.setGeometry(screen.geometry())
        self.setWindowOpacity(0.01)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        hwnd = int(self.winId())
        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        ctypes.windll.user32.SetWindowLongW(
            hwnd, GWL_EXSTYLE, style | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW
        )


def main() -> int:
    app = QApplication(sys.argv)
    probe = FullscreenProbe()
    probe.show()
    probe.raise_()
    probe.activateWindow()
    ctypes.windll.user32.SetForegroundWindow(int(probe.winId()))
    print("probe", probe.geometry().getRect(), flush=True)
    QTimer.singleShot(3600, app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
