"""Bazzite Clipboard — local clipboard history for KDE Plasma on Wayland."""

__version__ = "1.0.0"

APP_NAME = "bazzite-clipboard"
APP_DISPLAY_NAME = "Bazzite Clipboard"
DBUS_SERVICE = "org.bazzite.Clipboard"
DBUS_PATH = "/org/bazzite/Clipboard"
DBUS_INTERFACE = "org.bazzite.Clipboard"
WINDOW_TITLE = "Bazzite Clipboard"
RETENTION_DAYS = 30
MAX_IMAGE_BYTES = 25 * 1024 * 1024
MAX_TEXT_BYTES = 1 * 1024 * 1024
