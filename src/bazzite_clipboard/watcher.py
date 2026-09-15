from __future__ import annotations

import io
import logging
import shutil
import subprocess
import time

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from PIL import Image

from . import MAX_IMAGE_BYTES, MAX_TEXT_BYTES
from .restore import should_ignore
from .store import ClipPayload, hash_bytes

log = logging.getLogger(__name__)

IMAGE_MIMES = (
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/bmp",
    "image/webp",
    "image/tiff",
)
IMAGE_URL_HINTS = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".svg",
    ".avif",
    ".tif",
    "pbs.twimg.com",
    "media.tenor.com",
    "i.imgur.com",
    "i.redd.it",
    "preview.redd.it",
    "cdn.discordapp.com/attachments",
    "/media/",
)


class ClipboardWatcher(QObject):
    captured = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._proc = QProcess(self)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(80)
        self._debounce.timeout.connect(self._ingest)
        self._last_hash = ""
        self._last_at = 0.0
        self._stopping = False
        self._proc.readyReadStandardOutput.connect(self._on_watch_output)
        self._proc.finished.connect(self._on_finished)

    def start(self) -> None:
        wl_paste = shutil.which("wl-paste")
        if not wl_paste:
            log.error("wl-paste is not installed; clipboard watching disabled")
            return
        if self._proc.state() != QProcess.ProcessState.NotRunning:
            return
        self._stopping = False
        self._proc.setProgram(wl_paste)
        # Drain stdin so large image copies cannot deadlock the pipe.
        self._proc.setArguments(
            ["--watch", "sh", "-c", "cat >/dev/null; printf 'x\\n'"]
        )
        self._proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._proc.start()
        if not self._proc.waitForStarted(2000):
            log.error("Failed to start wl-paste --watch")

    def stop(self) -> None:
        self._stopping = True
        self._debounce.stop()
        if self._proc.state() != QProcess.ProcessState.NotRunning:
            self._proc.kill()
            self._proc.waitForFinished(1000)

    def _on_watch_output(self) -> None:
        self._proc.readAllStandardOutput()
        self._debounce.start()

    def _on_finished(self, _code: int = 0, _status: QProcess.ExitStatus = QProcess.ExitStatus.NormalExit) -> None:
        if self._stopping:
            return
        log.warning("wl-paste --watch exited; restarting in 2s")
        QTimer.singleShot(2000, self.start)

    def _ingest(self) -> None:
        payload = capture_clipboard()
        if payload is None:
            return
        if should_ignore(payload.content_hash):
            return
        now = time.monotonic()
        if payload.content_hash == self._last_hash and now - self._last_at < 0.4:
            return
        self._last_hash = payload.content_hash
        self._last_at = now
        self.captured.emit(payload)


def capture_clipboard() -> ClipPayload | None:
    types = _list_types()
    if not types:
        return None

    image_mime = next((mime for mime in IMAGE_MIMES if mime in types), None)
    has_text = any(t.startswith("text/") for t in types) or "TEXT" in types or "UTF8_STRING" in types

    if image_mime:
        image = _capture_image(image_mime)
        if image is not None:
            return image
    if has_text:
        text = _capture_text_value()
        if text and not is_image_url(text):
            return _payload_from_text(text)
    return None


def _list_types() -> list[str]:
    try:
        proc = subprocess.run(
            ["wl-paste", "--list-types"],
            capture_output=True,
            timeout=2,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.decode("utf-8", "replace").splitlines() if line.strip()]


def _capture_text_value() -> str | None:
    try:
        proc = subprocess.run(
            ["wl-paste", "--no-newline", "--type", "text"],
            capture_output=True,
            timeout=3,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    if len(proc.stdout) > MAX_TEXT_BYTES:
        log.info("Skipping oversized text clipboard (%s bytes)", len(proc.stdout))
        return None
    text = proc.stdout.decode("utf-8", "replace")
    if not text.strip():
        return None
    return text


def _payload_from_text(text: str) -> ClipPayload:
    data = text.encode("utf-8")
    return ClipPayload(
        kind="text",
        mime="text/plain;charset=utf-8",
        content_hash=hash_bytes(data),
        byte_size=len(data),
        text_content=text,
    )


def _capture_image(mime: str) -> ClipPayload | None:
    try:
        proc = subprocess.run(
            ["wl-paste", "--type", mime],
            capture_output=True,
            timeout=8,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    data = proc.stdout
    if proc.returncode != 0 or not data:
        return None
    if len(data) > MAX_IMAGE_BYTES:
        log.info("Skipping oversized image clipboard (%s bytes)", len(data))
        return None
    try:
        with Image.open(io.BytesIO(data)) as img:
            width, height = img.size
    except Exception:
        log.warning("Clipboard advertised %s but it was not a readable image", mime)
        return None
    return ClipPayload(
        kind="image",
        mime=mime,
        content_hash=hash_bytes(data),
        byte_size=len(data),
        image_bytes=data,
        width=width,
        height=height,
    )


def is_image_url(text: str) -> bool:
    candidate = text.strip().split()[0] if text.strip() else ""
    if not candidate:
        return False
    lowered = candidate.lower()
    if lowered.startswith(("http://", "https://", "file://", "media:")):
        if any(hint in lowered for hint in IMAGE_URL_HINTS):
            return True
        if "?" in lowered:
            path = lowered.split("?", 1)[0]
            if any(path.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".avif", ".tif", ".tiff")):
                return True
    return False
