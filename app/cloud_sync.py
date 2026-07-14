from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

from app.config import (
    SUPABASE_CONFIG_PATH,
    SUPABASE_SYNC_INTERVAL_SECONDS,
    SUPABASE_URL,
    SUPABASE_ANON_KEY,
    SUPABASE_ADMIN_SECRET,
    SUPABASE_EMPLOYEE_SYNC_SECRET,
)
from app.utils import to_cloud_timestamp


@dataclass
class SupabaseConfig:
    enabled: bool = False
    url: str = ""
    anon_key: str = ""
    admin_secret: str = ""
    employee_sync_secret: str = ""

    @property
    def is_ready(self) -> bool:
        return self.enabled and bool(self.url.strip()) and bool(self.anon_key.strip())

    @property
    def can_push(self) -> bool:
        return self.is_ready and bool(self.admin_secret.strip())

    @property
    def user_sync_secret(self) -> str:
        return (self.employee_sync_secret or self.admin_secret).strip()

    @property
    def can_pull_users(self) -> bool:
        return self.is_ready and bool(self.user_sync_secret)


@dataclass
class CloudSyncResult:
    enabled: bool
    ok: bool
    message: str = ""
    pushed: int = 0
    pulled: int = 0
    changed: bool = False


class SupabaseRestClient:
    def __init__(self, config: SupabaseConfig, timeout: int = 12) -> None:
        self.url = config.url.rstrip("/")
        self.anon_key = config.anon_key.strip()
        self.timeout = timeout

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, str] | None = None,
        body: object | None = None,
    ) -> object:
        query = ""
        if params:
            query = "?" + urllib.parse.urlencode(params, safe=",.*()")
        url = f"{self.url}/rest/v1/{path}{query}"
        data = None
        headers = {
            "apikey": self.anon_key,
            "Authorization": f"Bearer {self.anon_key}",
            "Accept": "application/json",
        }
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Supabase HTTP {exc.code}: {detail or exc.reason}") from exc
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"Supabase connection failed: {exc}") from exc
        if not payload:
            return None
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return payload

    def select(self, table: str, params: dict[str, str]) -> list[dict]:
        result = self._request("GET", table, params=params)
        return result if isinstance(result, list) else []

    def rpc(self, function_name: str, payload: dict) -> object:
        return self._request("POST", f"rpc/{function_name}", body=payload)


