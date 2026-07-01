from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
import uuid

from app.config import SALES_SERVICE_NAMES
from app.utils import is_timestamp_newer_or_equal, normalize_local_timestamp, parse_local_datetime


def _now() -> datetime:
    return datetime.now()


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat(timespec="microseconds")


def _today() -> str:
    return _now().strftime("%Y-%m-%d")


_CLOUD_TIMESTAMP_FIELDS = (
    "created_at",
    "updated_at",
    "started_at",
    "ended_at",
    "event_time",
    "current_break_started_at",
    "deleted_at",
)

# Explicit allowlist of app_settings keys that may sync through Supabase.
# This must stay an allowlist, not a blocklist: app_settings also holds
# secrets (the Supabase admin/employee sync secrets themselves) and per-device
# preferences (remembered login username) that must never leave this PC.
CLOUD_SYNCED_SETTING_KEYS = frozenset({"sales_workbook_path", "sales_worksheet_name"})

# Sentinel stored in sales_entries.excel_sync_error when an already-synced
# entry gets edited. Reusing this existing text column (rather than adding a
# new one) lets admin.py distinguish "edited, needs a fresh sync" from a
# genuine sync failure, without a schema migration.
EXCEL_RESYNC_AFTER_EDIT_MESSAGE = "Entry edited after Excel sync; re-sync needed."


def _normalize_cloud_timestamps(item: dict) -> dict:
    """Reformat any offset-aware timestamps from a synced Supabase row to naive local time.

    Without this, a value pulled from the cloud keeps its UTC offset while
    every locally created timestamp is naive, and mixing the two later
    raises `TypeError` the first time something subtracts them (e.g.
    computing elapsed break time).
    """
    normalized = dict(item)
    for field in _CLOUD_TIMESTAMP_FIELDS:
        value = normalized.get(field)
        if value:
            normalized[field] = normalize_local_timestamp(str(value))
    return normalized


