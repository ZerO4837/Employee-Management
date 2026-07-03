from __future__ import annotations

from dataclasses import dataclass
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

from app.config import APP_VERSION, UPDATE_REPO_NAME, UPDATE_REPO_OWNER


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


# A freshly downloaded, unsigned .exe is exactly what Windows Defender/
# SmartScreen scans hardest before releasing its lock - on a slow link or a
# build hash it has never seen, that scan can run well past ten seconds.
# This retries on the specific access-denied symptom with a generous
# budget rather than failing the whole update over a transient lock.
LOCK_RETRY_TOTAL_SECONDS = 300.0
LOCK_RETRY_INITIAL_DELAY = 2.0
LOCK_RETRY_MAX_DELAY = 20.0
LOCK_RETRY_BACKOFF = 1.6


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
            message="Latest release has no .exe or .msi asset.",
            can_update=False,
        )
    return UpdateInfo(
        available=True,
        latest_version=latest_version,
        release_url=release_url,
        asset=asset,
        can_update=True,
    )


def _downloads_dir() -> Path:
    # A stable, known location (not an auto-deleted TemporaryDirectory) so
    # that if the install step ever fails, the installer survives for the
    # user to run manually instead of vanishing along with the temp dir.
    directory = Path(tempfile.gettempdir()) / "DSPEmployeeUpdates"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _clear_directory(directory: Path) -> None:
    for child in directory.iterdir():
        try:
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
        except OSError:
            pass


DOWNLOAD_MAX_ATTEMPTS = 3
DOWNLOAD_RETRY_DELAYS = (2.0, 4.0)


def download_update(update_info: UpdateInfo, progress_callback=None, timeout: int = 120) -> Path:
    if update_info.asset is None:
        raise ValueError("No downloadable update asset was found.")

    download_dir = _downloads_dir()
    safe_name = Path(update_info.asset.name).name or "update_asset"
    target_path = download_dir / safe_name

    last_exc: Exception | None = None
    for attempt in range(DOWNLOAD_MAX_ATTEMPTS):
        if attempt:
            time.sleep(DOWNLOAD_RETRY_DELAYS[min(attempt - 1, len(DOWNLOAD_RETRY_DELAYS) - 1)])
        _clear_directory(download_dir)
        try:
            request = urllib.request.Request(
                update_info.asset.download_url,
                headers={"User-Agent": "Digital-Service-Pakistan-Employee-App"},
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                total = int(response.headers.get("Content-Length", "0") or 0)
                downloaded = 0
                with target_path.open("wb") as output:
                    while True:
                        chunk = response.read(1024 * 128)
                        if not chunk:
                            break
                        output.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(downloaded, total)

            actual_size = target_path.stat().st_size
            if total and actual_size != total:
                raise OSError(f"Download incomplete: expected {total} bytes, got {actual_size}.")
            return target_path
        except (OSError, urllib.error.URLError, TimeoutError, http.client.HTTPException) as exc:
            # HTTPException covers mid-stream disconnects (IncompleteRead)
            # that aren't OSError subclasses - without it, pulling the
            # network cable mid-download would crash past the retry loop.
            last_exc = exc

    raise OSError(
        f"Download failed after {DOWNLOAD_MAX_ATTEMPTS} attempts. Last error: {last_exc}"
    ) from last_exc


def _is_access_denied(exc: OSError) -> bool:
    return getattr(exc, "winerror", None) == 5 or exc.errno == 13


def install_update(installer_path: Path) -> subprocess.Popen:
    """Launch the installer directly, the same way the reference project does.

    No separate updater process and no "wait for this app to exit first" -
    /CLOSEAPPLICATIONS (paired with CloseApplications=yes in the .iss) tells
    Inno Setup to close the running app itself as part of installing, which
    routes through this app's own WM_DELETE_WINDOW handler (close_app) like
    a normal close - rather than this code trying to orchestrate that
    sequencing itself in a second process.
    """
    suffix = installer_path.suffix.lower()
    if suffix == ".msi":
        command = ["msiexec", "/i", str(installer_path), "/passive"]
    else:
        command = [
            str(installer_path),
            "/SP-",
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/CLOSEAPPLICATIONS",
        ]

    deadline = time.monotonic() + LOCK_RETRY_TOTAL_SECONDS
    delay = LOCK_RETRY_INITIAL_DELAY
    while True:
        try:
            return subprocess.Popen(command, startupinfo=_startupinfo(), close_fds=True)
        except OSError as exc:
            if not _is_access_denied(exc):
                raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise OSError(
                    f"Installer stayed locked for over {int(LOCK_RETRY_TOTAL_SECONDS)} seconds "
                    f"(most likely antivirus scanning) - giving up: {exc}"
                ) from exc
            time.sleep(min(delay, remaining))
            delay = min(delay * LOCK_RETRY_BACKOFF, LOCK_RETRY_MAX_DELAY)
