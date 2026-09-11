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

    def test_todos_and_session_notes_round_trip(self) -> None:
        first = self.store.add_todo("보고서 작성")
        second = self.store.add_todo("이메일 답장")
        self.store.set_todo_completed(second.id, True)
        self.store.update_todo_title(first.id, "주간 보고서")
        self.store.append_session_note(1_000, "주간 보고서")
        self.store.append_session_note(1_000, "이메일 답장")
        self.store.append_session_note(1_000, "주간 보고서")

        todos = self.store.list_todos()
        notes = self.store.get_session_notes([1_000, 2_000])

        self.assertEqual([todo.title for todo in todos], ["주간 보고서", "이메일 답장"])
        self.assertFalse(todos[0].completed)
        self.assertTrue(todos[1].completed)
        self.assertEqual(notes[1_000], "주간 보고서, 이메일 답장")
        self.assertNotIn(2_000, notes)

        self.store.set_session_note(1_000, "직접 수정한 업무")
        self.assertEqual(self.store.get_session_notes([1_000])[1_000], "직접 수정한 업무")

    def test_empty_todo_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.store.add_todo("   ")

    def test_deleting_todo_keeps_historical_session_note(self) -> None:
        todo = self.store.add_todo("배포 준비")
        self.store.append_session_note(3_000, todo.title)

        self.store.delete_todo(todo.id)

        self.assertEqual(self.store.list_todos(), [])
        self.assertEqual(self.store.get_session_notes([3_000])[3_000], "배포 준비")


if __name__ == "__main__":
    unittest.main()
