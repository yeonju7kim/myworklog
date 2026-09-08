from __future__ import annotations

import unittest

from myworklog.database import ActivityRow
from myworklog.stats import build_sessions


def row(minute: int, keys: int = 1) -> ActivityRow:
    timestamp = minute * 60
    return ActivityRow(timestamp, keys, 0, 0, timestamp + 1, timestamp + 10)


class SessionTests(unittest.TestCase):
    def test_nearby_activity_is_one_session(self) -> None:
        sessions = build_sessions([row(0, 2), row(5, 3), row(10, 4)], idle_minutes=10)
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].key_count, 9)
        self.assertEqual(sessions[0].active_minutes, 3)

    def test_long_gap_splits_sessions(self) -> None:
        sessions = build_sessions([row(0), row(5), row(20)], idle_minutes=10)
        self.assertEqual(len(sessions), 2)
        self.assertEqual(sessions[0].active_minutes, 2)
        self.assertEqual(sessions[1].active_minutes, 1)

    def test_empty_rows_have_no_sessions(self) -> None:
        self.assertEqual(build_sessions([], idle_minutes=10), ())


if __name__ == "__main__":
    unittest.main()

