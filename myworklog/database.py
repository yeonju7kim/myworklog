from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator


@dataclass(frozen=True)
class ActivityRow:
    bucket_start: int
    key_count: int
    click_count: int
    mouse_samples: int
    first_event: int
    last_event: int


class ActivityStore:
    """SQLite persistence for minute-level counters only.

    No key identity, mouse position, window title, or typed text is accepted by
    this API, which keeps the privacy boundary explicit.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        """Yield a transaction and always release its Windows file handle."""
        connection = self.connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.session() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS activity_minute (
                    bucket_start INTEGER PRIMARY KEY,
                    key_count INTEGER NOT NULL DEFAULT 0 CHECK (key_count >= 0),
                    click_count INTEGER NOT NULL DEFAULT 0 CHECK (click_count >= 0),
                    mouse_samples INTEGER NOT NULL DEFAULT 0 CHECK (mouse_samples >= 0),
                    first_event INTEGER NOT NULL,
                    last_event INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS settings (
                    name TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                PRAGMA user_version = 1;
                """
            )

    def merge_rows(
        self,
        rows: Iterable[ActivityRow],
        connection: sqlite3.Connection | None = None,
    ) -> None:
        values = [
            (
                row.bucket_start,
                row.key_count,
                row.click_count,
                row.mouse_samples,
                row.first_event,
                row.last_event,
            )
            for row in rows
        ]
        if not values:
            return

        owns_connection = connection is None
        db = connection or self.connect()
        try:
            db.executemany(
                """
                INSERT INTO activity_minute (
                    bucket_start, key_count, click_count, mouse_samples,
                    first_event, last_event
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(bucket_start) DO UPDATE SET
                    key_count = key_count + excluded.key_count,
                    click_count = click_count + excluded.click_count,
                    mouse_samples = mouse_samples + excluded.mouse_samples,
                    first_event = MIN(first_event, excluded.first_event),
                    last_event = MAX(last_event, excluded.last_event)
                """,
                values,
            )
            db.commit()
        finally:
            if owns_connection:
                db.close()

    def fetch_range(self, start_timestamp: int, end_timestamp: int) -> list[ActivityRow]:
        with self.session() as connection:
            rows = connection.execute(
                """
                SELECT bucket_start, key_count, click_count, mouse_samples,
                       first_event, last_event
                FROM activity_minute
                WHERE bucket_start >= ? AND bucket_start < ?
                ORDER BY bucket_start
                """,
                (start_timestamp, end_timestamp),
            ).fetchall()
        return [ActivityRow(**dict(row)) for row in rows]

    def get_setting(self, name: str, default: str) -> str:
        with self.session() as connection:
            row = connection.execute(
                "SELECT value FROM settings WHERE name = ?", (name,)
            ).fetchone()
        return str(row["value"]) if row else default

    def set_setting(self, name: str, value: str) -> None:
        with self.session() as connection:
            connection.execute(
                """
                INSERT INTO settings(name, value) VALUES (?, ?)
                ON CONFLICT(name) DO UPDATE SET value = excluded.value
                """,
                (name, value),
            )