class CloudSyncService:
    def __init__(self, store, config_loader, auth_store=None) -> None:
        self.store = store
        self.config_loader = config_loader
        self.auth_store = auth_store

    def delete_attendance_shift(self, cloud_id: str) -> None:
        if not cloud_id:
            return
        config = self.config_loader()
        if not config.can_push:
            return
        client = SupabaseRestClient(config)
        client.rpc(
            "dsp_delete_attendance_shift",
            {"admin_secret": config.admin_secret, "target_cloud_id": cloud_id},
        )

    def _push_rows_concurrently(self, rows: list, push_one: Callable[[Any], None], max_workers: int = 6) -> int:
        # Same idea as _run_concurrently, one level down: a single table can
        # have dozens of pending rows after a busy day or an offline spell,
        # and pushing them one HTTP call at a time is what made big backlogs
        # slow even after the categories themselves were parallelized.
        if not rows:
            return 0
        pushed = 0
        first_error: Exception | None = None
        with ThreadPoolExecutor(max_workers=min(max_workers, len(rows))) as pool:
            futures = [pool.submit(push_one, row) for row in rows]
            for future in futures:
                try:
                    future.result()
                    pushed += 1
                except Exception as exc:
                    if first_error is None:
                        first_error = exc
        if first_error is not None:
            raise first_error
        return pushed

    def _run_concurrently(self, jobs: list[Callable[[], int]]) -> int:
        # Each job is an independent table's push or pull - one HTTP round
        # trip apiece. Run them at once instead of one-after-another: this
        # alone was measured at a 2.5x speedup on a real project (the
        # network latency per call doesn't change, but it overlaps instead
        # of stacking). Every job still runs to completion even if another
        # one fails, so a single bad table doesn't block the rest.
        if not jobs:
            return 0
        total = 0
        first_error: Exception | None = None
        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            futures = [pool.submit(job) for job in jobs]
            for future in futures:
                try:
                    total += future.result()
                except Exception as exc:
                    if first_error is None:
                        first_error = exc
        if first_error is not None:
            raise first_error
        return total

    def sync(self, push_local: bool = False, pull_remote: bool = True) -> CloudSyncResult:
        config = self.config_loader()
        if not config.is_ready:
            return CloudSyncResult(enabled=False, ok=True, message="Cloud sync is not configured.")
        client = SupabaseRestClient(config)
        pushed = 0
        pulled = 0
        try:
            if push_local and config.can_pull_users:
                pushed += self._run_concurrently([
                    lambda: self._push_attendance_days(client, config.user_sync_secret),
                    lambda: self._push_attendance_shifts(client, config.user_sync_secret),
                    lambda: self._push_attendance_day_events(client, config.user_sync_secret),
                    lambda: self._push_attendance_events(client, config.user_sync_secret),
                    lambda: self._push_sales_entries(client, config.user_sync_secret),
                ])
            if push_local and config.can_push:
                pushed += self._run_concurrently([
                    lambda: self._push_employee_users(client, config.admin_secret),
                    lambda: self._push_announcements(client, config.admin_secret),
                    lambda: self._push_service_catalog(client, config.admin_secret),
                    lambda: self._push_service_templates(client, config.admin_secret),
                    lambda: self._push_inventory_items(client, config.admin_secret),
                    lambda: self._push_app_settings(client, config.admin_secret),
                ])
            if pull_remote:
                jobs: list[Callable[[], int]] = [
                    lambda: self._pull_announcements(client),
                    lambda: self._pull_service_catalog(client),
                    lambda: self._pull_service_templates(client),
                ]
                if config.can_pull_users:
                    jobs.append(lambda: self._pull_employee_users(client, config.user_sync_secret))
                    jobs.append(lambda: self._pull_inventory_items(client, config.user_sync_secret))
                    jobs.append(lambda: self._pull_app_settings(client, config.user_sync_secret))
                if config.can_pull_users and not config.can_push:
                    # Employee PCs (no admin secret): pull sales entries via
                    # the employee-gated RPC so admin edits reflect back.
                    # The admin PC keeps using the admin-gated pull below.
                    jobs.append(lambda: self._pull_sales_entries_shared(client, config.user_sync_secret))
                if config.can_push:
                    jobs.append(lambda: self._pull_attendance_days(client, config.admin_secret))
                    jobs.append(lambda: self._pull_attendance_shifts(client, config.admin_secret))
                    jobs.append(lambda: self._pull_attendance_day_events(client, config.admin_secret))
                    jobs.append(lambda: self._pull_attendance_events(client, config.admin_secret))
                    jobs.append(lambda: self._pull_sales_entries(client, config.admin_secret))
                pulled += self._run_concurrently(jobs)
        except Exception as exc:
            return CloudSyncResult(enabled=True, ok=False, message=str(exc), pushed=pushed, pulled=pulled)
        if push_local and not config.can_push:
            message = "Cloud read sync is active. Add the admin write secret on the admin PC to push changes."
        else:
            message = f"Cloud sync complete. Pushed {pushed}, pulled {pulled}."
        return CloudSyncResult(
            enabled=True,
            ok=True,
            message=message,
            pushed=pushed,
            pulled=pulled,
            changed=bool(pushed or pulled),
        )

    def _push_announcements(self, client: SupabaseRestClient, admin_secret: str) -> int:
        def push_one(row: Any) -> None:
            local_id = int(row["id"])
            ensured = self.store.ensure_announcement_cloud_id(local_id)
            try:
                client.rpc(
                    "dsp_upsert_announcement",
                    {"admin_secret": admin_secret, "row_data": self._announcement_payload(ensured)},
                )
                self.store.mark_announcement_cloud_sync(local_id)
            except Exception as exc:
                self.store.mark_announcement_cloud_error(local_id, str(exc))
                raise

        return self._push_rows_concurrently(self.store.list_cloud_pending_announcements(limit=100), push_one)

    def _push_service_templates(self, client: SupabaseRestClient, admin_secret: str) -> int:
        def push_one(row: Any) -> None:
            local_id = int(row["id"])
            ensured = self.store.ensure_service_message_template_cloud_id(local_id)
            try:
                client.rpc(
                    "dsp_upsert_service_message_template",
                    {"admin_secret": admin_secret, "row_data": self._service_template_payload(ensured)},
                )
                self.store.mark_service_message_template_cloud_sync(local_id)
            except Exception as exc:
                self.store.mark_service_message_template_cloud_error(local_id, str(exc))
                raise

        return self._push_rows_concurrently(
            self.store.list_cloud_pending_service_message_templates(limit=150), push_one
        )

    def _push_service_catalog(self, client: SupabaseRestClient, admin_secret: str) -> int:
        def push_one(row: Any) -> None:
            local_id = int(row["id"])
            ensured = self.store.ensure_service_catalog_cloud_id(local_id)
            try:
                client.rpc(
                    "dsp_upsert_service_catalog_item",
                    {"admin_secret": admin_secret, "row_data": self._service_catalog_payload(ensured)},
                )
                self.store.mark_service_catalog_cloud_sync(local_id)
            except Exception as exc:
                self.store.mark_service_catalog_cloud_error(local_id, str(exc))
                raise

        return self._push_rows_concurrently(self.store.list_cloud_pending_service_catalog(limit=300), push_one)

    def _push_inventory_items(self, client: SupabaseRestClient, admin_secret: str) -> int:
        def push_one(row: Any) -> None:
            local_id = int(row["id"])
            ensured = self.store.ensure_inventory_item_cloud_id(local_id)
            try:
                client.rpc(
                    "dsp_upsert_inventory_item",
                    {"admin_secret": admin_secret, "row_data": self._inventory_item_payload(ensured)},
                )
                self.store.mark_inventory_item_cloud_sync(local_id)
            except Exception as exc:
                self.store.mark_inventory_item_cloud_error(local_id, str(exc))
                raise

        return self._push_rows_concurrently(self.store.list_cloud_pending_inventory_items(limit=200), push_one)

    def _push_app_settings(self, client: SupabaseRestClient, admin_secret: str) -> int:
        def push_one(row: Any) -> None:
            key = str(row["setting_key"])
            try:
                client.rpc(
                    "dsp_upsert_app_setting",
                    {"admin_secret": admin_secret, "row_data": self._app_setting_payload(row)},
                )
                self.store.mark_setting_cloud_sync(key)
            except Exception as exc:
                self.store.mark_setting_cloud_error(key, str(exc))
                raise

        return self._push_rows_concurrently(self.store.list_cloud_pending_settings(), push_one)

    def _push_attendance_days(self, client: SupabaseRestClient, sync_secret: str) -> int:
        def push_one(row: Any) -> None:
            local_id = int(row["id"])
            ensured = self.store.ensure_attendance_day_cloud_id(local_id)
            try:
                client.rpc(
                    "dsp_upsert_attendance_day",
                    {"sync_secret": sync_secret, "row_data": self._attendance_day_payload(ensured)},
                )
                self.store.mark_attendance_day_cloud_sync(local_id)
            except Exception as exc:
                self.store.mark_attendance_day_cloud_error(local_id, str(exc))
                raise

        return self._push_rows_concurrently(self.store.list_cloud_pending_attendance_days(limit=200), push_one)

    def _push_attendance_shifts(self, client: SupabaseRestClient, sync_secret: str) -> int:
        def push_one(row: Any) -> None:
            local_id = int(row["id"])
            ensured = self.store.ensure_attendance_shift_cloud_id(local_id)
            try:
                client.rpc(
                    "dsp_upsert_attendance_shift",
                    {"sync_secret": sync_secret, "row_data": self._attendance_shift_payload(ensured)},
                )
                self.store.mark_attendance_shift_cloud_sync(local_id)
            except Exception as exc:
                self.store.mark_attendance_shift_cloud_error(local_id, str(exc))
                raise

        return self._push_rows_concurrently(self.store.list_cloud_pending_attendance_shifts(limit=200), push_one)

    def _push_attendance_day_events(self, client: SupabaseRestClient, sync_secret: str) -> int:
        def push_one(row: Any) -> None:
            local_id = int(row["id"])
            day = self.store.ensure_attendance_day_cloud_id(int(row["day_id"]))
            ensured = self.store.ensure_attendance_day_event_cloud_id(local_id)
            try:
                client.rpc(
                    "dsp_upsert_attendance_day_event",
                    {
                        "sync_secret": sync_secret,
                        "row_data": self._attendance_day_event_payload(ensured, day["cloud_id"]),
                    },
                )
                self.store.mark_attendance_day_event_cloud_sync(local_id)
            except Exception as exc:
                self.store.mark_attendance_day_event_cloud_error(local_id, str(exc))
                raise

        return self._push_rows_concurrently(
            self.store.list_cloud_pending_attendance_day_events(limit=300), push_one
        )

    def _push_attendance_events(self, client: SupabaseRestClient, sync_secret: str) -> int:
        def push_one(row: Any) -> None:
            local_id = int(row["id"])
            shift = self.store.ensure_attendance_shift_cloud_id(int(row["shift_id"]))
            ensured = self.store.ensure_attendance_event_cloud_id(local_id)
            try:
                client.rpc(
                    "dsp_upsert_attendance_event",
                    {"sync_secret": sync_secret, "row_data": self._attendance_event_payload(ensured, shift["cloud_id"])},
                )
                self.store.mark_attendance_event_cloud_sync(local_id)
            except Exception as exc:
                self.store.mark_attendance_event_cloud_error(local_id, str(exc))
                raise

        return self._push_rows_concurrently(self.store.list_cloud_pending_attendance_events(limit=300), push_one)

    def _push_sales_entries(self, client: SupabaseRestClient, sync_secret: str) -> int:
        def push_one(row: Any) -> None:
            local_id = int(row["id"])
            ensured = self.store.ensure_sales_entry_cloud_id(local_id)
            try:
                client.rpc(
                    "dsp_upsert_sales_entry",
                    {"sync_secret": sync_secret, "row_data": self._sales_entry_payload(ensured)},
                )
                self.store.mark_sales_entry_cloud_sync(local_id)
            except Exception as exc:
                self.store.mark_sales_entry_cloud_error(local_id, str(exc))
                raise

        return self._push_rows_concurrently(self.store.list_cloud_pending_sales_entries(limit=200), push_one)

    def _push_employee_users(self, client: SupabaseRestClient, admin_secret: str) -> int:
        if self.auth_store is None:
            return 0

        def push_one(row: Any) -> None:
            username_key = str(row.get("username_key") or row.get("username", ""))
            try:
                client.rpc(
                    "dsp_upsert_employee_user",
                    {"admin_secret": admin_secret, "row_data": self._employee_user_payload(row)},
                )
                self.auth_store.mark_user_cloud_sync(username_key)
            except Exception as exc:
                self.auth_store.mark_user_cloud_error(username_key, str(exc))
                raise

        return self._push_rows_concurrently(self.auth_store.list_cloud_pending_users(limit=100), push_one)

    def _pull_employee_users(self, client: SupabaseRestClient, sync_secret: str) -> int:
        if self.auth_store is None:
            return 0
        rows = client.rpc("dsp_list_employee_users", {"sync_secret": sync_secret})
        if not isinstance(rows, list):
            return 0
        changed = 0
        for row in rows:
            if isinstance(row, dict) and self.auth_store.import_cloud_user(row):
                changed += 1
        return changed

    def _pull_attendance_days(self, client: SupabaseRestClient, admin_secret: str) -> int:
        rows = client.rpc("dsp_list_attendance_days", {"admin_secret": admin_secret})
        if not isinstance(rows, list):
            return 0
        changed = 0
        for row in rows:
            if isinstance(row, dict) and self.store.import_cloud_attendance_day(row):
                changed += 1
        return changed

    def _pull_attendance_shifts(self, client: SupabaseRestClient, admin_secret: str) -> int:
        rows = client.rpc("dsp_list_attendance_shifts", {"admin_secret": admin_secret})
        if not isinstance(rows, list):
            return 0
        changed = 0
        for row in rows:
            if isinstance(row, dict) and self.store.import_cloud_attendance_shift(row):
                changed += 1
        return changed

    def _pull_attendance_day_events(self, client: SupabaseRestClient, admin_secret: str) -> int:
        rows = client.rpc("dsp_list_attendance_day_events", {"admin_secret": admin_secret})
        if not isinstance(rows, list):
            return 0
        changed = 0
        for row in rows:
            if isinstance(row, dict) and self.store.import_cloud_attendance_day_event(row):
                changed += 1
        return changed

    def _pull_attendance_events(self, client: SupabaseRestClient, admin_secret: str) -> int:
        rows = client.rpc("dsp_list_attendance_events", {"admin_secret": admin_secret})
        if not isinstance(rows, list):
            return 0
        changed = 0
        for row in rows:
            if isinstance(row, dict) and self.store.import_cloud_attendance_event(row):
                changed += 1
        return changed

    def _pull_sales_entries(self, client: SupabaseRestClient, admin_secret: str) -> int:
        rows = client.rpc("dsp_list_sales_entries", {"admin_secret": admin_secret})
        if not isinstance(rows, list):
            return 0
        changed = 0
        for row in rows:
            if isinstance(row, dict) and self.store.import_cloud_sales_entry(row):
                changed += 1
        return changed

    def _pull_sales_entries_shared(self, client: SupabaseRestClient, sync_secret: str) -> int:
        # Employee-secret pull so admin-side edits to sales data flow back
        # to employee PCs (they never hold the admin secret). Tolerates the
        # RPC not existing yet: on a Supabase project where
        # dsp_list_sales_entries_shared hasn't been created, employees just
        # keep the old push-only behavior instead of failing every sync.
        try:
            rows = client.rpc("dsp_list_sales_entries_shared", {"sync_secret": sync_secret})
        except Exception as exc:
            message = str(exc).lower()
            if "dsp_list_sales_entries_shared" in message or "pgrst202" in message or "404" in message:
                return 0
            raise
        if not isinstance(rows, list):
            return 0
        changed = 0
        for row in rows:
            if isinstance(row, dict) and self.store.import_cloud_sales_entry(row):
                changed += 1
        return changed

    def _pull_announcements(self, client: SupabaseRestClient) -> int:
        rows = client.select(
            "dsp_announcements",
            {
                "select": "cloud_id,category,title,message,created_by,created_at,updated_at,is_active",
                "order": "created_at.desc",
                "limit": "200",
            },
        )
        changed = 0
        for row in rows:
            if self.store.import_cloud_announcement(row):
                changed += 1
        return changed

    def _pull_service_catalog(self, client: SupabaseRestClient) -> int:
        rows = client.select(
            "dsp_service_catalog",
            {
                "select": "cloud_id,service_name,created_by,created_at,updated_at,is_active",
                "order": "service_name.asc",
                "limit": "500",
            },
        )
        changed = 0
        for row in rows:
            if self.store.import_cloud_service_catalog_item(row):
                changed += 1
        return changed

    def _pull_service_templates(self, client: SupabaseRestClient) -> int:
        rows = client.select(
            "dsp_service_message_templates",
            {
                "select": "cloud_id,service_name,title,message,created_by,created_at,updated_at,is_active",
                "order": "updated_at.desc",
                "limit": "500",
            },
        )
        changed = 0
        for row in rows:
            if self.store.import_cloud_service_message_template(row):
                changed += 1
        return changed

    def _pull_inventory_items(self, client: SupabaseRestClient, sync_secret: str) -> int:
        rows = client.rpc("dsp_list_inventory_items", {"sync_secret": sync_secret})
        if not isinstance(rows, list):
            return 0
        changed = 0
        for row in rows:
            if self.store.import_cloud_inventory_item(row):
                changed += 1
        return changed

    def _pull_app_settings(self, client: SupabaseRestClient, sync_secret: str) -> int:
        rows = client.rpc("dsp_list_app_settings", {"sync_secret": sync_secret})
        if not isinstance(rows, list):
            return 0
        changed = 0
        for row in rows:
            if isinstance(row, dict) and self.store.import_cloud_app_setting(row):
                changed += 1
        return changed

    def _attendance_day_payload(self, row: dict) -> dict:
        return {
            "cloud_id": row.get("cloud_id", ""),
            "employee_username": row.get("employee_username", ""),
            "day_date": row.get("day_date", ""),
            "status": row.get("status", ""),
            "started_at": to_cloud_timestamp(row.get("started_at", "")),
            "ended_at": to_cloud_timestamp(row.get("ended_at") or ""),
            "updated_at": to_cloud_timestamp(row.get("updated_at") or row.get("ended_at") or row.get("started_at", "")),
        }

    def _attendance_shift_payload(self, row: dict) -> dict:
        return {
            "cloud_id": row.get("cloud_id", ""),
            "employee_username": row.get("employee_username", ""),
            "shift_date": row.get("shift_date", ""),
            "shift_number": int(row.get("shift_number") or 0),
            "status": row.get("status", ""),
            "started_at": to_cloud_timestamp(row.get("started_at", "")),
            "ended_at": to_cloud_timestamp(row.get("ended_at") or ""),
            "break_count": int(row.get("break_count") or 0),
            "total_break_seconds": int(row.get("total_break_seconds") or 0),
            "current_break_started_at": to_cloud_timestamp(row.get("current_break_started_at") or ""),
            "updated_at": to_cloud_timestamp(row.get("updated_at") or row.get("ended_at") or row.get("started_at", "")),
        }

    def _attendance_day_event_payload(self, row: dict, day_cloud_id: str) -> dict:
        return {
            "cloud_id": row.get("cloud_id", ""),
            "day_cloud_id": day_cloud_id,
            "employee_username": row.get("employee_username", ""),
            "day_date": row.get("day_date", ""),
            "event_type": row.get("event_type", ""),
            "event_label": row.get("event_label", ""),
            "event_time": to_cloud_timestamp(row.get("event_time", "")),
            "details": row.get("details", ""),
            "updated_at": to_cloud_timestamp(row.get("updated_at") or row.get("event_time", "")),
        }

    def _attendance_event_payload(self, row: dict, shift_cloud_id: str) -> dict:
        return {
            "cloud_id": row.get("cloud_id", ""),
            "shift_cloud_id": shift_cloud_id,
            "employee_username": row.get("employee_username", ""),
            "shift_date": row.get("shift_date", ""),
            "shift_number": int(row.get("shift_number") or 0),
            "event_type": row.get("event_type", ""),
            "event_label": row.get("event_label", ""),
            "event_time": to_cloud_timestamp(row.get("event_time", "")),
            "details": row.get("details", ""),
            "updated_at": to_cloud_timestamp(row.get("updated_at") or row.get("event_time", "")),
        }

    def _service_catalog_payload(self, row: dict) -> dict:
        return {
            "cloud_id": row.get("cloud_id", ""),
            "service_name": row.get("service_name", ""),
            "created_by": row.get("created_by", ""),
            "created_at": to_cloud_timestamp(row.get("created_at", "")),
            "updated_at": to_cloud_timestamp(row.get("updated_at") or row.get("created_at", "")),
            "is_active": bool(row.get("is_active", 1)),
        }

    def _inventory_item_payload(self, row: dict) -> dict:
        return {
            "cloud_id": row.get("cloud_id", ""),
            "service_name": row.get("service_name", ""),
            "account_email": row.get("account_email", ""),
            "account_password": row.get("account_password", ""),
            "comment": row.get("comment", ""),
            "created_by": row.get("created_by", ""),
            "created_at": to_cloud_timestamp(row.get("created_at", "")),
            "updated_at": to_cloud_timestamp(row.get("updated_at") or row.get("created_at", "")),
            "is_active": bool(row.get("is_active", 1)),
        }

    def _sales_entry_payload(self, row: dict) -> dict:
        return {
            "cloud_id": row.get("cloud_id", ""),
            "employee_username": row.get("employee_username", ""),
            "entry_date": row.get("entry_date", ""),
            "entry_time": row.get("entry_time", ""),
            "customer": row.get("customer", ""),
            "item": row.get("item", ""),
            "order_id": row.get("order_id", ""),
            "buying_amount": row.get("buying_amount", ""),
            "selling_amount": row.get("selling_amount", ""),
            "profit": row.get("profit", ""),
            "status": row.get("status", ""),
            "notes": row.get("notes", ""),
            "excel_row": row.get("excel_row"),
            "excel_synced_at": row.get("excel_synced_at", ""),
            "excel_sync_error": row.get("excel_sync_error", ""),
            "created_at": to_cloud_timestamp(row.get("created_at", "")),
            "updated_at": to_cloud_timestamp(row.get("updated_at") or row.get("created_at", "")),
        }

    def _app_setting_payload(self, row: dict) -> dict:
        return {
            "setting_key": row.get("setting_key", ""),
            "setting_value": row.get("setting_value", ""),
            "updated_at": to_cloud_timestamp(row.get("updated_at", "")),
        }

    def _employee_user_payload(self, row: dict) -> dict:
        username = str(row.get("username", "")).strip()
        return {
            "username_key": str(row.get("username_key") or username).strip().lower(),
            "username": username,
            "display_name": row.get("display_name") or username,
            "role": "employee",
            "is_active": bool(row.get("is_active", True)),
            "is_deleted": bool(row.get("is_deleted", False)),
            "password_hash": row.get("password_hash", ""),
            "created_at": to_cloud_timestamp(row.get("created_at", "")),
            "updated_at": to_cloud_timestamp(row.get("updated_at") or row.get("created_at", "")),
            "deleted_at": to_cloud_timestamp(row.get("deleted_at", "")),
        }

    def _announcement_payload(self, row: dict) -> dict:
        return {
            "cloud_id": row.get("cloud_id", ""),
            "category": row.get("category", ""),
            "title": row.get("title", ""),
            "message": row.get("message", ""),
            "created_by": row.get("created_by", ""),
            "created_at": to_cloud_timestamp(row.get("created_at", "")),
            "updated_at": to_cloud_timestamp(row.get("updated_at") or row.get("created_at", "")),
            "is_active": bool(row.get("is_active", 1)),
        }

    def _service_template_payload(self, row: dict) -> dict:
        return {
            "cloud_id": row.get("cloud_id", ""),
            "service_name": row.get("service_name", ""),
            "title": row.get("title") or row.get("service_name", ""),
            "message": row.get("message", ""),
            "created_by": row.get("created_by", ""),
            "created_at": to_cloud_timestamp(row.get("created_at", "")),
            "updated_at": to_cloud_timestamp(row.get("updated_at") or row.get("created_at", "")),
            "is_active": bool(row.get("is_active", 1)),
        }


