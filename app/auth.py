from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import datetime
from pathlib import Path

from app.config import ADMIN_PASSWORD, ADMIN_USERNAME, DEFAULT_PASSWORD, DEFAULT_USERNAME, RESET_CODE


HASH_ITERATIONS = 260_000
BOOTSTRAP_FILENAME = "bootstrap_credentials.txt"


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), HASH_ITERATIONS)
    return f"pbkdf2_sha256${HASH_ITERATIONS}${salt}${digest.hex()}"


def _legacy_sha256(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(password: str, stored_hash: str) -> bool:
    if stored_hash.startswith("pbkdf2_sha256$"):
        try:
            _algorithm, iterations_text, salt, expected = stored_hash.split("$", 3)
            iterations = int(iterations_text)
        except ValueError:
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
        return hmac.compare_digest(digest.hex(), expected)
    return hmac.compare_digest(_legacy_sha256(password), stored_hash)


def _generated_secret() -> str:
    return secrets.token_urlsafe(18)


def generate_password() -> str:
    return secrets.token_urlsafe(12)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _user_key(username: str) -> str:
    return username.strip().lower()


def _as_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class AuthStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data = self._load()

    def _bootstrap_password(self, configured_password: str, label: str) -> tuple[str, bool]:
        if configured_password:
            return configured_password, False
        existing = self._read_bootstrap_secret(label)
        if existing:
            return existing, False
        generated = _generated_secret()
        self._write_bootstrap_secret(label, generated)
        return generated, True

    def _bootstrap_reset_code(self) -> str:
        if RESET_CODE:
            return RESET_CODE
        existing = self._read_bootstrap_secret("Reset code")
        if existing:
            return existing
        generated = secrets.token_urlsafe(12)
        self._write_bootstrap_secret("Reset code", generated)
        return generated

    def _read_bootstrap_secret(self, label: str) -> str:
        bootstrap_path = self.path.parent / BOOTSTRAP_FILENAME
        try:
            lines = bootstrap_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return ""
        prefix = f"{label}: "
        for line in lines:
            if line.startswith(prefix):
                return line[len(prefix) :].strip()
        return ""

    def _write_bootstrap_secret(self, label: str, value: str) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            bootstrap_path = self.path.parent / BOOTSTRAP_FILENAME
            existing = bootstrap_path.read_text(encoding="utf-8") if bootstrap_path.exists() else ""
            line = f"{label}: {value}\n"
            if line not in existing:
                bootstrap_path.write_text(existing + line, encoding="utf-8")
        except OSError:
            pass

    def _remove_bootstrap_secret(self, label: str) -> None:
        bootstrap_path = self.path.parent / BOOTSTRAP_FILENAME
        try:
            lines = bootstrap_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        prefix = f"{label}: "
        kept_lines = [line for line in lines if not line.startswith(prefix)]
        try:
            if kept_lines:
                bootstrap_path.write_text("\n".join(kept_lines) + "\n", encoding="utf-8")
            else:
                bootstrap_path.unlink(missing_ok=True)
        except OSError:
            pass

    def has_bootstrap_secret(self, label: str) -> bool:
        return bool(self._read_bootstrap_secret(label))

    def _default_data(self) -> dict:
        employee_password, _ = self._bootstrap_password(DEFAULT_PASSWORD, "Employee password")
        admin_password, _ = self._bootstrap_password(ADMIN_PASSWORD, "Admin password")
        reset_code = self._bootstrap_reset_code()
        return {
            "users": {
                DEFAULT_USERNAME.lower(): {
                    "username": DEFAULT_USERNAME,
                    "display_name": DEFAULT_USERNAME,
                    "role": "employee",
                    "is_active": True,
                    "password_hash": hash_password(employee_password),
                    "created_at": _now(),
                    "updated_at": _now(),
                },
                ADMIN_USERNAME.lower(): {
                    "username": ADMIN_USERNAME,
                    "display_name": "Admin",
                    "role": "admin",
                    "is_active": True,
                    "password_hash": hash_password(admin_password),
                    "created_at": _now(),
                    "updated_at": _now(),
                },
            },
            "reset_code_hash": hash_password(reset_code),
        }

    def _normalize_user(self, user: dict) -> dict:
        username = str(user.get("username", "")).strip()
        normalized = dict(user)
        normalized["username"] = username
        normalized["display_name"] = str(user.get("display_name") or username).strip() or username
        normalized["role"] = str(user.get("role") or "employee").strip().lower()
        normalized["is_active"] = _as_bool(user.get("is_active", True), True)
        normalized["is_deleted"] = _as_bool(user.get("is_deleted", False), False)
        normalized["password_hash"] = str(user.get("password_hash", ""))
        normalized["created_at"] = str(user.get("created_at", ""))
        normalized["updated_at"] = str(user.get("updated_at", ""))
        normalized["deleted_at"] = str(user.get("deleted_at", ""))
        normalized["cloud_synced_at"] = str(user.get("cloud_synced_at", ""))
        normalized["cloud_sync_error"] = str(user.get("cloud_sync_error", ""))
        return normalized

    def _load(self) -> dict:
        default_data = self._default_data()
        if not self.path.exists():
            self.data = default_data
            self.save()
            return default_data
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default_data

        if "users" in data and isinstance(data["users"], dict):
            saved_users = data["users"]
            users = {
                key: self._normalize_user(user)
                for key, user in (default_data["users"] | saved_users).items()
                if isinstance(user, dict)
            }
            changed = "reset_code_hash" not in data
            for key, user in default_data["users"].items():
                if key not in saved_users:
                    changed = True
            for key, user in users.items():
                original = saved_users.get(key, {})
                if not isinstance(original, dict) or self._normalize_user(original) != user:
                    changed = True
            reset_code_hash = data.get("reset_code_hash") or default_data["reset_code_hash"]
            loaded = {"users": users, "reset_code_hash": reset_code_hash}
            if changed:
                self.data = loaded
                self.save()
            return loaded

        # Migrate the first prototype's single-user config shape.
        if "username" in data and "password_hash" in data:
            migrated = default_data
            employee_key = str(data["username"]).lower()
            migrated["users"][employee_key] = {
                "username": str(data["username"]),
                "display_name": str(data["username"]),
                "role": "employee",
                "is_active": True,
                "password_hash": str(data["password_hash"]),
                "created_at": _now(),
                "updated_at": _now(),
            }
            self.data = migrated
            self.save()
            return migrated

        return default_data

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")

    def is_user_inactive(self, username: str) -> bool:
        user = self.data["users"].get(_user_key(username))
        return user is not None and not bool(user.get("is_deleted", False)) and not bool(user.get("is_active", True))

    def verify(self, username: str, password: str) -> dict[str, str] | None:
        user = self.data["users"].get(_user_key(username))
        if not user or user.get("is_deleted", False):
            return None
        if not user.get("is_active", True):
            return None
        if not verify_password(password, user["password_hash"]):
            return None
        if not user["password_hash"].startswith("pbkdf2_sha256$"):
            user["password_hash"] = hash_password(password)
            user["updated_at"] = _now()
            self.save()
        return {
            "username": user["username"],
            "display_name": user.get("display_name") or user["username"],
            "role": user["role"],
        }

    def reset_password(self, private_code: str, new_password: str) -> tuple[bool, str]:
        reset_code_hash = self.data.get("reset_code_hash", "")
        if not reset_code_hash or not verify_password(private_code.strip(), reset_code_hash):
            return False, "Private code is incorrect."
        if len(new_password) < 8:
            return False, "Password must be at least 8 characters."
        employee = self.data["users"][DEFAULT_USERNAME.lower()]
        employee["password_hash"] = hash_password(new_password)
        employee["updated_at"] = _now()
        employee["cloud_synced_at"] = ""
        employee["cloud_sync_error"] = ""
        self.save()
        return True, "Employee password reset successfully."

    def list_users(self, include_admin: bool = False) -> list[dict]:
        users = []
        for user in self.data.get("users", {}).values():
            if user.get("is_deleted", False):
                continue
            if not include_admin and user.get("role") == "admin":
                continue
            item = {
                "username": user.get("username", ""),
                "display_name": user.get("display_name") or user.get("username", ""),
                "role": user.get("role", "employee"),
                "is_active": bool(user.get("is_active", True)),
                "created_at": user.get("created_at", ""),
                "updated_at": user.get("updated_at", ""),
            }
            users.append(item)
        users.sort(key=lambda item: item["username"].casefold())
        return users

    def get_user(self, username: str) -> dict | None:
        user = self.data.get("users", {}).get(_user_key(username))
        if user is None or user.get("is_deleted", False):
            return None
        return {
            "username": user.get("username", ""),
            "display_name": user.get("display_name") or user.get("username", ""),
            "role": user.get("role", "employee"),
            "is_active": bool(user.get("is_active", True)),
            "created_at": user.get("created_at", ""),
            "updated_at": user.get("updated_at", ""),
        }

    def create_user(
        self,
        display_name: str,
        username: str,
        password: str | None = None,
        role: str = "employee",
    ) -> tuple[bool, str, str]:
        username = username.strip()
        display_name = display_name.strip() or username
        role = role.strip().lower() or "employee"
        if not username:
            return False, "Username is required.", ""
        existing_user = self.data["users"].get(_user_key(username))
        if existing_user is not None and not existing_user.get("is_deleted", False):
            return False, "Username already exists.", ""
        if role not in {"employee", "admin"}:
            return False, "Role must be employee or admin.", ""
        password = password or generate_password()
        if len(password) < 8:
            return False, "Password must be at least 8 characters.", ""
        now = _now()
        self.data["users"][_user_key(username)] = {
            "username": username,
            "display_name": display_name,
            "role": role,
            "is_active": True,
            "password_hash": hash_password(password),
            "created_at": now,
            "updated_at": now,
            "deleted_at": "",
            "is_deleted": False,
            "cloud_synced_at": "",
            "cloud_sync_error": "",
        }
        self.save()
        return True, "User created.", password

    def update_user(
        self,
        original_username: str,
        display_name: str,
        username: str,
        is_active: bool,
    ) -> tuple[bool, str]:
        original_key = _user_key(original_username)
        user = self.data["users"].get(original_key)
        if user is None:
            return False, "User could not be found."
        if user.get("role") == "admin":
            return False, "Admin account cannot be edited here."
        new_key = _user_key(username)
        if not new_key:
            return False, "Username is required."
        existing_new_user = self.data["users"].get(new_key)
        if new_key != original_key and existing_new_user is not None and not existing_new_user.get("is_deleted", False):
            return False, "Username already exists."
        now = _now()
        old_username = user.get("username", original_username)
        old_display_name = user.get("display_name", old_username)
        user["username"] = username.strip()
        user["display_name"] = display_name.strip() or username.strip()
        user["is_active"] = bool(is_active)
        user["is_deleted"] = False
        user["deleted_at"] = ""
        user["updated_at"] = now
        user["cloud_synced_at"] = ""
        user["cloud_sync_error"] = ""
        if new_key != original_key:
            self.data["users"][new_key] = user
            self.data["users"][original_key] = {
                "username": old_username,
                "display_name": old_display_name,
                "role": "employee",
                "is_active": False,
                "is_deleted": True,
                "password_hash": "",
                "created_at": user.get("created_at", now),
                "updated_at": now,
                "deleted_at": now,
                "cloud_synced_at": "",
                "cloud_sync_error": "",
            }
        self.save()
        return True, "User updated."

    def set_user_active(self, username: str, is_active: bool) -> tuple[bool, str]:
        user = self.data["users"].get(_user_key(username))
        if user is None:
            return False, "User could not be found."
        if user.get("role") == "admin":
            return False, "Admin account cannot be frozen here."
        user["is_active"] = bool(is_active)
        user["updated_at"] = _now()
        user["cloud_synced_at"] = ""
        user["cloud_sync_error"] = ""
        self.save()
        return True, "User status updated."

    def reset_user_password(self, username: str, password: str | None = None) -> tuple[bool, str, str]:
        user = self.data["users"].get(_user_key(username))
        if user is None:
            return False, "User could not be found.", ""
        if user.get("role") == "admin":
            return False, "Admin password cannot be reset here.", ""
        password = password or generate_password()
        if len(password) < 8:
            return False, "Password must be at least 8 characters.", ""
        user["password_hash"] = hash_password(password)
        user["updated_at"] = _now()
        user["cloud_synced_at"] = ""
        user["cloud_sync_error"] = ""
        self.save()
        return True, "Password reset.", password

    def change_own_password(self, username: str, current_password: str, new_password: str) -> tuple[bool, str]:
        user = self.data["users"].get(_user_key(username))
        if user is None or user.get("is_deleted", False):
            return False, "User could not be found."
        if not user.get("is_active", True):
            return False, "This account is not active."
        if not verify_password(current_password, user.get("password_hash", "")):
            return False, "Current password is incorrect."
        if len(new_password) < 8:
            return False, "New password must be at least 8 characters."
        user["password_hash"] = hash_password(new_password)
        user["updated_at"] = _now()
        if user.get("role") != "admin":
            user["cloud_synced_at"] = ""
            user["cloud_sync_error"] = ""
        self.save()
        if user.get("role") == "admin":
            self._remove_bootstrap_secret("Admin password")
        return True, "Password updated."

    def delete_user(self, username: str) -> tuple[bool, str]:
        key = _user_key(username)
        user = self.data["users"].get(key)
        if user is None:
            return False, "User could not be found."
        if user.get("role") == "admin":
            return False, "Admin account cannot be removed here."
        now = _now()
        user["is_active"] = False
        user["is_deleted"] = True
        user["password_hash"] = ""
        user["deleted_at"] = now
        user["updated_at"] = now
        user["cloud_synced_at"] = ""
        user["cloud_sync_error"] = ""
        self.save()
        return True, "User removed."

    def list_cloud_pending_users(self, limit: int = 100) -> list[dict]:
        users: list[dict] = []
        for key, user in self.data.get("users", {}).items():
            if user.get("role") == "admin":
                continue
            updated_at = str(user.get("updated_at", ""))
            cloud_synced_at = str(user.get("cloud_synced_at", ""))
            if cloud_synced_at and cloud_synced_at >= updated_at and not user.get("cloud_sync_error"):
                continue
            item = dict(user)
            item["username_key"] = key
            users.append(item)
            if len(users) >= limit:
                break
        users.sort(key=lambda item: (str(item.get("updated_at", "")), str(item.get("username_key", ""))))
        return users

    def mark_user_cloud_sync(self, username: str) -> None:
        key = _user_key(username)
        user = self.data.get("users", {}).get(key)
        if user is None:
            return
        user["cloud_synced_at"] = _now()
        user["cloud_sync_error"] = ""
        self.save()

    def mark_user_cloud_error(self, username: str, error: str) -> None:
        key = _user_key(username)
        user = self.data.get("users", {}).get(key)
        if user is None:
            return
        user["cloud_sync_error"] = error[:500]
        self.save()

    def import_cloud_user(self, item: dict) -> bool:
        username = str(item.get("username", "")).strip()
        key = str(item.get("username_key") or _user_key(username)).strip().lower()
        if not key:
            return False
        existing = self.data.get("users", {}).get(key)
        updated_at = str(item.get("updated_at") or _now())
        if existing is not None:
            local_updated = str(existing.get("updated_at", ""))
            if local_updated >= updated_at and not existing.get("cloud_sync_error"):
                return False
        is_deleted = _as_bool(item.get("is_deleted", False), False)
        now = _now()
        if is_deleted:
            synced_user = {
                "username": username or (existing or {}).get("username", key),
                "display_name": str(item.get("display_name") or (existing or {}).get("display_name") or username or key),
                "role": "employee",
                "is_active": False,
                "is_deleted": True,
                "password_hash": "",
                "created_at": str(item.get("created_at") or (existing or {}).get("created_at") or updated_at),
                "updated_at": updated_at,
                "deleted_at": str(item.get("deleted_at") or updated_at),
                "cloud_synced_at": now,
                "cloud_sync_error": "",
            }
        else:
            password_hash = str(item.get("password_hash") or (existing or {}).get("password_hash", ""))
            if not username or not password_hash:
                return False
            synced_user = {
                "username": username,
                "display_name": str(item.get("display_name") or username),
                "role": "employee",
                "is_active": _as_bool(item.get("is_active", True), True),
                "is_deleted": False,
                "password_hash": password_hash,
                "created_at": str(item.get("created_at") or (existing or {}).get("created_at") or updated_at),
                "updated_at": updated_at,
                "deleted_at": "",
                "cloud_synced_at": now,
                "cloud_sync_error": "",
            }
        self.data["users"][key] = synced_user
        self.save()
        return True
