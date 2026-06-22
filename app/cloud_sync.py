from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
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

    def sync(self, push_local: bool = False, pull_remote: bool = True) -> CloudSyncResult:
        config = self.config_loader()
        if not config.is_ready:
            return CloudSyncResult(enabled=False, ok=True, message="Cloud sync is not configured.")
        client = SupabaseRestClient(config)
        pushed = 0
        pulled = 0
        try:
            if push_local and config.can_push:
                pushed += self._push_employee_users(client, config.admin_secret)
                pushed += self._push_announcements(client, config.admin_secret)
                pushed += self._push_service_catalog(client, config.admin_secret)
                pushed += self._push_service_templates(client, config.admin_secret)
                pushed += self._push_inventory_items(client, config.admin_secret)
            if pull_remote:
                if config.can_pull_users:
                    pulled += self._pull_employee_users(client, config.user_sync_secret)
                    pulled += self._pull_inventory_items(client, config.user_sync_secret)
                pulled += self._pull_announcements(client)
                pulled += self._pull_service_catalog(client)
                pulled += self._pull_service_templates(client)
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
        pushed = 0
        for row in self.store.list_cloud_pending_announcements(limit=100):
            local_id = int(row["id"])
            row = self.store.ensure_announcement_cloud_id(local_id)
            try:
                client.rpc(
                    "dsp_upsert_announcement",
                    {"admin_secret": admin_secret, "row_data": self._announcement_payload(row)},
                )
                self.store.mark_announcement_cloud_sync(local_id)
                pushed += 1
            except Exception as exc:
                self.store.mark_announcement_cloud_error(local_id, str(exc))
                raise
        return pushed

    def _push_service_templates(self, client: SupabaseRestClient, admin_secret: str) -> int:
        pushed = 0
        for row in self.store.list_cloud_pending_service_message_templates(limit=150):
            local_id = int(row["id"])
            row = self.store.ensure_service_message_template_cloud_id(local_id)
            try:
                client.rpc(
                    "dsp_upsert_service_message_template",
                    {"admin_secret": admin_secret, "row_data": self._service_template_payload(row)},
                )
                self.store.mark_service_message_template_cloud_sync(local_id)
                pushed += 1
            except Exception as exc:
                self.store.mark_service_message_template_cloud_error(local_id, str(exc))
                raise
        return pushed

    def _push_service_catalog(self, client: SupabaseRestClient, admin_secret: str) -> int:
        pushed = 0
        for row in self.store.list_cloud_pending_service_catalog(limit=300):
            local_id = int(row["id"])
            row = self.store.ensure_service_catalog_cloud_id(local_id)
            try:
                client.rpc(
                    "dsp_upsert_service_catalog_item",
                    {"admin_secret": admin_secret, "row_data": self._service_catalog_payload(row)},
                )
                self.store.mark_service_catalog_cloud_sync(local_id)
                pushed += 1
            except Exception as exc:
                self.store.mark_service_catalog_cloud_error(local_id, str(exc))
                raise
        return pushed

    def _push_inventory_items(self, client: SupabaseRestClient, admin_secret: str) -> int:
        pushed = 0
        for row in self.store.list_cloud_pending_inventory_items(limit=200):
            local_id = int(row["id"])
            row = self.store.ensure_inventory_item_cloud_id(local_id)
            try:
                client.rpc(
                    "dsp_upsert_inventory_item",
                    {"admin_secret": admin_secret, "row_data": self._inventory_item_payload(row)},
                )
                self.store.mark_inventory_item_cloud_sync(local_id)
                pushed += 1
            except Exception as exc:
                self.store.mark_inventory_item_cloud_error(local_id, str(exc))
                raise
        return pushed

    def _push_employee_users(self, client: SupabaseRestClient, admin_secret: str) -> int:
        if self.auth_store is None:
            return 0
        pushed = 0
        for row in self.auth_store.list_cloud_pending_users(limit=100):
            username_key = str(row.get("username_key") or row.get("username", ""))
            try:
                client.rpc(
                    "dsp_upsert_employee_user",
                    {"admin_secret": admin_secret, "row_data": self._employee_user_payload(row)},
                )
                self.auth_store.mark_user_cloud_sync(username_key)
                pushed += 1
            except Exception as exc:
                self.auth_store.mark_user_cloud_error(username_key, str(exc))
                raise
        return pushed

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

    def _service_catalog_payload(self, row: dict) -> dict:
        return {
            "cloud_id": row.get("cloud_id", ""),
            "service_name": row.get("service_name", ""),
            "created_by": row.get("created_by", ""),
            "created_at": row.get("created_at", ""),
            "updated_at": row.get("updated_at") or row.get("created_at", ""),
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
            "created_at": row.get("created_at", ""),
            "updated_at": row.get("updated_at") or row.get("created_at", ""),
            "is_active": bool(row.get("is_active", 1)),
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
            "created_at": row.get("created_at", ""),
            "updated_at": row.get("updated_at") or row.get("created_at", ""),
            "deleted_at": row.get("deleted_at", ""),
        }

    def _announcement_payload(self, row: dict) -> dict:
        return {
            "cloud_id": row.get("cloud_id", ""),
            "category": row.get("category", ""),
            "title": row.get("title", ""),
            "message": row.get("message", ""),
            "created_by": row.get("created_by", ""),
            "created_at": row.get("created_at", ""),
            "updated_at": row.get("updated_at") or row.get("created_at", ""),
            "is_active": bool(row.get("is_active", 1)),
        }

    def _service_template_payload(self, row: dict) -> dict:
        return {
            "cloud_id": row.get("cloud_id", ""),
            "service_name": row.get("service_name", ""),
            "title": row.get("title") or row.get("service_name", ""),
            "message": row.get("message", ""),
            "created_by": row.get("created_by", ""),
            "created_at": row.get("created_at", ""),
            "updated_at": row.get("updated_at") or row.get("created_at", ""),
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