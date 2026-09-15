from __future__ import annotations

import argparse
import logging
import os
import signal
import sys

from PySide6.QtCore import QObject, QTimer, Slot, ClassInfo
from PySide6.QtDBus import QDBusAbstractAdaptor, QDBusConnection
from PySide6.QtGui import QAction, QGuiApplication
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import APP_DISPLAY_NAME, APP_NAME, DBUS_INTERFACE, DBUS_PATH, DBUS_SERVICE, __version__
from .icon import clipboard_icon
from .paths import log_path
from .popup import ClipboardPopup
from .position import install_position_hook
from .restore import restore_item
from .settings import Settings
from .store import ClipPayload, ClipboardStore
from .watcher import ClipboardWatcher

log = logging.getLogger(__name__)


class ClipboardService(QObject):
    def __init__(self, app: "ClipboardApp") -> None:
        super().__init__()
        self._app = app
        self.adaptor = ClipboardAdaptor(self)

    def toggle(self) -> None:
        self._app.toggle_popup()

    @Slot()
    def Toggle(self) -> None:  # noqa: N802 — fallback if adaptors are not exported
        self.toggle()


@ClassInfo({"D-Bus Interface": DBUS_INTERFACE})
class ClipboardAdaptor(QDBusAbstractAdaptor):
    def __init__(self, parent: ClipboardService) -> None:
        super().__init__(parent)

    @Slot()
    def Toggle(self) -> None:  # noqa: N802 — D-Bus method name
        parent = self.parent()
        if isinstance(parent, ClipboardService):
            parent.toggle()


class ClipboardApp:
    def __init__(self, qt_app: QApplication, show_on_start: bool = False) -> None:
        self.qt_app = qt_app
        self.settings = Settings.load()
        self.store = ClipboardStore(self.settings)
        self.popup = ClipboardPopup(self.store, self.settings)
        self.popup.restoreRequested.connect(self._restore)
        self.popup.deleteRequested.connect(self._delete)
        self.watcher = ClipboardWatcher()
        self.watcher.captured.connect(self._on_capture)
        self.service = ClipboardService(self)

        self._prune_timer = QTimer()
        self._prune_timer.setInterval(60 * 60 * 1000)
        self._prune_timer.timeout.connect(self.store.prune)
        self._prune_timer.start()

        self._setup_tray()
        self._register_dbus()
        install_position_hook()
        self.watcher.start()
        log.info("%s daemon ready", APP_DISPLAY_NAME)

        if show_on_start:
            QTimer.singleShot(250, self.popup.show_popup)

    def toggle_popup(self) -> None:
        self.popup.toggle_popup()

    def shutdown(self) -> None:
        self.watcher.stop()
        self.store.close()
        self.qt_app.quit()

    def _setup_tray(self) -> None:
        icon = clipboard_icon()
        self.qt_app.setWindowIcon(icon)
        if not QSystemTrayIcon.isSystemTrayAvailable():
            log.info("System tray is unavailable; the daemon will keep running without an icon")
            self.tray = None
            return
        self.tray = QSystemTrayIcon(icon)
        self.tray.setToolTip(APP_DISPLAY_NAME)
        menu = QMenu()
        open_action = QAction("Open history", menu)
        open_action.triggered.connect(self.popup.show_popup)
        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(self.shutdown)
        menu.addAction(open_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.toggle_popup()

    def _register_dbus(self) -> None:
        bus = QDBusConnection.sessionBus()
        if not bus.isConnected():
            log.warning("Session bus is not connected; Ctrl+` toggle via D-Bus will not work")
            return
        if not bus.registerService(DBUS_SERVICE):
            log.warning("Could not own %s", DBUS_SERVICE)
            return
        exported = bus.registerObject(
            DBUS_PATH,
            self.service,
            QDBusConnection.RegisterOption.ExportAdaptors
            | QDBusConnection.RegisterOption.ExportAllSlots,
        )
        if not exported:
            log.warning("Could not export %s", DBUS_PATH)

    def _on_capture(self, payload: ClipPayload) -> None:
        item = self.store.record(payload)
        if item is None:
            return
        log.info("Stored %s clipboard item (%s)", payload.kind, payload.mime)
        if self.popup.isVisible():
            self.popup.reload()

    def _restore(self, item_id: int) -> None:
        item = self.store.get(item_id)
        if item is None:
            return
        if restore_item(item):
            self.store.touch(item_id)
            self.popup.hide_popup()
        else:
            log.error("Failed to restore clipboard item %s", item_id)

    def _delete(self, item_id: int) -> None:
        self.store.delete(item_id)
        self.popup.reload()


def configure_logging() -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    try:
        handlers.append(logging.FileHandler(log_path(), encoding="utf-8"))
    except OSError:
        pass
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=APP_NAME, description=APP_DISPLAY_NAME)
    parser.add_argument(
        "--toggle",
        action="store_true",
        help="Show or hide the history popup (starts the daemon if needed)",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print the version and exit",
    )
    return parser.parse_args(argv)


