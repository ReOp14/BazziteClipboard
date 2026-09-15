from __future__ import annotations

import logging
import shutil
import subprocess
import time

from .store import ClipItem, hash_bytes

log = logging.getLogger(__name__)

_ignore_until = 0.0
_ignore_hashes: set[str] = set()


def should_ignore(content_hash: str) -> bool:
    if time.monotonic() > _ignore_until:
        _ignore_hashes.clear()
        return False
    return content_hash in _ignore_hashes


def ignore_hash(content_hash: str, seconds: float = 1.5) -> None:
    global _ignore_until
    _ignore_hashes.add(content_hash)
    _ignore_until = max(_ignore_until, time.monotonic() + seconds)


def restore_item(item: ClipItem) -> bool:
    wl_copy = shutil.which("wl-copy")
    if not wl_copy:
        log.error("wl-copy is not installed")
        return False

    if item.kind == "text":
        data = (item.text_content or "").encode("utf-8")
        ignore_hash(hash_bytes(data))
        proc = subprocess.run(
            [wl_copy, "--type", "text/plain"],
            input=data,
            check=False,
        )
        return proc.returncode == 0

    if item.kind == "image":
        path = item.blob_path
        if path is None or not path.exists():
            log.error("Image blob missing for item %s", item.id)
            return False
        data = path.read_bytes()
        ignore_hash(hash_bytes(data))
        proc = subprocess.run(
            [wl_copy, "--type", item.mime],
            input=data,
            check=False,
        )
        return proc.returncode == 0

    return False
