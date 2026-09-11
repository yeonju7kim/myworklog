from __future__ import annotations

import sqlite3
import time
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


@dataclass(frozen=True)
class TodoItem:
    id: int
    title: str
    completed: bool
    created_at: int


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
        connection.execute("PRAGMA foreign_keys = ON")
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

                CREATE TABLE IF NOT EXISTS todos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL CHECK (length(trim(title)) > 0),
                    completed INTEGER NOT NULL DEFAULT 0 CHECK (completed IN (0, 1)),
                    created_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS session_notes (
                    session_start INTEGER PRIMARY KEY,
                    note TEXT NOT NULL,
                    updated_at INTEGER NOT NULL
                );

                PRAGMA user_version = 3;
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

    def list_todos(self) -> list[TodoItem]:
        with self.session() as connection:
            rows = connection.execute(
                """
                SELECT id, title, completed, created_at
                FROM todos
                ORDER BY completed ASC, created_at DESC, id DESC
                """
            ).fetchall()
        return [
            TodoItem(
                id=int(row["id"]),
                title=str(row["title"]),
                completed=bool(row["completed"]),
                created_at=int(row["created_at"]),
            )
            for row in rows
        ]

    def add_todo(self, title: str) -> TodoItem:
        clean_title = title.strip()
        if not clean_title:
            raise ValueError("Todo 제목은 비어 있을 수 없습니다.")
        created_at = int(time.time())
        with self.session() as connection:
            cursor = connection.execute(
                "INSERT INTO todos(title, completed, created_at) VALUES (?, 0, ?)",
                (clean_title, created_at),
            )
            todo_id = int(cursor.lastrowid)
        return TodoItem(todo_id, clean_title, False, created_at)

    def set_todo_completed(self, todo_id: int, completed: bool) -> None:
        with self.session() as connection:
            connection.execute(
                "UPDATE todos SET completed = ? WHERE id = ?",
                (int(completed), todo_id),
            )

    def update_todo_title(self, todo_id: int, title: str) -> None:
        clean_title = title.strip()
        if not clean_title:
            raise ValueError("Todo 제목은 비어 있을 수 없습니다.")
        with self.session() as connection:
            connection.execute(
                "UPDATE todos SET title = ? WHERE id = ?",
                (clean_title, todo_id),
            )

    def delete_todo(self, todo_id: int) -> None:
        """Delete a Todo without touching historical session note text."""
        with self.session() as connection:
            connection.execute("DELETE FROM todos WHERE id = ?", (todo_id,))

    def get_session_notes(self, session_starts: Iterable[int]) -> dict[int, str]:
        starts = list(dict.fromkeys(int(value) for value in session_starts))
        if not starts:
            return {}
        placeholders = ",".join("?" for _ in starts)
        with self.session() as connection:
            rows = connection.execute(
                f"""
                SELECT session_start, note
                FROM session_notes
                WHERE session_start IN ({placeholders})
                """,
                starts,
            ).fetchall()
        return {int(row["session_start"]): str(row["note"]) for row in rows}

    def set_session_note(self, session_start: int, note: str) -> None:
        clean_note = note.strip()
        with self.session() as connection:
            if not clean_note:
                connection.execute(
                    "DELETE FROM session_notes WHERE session_start = ?",
                    (int(session_start),),
                )
                return
            connection.execute(
                """
                INSERT INTO session_notes(session_start, note, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(session_start) DO UPDATE SET
                    note = excluded.note,
                    updated_at = excluded.updated_at
                """,
                (int(session_start), clean_note, int(time.time())),
            )

    def append_session_note(self, session_start: int, todo_title: str) -> str:
        clean_title = todo_title.strip()
        if not clean_title:
            raise ValueError("기록할 Todo 제목은 비어 있을 수 없습니다.")
        with self.session() as connection:
            row = connection.execute(
                "SELECT note FROM session_notes WHERE session_start = ?",
                (int(session_start),),
            ).fetchone()
            entries = (
                [part.strip() for part in str(row["note"]).split(",") if part.strip()]
                if row
                else []
            )
            if clean_title not in entries:
                entries.append(clean_title)
            note = ", ".join(entries)
            connection.execute(
                """
                INSERT INTO session_notes(session_start, note, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(session_start) DO UPDATE SET
                    note = excluded.note,
                    updated_at = excluded.updated_at
                """,
                (int(session_start), note, int(time.time())),
            )
        return note
