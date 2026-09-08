from __future__ import annotations

import os
from pathlib import Path


APP_NAME = "MyWorkLog"


def data_dir() -> Path:
    """Return the per-user data directory without writing to the project folder."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / ".local" / "share"
    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def database_path() -> Path:
    return data_dir() / "worklog.db"


def lock_path() -> Path:
    return data_dir() / "myworklog.lock"

