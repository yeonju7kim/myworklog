from __future__ import annotations

import sys

from PySide6.QtCore import QLockFile
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from .database import ActivityStore
from .paths import database_path, lock_path
from .tracker import ActivityTracker
from .ui import DashboardWindow, make_app_icon


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("MyWorkLog")
    app.setOrganizationName("MyWorkLog")
    app.setFont(QFont("Malgun Gothic", 10))
    app.setWindowIcon(make_app_icon())
    app.setQuitOnLastWindowClosed(False)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, "MyWorkLog", "Windows 시스템 트레이를 사용할 수 없습니다.")
        return 1

    instance_lock = QLockFile(str(lock_path()))
    instance_lock.setStaleLockTime(0)
    if not instance_lock.tryLock(0):
        QMessageBox.information(None, "MyWorkLog", "MyWorkLog가 이미 실행 중입니다.")
        return 0

    store = ActivityStore(database_path())
    store.initialize()
    tracker = ActivityTracker(store)

    try:
        tracker.start()
    except Exception as exc:
        QMessageBox.critical(
            None,
            "MyWorkLog",
            f"입력 감지를 시작하지 못했습니다.\n\n{exc}",
        )
        return 1

    window = DashboardWindow(store, tracker)
    if "--background" not in sys.argv[1:]:
        window.show()
    exit_code = app.exec()
    tracker.stop()
    instance_lock.unlock()
    return exit_code
