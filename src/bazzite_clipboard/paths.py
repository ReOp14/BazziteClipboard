from __future__ import annotations

import os
from pathlib import Path


def _xdg_home(env_name: str, fallback: Path) -> Path:
    raw = os.environ.get(env_name, "").strip()
    return Path(raw).expanduser() if raw else fallback


def data_dir() -> Path:
    root = _xdg_home("XDG_DATA_HOME", Path.home() / ".local" / "share")
    path = root / "bazzite-clipboard"
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def state_dir() -> Path:
    root = _xdg_home("XDG_STATE_HOME", Path.home() / ".local" / "state")
    path = root / "bazzite-clipboard"
    path.mkdir(parents=True, exist_ok=True)
    return path


def blobs_dir() -> Path:
    path = data_dir() / "blobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def thumbs_dir() -> Path:
    path = data_dir() / "thumbs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return data_dir() / "history.db"


def log_path() -> Path:
    return state_dir() / "clipboard.log"


def config_dir() -> Path:
    root = _xdg_home("XDG_CONFIG_HOME", Path.home() / ".config")
    path = root / "bazzite-clipboard"
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path() -> Path:
    return config_dir() / "settings.json"