def service_is_running() -> bool:
    try:
        import dbus

        return bool(dbus.SessionBus().name_has_owner(DBUS_SERVICE))
    except Exception:
        bus = QDBusConnection.sessionBus()
        iface = bus.interface()
        if iface is None:
            return False
        reply = iface.isServiceRegistered(DBUS_SERVICE)
        return bool(reply.value()) if reply.isValid() else False


def call_toggle() -> bool:
    try:
        import dbus

        bus = dbus.SessionBus()
        obj = bus.get_object(DBUS_SERVICE, DBUS_PATH)
        for interface in (DBUS_INTERFACE, "local.ClipboardService", "local.ClipboardAdaptor"):
            try:
                dbus.Interface(obj, interface).Toggle()
                return True
            except Exception:
                continue
        bus.call_blocking(DBUS_SERVICE, DBUS_PATH, DBUS_INTERFACE, "Toggle", "", ())
        return True
    except Exception as exc:
        log.debug("Toggle call failed: %s", exc)
        return False


def run_daemon(qt_app: QApplication, show_on_start: bool) -> int:
    qt_app.setApplicationName(APP_NAME)
    qt_app.setApplicationDisplayName(APP_DISPLAY_NAME)
    qt_app.setQuitOnLastWindowClosed(False)
    app = ClipboardApp(qt_app, show_on_start=show_on_start)

    # Make SIGTERM/SIGINT interrupt the Qt event loop instead of waiting
    # until the next Python bytecode runs.
    read_fd, write_fd = os.pipe()
    os.set_blocking(read_fd, False)
    os.set_blocking(write_fd, False)
    signal.set_wakeup_fd(write_fd)
    from PySide6.QtCore import QSocketNotifier

    notifier = QSocketNotifier(read_fd, QSocketNotifier.Type.Read, qt_app)

    def _on_unix_signal() -> None:
        try:
            data = os.read(read_fd, 1024)
        except OSError:
            return
        if not data:
            return
        app.shutdown()

    notifier.activated.connect(lambda *_: _on_unix_signal())
    signal.signal(signal.SIGINT, lambda *_signum: None)
    signal.signal(signal.SIGTERM, lambda *_signum: None)
    return qt_app.exec()


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = parse_args(argv)
    if args.version:
        print(__version__)
        return 0

    os.environ.setdefault("QT_QPA_PLATFORM", "wayland")

    if args.toggle and service_is_running():
        if call_toggle():
            return 0
        log.warning("Daemon is running but Toggle failed; starting a visible popup anyway")

    if not args.toggle and service_is_running():
        log.info("%s is already running", APP_DISPLAY_NAME)
        return 0

    QGuiApplication.setDesktopFileName(APP_NAME)
    qt_app = QApplication.instance() or QApplication(sys.argv)
    return run_daemon(qt_app, show_on_start=args.toggle)
