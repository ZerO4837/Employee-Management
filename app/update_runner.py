from __future__ import annotations

import argparse
import ctypes
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import urllib.request
import zipfile


EXCLUDED_UPDATE_NAMES = {
    ".git",
    "__pycache__",
    "data",
    ".env",
    "auth_config.json",
    "bootstrap_credentials.txt",
    "employee_management.sqlite3",
    "employee_management.sqlite3-shm",
    "employee_management.sqlite3-wal",
    "sales_entries.xlsx",
    "sales_entries.xlsm",
    "sales_workbook.xlsx",
    "supabase_config.json",
    "update_error.log",
}

PRESERVED_UPDATE_SUFFIXES = (
    ".sqlite3",
    ".sqlite3-shm",
    ".sqlite3-wal",
    ".db",
    ".db-shm",
    ".db-wal",
)

# A freshly downloaded, unsigned .exe is exactly what Windows Defender/
# SmartScreen scans hardest before releasing its lock - on a slow link or a
# build hash it has never seen, that scan can run well past ten seconds. A
# short fixed retry budget failed in the field with "[WinError 5] Access is
# denied" on a perfectly good file that was just still locked. This runs in
# a detached background process with no UI to block, so it can afford to
# wait several minutes before truly giving up.
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


def _is_access_denied(exc: OSError) -> bool:
    return getattr(exc, "winerror", None) == 5 or exc.errno == 13


def _retry_on_lock(action, description: str):
    deadline = time.monotonic() + LOCK_RETRY_TOTAL_SECONDS
    delay = LOCK_RETRY_INITIAL_DELAY
    while True:
        try:
            return action()
        except OSError as exc:
            if not _is_access_denied(exc):
                raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise OSError(
                    f"{description} stayed locked for over {int(LOCK_RETRY_TOTAL_SECONDS)} seconds "
                    f"(most likely antivirus scanning) - giving up: {exc}"
                ) from exc
            time.sleep(min(delay, remaining))
            delay = min(delay * LOCK_RETRY_BACKOFF, LOCK_RETRY_MAX_DELAY)


