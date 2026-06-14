from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
import sqlite3


def _now() -> datetime:
    return datetime.now()


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat(timespec="microseconds")


def _today() -> str:
    return _now().strftime("%Y-%m-%d")


def _announcement_cutoff() -> str:
    return (_now() - timedelta(days=3)).isoformat(timespec="microseconds")


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return dict(row)


def _money_text(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _profit_value(buying_amount: str, selling_amount: str) -> str:
    try:
        buying = float((buying_amount or "0").replace(",", ""))
        selling = float((selling_amount or "0").replace(",", ""))
    except ValueError:
        return ""
    return _money_text(selling - buying)


def _normalize_sales_row(row: sqlite3.Row | None) -> dict | None:
    item = _row_to_dict(row)
    if item is None:
        return None
    if not item.get("selling_amount") and item.get("amount"):
        item["selling_amount"] = item["amount"]
    if not item.get("buying_amount"):
        item["buying_amount"] = "0"
    if not item.get("profit"):
        item["profit"] = _profit_value(item.get("buying_amount", "0"), item.get("selling_amount", ""))
    return item


class AttendanceStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        except Exception:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            connection.close()

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
                CREATE TABLE IF NOT EXISTS announcements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    title TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS announcement_reads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    announcement_id INTEGER NOT NULL,
                    employee_username TEXT NOT NULL,
                    read_at TEXT NOT NULL,
                    UNIQUE (announcement_id, employee_username),
                    FOREIGN KEY (announcement_id) REFERENCES announcements (id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS app_settings (
                    setting_key TEXT PRIMARY KEY,
                    setting_value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sales_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    employee_username TEXT NOT NULL,
                    entry_date TEXT NOT NULL,
                    entry_time TEXT NOT NULL,
                    customer TEXT NOT NULL DEFAULT '',
                    platform TEXT NOT NULL DEFAULT '',
                    order_id TEXT NOT NULL DEFAULT '',
                    item TEXT NOT NULL DEFAULT '',
                    quantity TEXT NOT NULL DEFAULT '',
                    amount TEXT NOT NULL DEFAULT '',
                    payment TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    buying_amount TEXT NOT NULL DEFAULT '',
                    selling_amount TEXT NOT NULL DEFAULT '',
                    profit TEXT NOT NULL DEFAULT '',
                    excel_row INTEGER,
                    excel_synced_at TEXT NOT NULL DEFAULT '',
                    excel_sync_error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._ensure_sales_schema(connection)
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
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_announcements_active
                ON announcements (is_active, created_at)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_announcement_reads_lookup
                ON announcement_reads (employee_username, announcement_id)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_app_settings_lookup
                ON app_settings (setting_key)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_sales_entries_lookup
                ON sales_entries (employee_username, entry_date)
                """
            )

    def _ensure_sales_schema(self, connection: sqlite3.Connection) -> None:
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(sales_entries)").fetchall()
        }
        required_columns = {
            "buying_amount": "TEXT NOT NULL DEFAULT ''",
            "selling_amount": "TEXT NOT NULL DEFAULT ''",
            "profit": "TEXT NOT NULL DEFAULT ''",
            "excel_row": "INTEGER",
            "excel_synced_at": "TEXT NOT NULL DEFAULT ''",
            "excel_sync_error": "TEXT NOT NULL DEFAULT ''",
        }
        for name, definition in required_columns.items():
            if name not in columns:
                connection.execute(f"ALTER TABLE sales_entries ADD COLUMN {name} {definition}")
        connection.execute(
            """
            UPDATE sales_entries
            SET selling_amount = amount
            WHERE selling_amount = '' AND amount <> ''
            """
        )
        connection.execute(
            """
            UPDATE sales_entries
            SET buying_amount = '0'
            WHERE buying_amount = ''
            """
        )

    def get_setting(self, key: str, default: str = "") -> str:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT setting_value FROM app_settings WHERE setting_key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return default
        return str(row["setting_value"])

    def set_setting(self, key: str, value: str) -> None:
        updated_at = _iso()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO app_settings (setting_key, setting_value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(setting_key) DO UPDATE SET
                    setting_value = excluded.setting_value,
                    updated_at = excluded.updated_at
                """,
                (key, value, updated_at),
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

    def create_announcement(self, category: str, title: str, message: str, created_by: str) -> dict:
        created_at = _iso()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO announcements
                (category, title, message, created_by, created_at, is_active)
                VALUES (?, ?, ?, ?, ?, 1)
                """,
                (category.strip(), title.strip(), message.strip(), created_by, created_at),
            )
            row = connection.execute("SELECT * FROM announcements WHERE id = ?", (int(cursor.lastrowid),)).fetchone()
        created = _row_to_dict(row)
        if created is None:
            raise RuntimeError("Failed to create announcement.")
        return created

    def list_announcements(self, limit: int = 50, active_only: bool = False) -> list[dict]:
        cutoff = _announcement_cutoff()
        with self.connect() as connection:
            if active_only:
                rows = connection.execute(
                    """
                    SELECT * FROM announcements
                    WHERE is_active = 1 AND created_at >= ?
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?
                    """,
                    (cutoff, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM announcements
                    WHERE created_at >= ?
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?
                    """,
                    (cutoff, limit),
                ).fetchall()
        return [dict(row) for row in rows]

    def list_active_announcements(self, limit: int = 10) -> list[dict]:
        return self.list_announcements(limit=limit, active_only=True)

    def list_employee_announcements(self, employee_username: str, limit: int = 20) -> list[dict]:
        cutoff = _announcement_cutoff()
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    a.*,
                    CASE WHEN r.id IS NULL THEN 0 ELSE 1 END AS is_read
                FROM announcements a
                LEFT JOIN announcement_reads r
                    ON r.announcement_id = a.id
                    AND r.employee_username = ?
                WHERE a.is_active = 1
                    AND a.created_at >= ?
                ORDER BY a.created_at DESC, a.id DESC
                LIMIT ?
                """,
                (employee_username, cutoff, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def unread_announcement_count(self, employee_username: str) -> int:
        cutoff = _announcement_cutoff()
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS unread_count
                FROM announcements a
                LEFT JOIN announcement_reads r
                    ON r.announcement_id = a.id
                    AND r.employee_username = ?
                WHERE a.is_active = 1
                    AND a.created_at >= ?
                    AND r.id IS NULL
                """,
                (employee_username, cutoff),
            ).fetchone()
        return int(row["unread_count"])

    def mark_announcements_read(self, employee_username: str, announcement_ids: list[int]) -> None:
        if not announcement_ids:
            return
        read_at = _iso()
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT OR IGNORE INTO announcement_reads
                (announcement_id, employee_username, read_at)
                VALUES (?, ?, ?)
                """,
                [(announcement_id, employee_username, read_at) for announcement_id in announcement_ids],
            )

    def list_sales_entries(self, employee_username: str, entry_date: str | None = None) -> list[dict]:
        entry_date = entry_date or _today()
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM sales_entries
                WHERE employee_username = ? AND entry_date = ?
                ORDER BY id ASC
                """,
                (employee_username, entry_date),
            ).fetchall()
        return [entry for row in rows if (entry := _normalize_sales_row(row)) is not None]

    def create_sales_entry(self, employee_username: str, entry_date: str, entry: dict[str, str]) -> dict:
        created_at = _iso()
        buying_amount = entry.get("buying_amount", "0")
        selling_amount = entry.get("selling_amount", "")
        profit = _profit_value(buying_amount, selling_amount)
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO sales_entries
                (
                    employee_username, entry_date, entry_time, customer, platform, order_id,
                    item, quantity, amount, payment, status, notes, buying_amount, selling_amount,
                    profit, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    employee_username,
                    entry_date,
                    entry.get("time", ""),
                    entry.get("customer", ""),
                    "",
                    entry.get("order_id", ""),
                    entry.get("item", ""),
                    "",
                    selling_amount,
                    "",
                    entry.get("status", ""),
                    entry.get("notes", ""),
                    buying_amount,
                    selling_amount,
                    profit,
                    created_at,
                    created_at,
                ),
            )
            row = connection.execute("SELECT * FROM sales_entries WHERE id = ?", (int(cursor.lastrowid),)).fetchone()
        created = _normalize_sales_row(row)
        if created is None:
            raise RuntimeError("Failed to create sales entry.")
        return created

    def update_sales_entry(self, entry_id: int, employee_username: str, updates: dict[str, str]) -> dict:
        updated_at = _iso()
        buying_amount = updates.get("buying_amount", "0")
        selling_amount = updates.get("selling_amount", "")
        profit = _profit_value(buying_amount, selling_amount)
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE sales_entries
                SET customer = ?,
                    order_id = ?,
                    item = ?,
                    amount = ?,
                    status = ?,
                    buying_amount = ?,
                    selling_amount = ?,
                    profit = ?,
                    notes = ?,
                    updated_at = ?
                WHERE id = ? AND employee_username = ?
                """,
                (
                    updates.get("customer", ""),
                    updates.get("order_id", ""),
                    updates.get("item", ""),
                    selling_amount,
                    updates.get("status", ""),
                    buying_amount,
                    selling_amount,
                    profit,
                    updates.get("notes", ""),
                    updated_at,
                    entry_id,
                    employee_username,
                ),
            )
            row = connection.execute(
                "SELECT * FROM sales_entries WHERE id = ? AND employee_username = ?",
                (entry_id, employee_username),
            ).fetchone()
        updated = _normalize_sales_row(row)
        if updated is None:
            raise ValueError("Sales entry could not be found.")
        return updated

    def mark_sales_excel_sync(self, entry_id: int, employee_username: str, excel_row: int) -> dict:
        synced_at = _iso()
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE sales_entries
                SET excel_row = ?,
                    excel_synced_at = ?,
                    excel_sync_error = '',
                    updated_at = ?
                WHERE id = ? AND employee_username = ?
                """,
                (excel_row, synced_at, synced_at, entry_id, employee_username),
            )
            row = connection.execute(
                "SELECT * FROM sales_entries WHERE id = ? AND employee_username = ?",
                (entry_id, employee_username),
            ).fetchone()
        synced = _normalize_sales_row(row)
        if synced is None:
            raise ValueError("Sales entry could not be found.")
        return synced

    def mark_sales_excel_error(self, entry_id: int, employee_username: str, error: str) -> dict:
        updated_at = _iso()
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE sales_entries
                SET excel_sync_error = ?,
                    updated_at = ?
                WHERE id = ? AND employee_username = ?
                """,
                (error[:500], updated_at, entry_id, employee_username),
            )
            row = connection.execute(
                "SELECT * FROM sales_entries WHERE id = ? AND employee_username = ?",
                (entry_id, employee_username),
            ).fetchone()
        updated = _normalize_sales_row(row)
        if updated is None:
            raise ValueError("Sales entry could not be found.")
        return updated

    def shift_sales_excel_rows_after(self, deleted_excel_row: int) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE sales_entries
                SET excel_row = excel_row - 1
                WHERE excel_row > ?
                """,
                (deleted_excel_row,),
            )

    def purge_old_synced_sales_entries(self, employee_username: str, cutoff_date: str) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM sales_entries
                WHERE employee_username = ?
                  AND entry_date < ?
                  AND excel_synced_at <> ''
                """,
                (employee_username, cutoff_date),
            )
        return int(cursor.rowcount)

    def delete_sales_entry(self, entry_id: int, employee_username: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "DELETE FROM sales_entries WHERE id = ? AND employee_username = ?",
                (entry_id, employee_username),
            )
