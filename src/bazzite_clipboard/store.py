from __future__ import annotations

import hashlib
import io
import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from .paths import blobs_dir, data_dir, db_path, thumbs_dir
from .settings import Settings

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY,
    created_at INTEGER NOT NULL,
    last_used_at INTEGER NOT NULL,
    kind TEXT NOT NULL,
    mime TEXT NOT NULL,
    text_content TEXT,
    text_preview TEXT,
    content_hash TEXT NOT NULL UNIQUE,
    blob_name TEXT,
    byte_size INTEGER NOT NULL,
    width INTEGER,
    height INTEGER
);

CREATE INDEX IF NOT EXISTS idx_items_last_used ON items(last_used_at DESC);
"""


@dataclass(slots=True)
class ClipItem:
    id: int
    created_at: int
    last_used_at: int
    kind: str
    mime: str
    text_content: str | None
    text_preview: str | None
    content_hash: str
    blob_name: str | None
    byte_size: int
    width: int | None
    height: int | None

    @property
    def blob_path(self) -> Path | None:
        if not self.blob_name:
            return None
        return blobs_dir() / self.blob_name

    @property
    def thumb_path(self) -> Path | None:
        if self.kind != "image" or not self.content_hash:
            return None
        return thumbs_dir() / f"{self.content_hash}.png"


@dataclass(slots=True)
class ClipPayload:
    kind: str
    mime: str
    content_hash: str
    byte_size: int
    text_content: str | None = None
    image_bytes: bytes | None = None
    width: int | None = None
    height: int | None = None


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def preview_text(text: str, limit: int = 180) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1] + "…"


class ClipboardStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or Settings.load()
        self._conn = sqlite3.connect(str(db_path()), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        self.prune()

    def close(self) -> None:
        self._conn.close()

    def record(self, payload: ClipPayload) -> ClipItem | None:
        now = int(time.time())
        existing = self._fetch_by_hash(payload.content_hash)
        if existing is not None:
            self._conn.execute(
                "UPDATE items SET last_used_at = ? WHERE id = ?",
                (now, existing.id),
            )
            self._conn.commit()
            return self.get(existing.id)

        blob_name = None
        preview = None
        if payload.kind == "text":
            preview = preview_text(payload.text_content or "")
        elif payload.kind == "image" and payload.image_bytes:
            ext = _ext_for_mime(payload.mime)
            blob_name = f"{payload.content_hash}{ext}"
            blob = blobs_dir() / blob_name
            if not blob.exists():
                blob.write_bytes(payload.image_bytes)
            _write_thumb(payload.content_hash, payload.image_bytes)
            preview = _image_label(payload.width, payload.height)
        else:
            return None

        cur = self._conn.execute(
            """
            INSERT INTO items (
                created_at, last_used_at, kind, mime, text_content, text_preview,
                content_hash, blob_name, byte_size, width, height
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now,
                now,
                payload.kind,
                payload.mime,
                payload.text_content,
                preview,
                payload.content_hash,
                blob_name,
                payload.byte_size,
                payload.width,
                payload.height,
            ),
        )
        self._conn.commit()
        item = self.get(int(cur.lastrowid))
        self.prune()
        return item

    def touch(self, item_id: int) -> None:
        self._conn.execute(
            "UPDATE items SET last_used_at = ? WHERE id = ?",
            (int(time.time()), item_id),
        )
        self._conn.commit()

    def delete(self, item_id: int) -> None:
        item = self.get(item_id)
        if item is None:
            return
        self._conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
        self._conn.commit()
        self._cleanup_files(item)

    def get(self, item_id: int) -> ClipItem | None:
        row = self._conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        return _row_to_item(row) if row else None

    def list_items(self, query: str = "", limit: int | None = None) -> list[ClipItem]:
        if limit is None:
            limit = self._settings.max_entries if self._settings.max_entries > 0 else 1000
        sql = "SELECT * FROM items"
        params: list[object] = []
        needle = query.strip()
        if needle:
            sql += " WHERE IFNULL(text_preview, '') LIKE ? OR IFNULL(text_content, '') LIKE ? OR kind LIKE ?"
            like = f"%{needle}%"
            params.extend([like, like, like])
        sql += " ORDER BY last_used_at DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(sql, params).fetchall()
        return [_row_to_item(row) for row in rows]

    def count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS n FROM items").fetchone()
        return int(row["n"] if row else 0)

    def storage_bytes(self) -> int:
        total = 0
        root = data_dir()
        for path in root.rglob("*"):
            if path.is_file():
                try:
                    total += path.stat().st_size
                except OSError:
                    continue
        return total

    def prune(self) -> None:
        removed = 0
        cutoff = int(time.time()) - self._settings.retention_days * 24 * 60 * 60
        stale = self._conn.execute(
            "SELECT * FROM items WHERE last_used_at < ?",
            (cutoff,),
        ).fetchall()
        if stale:
            ids = [int(row["id"]) for row in stale]
            self._conn.execute(
                f"DELETE FROM items WHERE id IN ({','.join('?' * len(ids))})",
                ids,
            )
            self._conn.commit()
            for row in stale:
                self._cleanup_files(_row_to_item(row))
            removed += len(ids)

        max_entries = self._settings.max_entries
        if max_entries > 0:
            extras = self._conn.execute(
                """
                SELECT * FROM items
                WHERE id NOT IN (
                    SELECT id FROM items ORDER BY last_used_at DESC LIMIT ?
                )
                """,
                (max_entries,),
            ).fetchall()
            if extras:
                ids = [int(row["id"]) for row in extras]
                self._conn.execute(
                    f"DELETE FROM items WHERE id IN ({','.join('?' * len(ids))})",
                    ids,
                )
                self._conn.commit()
                for row in extras:
                    self._cleanup_files(_row_to_item(row))
                removed += len(ids)

        if removed:
            log.info(
                "Pruned %s clipboard items (keep %s days, max %s entries)",
                removed,
                self._settings.retention_days,
                self._settings.max_entries or "unlimited",
            )

    def _fetch_by_hash(self, content_hash: str) -> ClipItem | None:
        row = self._conn.execute(
            "SELECT * FROM items WHERE content_hash = ?",
            (content_hash,),
        ).fetchone()
        return _row_to_item(row) if row else None

    def _cleanup_files(self, item: ClipItem) -> None:
        still_used = self._conn.execute(
            "SELECT 1 FROM items WHERE content_hash = ? LIMIT 1",
            (item.content_hash,),
        ).fetchone()
        if still_used:
            return
        for path in (item.blob_path, item.thumb_path):
            if path is not None and path.exists():
                try:
                    path.unlink()
                except OSError:
                    log.warning("Could not remove %s", path)


def _row_to_item(row: sqlite3.Row) -> ClipItem:
    return ClipItem(
        id=int(row["id"]),
        created_at=int(row["created_at"]),
        last_used_at=int(row["last_used_at"]),
        kind=str(row["kind"]),
        mime=str(row["mime"]),
        text_content=row["text_content"],
        text_preview=row["text_preview"],
        content_hash=str(row["content_hash"]),
        blob_name=row["blob_name"],
        byte_size=int(row["byte_size"]),
        width=row["width"],
        height=row["height"],
    )


def _ext_for_mime(mime: str) -> str:
    return {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/bmp": ".bmp",
        "image/webp": ".webp",
        "image/tiff": ".tiff",
    }.get(mime, ".bin")


def _image_label(width: int | None, height: int | None) -> str:
    if width and height:
        return f"Image {width}×{height}"
    return "Image"


def _write_thumb(content_hash: str, image_bytes: bytes, size: int = 192) -> None:
    dest = thumbs_dir() / f"{content_hash}.png"
    if dest.exists():
        return
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            img = img.convert("RGBA")
            img.thumbnail((size, size), Image.Resampling.LANCZOS)
            img.save(dest, format="PNG")
    except Exception:
        log.exception("Failed to write thumbnail for %s", content_hash)
