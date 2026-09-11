from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

from .database import ActivityRow, ActivityStore


FLUSH_INTERVAL_SECONDS = 10.0
MOUSE_SAMPLE_INTERVAL_SECONDS = 5.0


@dataclass
class _PendingBucket:
    bucket_start: int
    key_count: int = 0
    click_count: int = 0
    mouse_samples: int = 0
    first_event: int = 0
    last_event: int = 0

    def touch(self, kind: str, timestamp: int) -> None:
        if kind == "key":
            self.key_count += 1
        elif kind == "click":
            self.click_count += 1
        elif kind == "mouse":
            self.mouse_samples += 1
        else:
            raise ValueError(f"Unknown activity kind: {kind}")

        if self.first_event == 0:
            self.first_event = timestamp
        self.last_event = timestamp

    def as_row(self) -> ActivityRow:
        return ActivityRow(
            bucket_start=self.bucket_start,
            key_count=self.key_count,
            click_count=self.click_count,
            mouse_samples=self.mouse_samples,
            first_event=self.first_event,
            last_event=self.last_event,
        )


class ActivityTracker:
    """Low-overhead global input counter.

    Listener callbacks never perform disk I/O. They only update minute counters
    under a small lock; the writer merges all counters in one transaction.
    """

    def __init__(self, store: ActivityStore):
        self.store = store
        self._pending: dict[int, _PendingBucket] = {}
        self._pending_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._paused = threading.Event()
        self._writer_thread: threading.Thread | None = None
        self._keyboard_listener: Any = None
        self._mouse_listener: Any = None
        self._pressed_keys: set[Any] = set()
        self._last_mouse_sample = 0.0
        self._last_activity_timestamp = 0

    @property
    def paused(self) -> bool:
        return self._paused.is_set()

    @property
    def last_activity_timestamp(self) -> int:
        return self._last_activity_timestamp

    def set_paused(self, paused: bool) -> None:
        if paused:
            self._paused.set()
            self._pressed_keys.clear()
        else:
            self._paused.clear()

    def mark_app_activity(self) -> int | None:
        """Ensure an in-app action belongs to the current work session."""
        if self.paused:
            return None
        timestamp = int(time.time())
        self._record("mouse", timestamp)
        return timestamp

    def start(self) -> None:
        if self._writer_thread and self._writer_thread.is_alive():
            return

        # Importing here keeps database/statistics tools usable without pynput.
        from pynput import keyboard, mouse

        self._stop_event.clear()
        self._writer_thread = threading.Thread(
            target=self._writer_loop,
            name="activity-writer",
            daemon=True,
        )
        self._writer_thread.start()

        try:
            self._keyboard_listener = keyboard.Listener(
                on_press=self._on_key_press,
                on_release=self._on_key_release,
            )
            self._mouse_listener = mouse.Listener(
                on_move=self._on_mouse_move,
                on_click=self._on_mouse_click,
            )
            self._keyboard_listener.start()
            self._mouse_listener.start()
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        self._stop_event.set()
        for listener in (self._keyboard_listener, self._mouse_listener):
            if listener is not None:
                listener.stop()
        if self._writer_thread and self._writer_thread.is_alive():
            self._writer_thread.join(timeout=FLUSH_INTERVAL_SECONDS + 2)
        self.flush()

    def _on_key_press(self, key: Any) -> None:
        if self.paused:
            return
        # Windows sends repeated press events while a key is held. Keeping the
        # key object only until release counts the physical press once.
        if key in self._pressed_keys:
            return
        self._pressed_keys.add(key)
        self._record("key")

    def _on_key_release(self, key: Any) -> None:
        self._pressed_keys.discard(key)

    def _on_mouse_click(self, _x: int, _y: int, _button: Any, pressed: bool) -> None:
        if pressed and not self.paused:
            self._record("click")

    def _on_mouse_move(self, _x: int, _y: int) -> None:
        if self.paused:
            return
        now = time.monotonic()
        if now - self._last_mouse_sample < MOUSE_SAMPLE_INTERVAL_SECONDS:
            return
        self._last_mouse_sample = now
        self._record("mouse")

    def _record(self, kind: str, timestamp: int | None = None) -> None:
        event_time = int(time.time()) if timestamp is None else int(timestamp)
        bucket_start = event_time - event_time % 60
        with self._pending_lock:
            bucket = self._pending.get(bucket_start)
            if bucket is None:
                bucket = _PendingBucket(bucket_start=bucket_start)
                self._pending[bucket_start] = bucket
            bucket.touch(kind, event_time)
            self._last_activity_timestamp = event_time

    def flush(self) -> None:
        with self._pending_lock:
            if not self._pending:
                return
            rows = [bucket.as_row() for bucket in self._pending.values()]
            self._pending.clear()
        try:
            self.store.merge_rows(rows)
        except Exception:
            # Never discard counts merely because the database was momentarily
            # busy. Merge them back for the next writer cycle.
            with self._pending_lock:
                for row in rows:
                    bucket = self._pending.get(row.bucket_start)
                    if bucket is None:
                        self._pending[row.bucket_start] = _PendingBucket(
                            bucket_start=row.bucket_start,
                            key_count=row.key_count,
                            click_count=row.click_count,
                            mouse_samples=row.mouse_samples,
                            first_event=row.first_event,
                            last_event=row.last_event,
                        )
                    else:
                        bucket.key_count += row.key_count
                        bucket.click_count += row.click_count
                        bucket.mouse_samples += row.mouse_samples
                        bucket.first_event = min(bucket.first_event, row.first_event)
                        bucket.last_event = max(bucket.last_event, row.last_event)

    def _writer_loop(self) -> None:
        while not self._stop_event.wait(FLUSH_INTERVAL_SECONDS):
            self.flush()
        self.flush()