def _process_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        synchronize = 0x00100000
        wait_timeout = 0x00000102
        handle = ctypes.windll.kernel32.OpenProcess(synchronize, False, pid)
        if not handle:
            return False
        try:
            return ctypes.windll.kernel32.WaitForSingleObject(handle, 0) == wait_timeout
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _wait_for_parent(pid: int, timeout_seconds: float = 20.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline and _process_running(pid):
        time.sleep(0.25)


def _downloads_dir() -> Path:
    # Deliberately not a tempfile.TemporaryDirectory context manager: those
    # auto-delete on the way out, which means a failed update used to leave
    # the user with nothing to fall back on after waiting through a failed
    # install. A stable, known location survives a failure so the log/dialog
    # can point at a real file the user can double-click themselves.
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


def _download_asset(asset_url: str, asset_name: str, target_dir: Path) -> Path:
    safe_name = Path(asset_name).name or "update_asset"
    target = target_dir / safe_name
    request = urllib.request.Request(
        asset_url,
        headers={"User-Agent": "Digital-Service-Pakistan-Employee-App"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        expected_size = int(response.headers.get("Content-Length") or 0)
        with target.open("wb") as output:
            shutil.copyfileobj(response, output)
    actual_size = target.stat().st_size
    if expected_size and actual_size != expected_size:
        raise OSError(f"Download incomplete: expected {expected_size} bytes, got {actual_size}.")
    return target


def _zip_payload_root(extract_dir: Path) -> Path:
    children = [child for child in extract_dir.iterdir() if child.name not in EXCLUDED_UPDATE_NAMES]
    if len(children) == 1 and children[0].is_dir():
        return children[0]
    return extract_dir


def _ignore_update_names(_directory: str, names: list[str]) -> set[str]:
    ignored = {name for name in names if name in EXCLUDED_UPDATE_NAMES}
    ignored.update(name for name in names if name.endswith(".pyc"))
    ignored.update(name for name in names if name.lower().endswith(PRESERVED_UPDATE_SUFFIXES))
    return ignored


def _install_zip(asset_path: Path, app_dir: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="dsp_update_extract_") as temp_extract:
        extract_dir = Path(temp_extract)
        with _retry_on_lock(lambda: zipfile.ZipFile(asset_path), "Downloaded update archive") as archive:
            archive.extractall(extract_dir)
        payload_root = _zip_payload_root(extract_dir)
        shutil.copytree(payload_root, app_dir, dirs_exist_ok=True, ignore=_ignore_update_names)


def _run_installer(asset_path: Path) -> int:
    suffix = asset_path.suffix.lower()
    if suffix == ".msi":
        command = ["msiexec", "/i", str(asset_path), "/passive"]
    else:
        # /VERYSILENT, not /SILENT: empirically, the installer's own [Run]
        # section (which launches the app after install, guarded by
        # "skipifsilent") only actually gets skipped under /VERYSILENT - under
        # /SILENT it launches the app anyway, which would silently reintroduce
        # an auto-reopen this flow intentionally avoids. Confirmed by testing
        # both directly.
        command = [str(asset_path), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]

    def attempt() -> int:
        result = subprocess.run(command, startupinfo=_startupinfo(), check=False)
        return int(result.returncode)

    return _retry_on_lock(attempt, "Downloaded installer")


def _write_error(app_dir: Path, message: str) -> None:
    try:
        (app_dir / "update_error.log").write_text(message, encoding="utf-8")
    except OSError:
        pass


def _notify(title: str, message: str, is_error: bool = False) -> None:
    # A plain Win32 message box, not the Tkinter app - this process has no
    # GUI of its own and should not import/start one just to report status.
    if os.name != "nt":
        return
    icon = 0x10 if is_error else 0x40  # MB_ICONERROR vs MB_ICONINFORMATION
    try:
        ctypes.windll.user32.MessageBoxW(0, message, title, icon)
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-dir", required=True)
    parser.add_argument("--pid", type=int, default=0)
    parser.add_argument("--asset-url", required=True)
    parser.add_argument("--asset-name", required=True)
    args = parser.parse_args(argv)

    app_dir = Path(args.app_dir)
    _wait_for_parent(args.pid)

    download_dir = _downloads_dir()
    _clear_directory(download_dir)

    exit_code = 0
    asset_path: Path | None = None
    try:
        asset_path = _download_asset(args.asset_url, args.asset_name, download_dir)
        suffix = asset_path.suffix.lower()
        if suffix == ".zip":
            _install_zip(asset_path, app_dir)
        elif suffix in {".exe", ".msi"}:
            exit_code = _run_installer(asset_path)
        else:
            exit_code = 2
            _write_error(app_dir, f"Unsupported update asset: {asset_path.name}")
    except Exception as exc:
        exit_code = 1
        location_hint = f"\n\nThe downloaded file is still at:\n{asset_path}" if asset_path else ""
        _write_error(app_dir, f"Update failed:\n{exc}{location_hint}")

    if exit_code == 0:
        try:
            (app_dir / "update_error.log").unlink(missing_ok=True)
        except OSError:
            pass
        _clear_directory(download_dir)
        _notify(
            "Update complete",
            "Digital Service Pakistan Employee has been updated. Open it again to use the new version.",
        )
    else:
        manual_hint = (
            f"\n\nThe downloaded installer is saved at:\n{asset_path}\nYou can double-click it to finish "
            "updating yourself."
            if asset_path is not None and asset_path.exists()
            else ""
        )
        _notify(
            "Update failed",
            "The update could not be completed. The app was not changed - "
            "you can keep using it, or try updating again later.\n\n"
            f"Details were saved to: {app_dir / 'update_error.log'}{manual_hint}",
            is_error=True,
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
