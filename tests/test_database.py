from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from myworklog.database import ActivityRow, ActivityStore


class ActivityStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = ActivityStore(Path(self.temp_dir.name) / "test.db")
        self.store.initialize()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_merge_accumulates_counts_and_event_range(self) -> None:
        self.store.merge_rows([ActivityRow(120, 2, 1, 0, 125, 130)])
        self.store.merge_rows([ActivityRow(120, 3, 0, 1, 122, 150)])

        rows = self.store.fetch_range(0, 1000)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].key_count, 5)
        self.assertEqual(rows[0].click_count, 1)
        self.assertEqual(rows[0].mouse_samples, 1)
        self.assertEqual(rows[0].first_event, 122)
        self.assertEqual(rows[0].last_event, 150)

    def test_setting_round_trip(self) -> None:
        self.assertEqual(self.store.get_setting("idle_minutes", "10"), "10")
        self.store.set_setting("idle_minutes", "20")
        self.assertEqual(self.store.get_setting("idle_minutes", "10"), "20")


if __name__ == "__main__":
    unittest.main()

