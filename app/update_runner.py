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


def _startupinfo():
    if os.name != "nt":
        return None
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return startupinfo


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


def _download_asset(asset_url: str, asset_name: str, target_dir: Path) -> Path:
    safe_name = Path(asset_name).name or "update_asset"
    target = target_dir / safe_name
    request = urllib.request.Request(
        asset_url,
        headers={"User-Agent": "Digital-Service-Pakistan-Employee-App"},
    )
    with urllib.request.urlopen(request, timeout=120) as response, target.open("wb") as output:
        shutil.copyfileobj(response, output)
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


def _open_zip_with_retry(asset_path: Path) -> zipfile.ZipFile:
    # Same antivirus-scan-lock issue as _run_installer can hit a freshly
    # downloaded zip too - retry opening it instead of failing immediately.
    last_error: OSError | None = None
    for attempt in range(6):
        if attempt:
            time.sleep(1.5)
        try:
            return zipfile.ZipFile(asset_path)
        except OSError as exc:
            last_error = exc
    raise last_error


def _install_zip(asset_path: Path, app_dir: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="dsp_update_extract_") as temp_extract:
        extract_dir = Path(temp_extract)
        with _open_zip_with_retry(asset_path) as archive:
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
        # "skipifsilent") only actually gets skipped under /VERYSILENT -
        # under /SILENT it launches the app anyway, which would silently
        # reintroduce the auto-reopen this flow was explicitly changed to
        # not do. Confirmed by testing both directly.
        command = [str(asset_path), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]

    # A freshly downloaded .exe is a common target for antivirus/Windows
    # Defender real-time scanning, which briefly locks the file and makes
    # launching it fail with "[WinError 5] Access is denied" even though
    # nothing is actually wrong with the file. Retrying after a short wait
    # rides out that lock instead of failing the whole update over it.
    last_error: OSError | None = None
    for attempt in range(6):
        if attempt:
            time.sleep(1.5)
        try:
            result = subprocess.run(command, startupinfo=_startupinfo(), check=False)
            return int(result.returncode)
        except OSError as exc:
            last_error = exc
    raise last_error


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
    exit_code = 0
    try:
        with tempfile.TemporaryDirectory(prefix="dsp_update_") as temp_dir:
            asset_path = _download_asset(args.asset_url, args.asset_name, Path(temp_dir))
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
        _write_error(app_dir, f"Update failed:\n{exc}")

    if exit_code == 0:
        try:
            (app_dir / "update_error.log").unlink(missing_ok=True)
        except OSError:
            pass
        _notify(
            "Update complete",
            "Digital Service Pakistan Employee has been updated. Open it again to use the new version.",
        )
    else:
        _notify(
            "Update failed",
            "The update could not be completed. The app was not changed - "
            "you can keep using it, or try updating again later.\n\n"
            f"Details were saved to: {app_dir / 'update_error.log'}",
            is_error=True,
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