def _default_service_cloud_id(service_name: str) -> str:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"dsp-service-catalog:{service_name.strip().casefold()}").hex


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
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA foreign_keys = ON")
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
            connection.execute("PRAGMA journal_mode = WAL")
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
                CREATE TABLE IF NOT EXISTS employee_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    employee_username TEXT NOT NULL,
                    note_type TEXT NOT NULL,
                    note_date TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (employee_username, note_type, note_date)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS service_message_templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    service_name TEXT NOT NULL,
                    title TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS service_catalog (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cloud_id TEXT NOT NULL DEFAULT '',
                    service_name TEXT NOT NULL,
                    created_by TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    cloud_synced_at TEXT NOT NULL DEFAULT '',
                    cloud_sync_error TEXT NOT NULL DEFAULT ''
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS inventory_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cloud_id TEXT NOT NULL DEFAULT '',
                    service_name TEXT NOT NULL,
                    account_email TEXT NOT NULL DEFAULT '',
                    account_password TEXT NOT NULL DEFAULT '',
                    comment TEXT NOT NULL DEFAULT '',
                    created_by TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    cloud_synced_at TEXT NOT NULL DEFAULT '',
                    cloud_sync_error TEXT NOT NULL DEFAULT ''
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
            self._ensure_cloud_schema(connection)
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
                CREATE UNIQUE INDEX IF NOT EXISTS idx_attendance_days_cloud_id
                ON attendance_days (cloud_id)
                WHERE cloud_id <> ''
                """
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_attendance_day_events_cloud_id
                ON attendance_day_events (cloud_id)
                WHERE cloud_id <> ''
                """
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_attendance_shifts_cloud_id
                ON attendance_shifts (cloud_id)
                WHERE cloud_id <> ''
                """
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_attendance_events_cloud_id
                ON attendance_events (cloud_id)
                WHERE cloud_id <> ''
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_attendance_cloud_pending
                ON attendance_shifts (cloud_synced_at, updated_at)
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
                CREATE UNIQUE INDEX IF NOT EXISTS idx_announcements_cloud_id
                ON announcements (cloud_id)
                WHERE cloud_id <> ''
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
                CREATE INDEX IF NOT EXISTS idx_employee_notes_lookup
                ON employee_notes (employee_username, note_type, note_date)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_service_message_templates_active
                ON service_message_templates (is_active, service_name, updated_at)
                """
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_service_message_templates_cloud_id
                ON service_message_templates (cloud_id)
                WHERE cloud_id <> ''
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_service_catalog_active
                ON service_catalog (is_active, service_name, updated_at)
                """
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_service_catalog_cloud_id
                ON service_catalog (cloud_id)
                WHERE cloud_id <> ''
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_inventory_items_active
                ON inventory_items (is_active, service_name, updated_at)
                """
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_inventory_items_cloud_id
                ON inventory_items (cloud_id)
                WHERE cloud_id <> ''
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_sales_entries_lookup
                ON sales_entries (employee_username, entry_date)
                """
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_sales_entries_cloud_id
                ON sales_entries (cloud_id)
                WHERE cloud_id <> ''
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
            "previous_customer": "TEXT NOT NULL DEFAULT ''",
            "previous_item": "TEXT NOT NULL DEFAULT ''",
            "previous_order_id": "TEXT NOT NULL DEFAULT ''",
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

    def _ensure_cloud_schema(self, connection: sqlite3.Connection) -> None:
        required_columns = {
            "attendance_days": {
                "cloud_id": "TEXT NOT NULL DEFAULT ''",
                "updated_at": "TEXT NOT NULL DEFAULT ''",
                "cloud_synced_at": "TEXT NOT NULL DEFAULT ''",
                "cloud_sync_error": "TEXT NOT NULL DEFAULT ''",
            },
            "attendance_day_events": {
                "cloud_id": "TEXT NOT NULL DEFAULT ''",
                "updated_at": "TEXT NOT NULL DEFAULT ''",
                "cloud_synced_at": "TEXT NOT NULL DEFAULT ''",
                "cloud_sync_error": "TEXT NOT NULL DEFAULT ''",
            },
            "attendance_shifts": {
                "cloud_id": "TEXT NOT NULL DEFAULT ''",
                "updated_at": "TEXT NOT NULL DEFAULT ''",
                "cloud_synced_at": "TEXT NOT NULL DEFAULT ''",
                "cloud_sync_error": "TEXT NOT NULL DEFAULT ''",
            },
            "attendance_events": {
                "cloud_id": "TEXT NOT NULL DEFAULT ''",
                "updated_at": "TEXT NOT NULL DEFAULT ''",
                "cloud_synced_at": "TEXT NOT NULL DEFAULT ''",
                "cloud_sync_error": "TEXT NOT NULL DEFAULT ''",
            },
            "announcements": {
                "cloud_id": "TEXT NOT NULL DEFAULT ''",
                "updated_at": "TEXT NOT NULL DEFAULT ''",
                "cloud_synced_at": "TEXT NOT NULL DEFAULT ''",
                "cloud_sync_error": "TEXT NOT NULL DEFAULT ''",
            },
            "service_message_templates": {
                "cloud_id": "TEXT NOT NULL DEFAULT ''",
                "cloud_synced_at": "TEXT NOT NULL DEFAULT ''",
                "cloud_sync_error": "TEXT NOT NULL DEFAULT ''",
            },
            "inventory_items": {
                "cloud_id": "TEXT NOT NULL DEFAULT ''",
                "cloud_synced_at": "TEXT NOT NULL DEFAULT ''",
                "cloud_sync_error": "TEXT NOT NULL DEFAULT ''",
            },
            "service_catalog": {
                "cloud_id": "TEXT NOT NULL DEFAULT ''",
                "created_by": "TEXT NOT NULL DEFAULT ''",
                "cloud_synced_at": "TEXT NOT NULL DEFAULT ''",
                "cloud_sync_error": "TEXT NOT NULL DEFAULT ''",
            },
            "app_settings": {
                "cloud_synced_at": "TEXT NOT NULL DEFAULT ''",
                "cloud_sync_error": "TEXT NOT NULL DEFAULT ''",
            },
            "sales_entries": {
                "cloud_id": "TEXT NOT NULL DEFAULT ''",
                "cloud_synced_at": "TEXT NOT NULL DEFAULT ''",
                "cloud_sync_error": "TEXT NOT NULL DEFAULT ''",
            },
        }
        for table, columns in required_columns.items():
            existing_columns = {
                row["name"]
                for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
            }
            for name, definition in columns.items():
                if name not in existing_columns:
                    connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
        connection.execute(
            """
            UPDATE attendance_days
            SET updated_at = COALESCE(NULLIF(ended_at, ''), started_at)
            WHERE updated_at = ''
            """
        )
        connection.execute(
            """
            UPDATE attendance_day_events
            SET updated_at = event_time
            WHERE updated_at = ''
            """
        )
        connection.execute(
            """
            UPDATE attendance_shifts
            SET updated_at = COALESCE(NULLIF(ended_at, ''), started_at)
            WHERE updated_at = ''
            """
        )
        connection.execute(
            """
            UPDATE attendance_events
            SET updated_at = event_time
            WHERE updated_at = ''
            """
        )
        connection.execute(
            """
            UPDATE announcements
            SET updated_at = created_at
            WHERE updated_at = ''
            """
        )
        self._seed_service_catalog(connection)

    def _seed_service_catalog(self, connection: sqlite3.Connection) -> None:
        now = _iso()
        for service_name in SALES_SERVICE_NAMES:
            name = service_name.strip()
            if not name or name == "Other":
                continue
            canonical_cloud_id = _default_service_cloud_id(name)
            rows = connection.execute(
                "SELECT * FROM service_catalog WHERE LOWER(service_name) = ? ORDER BY is_active DESC, id ASC",
                (name.casefold(),),
            ).fetchall()
            if rows:
                primary = rows[0]
                if primary["cloud_id"] != canonical_cloud_id:
                    canonical_exists = connection.execute(
                        "SELECT id FROM service_catalog WHERE cloud_id = ?",
                        (canonical_cloud_id,),
                    ).fetchone()
                    if canonical_exists is None:
                        connection.execute(
                            """
                            UPDATE service_catalog
                            SET cloud_id = ?,
                                cloud_synced_at = '',
                                cloud_sync_error = ''
                            WHERE id = ?
                            """,
                            (canonical_cloud_id, int(primary["id"])),
                        )
                continue
            connection.execute(
                """
                INSERT INTO service_catalog
                (cloud_id, service_name, created_by, created_at, updated_at, is_active)
                VALUES (?, ?, 'System', ?, ?, 1)
                """,
                (canonical_cloud_id, name, now, now),
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
            if key in CLOUD_SYNCED_SETTING_KEYS:
                connection.execute(
                    """
                    INSERT INTO app_settings (setting_key, setting_value, updated_at, cloud_synced_at, cloud_sync_error)
                    VALUES (?, ?, ?, '', '')
                    ON CONFLICT(setting_key) DO UPDATE SET
                        setting_value = excluded.setting_value,
                        updated_at = excluded.updated_at,
                        cloud_synced_at = '',
                        cloud_sync_error = ''
                    """,
                    (key, value, updated_at),
                )
            else:
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

    def list_cloud_pending_settings(self, limit: int = 20) -> list[dict]:
        keys = tuple(CLOUD_SYNCED_SETTING_KEYS)
        placeholders = ", ".join("?" for _ in keys)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM app_settings
                WHERE setting_key IN ({placeholders})
                    AND (
                        cloud_synced_at = ''
                        OR cloud_synced_at < updated_at
                        OR cloud_sync_error <> ''
                    )
                ORDER BY updated_at ASC
                LIMIT ?
                """,
                (*keys, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_setting_cloud_sync(self, key: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE app_settings
                SET cloud_synced_at = ?,
                    cloud_sync_error = ''
                WHERE setting_key = ?
                """,
                (_iso(), key),
            )

    def mark_setting_cloud_error(self, key: str, error: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE app_settings
                SET cloud_sync_error = ?
                WHERE setting_key = ?
                """,
                (error[:500], key),
            )

    def import_cloud_app_setting(self, item: dict) -> bool:
        key = str(item.get("setting_key", "")).strip()
        if key not in CLOUD_SYNCED_SETTING_KEYS:
            return False
        value = str(item.get("setting_value", ""))
        updated_at = normalize_local_timestamp(str(item.get("updated_at") or _iso()))
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM app_settings WHERE setting_key = ?",
                (key,),
            ).fetchone()
            if existing is not None:
                local_updated = str(existing["updated_at"] or "")
                if is_timestamp_newer_or_equal(local_updated, updated_at) and not existing["cloud_sync_error"]:
                    return False
            connection.execute(
                """
                INSERT INTO app_settings (setting_key, setting_value, updated_at, cloud_synced_at, cloud_sync_error)
                VALUES (?, ?, ?, ?, '')
                ON CONFLICT(setting_key) DO UPDATE SET
                    setting_value = excluded.setting_value,
                    updated_at = excluded.updated_at,
                    cloud_synced_at = excluded.cloud_synced_at,
                    cloud_sync_error = ''
                """,
                (key, value, updated_at, _iso()),
            )
        return True

    def get_employee_note(self, employee_username: str, note_type: str, note_date: str = "") -> dict:
        note_type = note_type.strip().lower()
        note_date = note_date if note_type == "daily" else ""
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM employee_notes
                WHERE employee_username = ?
                  AND note_type = ?
                  AND note_date = ?
                """,
                (employee_username, note_type, note_date),
            ).fetchone()
        note = _row_to_dict(row)
        if note is not None:
            return note
        return {
            "employee_username": employee_username,
            "note_type": note_type,
            "note_date": note_date,
            "content": "",
            "created_at": "",
            "updated_at": "",
        }

    def save_employee_note(self, employee_username: str, note_type: str, content: str, note_date: str = "") -> dict:
        note_type = note_type.strip().lower()
        if note_type not in {"daily", "permanent"}:
            raise ValueError("Note type must be daily or permanent.")
        note_date = note_date if note_type == "daily" else ""
        updated_at = _iso()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO employee_notes
                (employee_username, note_type, note_date, content, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(employee_username, note_type, note_date) DO UPDATE SET
                    content = excluded.content,
                    updated_at = excluded.updated_at
                """,
                (employee_username, note_type, note_date, content, updated_at, updated_at),
            )
            row = connection.execute(
                """
                SELECT * FROM employee_notes
                WHERE employee_username = ?
                  AND note_type = ?
                  AND note_date = ?
                """,
                (employee_username, note_type, note_date),
            ).fetchone()
        saved = _row_to_dict(row)
        if saved is None:
            raise RuntimeError("Failed to save employee note.")
        return saved

    def list_employee_daily_notes(self, employee_username: str, limit: int = 30) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM employee_notes
                WHERE employee_username = ?
                  AND note_type = 'daily'
                  AND TRIM(content) <> ''
                ORDER BY note_date DESC, updated_at DESC
                LIMIT ?
                """,
                (employee_username, limit),
            ).fetchall()
        return [dict(row) for row in rows]

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
        ended_at = _iso()
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE attendance_days
                SET status = 'closed',
                    ended_at = ?,
                    updated_at = ?,
                    cloud_synced_at = '',
                    cloud_sync_error = ''
                WHERE id = ?
                """,
                (ended_at, ended_at, active_day["id"]),
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

        started_at = _iso()
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE attendance_shifts
                SET current_break_started_at = ?,
                    break_count = break_count + 1,
                    updated_at = ?,
                    cloud_synced_at = '',
                    cloud_sync_error = ''
                WHERE id = ?
                """,
                (started_at, started_at, shift_id),
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

        elapsed = int((_now() - parse_local_datetime(started_at)).total_seconds())
        updated_at = _iso()
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE attendance_shifts
                SET current_break_started_at = NULL,
                    total_break_seconds = total_break_seconds + ?,
                    updated_at = ?,
                    cloud_synced_at = '',
                    cloud_sync_error = ''
                WHERE id = ?
                """,
                (max(elapsed, 0), updated_at, shift_id),
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
        ended_at = _iso()
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE attendance_shifts
                SET status = 'closed',
                    ended_at = ?,
                    current_break_started_at = NULL,
                    updated_at = ?,
                    cloud_synced_at = '',
                    cloud_sync_error = ''
                WHERE id = ?
                """,
                (ended_at, ended_at, shift_id),
            )
        self.add_event(shift_id, event_type, event_label, details)
        refreshed = self.get_shift(shift_id)
        if refreshed is None:
            raise RuntimeError("Failed to refresh attendance shift.")
        return refreshed

    def has_active_shift(self, employee_username: str) -> bool:
        return self.get_active_shift(employee_username) is not None

    def purge_old_attendance(self, cutoff_date: str) -> dict[str, int]:
        """Delete attendance days/shifts/events dated before cutoff_date, so
        the local database doesn't grow without bound. Returns a per-table
        row count, mostly useful for testing/visibility."""
        counts: dict[str, int] = {}
        with self.connect() as connection:
            cursor = connection.execute("DELETE FROM attendance_events WHERE shift_date < ?", (cutoff_date,))
            counts["attendance_events"] = int(cursor.rowcount)
            cursor = connection.execute("DELETE FROM attendance_day_events WHERE day_date < ?", (cutoff_date,))
            counts["attendance_day_events"] = int(cursor.rowcount)
            cursor = connection.execute("DELETE FROM attendance_shifts WHERE shift_date < ?", (cutoff_date,))
            counts["attendance_shifts"] = int(cursor.rowcount)
            cursor = connection.execute("DELETE FROM attendance_days WHERE day_date < ?", (cutoff_date,))
            counts["attendance_days"] = int(cursor.rowcount)
        return counts

    def purge_old_attendance_if_due(self, retention_days: int = 30) -> dict[str, int] | None:
        """Runs purge_old_attendance at most once per calendar day (tracked
        via a local-only setting, never cloud-synced - each PC keeps its own
        schedule). Returns the per-table counts if a purge ran, else None."""
        today = _today()
        if self.get_setting("attendance_last_purge_date", "") == today:
            return None
        cutoff = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=retention_days)).strftime("%Y-%m-%d")
        counts = self.purge_old_attendance(cutoff)
        self.set_setting("attendance_last_purge_date", today)
        return counts

    def delete_attendance_shift(self, shift_id: int) -> str:
        """Delete a shift and its events. Returns the shift's cloud_id (may
        be empty) so the caller can also remove the cloud copy - otherwise a
        synced shift would just get silently re-imported on the next pull."""
        with self.connect() as connection:
            row = connection.execute(
                "SELECT cloud_id FROM attendance_shifts WHERE id = ?", (shift_id,)
            ).fetchone()
            cloud_id = str(row["cloud_id"]) if row is not None else ""
            connection.execute("DELETE FROM attendance_events WHERE shift_id = ?", (shift_id,))
            connection.execute("DELETE FROM attendance_shifts WHERE id = ?", (shift_id,))
        return cloud_id

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

    def _attendance_updated_at(self, row: sqlite3.Row | dict, *fallback_keys: str) -> str:
        for key in ("updated_at", *fallback_keys):
            try:
                value = row[key]  # type: ignore[index]
            except (KeyError, IndexError):
                value = ""
            if value:
                return str(value)
        return _iso()

    def _list_cloud_pending_attendance(self, table: str, updated_expr: str, limit: int) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM {table}
                WHERE cloud_id = ''
                    OR cloud_synced_at = ''
                    OR cloud_synced_at < {updated_expr}
                    OR cloud_sync_error <> ''
                ORDER BY {updated_expr} ASC, id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_cloud_pending_attendance_days(self, limit: int = 200) -> list[dict]:
        return self._list_cloud_pending_attendance(
            "attendance_days",
            "COALESCE(NULLIF(updated_at, ''), NULLIF(ended_at, ''), started_at)",
            limit,
        )

    def list_cloud_pending_attendance_day_events(self, limit: int = 300) -> list[dict]:
        return self._list_cloud_pending_attendance(
            "attendance_day_events",
            "COALESCE(NULLIF(updated_at, ''), event_time)",
            limit,
        )

    def list_cloud_pending_attendance_shifts(self, limit: int = 200) -> list[dict]:
        return self._list_cloud_pending_attendance(
            "attendance_shifts",
            "COALESCE(NULLIF(updated_at, ''), NULLIF(ended_at, ''), started_at)",
            limit,
        )

    def list_cloud_pending_attendance_events(self, limit: int = 300) -> list[dict]:
        return self._list_cloud_pending_attendance(
            "attendance_events",
            "COALESCE(NULLIF(updated_at, ''), event_time)",
            limit,
        )

    def _ensure_attendance_cloud_id(self, table: str, row_id: int, *fallback_keys: str) -> dict:
        with self.connect() as connection:
            # BEGIN IMMEDIATE takes the write lock before the read, so two
            # threads ensuring a cloud_id for the same shared parent row
            # (e.g. sibling events of one shift, pushed concurrently) can't
            # both see an empty cloud_id and each mint a different uuid -
            # the second one blocks until the first commits, then sees the
            # cloud_id already set.
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()
            if row is None:
                raise ValueError("Attendance row could not be found.")
            if row["cloud_id"]:
                return dict(row)
            cloud_id = uuid.uuid4().hex
            updated_at = self._attendance_updated_at(row, *fallback_keys)
            connection.execute(
                f"""
                UPDATE {table}
                SET cloud_id = ?,
                    updated_at = ?,
                    cloud_synced_at = '',
                    cloud_sync_error = ''
                WHERE id = ?
                """,
                (cloud_id, updated_at, row_id),
            )
            row = connection.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()
        item = _row_to_dict(row)
        if item is None:
            raise ValueError("Attendance row could not be found.")
        return item

    def ensure_attendance_day_cloud_id(self, day_id: int) -> dict:
        return self._ensure_attendance_cloud_id("attendance_days", day_id, "ended_at", "started_at")

    def ensure_attendance_day_event_cloud_id(self, event_id: int) -> dict:
        return self._ensure_attendance_cloud_id("attendance_day_events", event_id, "event_time")

    def ensure_attendance_shift_cloud_id(self, shift_id: int) -> dict:
        return self._ensure_attendance_cloud_id("attendance_shifts", shift_id, "ended_at", "started_at")

    def ensure_attendance_event_cloud_id(self, event_id: int) -> dict:
        return self._ensure_attendance_cloud_id("attendance_events", event_id, "event_time")

    def _mark_attendance_cloud_sync(self, table: str, row_id: int) -> None:
        with self.connect() as connection:
            connection.execute(
                f"""
                UPDATE {table}
                SET cloud_synced_at = ?,
                    cloud_sync_error = ''
                WHERE id = ?
                """,
                (_iso(), row_id),
            )

    def _mark_attendance_cloud_error(self, table: str, row_id: int, error: str) -> None:
        with self.connect() as connection:
            connection.execute(
                f"""
                UPDATE {table}
                SET cloud_sync_error = ?
                WHERE id = ?
                """,
                (error[:500], row_id),
            )

    def mark_attendance_day_cloud_sync(self, day_id: int) -> None:
        self._mark_attendance_cloud_sync("attendance_days", day_id)

    def mark_attendance_day_event_cloud_sync(self, event_id: int) -> None:
        self._mark_attendance_cloud_sync("attendance_day_events", event_id)

    def mark_attendance_shift_cloud_sync(self, shift_id: int) -> None:
        self._mark_attendance_cloud_sync("attendance_shifts", shift_id)

    def mark_attendance_event_cloud_sync(self, event_id: int) -> None:
        self._mark_attendance_cloud_sync("attendance_events", event_id)

    def mark_attendance_day_cloud_error(self, day_id: int, error: str) -> None:
        self._mark_attendance_cloud_error("attendance_days", day_id, error)

    def mark_attendance_day_event_cloud_error(self, event_id: int, error: str) -> None:
        self._mark_attendance_cloud_error("attendance_day_events", event_id, error)

    def mark_attendance_shift_cloud_error(self, shift_id: int, error: str) -> None:
        self._mark_attendance_cloud_error("attendance_shifts", shift_id, error)

    def mark_attendance_event_cloud_error(self, event_id: int, error: str) -> None:
        self._mark_attendance_cloud_error("attendance_events", event_id, error)

    def import_cloud_attendance_day(self, item: dict) -> bool:
        item = _normalize_cloud_timestamps(item)
        cloud_id = str(item.get("cloud_id", "")).strip()
        employee_username = str(item.get("employee_username", "")).strip()
        day_date = str(item.get("day_date", "")).strip()
        if not cloud_id or not employee_username or not day_date:
            return False
        started_at = str(item.get("started_at") or item.get("updated_at") or _iso())
        updated_at = str(item.get("updated_at") or item.get("ended_at") or started_at)
        ended_at = item.get("ended_at") or None
        with self.connect() as connection:
            existing = connection.execute("SELECT * FROM attendance_days WHERE cloud_id = ?", (cloud_id,)).fetchone()
            if existing is None:
                existing = connection.execute(
                    "SELECT * FROM attendance_days WHERE employee_username = ? AND day_date = ?",
                    (employee_username, day_date),
                ).fetchone()
            if existing is not None:
                local_updated = self._attendance_updated_at(existing, "ended_at", "started_at")
                if existing["cloud_id"] == cloud_id and is_timestamp_newer_or_equal(local_updated, updated_at) and not existing["cloud_sync_error"]:
                    return False
                connection.execute(
                    """
                    UPDATE attendance_days
                    SET cloud_id = ?,
                        employee_username = ?,
                        day_date = ?,
                        status = ?,
                        started_at = ?,
                        ended_at = ?,
                        updated_at = ?,
                        cloud_synced_at = ?,
                        cloud_sync_error = ''
                    WHERE id = ?
                    """,
                    (
                        cloud_id,
                        employee_username,
                        day_date,
                        str(item.get("status", "active")),
                        started_at,
                        ended_at,
                        updated_at,
                        _iso(),
                        int(existing["id"]),
                    ),
                )
                return True
            connection.execute(
                """
                INSERT INTO attendance_days
                (cloud_id, employee_username, day_date, status, started_at, ended_at, updated_at, cloud_synced_at, cloud_sync_error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, '')
                """,
                (
                    cloud_id,
                    employee_username,
                    day_date,
                    str(item.get("status", "active")),
                    started_at,
                    ended_at,
                    updated_at,
                    _iso(),
                ),
            )
        return True

    def import_cloud_attendance_shift(self, item: dict) -> bool:
        item = _normalize_cloud_timestamps(item)
        cloud_id = str(item.get("cloud_id", "")).strip()
        employee_username = str(item.get("employee_username", "")).strip()
        shift_date = str(item.get("shift_date", "")).strip()
        if not cloud_id or not employee_username or not shift_date:
            return False
        shift_number = int(item.get("shift_number") or 1)
        started_at = str(item.get("started_at") or item.get("updated_at") or _iso())
        updated_at = str(item.get("updated_at") or item.get("ended_at") or started_at)
        ended_at = item.get("ended_at") or None
        current_break_started_at = item.get("current_break_started_at") or None
        with self.connect() as connection:
            existing = connection.execute("SELECT * FROM attendance_shifts WHERE cloud_id = ?", (cloud_id,)).fetchone()
            if existing is None:
                existing = connection.execute(
                    """
                    SELECT * FROM attendance_shifts
                    WHERE employee_username = ? AND shift_date = ? AND shift_number = ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (employee_username, shift_date, shift_number),
                ).fetchone()
            if existing is not None:
                local_updated = self._attendance_updated_at(existing, "ended_at", "started_at")
                if existing["cloud_id"] == cloud_id and is_timestamp_newer_or_equal(local_updated, updated_at) and not existing["cloud_sync_error"]:
                    return False
                connection.execute(
                    """
                    UPDATE attendance_shifts
                    SET cloud_id = ?,
                        employee_username = ?,
                        shift_date = ?,
                        shift_number = ?,
                        status = ?,
                        started_at = ?,
                        ended_at = ?,
                        break_count = ?,
                        total_break_seconds = ?,
                        current_break_started_at = ?,
                        updated_at = ?,
                        cloud_synced_at = ?,
                        cloud_sync_error = ''
                    WHERE id = ?
                    """,
                    (
                        cloud_id,
                        employee_username,
                        shift_date,
                        shift_number,
                        str(item.get("status", "active")),
                        started_at,
                        ended_at,
                        int(item.get("break_count") or 0),
                        int(item.get("total_break_seconds") or 0),
                        current_break_started_at,
                        updated_at,
                        _iso(),
                        int(existing["id"]),
                    ),
                )
                return True
            connection.execute(
                """
                INSERT INTO attendance_shifts
                (cloud_id, employee_username, shift_date, shift_number, status, started_at, ended_at, break_count, total_break_seconds, current_break_started_at, updated_at, cloud_synced_at, cloud_sync_error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '')
                """,
                (
                    cloud_id,
                    employee_username,
                    shift_date,
                    shift_number,
                    str(item.get("status", "active")),
                    started_at,
                    ended_at,
                    int(item.get("break_count") or 0),
                    int(item.get("total_break_seconds") or 0),
                    current_break_started_at,
                    updated_at,
                    _iso(),
                ),
            )
        return True

    def import_cloud_attendance_day_event(self, item: dict) -> bool:
        item = _normalize_cloud_timestamps(item)
        cloud_id = str(item.get("cloud_id", "")).strip()
        day_cloud_id = str(item.get("day_cloud_id", "")).strip()
        employee_username = str(item.get("employee_username", "")).strip()
        day_date = str(item.get("day_date", "")).strip()
        if not cloud_id or not employee_username or not day_date:
            return False
        event_time = str(item.get("event_time") or item.get("updated_at") or _iso())
        updated_at = str(item.get("updated_at") or event_time)
        with self.connect() as connection:
            day = None
            if day_cloud_id:
                day = connection.execute("SELECT * FROM attendance_days WHERE cloud_id = ?", (day_cloud_id,)).fetchone()
            if day is None:
                day = connection.execute(
                    "SELECT * FROM attendance_days WHERE employee_username = ? AND day_date = ?",
                    (employee_username, day_date),
                ).fetchone()
            if day is None:
                return False
            existing = connection.execute("SELECT * FROM attendance_day_events WHERE cloud_id = ?", (cloud_id,)).fetchone()
            if existing is not None:
                local_updated = self._attendance_updated_at(existing, "event_time")
                if is_timestamp_newer_or_equal(local_updated, updated_at) and not existing["cloud_sync_error"]:
                    return False
                connection.execute(
                    """
                    UPDATE attendance_day_events
                    SET day_id = ?,
                        employee_username = ?,
                        day_date = ?,
                        event_type = ?,
                        event_label = ?,
                        event_time = ?,
                        details = ?,
                        updated_at = ?,
                        cloud_synced_at = ?,
                        cloud_sync_error = ''
                    WHERE cloud_id = ?
                    """,
                    (
                        int(day["id"]),
                        employee_username,
                        day_date,
                        str(item.get("event_type", "")),
                        str(item.get("event_label", "")),
                        event_time,
                        str(item.get("details", "")),
                        updated_at,
                        _iso(),
                        cloud_id,
                    ),
                )
                return True
            connection.execute(
                """
                INSERT INTO attendance_day_events
                (cloud_id, day_id, employee_username, day_date, event_type, event_label, event_time, details, updated_at, cloud_synced_at, cloud_sync_error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '')
                """,
                (
                    cloud_id,
                    int(day["id"]),
                    employee_username,
                    day_date,
                    str(item.get("event_type", "")),
                    str(item.get("event_label", "")),
                    event_time,
                    str(item.get("details", "")),
                    updated_at,
                    _iso(),
                ),
            )
        return True

    def import_cloud_attendance_event(self, item: dict) -> bool:
        item = _normalize_cloud_timestamps(item)
        cloud_id = str(item.get("cloud_id", "")).strip()
        shift_cloud_id = str(item.get("shift_cloud_id", "")).strip()
        employee_username = str(item.get("employee_username", "")).strip()
        shift_date = str(item.get("shift_date", "")).strip()
        if not cloud_id or not employee_username or not shift_date:
            return False
        shift_number = int(item.get("shift_number") or 1)
        event_time = str(item.get("event_time") or item.get("updated_at") or _iso())
        updated_at = str(item.get("updated_at") or event_time)
        with self.connect() as connection:
            shift = None
            if shift_cloud_id:
                shift = connection.execute("SELECT * FROM attendance_shifts WHERE cloud_id = ?", (shift_cloud_id,)).fetchone()
            if shift is None:
                shift = connection.execute(
                    """
                    SELECT * FROM attendance_shifts
                    WHERE employee_username = ? AND shift_date = ? AND shift_number = ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (employee_username, shift_date, shift_number),
                ).fetchone()
            if shift is None:
                return False
            existing = connection.execute("SELECT * FROM attendance_events WHERE cloud_id = ?", (cloud_id,)).fetchone()
            if existing is not None:
                local_updated = self._attendance_updated_at(existing, "event_time")
                if is_timestamp_newer_or_equal(local_updated, updated_at) and not existing["cloud_sync_error"]:
                    return False
                connection.execute(
                    """
                    UPDATE attendance_events
                    SET shift_id = ?,
                        employee_username = ?,
                        shift_date = ?,
                        shift_number = ?,
                        event_type = ?,
                        event_label = ?,
                        event_time = ?,
                        details = ?,
                        updated_at = ?,
                        cloud_synced_at = ?,
                        cloud_sync_error = ''
                    WHERE cloud_id = ?
                    """,
                    (
                        int(shift["id"]),
                        employee_username,
                        shift_date,
                        shift_number,
                        str(item.get("event_type", "")),
                        str(item.get("event_label", "")),
                        event_time,
                        str(item.get("details", "")),
                        updated_at,
                        _iso(),
                        cloud_id,
                    ),
                )
                return True
            connection.execute(
                """
                INSERT INTO attendance_events
                (cloud_id, shift_id, employee_username, shift_date, shift_number, event_type, event_label, event_time, details, updated_at, cloud_synced_at, cloud_sync_error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '')
                """,
                (
                    cloud_id,
                    int(shift["id"]),
                    employee_username,
                    shift_date,
                    shift_number,
                    str(item.get("event_type", "")),
                    str(item.get("event_label", "")),
                    event_time,
                    str(item.get("details", "")),
                    updated_at,
                    _iso(),
                ),
            )
        return True
    def create_announcement(self, category: str, title: str, message: str, created_by: str) -> dict:
        created_at = _iso()
        cloud_id = uuid.uuid4().hex
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO announcements
                (cloud_id, category, title, message, created_by, created_at, updated_at, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (cloud_id, category.strip(), title.strip(), message.strip(), created_by, created_at, created_at),
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

    def merge_announcement_read_aliases(self, employee_username: str, aliases: list[str]) -> None:
        canonical_username = employee_username.strip()
        normalized_aliases = []
        seen_aliases = set()
        for alias in aliases:
            normalized = alias.strip()
            normalized_key = normalized.casefold()
            if not normalized or normalized_key == canonical_username.casefold() or normalized_key in seen_aliases:
                continue
            normalized_aliases.append(normalized)
            seen_aliases.add(normalized_key)
        if not canonical_username or not normalized_aliases:
            return

        placeholders = ", ".join("?" for _ in normalized_aliases)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT announcement_id, MIN(read_at) AS read_at
                FROM announcement_reads
                WHERE employee_username IN ({placeholders})
                GROUP BY announcement_id
                """,
                tuple(normalized_aliases),
            ).fetchall()
            connection.executemany(
                """
                INSERT OR IGNORE INTO announcement_reads
                (announcement_id, employee_username, read_at)
                VALUES (?, ?, ?)
                """,
                [
                    (int(row["announcement_id"]), canonical_username, row["read_at"] or _iso())
                    for row in rows
                ],
            )
            connection.execute(
                f"DELETE FROM announcement_reads WHERE employee_username IN ({placeholders})",
                tuple(normalized_aliases),
            )

    def deactivate_announcement(self, announcement_id: int) -> None:
        # Soft delete: flip is_active off and bump updated_at so the change is
        # picked up as pending and pushed to the cloud, which then propagates
        # to employee PCs on their next pull (their list/badge queries all
        # filter is_active = 1, so it disappears for them too). A hard DELETE
        # would only remove the local row and never tell other PCs to drop it.
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE announcements
                SET is_active = 0,
                    updated_at = ?,
                    cloud_synced_at = '',
                    cloud_sync_error = ''
                WHERE id = ?
                """,
                (_iso(), announcement_id),
            )

    def list_cloud_pending_announcements(self, limit: int = 100) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM announcements
                WHERE cloud_id = ''
                    OR cloud_synced_at = ''
                    OR cloud_synced_at < updated_at
                    OR cloud_sync_error <> ''
                ORDER BY updated_at ASC, id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def ensure_announcement_cloud_id(self, announcement_id: int) -> dict:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM announcements WHERE id = ?", (announcement_id,)).fetchone()
            if row is None:
                raise ValueError("Announcement could not be found.")
            if row["cloud_id"]:
                return dict(row)
            cloud_id = uuid.uuid4().hex
            updated_at = row["updated_at"] or row["created_at"] or _iso()
            connection.execute(
                """
                UPDATE announcements
                SET cloud_id = ?,
                    updated_at = ?,
                    cloud_synced_at = '',
                    cloud_sync_error = ''
                WHERE id = ?
                """,
                (cloud_id, updated_at, announcement_id),
            )
            row = connection.execute("SELECT * FROM announcements WHERE id = ?", (announcement_id,)).fetchone()
        item = _row_to_dict(row)
        if item is None:
            raise ValueError("Announcement could not be found.")
        return item

    def mark_announcement_cloud_sync(self, announcement_id: int) -> None:
        synced_at = _iso()
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE announcements
                SET cloud_synced_at = ?,
                    cloud_sync_error = ''
                WHERE id = ?
                """,
                (synced_at, announcement_id),
            )

    def mark_announcement_cloud_error(self, announcement_id: int, error: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE announcements
                SET cloud_sync_error = ?
                WHERE id = ?
                """,
                (error[:500], announcement_id),
            )

    def import_cloud_announcement(self, item: dict) -> bool:
        item = _normalize_cloud_timestamps(item)
        cloud_id = str(item.get("cloud_id", "")).strip()
        if not cloud_id:
            return False
        created_at = str(item.get("created_at") or item.get("updated_at") or _iso())
        updated_at = str(item.get("updated_at") or created_at)
        is_active = 1 if bool(item.get("is_active", True)) else 0
        values = (
            str(item.get("category", "")),
            str(item.get("title", "")),
            str(item.get("message", "")),
            str(item.get("created_by", "")),
            created_at,
            updated_at,
            is_active,
            _iso(),
            cloud_id,
        )
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM announcements WHERE cloud_id = ?",
                (cloud_id,),
            ).fetchone()
            if existing is not None:
                local_updated = str(existing["updated_at"] or existing["created_at"] or "")
                if is_timestamp_newer_or_equal(local_updated, updated_at) and not existing["cloud_sync_error"]:
                    return False
                connection.execute(
                    """
                    UPDATE announcements
                    SET category = ?,
                        title = ?,
                        message = ?,
                        created_by = ?,
                        created_at = ?,
                        updated_at = ?,
                        is_active = ?,
                        cloud_synced_at = ?,
                        cloud_sync_error = ''
                    WHERE cloud_id = ?
                    """,
                    values,
                )
                return True
            connection.execute(
                """
                INSERT INTO announcements
                (cloud_id, category, title, message, created_by, created_at, updated_at, is_active, cloud_synced_at, cloud_sync_error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '')
                """,
                (
                    cloud_id,
                    str(item.get("category", "")),
                    str(item.get("title", "")),
                    str(item.get("message", "")),
                    str(item.get("created_by", "")),
                    created_at,
                    updated_at,
                    is_active,
                    _iso(),
                ),
            )
        return True

    def list_service_catalog(self, limit: int = 300, active_only: bool = True) -> list[dict]:
        with self.connect() as connection:
            if active_only:
                rows = connection.execute(
                    """
                    SELECT * FROM service_catalog
                    WHERE is_active = 1
                    ORDER BY service_name COLLATE NOCASE ASC, id ASC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM service_catalog
                    ORDER BY is_active DESC, service_name COLLATE NOCASE ASC, id ASC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [dict(row) for row in rows]

    def list_service_names(self, include_other: bool = True) -> list[str]:
        names = [item["service_name"] for item in self.list_service_catalog(limit=500, active_only=True)]
        if include_other and "Other" not in names:
            names.append("Other")
        return names

    def _service_catalog_duplicate(self, connection: sqlite3.Connection, service_name: str, exclude_id: int | None = None) -> sqlite3.Row | None:
        normalized = service_name.strip().casefold()
        if exclude_id is None:
            return connection.execute(
                "SELECT * FROM service_catalog WHERE LOWER(service_name) = ? AND is_active = 1",
                (normalized,),
            ).fetchone()
        return connection.execute(
            "SELECT * FROM service_catalog WHERE LOWER(service_name) = ? AND id <> ? AND is_active = 1",
            (normalized, exclude_id),
        ).fetchone()

    def create_service_catalog_item(self, service_name: str, created_by: str) -> dict:
        name = service_name.strip()
        if not name or name == "Other":
            raise ValueError("Service name is required.")
        now = _iso()
        with self.connect() as connection:
            duplicate = self._service_catalog_duplicate(connection, name)
            if duplicate is not None:
                raise ValueError("This service already exists in the active Items Sold list.")
            inactive = connection.execute(
                "SELECT * FROM service_catalog WHERE LOWER(service_name) = ? AND is_active = 0 ORDER BY updated_at DESC, id DESC LIMIT 1",
                (name.casefold(),),
            ).fetchone()
            if inactive is not None:
                connection.execute(
                    """
                    UPDATE service_catalog
                    SET service_name = ?,
                        created_by = ?,
                        updated_at = ?,
                        is_active = 1,
                        cloud_synced_at = '',
                        cloud_sync_error = ''
                    WHERE id = ?
                    """,
                    (name, created_by, now, int(inactive["id"])),
                )
                row = connection.execute("SELECT * FROM service_catalog WHERE id = ?", (int(inactive["id"]),)).fetchone()
            else:
                cursor = connection.execute(
                    """
                    INSERT INTO service_catalog
                    (cloud_id, service_name, created_by, created_at, updated_at, is_active)
                    VALUES (?, ?, ?, ?, ?, 1)
                    """,
                    (uuid.uuid4().hex, name, created_by, now, now),
                )
                row = connection.execute("SELECT * FROM service_catalog WHERE id = ?", (int(cursor.lastrowid),)).fetchone()
        created = _row_to_dict(row)
        if created is None:
            raise RuntimeError("Failed to create service item.")
        return created

    def update_service_catalog_item(self, item_id: int, service_name: str) -> dict:
        name = service_name.strip()
        if not name or name == "Other":
            raise ValueError("Service name is required.")
        updated_at = _iso()
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM service_catalog WHERE id = ?", (item_id,)).fetchone()
            if row is None:
                raise ValueError("Service item could not be found.")
            duplicate = self._service_catalog_duplicate(connection, name, exclude_id=item_id)
            if duplicate is not None:
                raise ValueError("This service already exists in the active Items Sold list.")
            connection.execute(
                """
                UPDATE service_catalog
                SET service_name = ?,
                    updated_at = ?,
                    is_active = 1,
                    cloud_synced_at = '',
                    cloud_sync_error = ''
                WHERE id = ?
                """,
                (name, updated_at, item_id),
            )
            updated = connection.execute("SELECT * FROM service_catalog WHERE id = ?", (item_id,)).fetchone()
        item = _row_to_dict(updated)
        if item is None:
            raise RuntimeError("Failed to update service item.")
        return item

    def deactivate_service_catalog_item(self, item_id: int) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE service_catalog
                SET is_active = 0,
                    updated_at = ?,
                    cloud_synced_at = '',
                    cloud_sync_error = ''
                WHERE id = ?
                """,
                (_iso(), item_id),
            )

    def list_cloud_pending_service_catalog(self, limit: int = 300) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM service_catalog
                WHERE cloud_id = ''
                    OR cloud_synced_at = ''
                    OR cloud_synced_at < updated_at
                    OR cloud_sync_error <> ''
                ORDER BY updated_at ASC, id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def ensure_service_catalog_cloud_id(self, item_id: int) -> dict:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM service_catalog WHERE id = ?", (item_id,)).fetchone()
            if row is None:
                raise ValueError("Service item could not be found.")
            if row["cloud_id"]:
                return dict(row)
            cloud_id = uuid.uuid4().hex
            updated_at = row["updated_at"] or row["created_at"] or _iso()
            connection.execute(
                """
                UPDATE service_catalog
                SET cloud_id = ?,
                    updated_at = ?,
                    cloud_synced_at = '',
                    cloud_sync_error = ''
                WHERE id = ?
                """,
                (cloud_id, updated_at, item_id),
            )
            row = connection.execute("SELECT * FROM service_catalog WHERE id = ?", (item_id,)).fetchone()
        item = _row_to_dict(row)
        if item is None:
            raise ValueError("Service item could not be found.")
        return item

    def mark_service_catalog_cloud_sync(self, item_id: int) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE service_catalog
                SET cloud_synced_at = ?,
                    cloud_sync_error = ''
                WHERE id = ?
                """,
                (_iso(), item_id),
            )

    def mark_service_catalog_cloud_error(self, item_id: int, error: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE service_catalog
                SET cloud_sync_error = ?
                WHERE id = ?
                """,
                (error[:500], item_id),
            )

    def import_cloud_service_catalog_item(self, item: dict) -> bool:
        item = _normalize_cloud_timestamps(item)
        cloud_id = str(item.get("cloud_id", "")).strip()
        service_name = str(item.get("service_name", "")).strip()
        if not cloud_id or not service_name or service_name == "Other":
            return False
        created_at = str(item.get("created_at") or item.get("updated_at") or _iso())
        updated_at = str(item.get("updated_at") or created_at)
        is_active = 1 if bool(item.get("is_active", True)) else 0
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM service_catalog WHERE cloud_id = ?",
                (cloud_id,),
            ).fetchone()
            if existing is None:
                existing = connection.execute(
                    "SELECT * FROM service_catalog WHERE LOWER(service_name) = ? ORDER BY is_active DESC, id ASC LIMIT 1",
                    (service_name.casefold(),),
                ).fetchone()
            if existing is not None:
                local_updated = str(existing["updated_at"] or existing["created_at"] or "")
                if is_timestamp_newer_or_equal(local_updated, updated_at) and not existing["cloud_sync_error"]:
                    return False
                connection.execute(
                    """
                    UPDATE service_catalog
                    SET cloud_id = ?,
                        service_name = ?,
                        created_by = ?,
                        created_at = ?,
                        updated_at = ?,
                        is_active = ?,
                        cloud_synced_at = ?,
                        cloud_sync_error = ''
                    WHERE id = ?
                    """,
                    (
                        cloud_id,
                        service_name,
                        str(item.get("created_by", "")),
                        created_at,
                        updated_at,
                        is_active,
                        _iso(),
                        int(existing["id"]),
                    ),
                )
                return True
            connection.execute(
                """
                INSERT INTO service_catalog
                (cloud_id, service_name, created_by, created_at, updated_at, is_active, cloud_synced_at, cloud_sync_error)
                VALUES (?, ?, ?, ?, ?, ?, ?, '')
                """,
                (
                    cloud_id,
                    service_name,
                    str(item.get("created_by", "")),
                    created_at,
                    updated_at,
                    is_active,
                    _iso(),
                ),
            )
        return True
    def create_inventory_item(
        self,
        service_name: str,
        account_email: str,
        account_password: str,
        comment: str,
        created_by: str,
    ) -> dict:
        created_at = _iso()
        cloud_id = uuid.uuid4().hex
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO inventory_items
                (cloud_id, service_name, account_email, account_password, comment, created_by, created_at, updated_at, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    cloud_id,
                    service_name.strip(),
                    account_email.strip(),
                    account_password.strip(),
                    comment.strip(),
                    created_by,
                    created_at,
                    created_at,
                ),
            )
            row = connection.execute("SELECT * FROM inventory_items WHERE id = ?", (int(cursor.lastrowid),)).fetchone()
        created = _row_to_dict(row)
        if created is None:
            raise RuntimeError("Failed to create inventory item.")
        return created

    def update_inventory_item(
        self,
        item_id: int,
        service_name: str,
        account_email: str,
        account_password: str,
        comment: str,
    ) -> dict:
        updated_at = _iso()
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE inventory_items
                SET service_name = ?,
                    account_email = ?,
                    account_password = ?,
                    comment = ?,
                    updated_at = ?,
                    cloud_synced_at = '',
                    cloud_sync_error = ''
                WHERE id = ? AND is_active = 1
                """,
                (service_name.strip(), account_email.strip(), account_password.strip(), comment.strip(), updated_at, item_id),
            )
            row = connection.execute("SELECT * FROM inventory_items WHERE id = ?", (item_id,)).fetchone()
        updated = _row_to_dict(row)
        if updated is None:
            raise RuntimeError("Failed to update inventory item.")
        return updated

    def deactivate_inventory_item(self, item_id: int) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE inventory_items
                SET is_active = 0,
                    updated_at = ?,
                    cloud_synced_at = '',
                    cloud_sync_error = ''
                WHERE id = ?
                """,
                (_iso(), item_id),
            )

    def list_inventory_items(self, limit: int = 500, active_only: bool = True) -> list[dict]:
        with self.connect() as connection:
            if active_only:
                rows = connection.execute(
                    """
                    SELECT * FROM inventory_items
                    WHERE is_active = 1
                    ORDER BY service_name COLLATE NOCASE ASC, account_email COLLATE NOCASE ASC, updated_at DESC, id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM inventory_items
                    ORDER BY updated_at DESC, id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [dict(row) for row in rows]

    def list_cloud_pending_inventory_items(self, limit: int = 200) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM inventory_items
                WHERE cloud_id = ''
                    OR cloud_synced_at = ''
                    OR cloud_synced_at < updated_at
                    OR cloud_sync_error <> ''
                ORDER BY updated_at ASC, id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def ensure_inventory_item_cloud_id(self, item_id: int) -> dict:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM inventory_items WHERE id = ?", (item_id,)).fetchone()
            if row is None:
                raise ValueError("Inventory item could not be found.")
            if row["cloud_id"]:
                return dict(row)
            cloud_id = uuid.uuid4().hex
            updated_at = row["updated_at"] or row["created_at"] or _iso()
            connection.execute(
                """
                UPDATE inventory_items
                SET cloud_id = ?,
                    updated_at = ?,
                    cloud_synced_at = '',
                    cloud_sync_error = ''
                WHERE id = ?
                """,
                (cloud_id, updated_at, item_id),
            )
            row = connection.execute("SELECT * FROM inventory_items WHERE id = ?", (item_id,)).fetchone()
        item = _row_to_dict(row)
        if item is None:
            raise ValueError("Inventory item could not be found.")
        return item

    def mark_inventory_item_cloud_sync(self, item_id: int) -> None:
        synced_at = _iso()
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE inventory_items
                SET cloud_synced_at = ?,
                    cloud_sync_error = ''
                WHERE id = ?
                """,
                (synced_at, item_id),
            )

    def mark_inventory_item_cloud_error(self, item_id: int, error: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE inventory_items
                SET cloud_sync_error = ?
                WHERE id = ?
                """,
                (error[:500], item_id),
            )

    def import_cloud_inventory_item(self, item: dict) -> bool:
        item = _normalize_cloud_timestamps(item)
        cloud_id = str(item.get("cloud_id", "")).strip()
        if not cloud_id:
            return False
        service_name = str(item.get("service_name", "")).strip()
        if not service_name:
            return False
        created_at = str(item.get("created_at") or item.get("updated_at") or _iso())
        updated_at = str(item.get("updated_at") or created_at)
        is_active = 1 if bool(item.get("is_active", True)) else 0
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM inventory_items WHERE cloud_id = ?",
                (cloud_id,),
            ).fetchone()
            if existing is not None:
                local_updated = str(existing["updated_at"] or existing["created_at"] or "")
                if is_timestamp_newer_or_equal(local_updated, updated_at) and not existing["cloud_sync_error"]:
                    return False
                connection.execute(
                    """
                    UPDATE inventory_items
                    SET service_name = ?,
                        account_email = ?,
                        account_password = ?,
                        comment = ?,
                        created_by = ?,
                        created_at = ?,
                        updated_at = ?,
                        is_active = ?,
                        cloud_synced_at = ?,
                        cloud_sync_error = ''
                    WHERE cloud_id = ?
                    """,
                    (
                        service_name,
                        str(item.get("account_email", "")),
                        str(item.get("account_password", "")),
                        str(item.get("comment", "")),
                        str(item.get("created_by", "")),
                        created_at,
                        updated_at,
                        is_active,
                        _iso(),
                        cloud_id,
                    ),
                )
                return True
            connection.execute(
                """
                INSERT INTO inventory_items
                (cloud_id, service_name, account_email, account_password, comment, created_by, created_at, updated_at, is_active, cloud_synced_at, cloud_sync_error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '')
                """,
                (
                    cloud_id,
                    service_name,
                    str(item.get("account_email", "")),
                    str(item.get("account_password", "")),
                    str(item.get("comment", "")),
                    str(item.get("created_by", "")),
                    created_at,
                    updated_at,
                    is_active,
                    _iso(),
                ),
            )
        return True
    def list_cloud_pending_service_message_templates(self, limit: int = 150) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM service_message_templates
                WHERE cloud_id = ''
                    OR cloud_synced_at = ''
                    OR cloud_synced_at < updated_at
                    OR cloud_sync_error <> ''
                ORDER BY updated_at ASC, id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def ensure_service_message_template_cloud_id(self, template_id: int) -> dict:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM service_message_templates WHERE id = ?", (template_id,)).fetchone()
            if row is None:
                raise ValueError("Service message could not be found.")
            if row["cloud_id"]:
                return dict(row)
            cloud_id = uuid.uuid4().hex
            updated_at = row["updated_at"] or row["created_at"] or _iso()
            connection.execute(
                """
                UPDATE service_message_templates
                SET cloud_id = ?,
                    updated_at = ?,
                    cloud_synced_at = '',
                    cloud_sync_error = ''
                WHERE id = ?
                """,
                (cloud_id, updated_at, template_id),
            )
            row = connection.execute("SELECT * FROM service_message_templates WHERE id = ?", (template_id,)).fetchone()
        item = _row_to_dict(row)
        if item is None:
            raise ValueError("Service message could not be found.")
        return item

    def mark_service_message_template_cloud_sync(self, template_id: int) -> None:
        synced_at = _iso()
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE service_message_templates
                SET cloud_synced_at = ?,
                    cloud_sync_error = ''
                WHERE id = ?
                """,
                (synced_at, template_id),
            )

    def mark_service_message_template_cloud_error(self, template_id: int, error: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE service_message_templates
                SET cloud_sync_error = ?
                WHERE id = ?
                """,
                (error[:500], template_id),
            )

    def import_cloud_service_message_template(self, item: dict) -> bool:
        item = _normalize_cloud_timestamps(item)
        cloud_id = str(item.get("cloud_id", "")).strip()
        if not cloud_id:
            return False
        service_name = str(item.get("service_name", "")).strip()
        if not service_name:
            return False
        created_at = str(item.get("created_at") or item.get("updated_at") or _iso())
        updated_at = str(item.get("updated_at") or created_at)
        is_active = 1 if bool(item.get("is_active", True)) else 0
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM service_message_templates WHERE cloud_id = ?",
                (cloud_id,),
            ).fetchone()
            if existing is not None:
                local_updated = str(existing["updated_at"] or existing["created_at"] or "")
                if is_timestamp_newer_or_equal(local_updated, updated_at) and not existing["cloud_sync_error"]:
                    return False
                connection.execute(
                    """
                    UPDATE service_message_templates
                    SET service_name = ?,
                        title = ?,
                        message = ?,
                        created_by = ?,
                        created_at = ?,
                        updated_at = ?,
                        is_active = ?,
                        cloud_synced_at = ?,
                        cloud_sync_error = ''
                    WHERE cloud_id = ?
                    """,
                    (
                        service_name,
                        str(item.get("title") or service_name),
                        str(item.get("message", "")),
                        str(item.get("created_by", "")),
                        created_at,
                        updated_at,
                        is_active,
                        _iso(),
                        cloud_id,
                    ),
                )
                return True
            connection.execute(
                """
                INSERT INTO service_message_templates
                (cloud_id, service_name, title, message, created_by, created_at, updated_at, is_active, cloud_synced_at, cloud_sync_error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '')
                """,
                (
                    cloud_id,
                    service_name,
                    str(item.get("title") or service_name),
                    str(item.get("message", "")),
                    str(item.get("created_by", "")),
                    created_at,
                    updated_at,
                    is_active,
                    _iso(),
                ),
            )
        return True
    def create_service_message_template(
        self,
        service_name: str,
        message: str,
        created_by: str,
    ) -> dict:
        created_at = _iso()
        cloud_id = uuid.uuid4().hex
        service_name = service_name.strip()
        message = message.strip()
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE service_message_templates
                SET is_active = 0,
                    updated_at = ?
                WHERE is_active = 1
                    AND LOWER(service_name) = LOWER(?)
                """,
                (created_at, service_name),
            )
            cursor = connection.execute(
                """
                INSERT INTO service_message_templates
                (cloud_id, service_name, title, message, created_by, created_at, updated_at, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (cloud_id, service_name, service_name, message, created_by, created_at, created_at),
            )
            row = connection.execute(
                "SELECT * FROM service_message_templates WHERE id = ?",
                (int(cursor.lastrowid),),
            ).fetchone()
        created = _row_to_dict(row)
        if created is None:
            raise RuntimeError("Failed to create service message template.")
        return created

    def update_service_message_template(self, template_id: int, service_name: str, message: str) -> dict:
        updated_at = _iso()
        service_name = service_name.strip()
        message = message.strip()
        with self.connect() as connection:
            existing = connection.execute(
                """
                SELECT * FROM service_message_templates
                WHERE id = ? AND is_active = 1
                """,
                (template_id,),
            ).fetchone()
            if existing is None:
                raise ValueError("Service message could not be found.")
            connection.execute(
                """
                UPDATE service_message_templates
                SET is_active = 0,
                    updated_at = ?
                WHERE is_active = 1
                    AND id <> ?
                    AND LOWER(service_name) = LOWER(?)
                """,
                (updated_at, template_id, service_name),
            )
            connection.execute(
                """
                UPDATE service_message_templates
                SET service_name = ?,
                    title = ?,
                    message = ?,
                    updated_at = ?,
                    cloud_synced_at = '',
                    cloud_sync_error = ''
                WHERE id = ? AND is_active = 1
                """,
                (service_name, service_name, message, updated_at, template_id),
            )
            row = connection.execute(
                "SELECT * FROM service_message_templates WHERE id = ?",
                (template_id,),
            ).fetchone()
        updated = _row_to_dict(row)
        if updated is None:
            raise RuntimeError("Failed to update service message template.")
        return updated

    def list_service_message_templates(self, limit: int = 200, active_only: bool = True) -> list[dict]:
        with self.connect() as connection:
            if active_only:
                rows = connection.execute(
                    """
                    SELECT * FROM service_message_templates
                    WHERE is_active = 1
                    ORDER BY service_name COLLATE NOCASE ASC, updated_at DESC, id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM service_message_templates
                    ORDER BY updated_at DESC, id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [dict(row) for row in rows]

    def deactivate_service_message_template(self, template_id: int) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE service_message_templates
                SET is_active = 0,
                    updated_at = ?,
                    cloud_synced_at = '',
                    cloud_sync_error = ''
                WHERE id = ?
                """,
                (_iso(), template_id),
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

    def list_sales_entries_between(
        self,
        start_date: str,
        end_date: str,
        employee_username: str | None = None,
    ) -> list[dict]:
        params: list[str] = [start_date, end_date]
        employee_filter = ""
        if employee_username:
            employee_filter = "AND employee_username = ?"
            params.append(employee_username)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM sales_entries
                WHERE entry_date BETWEEN ? AND ?
                {employee_filter}
                ORDER BY entry_date DESC, created_at DESC
                """,
                tuple(params),
            ).fetchall()
        return [entry for row in rows if (entry := _normalize_sales_row(row)) is not None]

    def list_sales_entries_needing_excel_sync(self, limit: int = 1000) -> list[dict]:
        # Oldest first: screen-shared services (Netflix/HBO) append each new
        # customer to the same Excel row in the order they were sold, so a
        # batch sync must process entries in that same chronological order.
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM sales_entries
                WHERE excel_synced_at = ''
                  AND LOWER(excel_sync_error) NOT LIKE '%account is full%'
                ORDER BY entry_date ASC, created_at ASC
                LIMIT ?
                """,
                (limit,),
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
            previous = connection.execute(
                """
                SELECT customer, item, order_id, excel_synced_at
                FROM sales_entries
                WHERE id = ? AND employee_username = ?
                """,
                (entry_id, employee_username),
            ).fetchone()
            if previous is None:
                raise ValueError("Sales entry could not be found.")
            needs_excel_resync = bool(previous["excel_synced_at"])
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
                    previous_customer = ?,
                    previous_item = ?,
                    previous_order_id = ?,
                    updated_at = ?,
                    cloud_synced_at = '',
                    cloud_sync_error = ''
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
                    previous["customer"],
                    previous["item"],
                    previous["order_id"],
                    updated_at,
                    entry_id,
                    employee_username,
                ),
            )
            if needs_excel_resync:
                connection.execute(
                    """
                    UPDATE sales_entries
                    SET excel_synced_at = '',
                        excel_sync_error = ?
                    WHERE id = ? AND employee_username = ?
                    """,
                    (EXCEL_RESYNC_AFTER_EDIT_MESSAGE, entry_id, employee_username),
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
                    previous_customer = '',
                    previous_item = '',
                    previous_order_id = '',
                    updated_at = ?,
                    cloud_synced_at = '',
                    cloud_sync_error = ''
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
                    excel_synced_at = '',
                    updated_at = ?,
                    cloud_synced_at = '',
                    cloud_sync_error = ''
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

    def delete_blocked_sales_entries(self, employee_username: str | None = None) -> int:
        params: list[str] = []
        employee_filter = ""
        if employee_username:
            employee_filter = "AND employee_username = ?"
            params.append(employee_username)
        with self.connect() as connection:
            cursor = connection.execute(
                f"""
                DELETE FROM sales_entries
                WHERE excel_synced_at = ''
                  AND LOWER(excel_sync_error) LIKE '%account is full%'
                  {employee_filter}
                """,
                tuple(params),
            )
        return int(cursor.rowcount)

    def delete_sales_entry(self, entry_id: int, employee_username: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "DELETE FROM sales_entries WHERE id = ? AND employee_username = ?",
                (entry_id, employee_username),
            )

    def list_cloud_pending_sales_entries(self, limit: int = 200) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM sales_entries
                WHERE cloud_id = ''
                    OR cloud_synced_at = ''
                    OR cloud_synced_at < updated_at
                    OR cloud_sync_error <> ''
                ORDER BY updated_at ASC, id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [entry for row in rows if (entry := _normalize_sales_row(row)) is not None]

    def ensure_sales_entry_cloud_id(self, entry_id: int) -> dict:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM sales_entries WHERE id = ?", (entry_id,)).fetchone()
            if row is None:
                raise ValueError("Sales entry could not be found.")
            if not row["cloud_id"]:
                connection.execute(
                    """
                    UPDATE sales_entries
                    SET cloud_id = ?,
                        cloud_synced_at = '',
                        cloud_sync_error = ''
                    WHERE id = ?
                    """,
                    (uuid.uuid4().hex, entry_id),
                )
                row = connection.execute("SELECT * FROM sales_entries WHERE id = ?", (entry_id,)).fetchone()
        item = _normalize_sales_row(row)
        if item is None:
            raise ValueError("Sales entry could not be found.")
        return item

    def mark_sales_entry_cloud_sync(self, entry_id: int) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE sales_entries
                SET cloud_synced_at = ?,
                    cloud_sync_error = ''
                WHERE id = ?
                """,
                (_iso(), entry_id),
            )

    def mark_sales_entry_cloud_error(self, entry_id: int, error: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE sales_entries
                SET cloud_sync_error = ?
                WHERE id = ?
                """,
                (error[:500], entry_id),
            )

    def import_cloud_sales_entry(self, item: dict) -> bool:
        cloud_id = str(item.get("cloud_id", "")).strip()
        employee_username = str(item.get("employee_username", "")).strip()
        entry_date = str(item.get("entry_date", "")).strip()
        if not cloud_id or not employee_username or not entry_date:
            return False
        created_at = normalize_local_timestamp(str(item.get("created_at") or item.get("updated_at") or _iso()))
        updated_at = normalize_local_timestamp(str(item.get("updated_at") or created_at))
        excel_synced_at = normalize_local_timestamp(str(item.get("excel_synced_at") or ""))
        buying_amount = str(item.get("buying_amount") or "0")
        selling_amount = str(item.get("selling_amount") or "")
        profit = str(item.get("profit") or "") or _profit_value(buying_amount, selling_amount)
        excel_row = item.get("excel_row")
        try:
            excel_row = int(excel_row) if excel_row not in (None, "") else None
        except (TypeError, ValueError):
            excel_row = None

        with self.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM sales_entries WHERE cloud_id = ?",
                (cloud_id,),
            ).fetchone()
            if existing is not None:
                local_updated = str(existing["updated_at"] or "")
                if is_timestamp_newer_or_equal(local_updated, updated_at) and not existing["cloud_sync_error"]:
                    return False
                connection.execute(
                    """
                    UPDATE sales_entries
                    SET employee_username = ?,
                        entry_date = ?,
                        entry_time = ?,
                        customer = ?,
                        item = ?,
                        order_id = ?,
                        buying_amount = ?,
                        selling_amount = ?,
                        amount = ?,
                        profit = ?,
                        status = ?,
                        notes = ?,
                        excel_row = ?,
                        excel_synced_at = ?,
                        excel_sync_error = ?,
                        updated_at = ?,
                        cloud_synced_at = ?,
                        cloud_sync_error = ''
                    WHERE cloud_id = ?
                    """,
                    (
                        employee_username,
                        entry_date,
                        str(item.get("entry_time", "")),
                        str(item.get("customer", "")),
                        str(item.get("item", "")),
                        str(item.get("order_id", "")),
                        buying_amount,
                        selling_amount,
                        selling_amount,
                        profit,
                        str(item.get("status", "")),
                        str(item.get("notes", "")),
                        excel_row,
                        excel_synced_at,
                        str(item.get("excel_sync_error", "")),
                        updated_at,
                        _iso(),
                        cloud_id,
                    ),
                )
                return True
            connection.execute(
                """
                INSERT INTO sales_entries
                (cloud_id, employee_username, entry_date, entry_time, customer, item, order_id,
                 buying_amount, selling_amount, amount, profit, status, notes,
                 excel_row, excel_synced_at, excel_sync_error, created_at, updated_at,
                 cloud_synced_at, cloud_sync_error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '')
                """,
                (
                    cloud_id,
                    employee_username,
                    entry_date,
                    str(item.get("entry_time", "")),
                    str(item.get("customer", "")),
                    str(item.get("item", "")),
                    str(item.get("order_id", "")),
                    buying_amount,
                    selling_amount,
                    selling_amount,
                    profit,
                    str(item.get("status", "")),
                    str(item.get("notes", "")),
                    excel_row,
                    excel_synced_at,
                    str(item.get("excel_sync_error", "")),
                    created_at,
                    updated_at,
                    _iso(),
                ),
            )
        return True
