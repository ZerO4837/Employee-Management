from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.config import ADMIN_PASSWORD, ADMIN_USERNAME, DEFAULT_PASSWORD, DEFAULT_USERNAME, RESET_CODE


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


class AuthStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data = self._load()

    def _default_data(self) -> dict[str, dict[str, dict[str, str]]]:
        return {
            "users": {
                DEFAULT_USERNAME.lower(): {
                    "username": DEFAULT_USERNAME,
                    "role": "employee",
                    "password_hash": hash_password(DEFAULT_PASSWORD),
                },
                ADMIN_USERNAME.lower(): {
                    "username": ADMIN_USERNAME,
                    "role": "admin",
                    "password_hash": hash_password(ADMIN_PASSWORD),
                },
            }
        }

    def _load(self) -> dict:
        default_data = self._default_data()
        if not self.path.exists():
            return default_data
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default_data

        if "users" in data and isinstance(data["users"], dict):
            users = default_data["users"] | data["users"]
            for key, user in default_data["users"].items():
                users.setdefault(key, user)
            return {"users": users}

        # Migrate the first prototype's single-user config shape.
        if "username" in data and "password_hash" in data:
            migrated = default_data
            employee_key = str(data["username"]).lower()
            migrated["users"][employee_key] = {
                "username": str(data["username"]),
                "role": "employee",
                "password_hash": str(data["password_hash"]),
            }
            return migrated

        return default_data

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")

    def verify(self, username: str, password: str) -> dict[str, str] | None:
        user = self.data["users"].get(username.strip().lower())
        if not user:
            return None
        if hash_password(password) != user["password_hash"]:
            return None
        return {"username": user["username"], "role": user["role"]}

    def reset_password(self, private_code: str, new_password: str) -> tuple[bool, str]:
        if private_code.strip() != RESET_CODE:
            return False, "Private code is incorrect."
        if len(new_password) < 8:
            return False, "Password must be at least 8 characters."
        employee = self.data["users"][DEFAULT_USERNAME.lower()]
        employee["password_hash"] = hash_password(new_password)
        self.save()
        return True, "Employee password reset successfully."