def _file_config() -> dict:
    try:
        if SUPABASE_CONFIG_PATH.exists():
            return json.loads(SUPABASE_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {}


def load_supabase_config(store) -> SupabaseConfig:
    file_data = _file_config()
    url = store.get_setting("supabase_url", "") or os.environ.get("DSP_SUPABASE_URL", "") or SUPABASE_URL or file_data.get("url", "")
    anon_key = (
        store.get_setting("supabase_anon_key", "")
        or os.environ.get("DSP_SUPABASE_ANON_KEY", "")
        or SUPABASE_ANON_KEY
        or file_data.get("anon_key", "")
    )
    admin_secret = (
        store.get_setting("supabase_admin_secret", "")
        or os.environ.get("DSP_SUPABASE_ADMIN_SECRET", "")
        or SUPABASE_ADMIN_SECRET
        or file_data.get("admin_secret", "")
    )
    employee_sync_secret = (
        store.get_setting("supabase_employee_sync_secret", "")
        or os.environ.get("DSP_SUPABASE_EMPLOYEE_SYNC_SECRET", "")
        or SUPABASE_EMPLOYEE_SYNC_SECRET
        or file_data.get("employee_sync_secret", "")
    )
    enabled_setting = store.get_setting("supabase_sync_enabled", "")
    if enabled_setting:
        enabled = enabled_setting.strip().lower() in {"1", "true", "yes", "on"}
    else:
        enabled = bool(file_data.get("enabled", bool(url and anon_key)))
    return SupabaseConfig(
        enabled=enabled,
        url=str(url).strip(),
        anon_key=str(anon_key).strip(),
        admin_secret=str(admin_secret).strip(),
        employee_sync_secret=str(employee_sync_secret).strip(),
    )


def save_supabase_config(store, config: SupabaseConfig) -> None:
    store.set_setting("supabase_sync_enabled", "1" if config.enabled else "0")
    store.set_setting("supabase_url", config.url.strip())
    store.set_setting("supabase_anon_key", config.anon_key.strip())
    store.set_setting("supabase_admin_secret", config.admin_secret.strip())
    store.set_setting("supabase_employee_sync_secret", config.employee_sync_secret.strip())


def write_supabase_config_file(config: SupabaseConfig) -> Path:
    SUPABASE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "enabled": config.enabled,
        "url": config.url.strip(),
        "anon_key": config.anon_key.strip(),
        "admin_secret": config.admin_secret.strip(),
        "employee_sync_secret": config.employee_sync_secret.strip(),
    }
    SUPABASE_CONFIG_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return SUPABASE_CONFIG_PATH


def cloud_sync_interval_ms() -> int:
    return max(5, SUPABASE_SYNC_INTERVAL_SECONDS) * 1000