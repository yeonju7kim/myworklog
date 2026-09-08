from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from .database import ActivityRow, ActivityStore


@dataclass(frozen=True)
class WorkSession:
    start: int
    end: int
    key_count: int
    click_count: int
    active_minutes: int

    @property
    def span_seconds(self) -> int:
        return max(60, self.end - self.start)


@dataclass(frozen=True)
class DayStats:
    day: date
    key_count: int
    click_count: int
    mouse_samples: int
    active_minutes: int
    estimated_work_seconds: int
    hourly_keys: tuple[int, ...]
    sessions: tuple[WorkSession, ...]
    first_activity: int | None
    last_activity: int | None

    @property
    def busiest_hour(self) -> int | None:
        if not any(self.hourly_keys):
            return None
        return max(range(24), key=self.hourly_keys.__getitem__)


def day_bounds(day: date) -> tuple[int, int]:
    start = datetime.combine(day, time.min).astimezone()
    end = datetime.combine(day + timedelta(days=1), time.min).astimezone()
    return int(start.timestamp()), int(end.timestamp())


def build_sessions(rows: list[ActivityRow], idle_minutes: int) -> tuple[WorkSession, ...]:
    if not rows:
        return ()

    idle_seconds = idle_minutes * 60
    sessions: list[WorkSession] = []
    session_start = rows[0].first_event
    session_end = rows[0].last_event
    key_count = rows[0].key_count
    click_count = rows[0].click_count
    active_minutes = 1

    for row in rows[1:]:
        if row.first_event - session_end > idle_seconds:
            sessions.append(
                WorkSession(
                    start=session_start,
                    end=session_end,
                    key_count=key_count,
                    click_count=click_count,
                    active_minutes=active_minutes,
                )
            )
            session_start = row.first_event
            key_count = 0
            click_count = 0
            active_minutes = 0

        session_end = row.last_event
        key_count += row.key_count
        click_count += row.click_count
        active_minutes += 1

    sessions.append(
        WorkSession(
            start=session_start,
            end=session_end,
            key_count=key_count,
            click_count=click_count,
            active_minutes=active_minutes,
        )
    )
    return tuple(sessions)


def get_day_stats(store: ActivityStore, day: date, idle_minutes: int = 10) -> DayStats:
    start, end = day_bounds(day)
    rows = store.fetch_range(start, end)
    hourly_keys = [0] * 24
    for row in rows:
        hour = datetime.fromtimestamp(row.bucket_start).hour
        hourly_keys[hour] += row.key_count

    sessions = build_sessions(rows, idle_minutes)
    return DayStats(
        day=day,
        key_count=sum(row.key_count for row in rows),
        click_count=sum(row.click_count for row in rows),
        mouse_samples=sum(row.mouse_samples for row in rows),
        active_minutes=len(rows),
        estimated_work_seconds=sum(session.span_seconds for session in sessions),
        hourly_keys=tuple(hourly_keys),
        sessions=sessions,
        first_activity=rows[0].first_event if rows else None,
        last_activity=rows[-1].last_event if rows else None,
    )


def get_daily_key_totals(
    store: ActivityStore, start_day: date, number_of_days: int
) -> list[tuple[date, int]]:
    if number_of_days <= 0:
        return []
    start, _ = day_bounds(start_day)
    _, end = day_bounds(start_day + timedelta(days=number_of_days - 1))
    totals = {start_day + timedelta(days=i): 0 for i in range(number_of_days)}
    for row in store.fetch_range(start, end):
        local_day = datetime.fromtimestamp(row.bucket_start).date()
        if local_day in totals:
            totals[local_day] += row.key_count
    return list(totals.items())

