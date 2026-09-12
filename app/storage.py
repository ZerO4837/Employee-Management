from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import calendar
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import sqlite3
import uuid

from app.config import SALES_SERVICE_NAMES, screen_service_limit
from app.utils import (
    FUTURE_TIMESTAMP_TOLERANCE_SECONDS,
    is_future_timestamp,
    is_timestamp_newer_or_equal,
    normalize_local_timestamp,
    parse_local_datetime,
)


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

# Sentinel stored in sales_entries.excel_sync_error while an entry is queued
# for its first Excel attempt. It rides the same text column, so admin.py can
# tell "waiting for its first real Excel attempt" (Sync Pending) apart from
# "an actual attempt failed" (Retry needed). The exact text must stay stable:
# entries already in the cloud/other PCs carry this string.
EXCEL_SYNC_PENDING_MESSAGE = "Excel sync pending in background."


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
        self._heal_future_timestamps()

    def _heal_future_timestamps(self) -> None:
        """Repair rows whose sync timestamps drifted days into the future.

        Leftover damage from the old naive-timezone push bug: each cloud
        round trip silently added the local UTC offset, so timestamps
        snowballed weeks ahead of real time. A future-stamped row always
        looks "newer" than any legitimate edit (so it can never be
        replaced), and because its updated_at stays ahead of
        cloud_synced_at forever, it re-pushes itself to the cloud on every
        sync cycle - the source of both the "deleted user keeps coming
        back" bug and the constant sync churn.

        Rewinding updated_at to the row's last successful sync time (the
        newest locally-generated timestamp known for it) lets genuinely
        newer cloud state win again and ends the endless re-push loop.
        """
        bound = (_now() + timedelta(seconds=FUTURE_TIMESTAMP_TOLERANCE_SECONDS)).isoformat(timespec="microseconds")
        now_value = _iso()
        tables = [
            "attendance_days",
            "attendance_shifts",
            "attendance_day_events",
            "attendance_events",
            "announcements",
            "service_catalog",
            "inventory_items",
            "inventory_slot_uses",
            "service_message_templates",
            "sales_entries",
            "app_settings",
        ]
        with self.connect() as connection:
            for table in tables:
                try:
                    connection.execute(
                        f"""
                        UPDATE {table}
                        SET updated_at = CASE
                            WHEN cloud_synced_at <> '' AND cloud_synced_at < ? THEN cloud_synced_at
                            ELSE ?
                        END
                        WHERE updated_at > ?
                        """,
                        (bound, now_value, bound),
                    )
                except sqlite3.OperationalError:
                    continue
                try:
                    connection.execute(
                        f"UPDATE {table} SET created_at = updated_at WHERE created_at > ?",
                        (bound,),
                    )
                except sqlite3.OperationalError:
                    pass

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
                    item_kind TEXT NOT NULL DEFAULT 'timed',
                    purchase_date TEXT NOT NULL DEFAULT '',
                    valid_days INTEGER NOT NULL DEFAULT 30,
                    total_slots INTEGER NOT NULL DEFAULT 0,
                    created_by TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    cloud_synced_at TEXT NOT NULL DEFAULT '',
                    cloud_sync_error TEXT NOT NULL DEFAULT ''
                )
                """
            )
            # A slot service (Canva, Spotify, Adobe...) is one account shared
            # by several clients. Each row here is one client sitting in one
            # slot; slots_left is derived from these, never stored, so the
            # two PCs can never drift apart on the count.
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS inventory_slot_uses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cloud_id TEXT NOT NULL DEFAULT '',
                    item_cloud_id TEXT NOT NULL DEFAULT '',
                    item_id INTEGER NOT NULL DEFAULT 0,
                    client_email TEXT NOT NULL DEFAULT '',
                    package TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    used_by TEXT NOT NULL DEFAULT '',
                    updated_by TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    cloud_synced_at TEXT NOT NULL DEFAULT '',
                    cloud_sync_error TEXT NOT NULL DEFAULT ''
                )
                """
            )
            # ----- Renewal Services (admin-only) -------------------------
            # Three levels: a service heading (Canva, Adobe...), the team
            # accounts bought for it, and the clients sharing each account.
            # Separate from inventory_items on purpose - inventory is the
            # employee-facing credential list, this is the admin's renewal
            # tracker. Cloud columns exist so it can be synced later without
            # a migration; today it stays on the admin PC.
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS renewal_services (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cloud_id TEXT NOT NULL DEFAULT '',
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS renewal_accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cloud_id TEXT NOT NULL DEFAULT '',
                    service_id INTEGER NOT NULL,
                    account_email TEXT NOT NULL DEFAULT '',
                    account_password TEXT NOT NULL DEFAULT '',
                    client_number TEXT NOT NULL DEFAULT '',
                    sold_date TEXT NOT NULL DEFAULT '',
                    package TEXT NOT NULL DEFAULT '1 Month',
                    expiry_date TEXT NOT NULL DEFAULT '',
                    reminded_at TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    created_by TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    FOREIGN KEY (service_id) REFERENCES renewal_services (id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS renewal_clients (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cloud_id TEXT NOT NULL DEFAULT '',
                    account_id INTEGER NOT NULL,
                    package TEXT NOT NULL DEFAULT '1 Month',
                    client_name TEXT NOT NULL DEFAULT '',
                    client_number TEXT NOT NULL DEFAULT '',
                    client_email TEXT NOT NULL DEFAULT '',
                    purchase_date TEXT NOT NULL DEFAULT '',
                    expiry_date TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    reminded_at TEXT NOT NULL DEFAULT '',
                    created_by TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    FOREIGN KEY (account_id) REFERENCES renewal_accounts (id)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_renewal_clients_lookup
                ON renewal_clients (account_id, is_active, expiry_date)
                """
            )
            # Older builds created these tables without the package/expiry
            # columns; add them in place rather than losing the rows.
            client_columns = {row["name"] for row in connection.execute("PRAGMA table_info(renewal_clients)")}
            if "package" not in client_columns:
                connection.execute(
                    "ALTER TABLE renewal_clients ADD COLUMN package TEXT NOT NULL DEFAULT '1 Month'"
                )
            account_columns = {row["name"] for row in connection.execute("PRAGMA table_info(renewal_accounts)")}
            for column, ddl in (
                ("package", "ALTER TABLE renewal_accounts ADD COLUMN package TEXT NOT NULL DEFAULT '1 Month'"),
                ("expiry_date", "ALTER TABLE renewal_accounts ADD COLUMN expiry_date TEXT NOT NULL DEFAULT ''"),
                ("reminded_at", "ALTER TABLE renewal_accounts ADD COLUMN reminded_at TEXT NOT NULL DEFAULT ''"),
                ("client_number", "ALTER TABLE renewal_accounts ADD COLUMN client_number TEXT NOT NULL DEFAULT ''"),
            ):
                if column not in account_columns:
                    connection.execute(ddl)
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
                CREATE INDEX IF NOT EXISTS idx_inventory_slot_uses_lookup
                ON inventory_slot_uses (item_cloud_id, is_active, id)
                """
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_inventory_slot_uses_cloud_id
                ON inventory_slot_uses (cloud_id)
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
                # Existing rows become plain timed services with no purchase
                # date, so nothing suddenly claims to be expiring.
                "item_kind": "TEXT NOT NULL DEFAULT 'timed'",
                "purchase_date": "TEXT NOT NULL DEFAULT ''",
                "valid_days": "INTEGER NOT NULL DEFAULT 30",
                "total_slots": "INTEGER NOT NULL DEFAULT 0",
            },
            "inventory_slot_uses": {
                "cloud_id": "TEXT NOT NULL DEFAULT ''",
                "updated_by": "TEXT NOT NULL DEFAULT ''",
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
        if is_future_timestamp(updated_at):
            return False
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

    def list_shift_summaries(
        self,
        start_date: str = "",
        end_date: str = "",
        limit: int = 250,
    ) -> list[dict]:
        conditions = []
        params: list[object] = []
        if start_date:
            conditions.append("shift_date >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("shift_date <= ?")
            params.append(end_date)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM attendance_shifts
                {where}
                ORDER BY shift_date DESC, shift_number DESC, started_at DESC
                LIMIT ?
                """,
                params,
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
        if is_future_timestamp(updated_at):
            return False
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
        if is_future_timestamp(updated_at):
            return False
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
        if is_future_timestamp(updated_at):
            return False
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
        if is_future_timestamp(updated_at):
            return False
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
        if is_future_timestamp(updated_at):
            return False
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
        if is_future_timestamp(updated_at):
            return False
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
    # ===== Inventory ====================================================
    # Two kinds of stock, because they are sold differently:
    #   timed - one account, one client, runs out after so many days
    #           (Proton VPN and friends). Default 30 days.
    #   slots - one team account several clients share (Canva, Spotify,
    #           Adobe). No countdown; what matters is how many slots are
    #           still free.
    INVENTORY_KINDS = ("timed", "slots")
    INVENTORY_DEFAULT_VALID_DAYS = 30
    # Inside this many days of expiry the countdown turns red.
    INVENTORY_REMINDER_DAYS = 5

    @classmethod
    def normalise_inventory_kind(cls, kind: str) -> str:
        text = str(kind or "").strip().lower()
        return text if text in cls.INVENTORY_KINDS else "timed"

    def create_inventory_item(
        self,
        service_name: str,
        account_email: str,
        account_password: str,
        comment: str,
        created_by: str,
        item_kind: str = "timed",
        purchase_date: str = "",
        valid_days: int = INVENTORY_DEFAULT_VALID_DAYS,
        total_slots: int = 0,
    ) -> dict:
        created_at = _iso()
        cloud_id = uuid.uuid4().hex
        kind = self.normalise_inventory_kind(item_kind)
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO inventory_items
                (cloud_id, service_name, account_email, account_password, comment,
                 item_kind, purchase_date, valid_days, total_slots,
                 created_by, created_at, updated_at, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    cloud_id,
                    service_name.strip(),
                    account_email.strip(),
                    account_password.strip(),
                    comment.strip(),
                    kind,
                    str(purchase_date or "").strip() if kind == "timed" else "",
                    max(1, int(valid_days or self.INVENTORY_DEFAULT_VALID_DAYS)),
                    max(0, int(total_slots or 0)) if kind == "slots" else 0,
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
        item_kind: str = "timed",
        purchase_date: str = "",
        valid_days: int = INVENTORY_DEFAULT_VALID_DAYS,
        total_slots: int = 0,
    ) -> dict:
        updated_at = _iso()
        kind = self.normalise_inventory_kind(item_kind)
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE inventory_items
                SET service_name = ?,
                    account_email = ?,
                    account_password = ?,
                    comment = ?,
                    item_kind = ?,
                    purchase_date = ?,
                    valid_days = ?,
                    total_slots = ?,
                    updated_at = ?,
                    cloud_synced_at = '',
                    cloud_sync_error = ''
                WHERE id = ? AND is_active = 1
                """,
                (
                    service_name.strip(),
                    account_email.strip(),
                    account_password.strip(),
                    comment.strip(),
                    kind,
                    str(purchase_date or "").strip() if kind == "timed" else "",
                    max(1, int(valid_days or self.INVENTORY_DEFAULT_VALID_DAYS)),
                    max(0, int(total_slots or 0)) if kind == "slots" else 0,
                    updated_at,
                    item_id,
                ),
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
        used = self.inventory_slot_use_counts()
        return [self._decorate_inventory_item(dict(row), used) for row in rows]

    def inventory_slot_use_counts(self) -> dict[str, int]:
        """How many slots are taken on each account, keyed by the account's
        cloud id - that is the id both PCs agree on."""
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT item_cloud_id, COUNT(*) AS taken
                FROM inventory_slot_uses
                WHERE is_active = 1
                GROUP BY item_cloud_id
                """
            ).fetchall()
        return {str(row["item_cloud_id"]): int(row["taken"]) for row in rows}

    def _decorate_inventory_item(self, row: dict, used: dict[str, int] | None = None) -> dict:
        """Attach what the screens show but the table does not store: the
        expiry countdown for timed items and the free-slot count for shared
        ones. Slots left is always derived, so removing a client's details
        hands the slot straight back."""
        record = dict(row)
        kind = self.normalise_inventory_kind(record.get("item_kind"))
        record["item_kind"] = kind
        taken = (used if used is not None else self.inventory_slot_use_counts()).get(
            str(record.get("cloud_id", "")), 0
        )
        if kind == "slots":
            total = max(0, int(record.get("total_slots") or 0))
            record["total_slots"] = total
            record["slots_used"] = taken
            record["slots_left"] = max(0, total - taken)
            record["expiry_date"] = ""
            record["days_left"] = None
            record["state"] = "full" if record["slots_left"] == 0 and total else "open"
            return record

        record["slots_used"] = 0
        record["slots_left"] = 0
        purchase = str(record.get("purchase_date", "")).strip()
        days = max(1, int(record.get("valid_days") or self.INVENTORY_DEFAULT_VALID_DAYS))
        record["valid_days"] = days
        expiry = ""
        days_left: int | None = None
        if purchase:
            try:
                expiry_date = datetime.strptime(purchase, "%Y-%m-%d").date() + timedelta(days=days)
                expiry = expiry_date.strftime("%Y-%m-%d")
                days_left = (expiry_date - _now().date()).days
            except ValueError:
                expiry = ""
        record["expiry_date"] = expiry
        record["days_left"] = days_left
        if days_left is None:
            record["state"] = "unknown"
        elif days_left < 0:
            record["state"] = "expired"
        elif days_left <= self.INVENTORY_REMINDER_DAYS:
            record["state"] = "expiring"
        else:
            record["state"] = "active"
        return record

    def get_inventory_item(self, item_id: int) -> dict | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM inventory_items WHERE id = ?", (int(item_id),)).fetchone()
        if row is None:
            return None
        return self._decorate_inventory_item(dict(row))

    # ----- slot usage on shared accounts --------------------------------
    def create_inventory_slot_use(
        self,
        item_id: int,
        client_email: str,
        package: str = "",
        notes: str = "",
        used_by: str = "",
    ) -> dict:
        """Seat one client in a free slot. Refuses when the account is full
        so two people cannot oversell the same account."""
        item = self.get_inventory_item(int(item_id))
        if item is None or not item.get("is_active", 1):
            raise ValueError("That inventory account could not be found.")
        if item["item_kind"] != "slots":
            raise ValueError("Only shared accounts have slots to use.")
        if item["slots_left"] <= 0:
            raise ValueError(
                f"{item['service_name']} - {item['account_email']} has no slots left."
            )
        email = str(client_email or "").strip()
        if not email:
            raise ValueError("Enter the client email for this slot.")
        now = _iso()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO inventory_slot_uses
                (cloud_id, item_cloud_id, item_id, client_email, package, notes,
                 used_by, updated_by, created_at, updated_at, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    uuid.uuid4().hex,
                    str(item.get("cloud_id", "")),
                    int(item_id),
                    email,
                    str(package or "").strip(),
                    str(notes or "").strip(),
                    used_by,
                    used_by,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM inventory_slot_uses WHERE id = ?", (int(cursor.lastrowid),)
            ).fetchone()
        created = _row_to_dict(row)
        if created is None:
            raise RuntimeError("The slot could not be saved.")
        return created

    def update_inventory_slot_use(
        self,
        use_id: int,
        client_email: str,
        package: str = "",
        notes: str = "",
        updated_by: str = "",
    ) -> dict:
        """Clients change their email; whoever spots it can correct it here
        and the other PC picks the change up on the next sync."""
        email = str(client_email or "").strip()
        if not email:
            raise ValueError("Enter the client email for this slot.")
        now = _iso()
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE inventory_slot_uses
                SET client_email = ?, package = ?, notes = ?, updated_by = ?, updated_at = ?,
                    cloud_synced_at = '', cloud_sync_error = ''
                WHERE id = ?
                """,
                (email, str(package or "").strip(), str(notes or "").strip(), updated_by, now, int(use_id)),
            )
            row = connection.execute("SELECT * FROM inventory_slot_uses WHERE id = ?", (int(use_id),)).fetchone()
        updated = _row_to_dict(row)
        if updated is None:
            raise ValueError("That slot could not be found.")
        return updated

    def remove_inventory_slot_use(self, use_id: int, removed_by: str = "") -> None:
        """Soft delete so the removal travels to the other PC - and the slot
        it was holding comes straight back."""
        now = _iso()
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE inventory_slot_uses
                SET is_active = 0, updated_by = ?, updated_at = ?, cloud_synced_at = '', cloud_sync_error = ''
                WHERE id = ?
                """,
                (removed_by, now, int(use_id)),
            )

    def list_inventory_slot_uses(
        self,
        item_id: int | None = None,
        item_cloud_id: str = "",
        active_only: bool = True,
    ) -> list[dict]:
        conditions = []
        params: list[object] = []
        if item_cloud_id:
            conditions.append("item_cloud_id = ?")
            params.append(str(item_cloud_id))
        elif item_id is not None:
            conditions.append("item_id = ?")
            params.append(int(item_id))
        if active_only:
            conditions.append("is_active = 1")
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM inventory_slot_uses {where} ORDER BY created_at ASC, id ASC",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def get_inventory_slot_use(self, use_id: int) -> dict | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM inventory_slot_uses WHERE id = ?", (int(use_id),)).fetchone()
        return _row_to_dict(row)

    # ===== Renewal Services (admin-only): service -> accounts -> clients =
    # Renewal reminders start this many days before expiry; inside this
    # window the days-left countdown turns red.
    CLIENT_REMINDER_DAYS = 5
    # The packages a client can buy, and how many months each runs for.
    # Expiry is always calculated from purchase date + package, never typed.
    RENEWAL_PACKAGES: dict[str, int] = {"1 Month": 1, "6 Months": 6, "1 Year": 12}

    @staticmethod
    def add_months(start: date, months: int) -> date:
        """Same day-of-month N months on, clamped to the month's length so
        31 Jan + 1 month lands on 28/29 Feb rather than overflowing."""
        month_index = start.month - 1 + months
        year = start.year + month_index // 12
        month = month_index % 12 + 1
        day = min(start.day, calendar.monthrange(year, month)[1])
        return date(year, month, day)

    def package_months(self, package: str) -> int:
        return self.RENEWAL_PACKAGES.get(str(package or "").strip(), 1)

    def expiry_for_package(self, purchase_date: str, package: str) -> str:
        """Expiry = purchase date + the package length."""
        text = str(purchase_date or "").strip()
        if not text:
            return ""
        try:
            start = datetime.strptime(text, "%Y-%m-%d").date()
        except ValueError:
            return ""
        return self.add_months(start, self.package_months(package)).strftime("%Y-%m-%d")

    def create_renewal_service(self, name: str) -> dict:
        name = name.strip()
        if not name:
            raise ValueError("Service name is required.")
        now = _iso()
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM renewal_services WHERE LOWER(TRIM(name)) = ?", (name.casefold(),)
            ).fetchone()
            if existing is not None:
                if not existing["is_active"]:
                    connection.execute(
                        "UPDATE renewal_services SET is_active = 1, updated_at = ? WHERE id = ?",
                        (now, int(existing["id"])),
                    )
                    existing = connection.execute(
                        "SELECT * FROM renewal_services WHERE id = ?", (int(existing["id"]),)
                    ).fetchone()
                return dict(existing)
            cursor = connection.execute(
                "INSERT INTO renewal_services (cloud_id, name, created_at, updated_at, is_active) "
                "VALUES ('', ?, ?, ?, 1)",
                (name, now, now),
            )
            row = connection.execute(
                "SELECT * FROM renewal_services WHERE id = ?", (int(cursor.lastrowid),)
            ).fetchone()
        created = _row_to_dict(row)
        if created is None:
            raise RuntimeError("Service could not be saved.")
        return created

    def rename_renewal_service(self, service_id: int, name: str) -> None:
        name = name.strip()
        if not name:
            raise ValueError("Service name is required.")
        with self.connect() as connection:
            connection.execute(
                "UPDATE renewal_services SET name = ?, updated_at = ? WHERE id = ?",
                (name, _iso(), int(service_id)),
            )

    def remove_renewal_service(self, service_id: int) -> None:
        """Soft-delete the service and everything under it, so the heading
        disappears together with its accounts and clients."""
        now = _iso()
        with self.connect() as connection:
            connection.execute(
                "UPDATE renewal_services SET is_active = 0, updated_at = ? WHERE id = ?", (now, int(service_id))
            )
            connection.execute(
                "UPDATE renewal_accounts SET is_active = 0, updated_at = ? WHERE service_id = ?",
                (now, int(service_id)),
            )
            connection.execute(
                """
                UPDATE renewal_clients SET is_active = 0, updated_at = ?
                WHERE account_id IN (SELECT id FROM renewal_accounts WHERE service_id = ?)
                """,
                (now, int(service_id)),
            )

    def list_renewal_services(self, active_only: bool = True) -> list[dict]:
        where = "WHERE is_active = 1" if active_only else ""
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM renewal_services {where} ORDER BY name COLLATE NOCASE ASC"
            ).fetchall()
        return [dict(row) for row in rows]

    def create_renewal_account(
        self,
        service_id: int,
        account_email: str,
        account_password: str,
        sold_date: str = "",
        package: str = "1 Month",
        client_number: str = "",
        notes: str = "",
        created_by: str = "",
    ) -> dict:
        now = _iso()
        # The account itself is sold too, so it carries its own package and
        # expiry exactly like a client does.
        expiry_date = self.expiry_for_package(sold_date, package)
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO renewal_accounts
                (cloud_id, service_id, account_email, account_password, client_number, sold_date, package,
                 expiry_date, notes, created_by, created_at, updated_at, is_active)
                VALUES ('', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    int(service_id),
                    account_email.strip(),
                    account_password.strip(),
                    client_number.strip(),
                    sold_date.strip(),
                    str(package).strip(),
                    expiry_date,
                    notes.strip(),
                    created_by,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM renewal_accounts WHERE id = ?", (int(cursor.lastrowid),)
            ).fetchone()
        created = _row_to_dict(row)
        if created is None:
            raise RuntimeError("Account could not be saved.")
        return created

    def update_renewal_account(
        self,
        account_id: int,
        account_email: str,
        account_password: str,
        sold_date: str = "",
        package: str = "1 Month",
        client_number: str = "",
        notes: str = "",
    ) -> dict:
        expiry_date = self.expiry_for_package(sold_date, package)
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE renewal_accounts
                SET account_email = ?, account_password = ?, client_number = ?, sold_date = ?, package = ?,
                    expiry_date = ?, notes = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    account_email.strip(),
                    account_password.strip(),
                    client_number.strip(),
                    sold_date.strip(),
                    str(package).strip(),
                    expiry_date,
                    notes.strip(),
                    _iso(),
                    int(account_id),
                ),
            )
            row = connection.execute("SELECT * FROM renewal_accounts WHERE id = ?", (int(account_id),)).fetchone()
        updated = _row_to_dict(row)
        if updated is None:
            raise ValueError("Account could not be found.")
        return updated

    def renew_renewal_account(self, account_id: int, package: str = "") -> dict:
        """Add another package length to the account itself, keeping any
        time still remaining (see renew_renewal_client)."""
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM renewal_accounts WHERE id = ?", (int(account_id),)
            ).fetchone()
            if row is None:
                raise ValueError("Account could not be found.")
            chosen = str(package).strip() or str(row["package"] or "1 Month")
            today = _now().date()
            start = today
            expiry_text = str(row["expiry_date"] or "").strip()
            if expiry_text:
                try:
                    current = datetime.strptime(expiry_text, "%Y-%m-%d").date()
                    if current > today:
                        start = current
                except ValueError:
                    pass
            new_expiry = self.add_months(start, self.package_months(chosen)).strftime("%Y-%m-%d")
            connection.execute(
                """
                UPDATE renewal_accounts
                SET expiry_date = ?, package = ?, reminded_at = '', is_active = 1, updated_at = ?
                WHERE id = ?
                """,
                (new_expiry, chosen, _iso(), int(account_id)),
            )
            row = connection.execute("SELECT * FROM renewal_accounts WHERE id = ?", (int(account_id),)).fetchone()
        renewed = _row_to_dict(row)
        if renewed is None:
            raise ValueError("Account could not be found.")
        return renewed

    def close_renewal_account(self, account_id: int) -> dict:
        """The client walked away, so the account goes back on the shelf.

        The email and password are what we actually own, so they stay; the
        sale details - client number, sold date, package, expiry - are wiped
        so the account reads as in stock and ready to sell again. Clients
        are never closed this way, only accounts.
        """
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE renewal_accounts
                SET client_number = '', sold_date = '', package = '', expiry_date = '',
                    reminded_at = '', updated_at = ?
                WHERE id = ?
                """,
                (_iso(), int(account_id)),
            )
            row = connection.execute("SELECT * FROM renewal_accounts WHERE id = ?", (int(account_id),)).fetchone()
        closed = _row_to_dict(row)
        if closed is None:
            raise ValueError("Account could not be found.")
        return closed

    def mark_renewal_account_reminded(self, account_id: int) -> None:
        now = _iso()
        with self.connect() as connection:
            connection.execute(
                "UPDATE renewal_accounts SET reminded_at = ?, updated_at = ? WHERE id = ?",
                (now, now, int(account_id)),
            )

    def remove_renewal_account(self, account_id: int) -> None:
        now = _iso()
        with self.connect() as connection:
            connection.execute(
                "UPDATE renewal_accounts SET is_active = 0, updated_at = ? WHERE id = ?", (now, int(account_id))
            )
            connection.execute(
                "UPDATE renewal_clients SET is_active = 0, updated_at = ? WHERE account_id = ?",
                (now, int(account_id)),
            )

    def list_renewal_accounts(self, service_id: int | None = None, active_only: bool = True) -> list[dict]:
        conditions = []
        params: list[object] = []
        if service_id is not None:
            conditions.append("a.service_id = ?")
            params.append(int(service_id))
        if active_only:
            conditions.append("a.is_active = 1")
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT a.*, s.name AS service_name
                FROM renewal_accounts a
                JOIN renewal_services s ON s.id = a.service_id
                {where}
                ORDER BY a.account_email COLLATE NOCASE ASC, a.id ASC
                """,
                params,
            ).fetchall()
        return [self._decorate_expiry(dict(row), is_account=True) for row in rows]

    def create_renewal_client(
        self,
        account_id: int,
        client_number: str,
        client_email: str,
        purchase_date: str,
        package: str,
        notes: str = "",
        created_by: str = "",
    ) -> dict:
        now = _iso()
        expiry_date = self.expiry_for_package(purchase_date, package)
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO renewal_clients
                (cloud_id, account_id, package, client_name, client_number, client_email,
                 purchase_date, expiry_date, notes, created_by, created_at, updated_at, is_active)
                VALUES ('', ?, ?, '', ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    int(account_id),
                    str(package).strip(),
                    client_number.strip(),
                    client_email.strip(),
                    purchase_date.strip(),
                    expiry_date,
                    notes.strip(),
                    created_by,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM renewal_clients WHERE id = ?", (int(cursor.lastrowid),)
            ).fetchone()
        created = _row_to_dict(row)
        if created is None:
            raise RuntimeError("Client could not be saved.")
        return created

    def update_renewal_client(
        self,
        client_id: int,
        client_number: str,
        client_email: str,
        purchase_date: str,
        package: str,
        notes: str = "",
    ) -> dict:
        expiry_date = self.expiry_for_package(purchase_date, package)
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE renewal_clients
                SET client_number = ?, client_email = ?, package = ?,
                    purchase_date = ?, expiry_date = ?, notes = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    client_number.strip(),
                    client_email.strip(),
                    str(package).strip(),
                    purchase_date.strip(),
                    expiry_date,
                    notes.strip(),
                    _iso(),
                    int(client_id),
                ),
            )
            row = connection.execute("SELECT * FROM renewal_clients WHERE id = ?", (int(client_id),)).fetchone()
        updated = _row_to_dict(row)
        if updated is None:
            raise ValueError("Client could not be found.")
        return updated

    def remove_renewal_client(self, client_id: int) -> None:
        """Client taken off the account (renewal declined, or cleaned up
        after expiry). Soft delete so the history is not lost."""
        with self.connect() as connection:
            connection.execute(
                "UPDATE renewal_clients SET is_active = 0, updated_at = ? WHERE id = ?",
                (_iso(), int(client_id)),
            )

    def mark_renewal_client_reminded(self, client_id: int) -> None:
        now = _iso()
        with self.connect() as connection:
            connection.execute(
                "UPDATE renewal_clients SET reminded_at = ?, updated_at = ? WHERE id = ?",
                (now, now, int(client_id)),
            )

    def renew_renewal_client(self, client_id: int, package: str = "") -> dict:
        """Add another package length of time. Time still remaining is kept
        (extended from the current expiry); an already-expired client
        restarts from today. Clears the reminder so the countdown is fresh.
        """
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM renewal_clients WHERE id = ?", (int(client_id),)
            ).fetchone()
            if row is None:
                raise ValueError("Client could not be found.")
            chosen = str(package).strip() or str(row["package"] or "1 Month")
            today = _now().date()
            start = today
            expiry_text = str(row["expiry_date"] or "").strip()
            if expiry_text:
                try:
                    current = datetime.strptime(expiry_text, "%Y-%m-%d").date()
                    if current > today:
                        start = current
                except ValueError:
                    pass
            new_expiry = self.add_months(start, self.package_months(chosen)).strftime("%Y-%m-%d")
            connection.execute(
                """
                UPDATE renewal_clients
                SET expiry_date = ?, package = ?, reminded_at = '', is_active = 1, updated_at = ?
                WHERE id = ?
                """,
                (new_expiry, chosen, _iso(), int(client_id)),
            )
            row = connection.execute("SELECT * FROM renewal_clients WHERE id = ?", (int(client_id),)).fetchone()
        renewed = _row_to_dict(row)
        if renewed is None:
            raise ValueError("Client could not be found.")
        return renewed

    def _decorate_expiry(self, row: dict, is_account: bool = False) -> dict:
        """Attach the countdown the UI needs - days_left plus a state of
        active / expiring / expired. Used for accounts and clients alike,
        since both are sold with their own expiry.

        Accounts get one extra state: an account with no sold date is not
        missing data, it is sitting in stock waiting to be sold.
        """
        record = dict(row)
        expiry = str(record.get("expiry_date", "")).strip()
        days_left: int | None = None
        if expiry:
            try:
                days_left = (datetime.strptime(expiry, "%Y-%m-%d").date() - _now().date()).days
            except ValueError:
                days_left = None
        record["days_left"] = days_left
        record["in_stock"] = is_account and not str(record.get("sold_date", "")).strip()
        if days_left is None:
            record["state"] = "in_stock" if record["in_stock"] else "unknown"
        elif days_left < 0:
            record["state"] = "expired"
        elif days_left <= self.CLIENT_REMINDER_DAYS:
            record["state"] = "expiring"
        else:
            record["state"] = "active"
        return record

    def list_renewal_clients(
        self,
        account_id: int | None = None,
        service_id: int | None = None,
        active_only: bool = True,
    ) -> list[dict]:
        conditions = []
        params: list[object] = []
        if account_id is not None:
            conditions.append("c.account_id = ?")
            params.append(int(account_id))
        if service_id is not None:
            conditions.append("a.service_id = ?")
            params.append(int(service_id))
        if active_only:
            conditions.append("c.is_active = 1 AND a.is_active = 1")
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT c.*, a.account_email, a.account_password, a.sold_date, a.service_id,
                       s.name AS service_name
                FROM renewal_clients c
                JOIN renewal_accounts a ON a.id = c.account_id
                JOIN renewal_services s ON s.id = a.service_id
                {where}
                ORDER BY (c.expiry_date = '') ASC, c.expiry_date ASC, c.id ASC
                """,
                params,
            ).fetchall()
        return [self._decorate_expiry(dict(row)) for row in rows]

    def list_renewal_reminders(self, within_days: int | None = None) -> list[dict]:
        """Everything needing action - accounts AND the clients on them -
        expiring inside the reminder window or already expired. Each row
        carries a "kind" of account/client so the caller can act on the
        right record. Most urgent first."""
        window = self.CLIENT_REMINDER_DAYS if within_days is None else within_days
        reminders: list[dict] = []
        for account in self.list_renewal_accounts(active_only=True):
            if account["days_left"] is not None and account["days_left"] <= window:
                entry = dict(account)
                entry["kind"] = "account"
                reminders.append(entry)
        for client in self.list_renewal_clients(active_only=True):
            if client["days_left"] is not None and client["days_left"] <= window:
                entry = dict(client)
                entry["kind"] = "client"
                reminders.append(entry)
        reminders.sort(key=lambda record: record["days_left"])
        return reminders

    def search_renewals(self, query: str, service_id: int | None = None, limit: int = 60) -> list[dict]:
        """Find accounts and clients by email or number within one service.

        The admin searches the service they have open - searching inside
        Canva returns only Canva's accounts and clients. Accounts match on
        their own email and client number; clients on their own email and
        number only, so a client is not listed just because its account's
        email matched.
        """
        from app.utils import text_or_phone_matches

        if not str(query or "").strip():
            return []
        results: list[dict] = []
        for account in self.list_renewal_accounts(service_id=service_id):
            if text_or_phone_matches(
                (account.get("account_email"), account.get("client_number")),
                query,
            ):
                record = dict(account)
                record["kind"] = "account"
                record["account_id"] = int(account["id"])
                results.append(record)
        for client in self.list_renewal_clients(service_id=service_id):
            if text_or_phone_matches((client.get("client_email"), client.get("client_number")), query):
                record = dict(client)
                record["kind"] = "client"
                record["account_id"] = int(client["account_id"])
                results.append(record)
        # Clients first - they are what is hardest to find by clicking - then
        # by service and email so the list reads predictably.
        results.sort(
            key=lambda r: (
                0 if r["kind"] == "client" else 1,
                str(r.get("service_name", "")).casefold(),
                str(r.get("account_email", "")).casefold(),
                str(r.get("client_email", "") or r.get("client_number", "")).casefold(),
            )
        )
        return results[:limit]

    def renewal_counts(self) -> dict[str, int]:
        clients = self.list_renewal_clients(active_only=True)
        accounts = self.list_renewal_accounts()
        needing = [
            record
            for record in accounts + clients
            if record["days_left"] is not None and record["days_left"] <= self.CLIENT_REMINDER_DAYS
        ]
        return {
            "services": len(self.list_renewal_services()),
            "accounts": len(accounts),
            "in_stock": sum(1 for a in accounts if a["in_stock"]),
            "clients": len(clients),
            "expiring": sum(1 for r in needing if r["state"] == "expiring"),
            "expired": sum(1 for r in needing if r["state"] == "expired"),
        }

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
        if is_future_timestamp(updated_at):
            return False
        is_active = 1 if bool(item.get("is_active", True)) else 0
        kind = self.normalise_inventory_kind(item.get("item_kind"))
        purchase_date = str(item.get("purchase_date", "") or "").strip() if kind == "timed" else ""
        try:
            valid_days = max(1, int(item.get("valid_days") or self.INVENTORY_DEFAULT_VALID_DAYS))
        except (TypeError, ValueError):
            valid_days = self.INVENTORY_DEFAULT_VALID_DAYS
        try:
            total_slots = max(0, int(item.get("total_slots") or 0)) if kind == "slots" else 0
        except (TypeError, ValueError):
            total_slots = 0
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
                        item_kind = ?,
                        purchase_date = ?,
                        valid_days = ?,
                        total_slots = ?,
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
                        kind,
                        purchase_date,
                        valid_days,
                        total_slots,
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
                (cloud_id, service_name, account_email, account_password, comment,
                 item_kind, purchase_date, valid_days, total_slots,
                 created_by, created_at, updated_at, is_active, cloud_synced_at, cloud_sync_error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '')
                """,
                (
                    cloud_id,
                    service_name,
                    str(item.get("account_email", "")),
                    str(item.get("account_password", "")),
                    str(item.get("comment", "")),
                    kind,
                    purchase_date,
                    valid_days,
                    total_slots,
                    str(item.get("created_by", "")),
                    created_at,
                    updated_at,
                    is_active,
                    _iso(),
                ),
            )
        return True

    def list_cloud_pending_inventory_slot_uses(self, limit: int = 200) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM inventory_slot_uses
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

    def ensure_inventory_slot_use_cloud_id(self, use_id: int) -> dict:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM inventory_slot_uses WHERE id = ?", (int(use_id),)).fetchone()
            if row is None:
                raise ValueError("Slot could not be found.")
            if row["cloud_id"]:
                return dict(row)
            connection.execute(
                """
                UPDATE inventory_slot_uses
                SET cloud_id = ?, updated_at = ?, cloud_synced_at = '', cloud_sync_error = ''
                WHERE id = ?
                """,
                (uuid.uuid4().hex, row["updated_at"] or row["created_at"] or _iso(), int(use_id)),
            )
            row = connection.execute("SELECT * FROM inventory_slot_uses WHERE id = ?", (int(use_id),)).fetchone()
        use = _row_to_dict(row)
        if use is None:
            raise ValueError("Slot could not be found.")
        return use

    def mark_inventory_slot_use_cloud_sync(self, use_id: int) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE inventory_slot_uses SET cloud_synced_at = ?, cloud_sync_error = '' WHERE id = ?",
                (_iso(), int(use_id)),
            )

    def mark_inventory_slot_use_cloud_error(self, use_id: int, error: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE inventory_slot_uses SET cloud_sync_error = ? WHERE id = ?",
                (error[:500], int(use_id)),
            )

    def import_cloud_inventory_slot_use(self, use: dict) -> bool:
        """Slots are linked by the account's cloud id, not its local row id -
        the two PCs number their rows differently."""
        use = _normalize_cloud_timestamps(use)
        cloud_id = str(use.get("cloud_id", "")).strip()
        item_cloud_id = str(use.get("item_cloud_id", "")).strip()
        if not cloud_id or not item_cloud_id:
            return False
        created_at = str(use.get("created_at") or use.get("updated_at") or _iso())
        updated_at = str(use.get("updated_at") or created_at)
        if is_future_timestamp(updated_at):
            return False
        is_active = 1 if bool(use.get("is_active", True)) else 0
        with self.connect() as connection:
            local_item = connection.execute(
                "SELECT id FROM inventory_items WHERE cloud_id = ?", (item_cloud_id,)
            ).fetchone()
            item_id = int(local_item["id"]) if local_item is not None else 0
            existing = connection.execute(
                "SELECT * FROM inventory_slot_uses WHERE cloud_id = ?", (cloud_id,)
            ).fetchone()
            values = (
                item_cloud_id,
                item_id,
                str(use.get("client_email", "")),
                str(use.get("package", "")),
                str(use.get("notes", "")),
                str(use.get("used_by", "")),
                str(use.get("updated_by", "")),
                created_at,
                updated_at,
                is_active,
                _iso(),
            )
            if existing is not None:
                local_updated = str(existing["updated_at"] or existing["created_at"] or "")
                if is_timestamp_newer_or_equal(local_updated, updated_at) and not existing["cloud_sync_error"]:
                    return False
                connection.execute(
                    """
                    UPDATE inventory_slot_uses
                    SET item_cloud_id = ?, item_id = ?, client_email = ?, package = ?, notes = ?,
                        used_by = ?, updated_by = ?, created_at = ?, updated_at = ?, is_active = ?,
                        cloud_synced_at = ?, cloud_sync_error = ''
                    WHERE cloud_id = ?
                    """,
                    values + (cloud_id,),
                )
                return True
            connection.execute(
                """
                INSERT INTO inventory_slot_uses
                (cloud_id, item_cloud_id, item_id, client_email, package, notes,
                 used_by, updated_by, created_at, updated_at, is_active, cloud_synced_at, cloud_sync_error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '')
                """,
                (cloud_id,) + values,
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
        if is_future_timestamp(updated_at):
            return False
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

    def list_sales_entries_needing_excel_sync(
        self,
        start_date: str = "",
        end_date: str = "",
        limit: int = 1000,
    ) -> list[dict]:
        # Oldest first: screen-shared services (Netflix/HBO) append each new
        # customer to the same Excel row in the order they were sold, so a
        # batch sync must process entries in that same chronological order.
        # An optional date window lets Sync All target only the period the
        # admin currently has selected (e.g. a single day).
        conditions = [
            "excel_synced_at = ''",
            "LOWER(excel_sync_error) NOT LIKE '%account is full%'",
        ]
        params: list[object] = []
        if start_date:
            conditions.append("entry_date >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("entry_date <= ?")
            params.append(end_date)
        params.append(limit)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM sales_entries
                WHERE {" AND ".join(conditions)}
                ORDER BY entry_date ASC, created_at ASC
                LIMIT ?
                """,
                params,
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

    # A freshly stocked account gets its screens filled within about two
    # days; nothing new is added to that email afterwards. So only sales
    # from the last couple of days say anything about how full an account
    # is right now. Counting every customer ever recorded on an account
    # made every reused email eventually read "full" forever.
    SCREEN_ACCOUNT_ACTIVE_DAYS = 2

    def screen_account_customer_count(
        self,
        item: str,
        order_id: str,
        customer: str = "",
        exclude_entry_id: int | None = None,
    ) -> tuple[int | None, int, bool]:
        """Capacity check for a screen-shared account email.

        Mirrors the Excel row-grouping: distinct customer NAMES per
        (screen service, account email). Returns
        (limit, distinct_other_customers, customer_already_present):
          - limit: the per-account name cap, or None if this service is not
            a limited screen service or has no account email.
          - distinct_other_customers: how many different customers already
            hold a screen on this account (excluding the entry being edited
            and excluding `customer`).
          - customer_already_present: True if `customer` already has a
            screen on the account, in which case reassigning is a no-op and
            must never be blocked.
        """
        limit = screen_service_limit(item)
        order_id_key = str(order_id or "").strip().casefold()
        if limit is None or not order_id_key:
            return None, 0, False
        item_key = str(item or "").strip().casefold()
        customer_key = str(customer or "").strip().casefold()
        cutoff = (_now() - timedelta(days=self.SCREEN_ACCOUNT_ACTIVE_DAYS)).strftime("%Y-%m-%d")
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id, customer FROM sales_entries "
                "WHERE LOWER(TRIM(item)) = ? AND LOWER(TRIM(order_id)) = ? AND entry_date >= ?",
                (item_key, order_id_key, cutoff),
            ).fetchall()
        others: set[str] = set()
        already_present = False
        for row in rows:
            if exclude_entry_id is not None and int(row["id"]) == int(exclude_entry_id):
                continue
            name_key = str(row["customer"] or "").strip().casefold()
            if not name_key:
                continue
            if customer_key and name_key == customer_key:
                already_present = True
                continue
            others.add(name_key)
        return limit, len(others), already_present

    def screen_account_blocked_message(
        self,
        item: str,
        order_id: str,
        customer: str = "",
        exclude_entry_id: int | None = None,
    ) -> str | None:
        """User-facing reason if assigning this customer to this screen
        account would exceed the per-account limit, else None (allowed)."""
        limit, used, already_present = self.screen_account_customer_count(
            item, order_id, customer, exclude_entry_id
        )
        if limit is None or already_present or used < limit:
            return None
        service = str(item or "This account").strip()
        email = str(order_id or "").strip()
        return (
            f"{service} account already has {used} customer(s) in the last "
            f"{self.SCREEN_ACCOUNT_ACTIVE_DAYS} days (limit {limit}):\n{email}\n\n"
            "Use a different account email if this one is really full.\n\n"
            "Do you want to save this entry anyway?"
        )

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
        if is_future_timestamp(updated_at):
            return False
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
