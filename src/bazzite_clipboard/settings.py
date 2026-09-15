from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass

from . import RETENTION_DAYS
from .paths import settings_path

log = logging.getLogger(__name__)

MIN_OPACITY = 0.40
MAX_OPACITY = 1.00
DEFAULT_OPACITY = 0.88
DEFAULT_MAX_ENTRIES = 500
DEFAULT_WINDOW_WIDTH = 520
DEFAULT_WINDOW_HEIGHT = 560
MIN_WINDOW_WIDTH = 380
MAX_WINDOW_WIDTH = 1400
MIN_WINDOW_HEIGHT = 360
MAX_WINDOW_HEIGHT = 1100


@dataclass
class Settings:
    panel_opacity: float = DEFAULT_OPACITY
    max_entries: int = DEFAULT_MAX_ENTRIES
    retention_days: int = RETENTION_DAYS
    window_width: int = DEFAULT_WINDOW_WIDTH
    window_height: int = DEFAULT_WINDOW_HEIGHT

    @classmethod
    def load(cls) -> "Settings":
        path = settings_path()
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            log.warning("Could not read %s; using defaults", path)
            return cls()
        if not isinstance(raw, dict):
            return cls()
        opacity = _clamp_float(raw.get("panel_opacity"), DEFAULT_OPACITY, MIN_OPACITY, MAX_OPACITY)
        max_entries = _clamp_int(raw.get("max_entries"), DEFAULT_MAX_ENTRIES, 0, 50_000)
        retention = _clamp_int(raw.get("retention_days"), RETENTION_DAYS, 1, 3650)
        width = _clamp_int(raw.get("window_width"), DEFAULT_WINDOW_WIDTH, MIN_WINDOW_WIDTH, MAX_WINDOW_WIDTH)
        height = _clamp_int(raw.get("window_height"), DEFAULT_WINDOW_HEIGHT, MIN_WINDOW_HEIGHT, MAX_WINDOW_HEIGHT)
        return cls(
            panel_opacity=opacity,
            max_entries=max_entries,
            retention_days=retention,
            window_width=width,
            window_height=height,
        )

    def save(self) -> None:
        path = settings_path()
        payload = asdict(self)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        path.chmod(0o600)


def format_bytes(n: int) -> str:
    value = float(max(0, n))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{n} B"


def _clamp_float(value: object, default: float, lo: float, hi: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, number))


def _clamp_int(value: object, default: int, lo: int, hi: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, number))
