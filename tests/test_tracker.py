from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from myworklog.database import ActivityStore
from myworklog.tracker import ActivityTracker


class TrackerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = ActivityStore(Path(self.temp_dir.name) / "tracker.db")
        self.store.initialize()
        self.tracker = ActivityTracker(self.store)

    def tearDown(self) -> None:
        self.tracker.stop()
        self.temp_dir.cleanup()

    def test_held_key_auto_repeat_counts_once(self) -> None:
        key = object()
        self.tracker._on_key_press(key)
        self.tracker._on_key_press(key)
        self.tracker._on_key_press(key)
        self.tracker._on_key_release(key)
        self.tracker._on_key_press(key)
        self.tracker.flush()

        rows = self.store.fetch_range(0, 2**31)
        self.assertEqual(sum(row.key_count for row in rows), 2)

    def test_pause_discards_activity(self) -> None:
        self.tracker.set_paused(True)
        self.tracker._on_key_press(object())
        self.tracker.flush()

        self.assertEqual(self.store.fetch_range(0, 2**31), [])

    def test_counts_only_are_written(self) -> None:
        self.tracker._record("key", timestamp=1_000)
        self.tracker._record("click", timestamp=1_001)
        self.tracker._record("mouse", timestamp=1_002)
        self.tracker.flush()

        row = self.store.fetch_range(0, 2_000)[0]
        self.assertEqual((row.key_count, row.click_count, row.mouse_samples), (1, 1, 1))
        self.assertEqual((row.first_event, row.last_event), (1_000, 1_002))


if __name__ == "__main__":
    unittest.main()
