from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from PySide6.QtDBus import QDBusConnection, QDBusInterface, QDBusMessage

from . import WINDOW_TITLE

log = logging.getLogger(__name__)

SCRIPT_ID = "bazziteclipboardpos"

KWIN_SCRIPT = f"""
(function() {{
    const caption = "{WINDOW_TITLE}";
    const windows = workspace.windowList();
    let target = null;
    for (const w of windows) {{
        const cls = (w.resourceClass || "").toString().toLowerCase();
        const name = (w.resourceName || "").toString().toLowerCase();
        if (w.caption === caption || cls.indexOf("bazzite-clipboard") !== -1 || name.indexOf("bazzite-clipboard") !== -1) {{
            target = w;
            break;
        }}
    }}
    if (!target) {{
        return;
    }}
    try {{
        target.skipTaskbar = true;
        target.keepAbove = true;
    }} catch (e) {{}}
    const pos = workspace.cursorPos;
    const g = target.frameGeometry;
    let x = pos.x;
    let y = pos.y + 12;
    let area = null;
    try {{
        area = workspace.clientArea(KWin.WorkArea, target);
    }} catch (e) {{
        try {{
            area = workspace.clientArea(KWin.PlacementArea, target);
        }} catch (e2) {{
            area = null;
        }}
    }}
    if (area) {{
        if (x + g.width > area.x + area.width) {{
            x = area.x + area.width - g.width;
        }}
        if (y + g.height > area.y + area.height) {{
            y = area.y + area.height - g.height;
        }}
        if (x < area.x) {{
            x = area.x;
        }}
        if (y < area.y) {{
            y = area.y;
        }}
    }}
    target.frameGeometry = {{
        x: Math.round(x),
        y: Math.round(y),
        width: g.width,
        height: g.height
    }};
}})();
"""


def bundled_script_dir() -> Path:
    return Path(__file__).resolve().parent / "kwin" / SCRIPT_ID


def install_position_hook() -> None:
    """Install a persistent KWin script so the popup is placed at map-time."""
    src = bundled_script_dir()
    dest = Path.home() / ".local" / "share" / "kwin" / "scripts" / SCRIPT_ID
    try:
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "contents" / "code").mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / "metadata.json", dest / "metadata.json")
        shutil.copy2(
            src / "contents" / "code" / "main.js",
            dest / "contents" / "code" / "main.js",
        )
    except OSError:
        log.exception("Could not install KWin position script")
        return

    kwrite = shutil.which("kwriteconfig6")
    if kwrite:
        subprocess.run(
            [
                kwrite,
                "--file",
                "kwinrc",
                "--group",
                "Plugins",
                "--key",
                f"{SCRIPT_ID}Enabled",
                "true",
            ],
            capture_output=True,
            check=False,
        )

    bus = QDBusConnection.sessionBus()
    kwin = QDBusInterface("org.kde.KWin", "/KWin", "org.kde.KWin", bus)
    if kwin.isValid():
        kwin.call("reconfigure")
    scripting = QDBusInterface("org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting", bus)
    if scripting.isValid():
        scripting.call("start")


def place_popup_at_cursor() -> None:
    script_path = _write_script()
    if not _load_via_qtdbus(script_path) and not _load_via_cli(script_path):
        log.warning("Could not ask KWin to move the popup under the cursor")


def _write_script() -> Path:
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", tempfile.gettempdir()))
    path = runtime / "bazzite-clipboard-place.js"
    path.write_text(KWIN_SCRIPT, encoding="utf-8")
    return path


def _load_via_qtdbus(script_path: Path) -> bool:
    bus = QDBusConnection.sessionBus()
    if not bus.isConnected():
        return False
    iface = QDBusInterface("org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting", bus)
    if not iface.isValid():
        return False
    loaded = iface.call("loadScript", str(script_path), "bazzite-clipboard-pos")
    if loaded.type() == QDBusMessage.MessageType.ErrorMessage:
        loaded = iface.call("loadScript", str(script_path))
        if loaded.type() == QDBusMessage.MessageType.ErrorMessage:
            log.debug("KWin loadScript failed: %s", loaded.errorMessage())
            return False
    started = iface.call("start")
    if started.type() == QDBusMessage.MessageType.ErrorMessage:
        log.debug("KWin start failed: %s", started.errorMessage())
        return False
    iface.call("unloadScript", "bazzite-clipboard-pos")
    return True


def _load_via_cli(script_path: Path) -> bool:
    qdbus = shutil.which("qdbus") or shutil.which("qdbus6")
    if qdbus:
        load = subprocess.run(
            [
                qdbus,
                "org.kde.KWin",
                "/Scripting",
                "org.kde.kwin.Scripting.loadScript",
                str(script_path),
                "bazzite-clipboard-pos",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if load.returncode != 0:
            load = subprocess.run(
                [
                    qdbus,
                    "org.kde.KWin",
                    "/Scripting",
                    "loadScript",
                    str(script_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        start = subprocess.run(
            [qdbus, "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.start"],
            capture_output=True,
            text=True,
            check=False,
        )
        if start.returncode != 0:
            start = subprocess.run(
                [qdbus, "org.kde.KWin", "/Scripting", "start"],
                capture_output=True,
                text=True,
                check=False,
            )
        return load.returncode == 0 and start.returncode == 0
    return False
