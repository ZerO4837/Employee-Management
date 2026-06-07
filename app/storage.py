from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sqlite3


def _now() -> datetime:
    return datetime.now()


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat(timespec="microseconds")


def _today() -> str:
    return _now().strftime("%Y-%m-%d")


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return dict(row)


class AttendanceStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_schema(self) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS attendance_days (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    employee_username TEXT NOT NULL,
                    day_date TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    UNIQUE (employee_username, day_date)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS attendance_day_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    day_id INTEGER NOT NULL,
                    employee_username TEXT NOT NULL,
                    day_date TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    event_label TEXT NOT NULL,
                    event_time TEXT NOT NULL,
                    details TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY (day_id) REFERENCES attendance_days (id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS attendance_shifts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    employee_username TEXT NOT NULL,
                    shift_date TEXT NOT NULL,
                    shift_number INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    break_count INTEGER NOT NULL DEFAULT 0,
                    total_break_seconds INTEGER NOT NULL DEFAULT 0,
                    current_break_started_at TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS attendance_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    shift_id INTEGER NOT NULL,
                    employee_username TEXT NOT NULL,
                    shift_date TEXT NOT NULL,
                    shift_number INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    event_label TEXT NOT NULL,
                    event_time TEXT NOT NULL,
                    details TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY (shift_id) REFERENCES attendance_shifts (id)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_attendance_shift_lookup
                ON attendance_shifts (employee_username, shift_date, status)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_attendance_day_lookup
                ON attendance_days (employee_username, day_date, status)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_attendance_events_shift
                ON attendance_events (shift_id, event_time)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_attendance_day_events
                ON attendance_day_events (day_id, event_time)
                """
            )

    def get_active_day(self, employee_username: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM attendance_days
                WHERE employee_username = ? AND status = 'active'
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (employee_username,),
            ).fetchone()
        return _row_to_dict(row)

    def get_day(self, day_id: int) -> dict | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM attendance_days WHERE id = ?", (day_id,)).fetchone()
        return _row_to_dict(row)

    def start_day(self, employee_username: str) -> dict:
        active = self.get_active_day(employee_username)
        if active:
            return active

        day_date = _today()
        started_at = _iso()
        with self.connect() as connection:
            existing = connection.execute(
                """
                SELECT * FROM attendance_days
                WHERE employee_username = ? AND day_date = ?
                """,
                (employee_username, day_date),
            ).fetchone()
            if existing and existing["status"] == "closed":
                return dict(existing)
            if existing:
                day = existing
            else:
                cursor = connection.execute(
                    """
                    INSERT INTO attendance_days
                    (employee_username, day_date, status, started_at)
                    VALUES (?, ?, 'active', ?)
                    """,
                    (employee_username, day_date, started_at),
                )
                day = connection.execute("SELECT * FROM attendance_days WHERE id = ?", (int(cursor.lastrowid),)).fetchone()

        created = _row_to_dict(day)
        if created is None:
            raise RuntimeError("Failed to create attendance day.")
        self.add_day_event(int(created["id"]), "day_start", "Day Started", "Attendance day started")
        return created

    def add_day_event(self, day_id: int, event_type: str, event_label: str, details: str = "") -> None:
        day = self.get_day(day_id)
        if day is None:
            raise ValueError(f"Attendance day {day_id} does not exist.")
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO attendance_day_events
                (day_id, employee_username, day_date, event_type, event_label, event_time, details)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    day_id,
                    day["employee_username"],
                    day["day_date"],
                    event_type,
                    event_label,
                    _iso(),
                    details,
                ),
            )

    def end_day(self, employee_username: str) -> dict | None:
        active_day = self.get_active_day(employee_username)
        if active_day is None:
            return None
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE attendance_days
                SET status = 'closed', ended_at = ?
                WHERE id = ?
                """,
                (_iso(), active_day["id"]),
            )
        self.add_day_event(int(active_day["id"]), "day_end", "Day Ended", "Attendance day closed")
        return self.get_day(int(active_day["id"]))

    def get_active_shift(self, employee_username: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM attendance_shifts
                WHERE employee_username = ? AND status = 'active'
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (employee_username,),
            ).fetchone()
        return _row_to_dict(row)

    def get_shift(self, shift_id: int) -> dict | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM attendance_shifts WHERE id = ?", (shift_id,)).fetchone()
        return _row_to_dict(row)

    def next_shift_number(self, employee_username: str, shift_date: str | None = None) -> int:
        shift_date = shift_date or _today()
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(MAX(shift_number), 0) AS max_shift
                FROM attendance_shifts
                WHERE employee_username = ? AND shift_date = ?
                """,
                (employee_username, shift_date),
            ).fetchone()
        return int(row["max_shift"]) + 1

    def start_shift(self, employee_username: str) -> dict:
        active = self.get_active_shift(employee_username)
        if active:
            return active

        active_day = self.get_active_day(employee_username)
        if active_day is None:
            raise RuntimeError("Start day before checking in.")

        shift_date = active_day["day_date"]
        shift_number = self.next_shift_number(employee_username, shift_date)
        started_at = _iso()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO attendance_shifts
                (employee_username, shift_date, shift_number, status, started_at)
                VALUES (?, ?, ?, 'active', ?)
                """,
                (employee_username, shift_date, shift_number, started_at),
            )
            shift_id = int(cursor.lastrowid)
            shift = connection.execute("SELECT * FROM attendance_shifts WHERE id = ?", (shift_id,)).fetchone()

        created = _row_to_dict(shift)
        if created is None:
            raise RuntimeError("Failed to create attendance shift.")
        self.add_event(shift_id, "check_in", "Check In", f"Shift {shift_number} started")
        return created

    def add_event(self, shift_id: int, event_type: str, event_label: str, details: str = "") -> None:
        shift = self.get_shift(shift_id)
        if shift is None:
            raise ValueError(f"Shift {shift_id} does not exist.")
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO attendance_events
                (shift_id, employee_username, shift_date, shift_number, event_type, event_label, event_time, details)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    shift_id,
                    shift["employee_username"],
                    shift["shift_date"],
                    shift["shift_number"],
                    event_type,
                    event_label,
                    _iso(),
                    details,
                ),
            )

    def start_break(self, shift_id: int) -> dict:
        shift = self.get_shift(shift_id)
        if shift is None:
            raise ValueError(f"Shift {shift_id} does not exist.")
        if shift["current_break_started_at"]:
            return shift

        with self.connect() as connection:
            connection.execute(
                """
                UPDATE attendance_shifts
                SET current_break_started_at = ?, break_count = break_count + 1
                WHERE id = ?
                """,
                (_iso(), shift_id),
            )
        self.add_event(shift_id, "break_start", "Break Started", "Break timer running")
        refreshed = self.get_shift(shift_id)
        if refreshed is None:
            raise RuntimeError("Failed to refresh attendance shift.")
        return refreshed

    def end_break(self, shift_id: int) -> tuple[dict, int]:
        shift = self.get_shift(shift_id)
        if shift is None:
            raise ValueError(f"Shift {shift_id} does not exist.")
        started_at = shift["current_break_started_at"]
        if not started_at:
            return shift, 0

        elapsed = int((_now() - datetime.fromisoformat(started_at)).total_seconds())
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE attendance_shifts
                SET current_break_started_at = NULL,
                    total_break_seconds = total_break_seconds + ?
                WHERE id = ?
                """,
                (max(elapsed, 0), shift_id),
            )
        self.add_event(shift_id, "break_end", "Break Ended", f"Duration: {max(elapsed, 0) // 60}m")
        refreshed = self.get_shift(shift_id)
        if refreshed is None:
            raise RuntimeError("Failed to refresh attendance shift.")
        return refreshed, max(elapsed, 0)

    def close_shift(self, shift_id: int, event_type: str, event_label: str, details: str = "") -> dict:
        shift = self.get_shift(shift_id)
        if shift is None:
            raise ValueError(f"Shift {shift_id} does not exist.")
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE attendance_shifts
                SET status = 'closed', ended_at = ?, current_break_started_at = NULL
                WHERE id = ?
                """,
                (_iso(), shift_id),
            )
        self.add_event(shift_id, event_type, event_label, details)
        refreshed = self.get_shift(shift_id)
        if refreshed is None:
            raise RuntimeError("Failed to refresh attendance shift.")
        return refreshed

    def has_active_shift(self, employee_username: str) -> bool:
        return self.get_active_shift(employee_username) is not None

    def list_shift_summaries(self, limit: int = 250) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM attendance_shifts
                ORDER BY shift_date DESC, shift_number DESC, started_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_events(self, shift_id: int | None = None, limit: int = 500) -> list[dict]:
        with self.connect() as connection:
            if shift_id is None:
                shift_rows = connection.execute(
                    """
                    SELECT * FROM attendance_events
                    ORDER BY event_time DESC, id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
                day_rows = connection.execute(
                    """
                    SELECT
                        id,
                        day_id,
                        employee_username,
                        day_date AS shift_date,
                        0 AS shift_number,
                        event_type,
                        event_label,
                        event_time,
                        details
                    FROM attendance_day_events
                    ORDER BY event_time DESC, id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
                events = [dict(row) for row in shift_rows] + [dict(row) for row in day_rows]
                events.sort(key=lambda item: (item["event_time"], int(item["id"])), reverse=True)
                return events[:limit]
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM attendance_events
                    WHERE shift_id = ?
                    ORDER BY event_time ASC, id ASC
                    LIMIT ?
                    """,
                    (shift_id, limit),
                ).fetchall()
        return [dict(row) for row in rows]

    def list_employee_events(self, employee_username: str, shift_date: str | None = None, limit: int = 100) -> list[dict]:
        if shift_date is None:
            active_day = self.get_active_day(employee_username)
            shift_date = active_day["day_date"] if active_day else _today()
        with self.connect() as connection:
            shift_rows = connection.execute(
                """
                SELECT * FROM attendance_events
                WHERE employee_username = ? AND shift_date = ?
                ORDER BY event_time ASC, id ASC
                LIMIT ?
                """,
                (employee_username, shift_date, limit),
            ).fetchall()
            day_rows = connection.execute(
                """
                SELECT
                    id,
                    day_id,
                    employee_username,
                    day_date AS shift_date,
                    0 AS shift_number,
                    event_type,
                    event_label,
                    event_time,
                    details
                FROM attendance_day_events
                WHERE employee_username = ? AND day_date = ?
                ORDER BY event_time ASC, id ASC
                LIMIT ?
                """,
                (employee_username, shift_date, limit),
            ).fetchall()
        events = [dict(row) for row in shift_rows] + [dict(row) for row in day_rows]
        events.sort(key=lambda item: (item["event_time"], int(item["id"])))
        return events[:limit]
