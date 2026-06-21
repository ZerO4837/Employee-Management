from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.error
import urllib.request

from app.config import APP_VERSION, BASE_DIR, UPDATE_REPO_NAME, UPDATE_REPO_OWNER


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    download_url: str
    size: int = 0


@dataclass(frozen=True)
class UpdateInfo:
    available: bool
    current_version: str = APP_VERSION
    latest_version: str = ""
    release_url: str = ""
    asset: ReleaseAsset | None = None
    message: str = ""
    can_update: bool = False


def _startupinfo():
    if os.name != "nt":
        return None
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return startupinfo


def _version_parts(value: str) -> tuple[int, ...]:
    cleaned = value.strip().lstrip("vV")
    numbers = re.findall(r"\d+", cleaned)
    return tuple(int(number) for number in numbers) or (0,)


def _is_newer(latest: str, current: str) -> bool:
    latest_parts = _version_parts(latest)
    current_parts = _version_parts(current)
    length = max(len(latest_parts), len(current_parts))
    latest_parts += (0,) * (length - len(latest_parts))
    current_parts += (0,) * (length - len(current_parts))
    return latest_parts > current_parts


def _release_request(url: str, timeout: int = 10) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "Digital-Service-Pakistan-Employee-App",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _asset_priority(name: str) -> int:
    lower = name.lower()
    if os.name == "nt":
        if lower.endswith(".exe"):
            return 0
        if lower.endswith(".msi"):
            return 1
        if lower.endswith(".zip"):
            return 2
    if lower.endswith(".zip"):
        return 3
    return 99


def _select_asset(assets: list[dict]) -> ReleaseAsset | None:
    candidates: list[ReleaseAsset] = []
    for asset in assets:
        name = str(asset.get("name", ""))
        download_url = str(asset.get("browser_download_url", ""))
        if not name or not download_url:
            continue
        if _asset_priority(name) >= 99:
            continue
        candidates.append(ReleaseAsset(name=name, download_url=download_url, size=int(asset.get("size") or 0)))
    candidates.sort(key=lambda asset: (_asset_priority(asset.name), asset.name.lower()))
    return candidates[0] if candidates else None


def check_for_update() -> UpdateInfo:
    url = f"https://api.github.com/repos/{UPDATE_REPO_OWNER}/{UPDATE_REPO_NAME}/releases/latest"
    try:
        release = _release_request(url)
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return UpdateInfo(available=False, message=str(exc))

    latest_version = str(release.get("tag_name", "")).strip()
    release_url = str(release.get("html_url", "")).strip()
    if not latest_version:
        return UpdateInfo(available=False, message="Latest release has no version tag.")
    if not _is_newer(latest_version, APP_VERSION):
        return UpdateInfo(available=False, latest_version=latest_version, release_url=release_url)

    asset = _select_asset(list(release.get("assets") or []))
    if asset is None:
        return UpdateInfo(
            available=True,
            latest_version=latest_version,
            release_url=release_url,
            message="Latest release has no .exe, .msi, or .zip asset.",
            can_update=False,
        )
    return UpdateInfo(
        available=True,
        latest_version=latest_version,
        release_url=release_url,
        asset=asset,
        can_update=True,
    )


def start_update_and_relaunch(update_info: UpdateInfo, repo_root: Path = BASE_DIR) -> tuple[bool, str]:
    if update_info.asset is None:
        return False, update_info.message or "No downloadable update asset was found."

    if getattr(sys, "frozen", False):
        relaunch = [sys.executable]
    else:
        relaunch = [sys.executable, str(repo_root / "main.py")]

    command = [
        sys.executable,
        "-m",
        "app.update_runner",
        "--app-dir",
        str(repo_root),
        "--pid",
        str(os.getpid()),
        "--asset-url",
        update_info.asset.download_url,
        "--asset-name",
        update_info.asset.name,
        "--relaunch",
        *relaunch,
    ]
    creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    subprocess.Popen(
        command,
        cwd=str(repo_root),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        startupinfo=_startupinfo(),
        creationflags=creationflags,
    )
    return True, "Updater started."
