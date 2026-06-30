from __future__ import annotations

import ctypes
from datetime import datetime
import os
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

try:
    from PIL import Image, ImageOps, ImageTk
except Exception:  # pragma: no cover - the app can still run without the logo.
    Image = None
    ImageOps = None
    ImageTk = None

from app.auth import BOOTSTRAP_FILENAME, AuthStore
from app.cloud_sync import CloudSyncResult, CloudSyncService, SupabaseConfig, cloud_sync_interval_ms, load_supabase_config, save_supabase_config, write_supabase_config_file
from app.config import (
    ADMIN_USERNAME,
    APP_DB_PATH,
    APP_ICON_PATH,
    APP_NAME,
    AUTH_CONFIG_PATH,
    BG,
    DEFAULT_USERNAME,
    LOGO_PATH,
    SALES_WORKSHEET_NAME,
)
from app.excel_sales import SalesWorkbook
from app.storage import AttendanceStore
from app.updater import UpdateInfo, check_for_update, download_update, install_update
from app.ui.admin import AdminPage
from app.ui.dashboard import DashboardPage
from app.ui.login import LoginPage
from app.ui.reset_password import ResetPasswordPage
from app.ui.widgets import configure_treeview


def _enable_windows_dpi_awareness() -> None:
    """Make Tk report real screen pixels instead of being upscaled by Windows.

    Without this, Windows display scaling (common on small/high-DPI laptop
    screens) silently stretches the whole window past the visible screen,
    which is what hides bottom controls on smaller laptops.
    """
    if os.name != "nt":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


class EmployeeApp(tk.Tk):
    def __init__(self) -> None:
        _enable_windows_dpi_awareness()
        super().__init__()
        self.title(APP_NAME)
        self._configure_window_geometry()
        self.configure(bg=BG)

        self.auth = AuthStore(AUTH_CONFIG_PATH)
        self.attendance_store = AttendanceStore(APP_DB_PATH)
        # At most once per day, on whichever PC happens to start first that
        # day - keeps 30+ day old attendance history from accumulating
        # forever in the local database.
        self.attendance_store.purge_old_attendance_if_due()
        self.sales_workbook = SalesWorkbook()
        self.load_sales_workbook_settings()
        self.logo_cache: dict[tuple[int, int], tk.PhotoImage] = {}
        self.current_user = ""
        self.current_display_name = ""
        self.current_role = ""
        self.close_waiting_for_excel_sync = False
        self.update_check_queue: queue.Queue[UpdateInfo] = queue.Queue()
        self.update_check_started = False
        self.update_check_after_id: str | None = None
        self.update_download_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.cloud_sync_service = CloudSyncService(self.attendance_store, self.load_supabase_config, self.auth)
        self.cloud_sync_queue: queue.Queue[CloudSyncResult] = queue.Queue()
        self.cloud_sync_running = False
        self.cloud_sync_after_id: str | None = None
        self.login_verification_queue: queue.Queue[CloudSyncResult] = queue.Queue()

        self._configure_style()
        self._set_window_icon()
        self._build_pages()
        self.protocol("WM_DELETE_WINDOW", self.close_app)
        self._check_update_notification()
        self.show_page("login")
        self._schedule_cloud_sync(3000)

    def _configure_window_geometry(self) -> None:
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        width = max(1000, min(1220, screen_width - 60))
        height = max(620, min(780, screen_height - 90))
        x = max(0, (screen_width - width) // 2)
        y = max(0, (screen_height - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.minsize(min(1000, width), min(620, height))

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        configure_treeview(style)

    def _set_window_icon(self) -> None:
        icon_set = False
        if APP_ICON_PATH.exists():
            try:
                self.iconbitmap(str(APP_ICON_PATH))
                icon_set = True
            except tk.TclError:
                pass
        if icon_set:
            return
        logo = self.get_logo((96, 96))
        if logo is not None:
            self.iconphoto(True, logo)

    def get_logo(self, size: tuple[int, int]) -> tk.PhotoImage | None:
        if size in self.logo_cache:
            return self.logo_cache[size]
        if Image is None or ImageOps is None or ImageTk is None or not LOGO_PATH.exists():
            return None
        with Image.open(LOGO_PATH) as source:
            image = source.convert("RGB")
        resampling = getattr(Image, "Resampling", Image).LANCZOS
        image = ImageOps.fit(image, size, method=resampling)
        photo = ImageTk.PhotoImage(image)
        self.logo_cache[size] = photo
        return photo

    def _build_pages(self) -> None:
        self.page_host = tk.Frame(self, bg=BG)
        self.page_host.pack(fill="both", expand=True)
        self.pages = {
            "login": LoginPage(self.page_host, self),
            "reset": ResetPasswordPage(self.page_host, self),
            "dashboard": DashboardPage(self.page_host, self),
            "admin": AdminPage(self.page_host, self),
        }

    def show_page(self, name: str) -> None:
        for page in self.pages.values():
            page.pack_forget()
        self.current_page = name
        page = self.pages[name]
        page.pack(fill="both", expand=True)
        if name in {"dashboard", "admin"}:
            self.pages[name].refresh_all()

    def login(self, username: str, password: str) -> None:
        username = username.strip()
        # The admin account has to keep working purely locally - it's the
        # one that configures Supabase in the first place, so requiring a
        # cloud round trip to log in would be a chicken-and-egg problem on a
        # brand new install. Employee accounts have no such bootstrap need,
        # and are the ones that actually get deleted/deactivated, so for
        # them a stale local cache is a real risk worth closing.
        is_admin_attempt = username.casefold() == ADMIN_USERNAME.casefold()
        if is_admin_attempt or not self.load_supabase_config().can_pull_users:
            self._complete_login(username, password)
            return
        self._start_login_verification(username, password)

    def _start_login_verification(self, username: str, password: str) -> None:
        login_page = self.pages.get("login")
        if hasattr(login_page, "set_verifying"):
            login_page.set_verifying(True)
        worker = threading.Thread(target=self._run_login_verification_worker, daemon=True)
        worker.start()
        self.after(150, lambda: self._poll_login_verification(username, password))

    def _run_login_verification_worker(self) -> None:
        try:
            result = self.cloud_sync_service.sync(push_local=False, pull_remote=True)
        except Exception as exc:
            result = CloudSyncResult(enabled=True, ok=False, message=f"Cloud verification failed: {exc}")
        self.login_verification_queue.put(result)

    def _poll_login_verification(self, username: str, password: str) -> None:
        try:
            result = self.login_verification_queue.get_nowait()
        except queue.Empty:
            self.after(150, lambda: self._poll_login_verification(username, password))
            return
        login_page = self.pages.get("login")
        if hasattr(login_page, "set_verifying"):
            login_page.set_verifying(False)
        if not result.ok:
            if hasattr(login_page, "show_login_error"):
                login_page.show_login_error(
                    "Could not verify your account online. Check your internet connection and try again."
                )
            return
        self._record_successful_sync()
        self._complete_login(username, password)

    def _complete_login(self, username: str, password: str) -> None:
        user = self.auth.verify(username, password)
        if user:
            login_page = self.pages.get("login")
            if hasattr(login_page, "clear_login_error"):
                login_page.clear_login_error()
            if hasattr(login_page, "remember_successful_username"):
                login_page.remember_successful_username(user["username"])
            self.current_user = user["username"]
            self.current_display_name = user.get("display_name", user["username"])
            self.current_role = user["role"]
            self._normalize_current_user_notification_reads()
            self.show_page("admin" if self.current_role == "admin" else "dashboard")
            self.after(700, self.start_update_check)
            if self.current_role == "employee":
                # The employee_users pull above already verified this login
                # against the cloud, but other tables (attendance, sales,
                # settings) haven't been pushed/pulled yet - do that now.
                self.request_cloud_sync(push_local=False)
            return
        login_page = self.pages.get("login")
        if hasattr(login_page, "show_login_error"):
            if self.auth.is_user_inactive(username):
                login_page.show_login_error(
                    "Your account is not active. Please contact the admin to reactivate your employee access."
                )
            elif username.strip() and self.auth.get_user(username) is None:
                login_page.show_login_error("User not found. Please contact the admin." + self._last_successful_sync_note())
            else:
                bootstrap_path = AUTH_CONFIG_PATH.parent / BOOTSTRAP_FILENAME
                if username.strip().casefold() == ADMIN_USERNAME.casefold() and self.auth.has_bootstrap_secret("Admin password"):
                    login_page.show_login_error(
                        "Admin password is saved in the private bootstrap file on this PC. "
                        f"Open this file and use the Admin password:\n{bootstrap_path}"
                    )
                else:
                    login_page.show_login_error("Username or password is incorrect. Please check the details and try again.")

    def logout(self) -> None:
        self.current_user = ""
        self.current_display_name = ""
        self.current_role = ""
        self.show_page("login")

    def close_app(self) -> None:
        dashboard = self.pages.get("dashboard")
        if (
            isinstance(dashboard, DashboardPage)
            and dashboard.close_after_excel_sync(self._finish_close_app)
        ):
            self.close_waiting_for_excel_sync = True
            self.title(f"{APP_NAME} - Finishing Excel sync")
            return
        self._finish_close_app()

    def _finish_close_app(self) -> None:
        if self.update_check_after_id is not None:
            try:
                self.after_cancel(self.update_check_after_id)
            except tk.TclError:
                pass
            self.update_check_after_id = None
        if self.cloud_sync_after_id is not None:
            try:
                self.after_cancel(self.cloud_sync_after_id)
            except tk.TclError:
                pass
            self.cloud_sync_after_id = None
        self.current_user = ""
        self.current_display_name = ""
        self.current_role = ""
        self.destroy()

    def _normalize_current_user_notification_reads(self) -> None:
        if not self.current_user:
            return
        display_name = self.current_display_name.strip()
        if not display_name or display_name.casefold() == self.current_user.casefold():
            return
        registered_usernames = {
            user["username"].casefold()
            for user in self.auth.list_users(include_admin=True)
        }
        if display_name.casefold() in registered_usernames:
            return
        self.attendance_store.merge_announcement_read_aliases(self.current_user, [display_name])

    def load_supabase_config(self) -> SupabaseConfig:
        return load_supabase_config(self.attendance_store)

    def save_supabase_config(self, config: SupabaseConfig, write_file: bool = False):
        save_supabase_config(self.attendance_store, config)
        if write_file:
            return write_supabase_config_file(config)
        return None

    def request_cloud_sync(self, push_local: bool = False) -> None:
        self._start_cloud_sync(push_local=push_local, reschedule=False)

    def _schedule_cloud_sync(self, delay_ms: int | None = None) -> None:
        if self.cloud_sync_after_id is not None:
            try:
                self.after_cancel(self.cloud_sync_after_id)
            except tk.TclError:
                pass
        self.cloud_sync_after_id = self.after(delay_ms or cloud_sync_interval_ms(), self._start_cloud_sync)

    def _start_cloud_sync(self, push_local: bool | None = None, reschedule: bool = True) -> None:
        self.cloud_sync_after_id = None
        if self.cloud_sync_running:
            if reschedule:
                self._schedule_cloud_sync()
            return
        config = self.load_supabase_config()
        if not config.is_ready:
            if reschedule:
                self._schedule_cloud_sync()
            return
        self.cloud_sync_running = True
        should_push = self.current_role in {"admin", "employee"} if push_local is None else push_local
        worker = threading.Thread(target=self._run_cloud_sync_worker, args=(should_push,), daemon=True)
        worker.start()
        self.after(250, lambda: self._poll_cloud_sync(reschedule))

    def _run_cloud_sync_worker(self, push_local: bool) -> None:
        try:
            result = self.cloud_sync_service.sync(push_local=push_local, pull_remote=True)
        except Exception as exc:
            result = CloudSyncResult(enabled=True, ok=False, message=f"Cloud sync failed: {exc}")
        self.cloud_sync_queue.put(result)

    def _poll_cloud_sync(self, reschedule: bool) -> None:
        try:
            result = self.cloud_sync_queue.get_nowait()
        except queue.Empty:
            self.after(250, lambda: self._poll_cloud_sync(reschedule))
            return
        self.cloud_sync_running = False
        self._handle_cloud_sync_result(result)
        if reschedule:
            self._schedule_cloud_sync()

    def _handle_cloud_sync_result(self, result: CloudSyncResult) -> None:
        if not result.enabled:
            return
        if result.ok:
            self._record_successful_sync()
        page = self.pages.get(getattr(self, "current_page", ""))
        if result.changed:
            # A pulled setting (e.g. the sales workbook target) only takes
            # effect once self.sales_workbook is rebuilt from the latest
            # value - without this, an employee install that just received
            # the admin's configured target keeps writing to its old one
            # until the app is restarted.
            self.load_sales_workbook_settings()
            if isinstance(page, DashboardPage):
                page._refresh_notification_badge()
                page._refresh_service_catalog_values()
                page._refresh_service_message_templates()
                page._refresh_inventory_items()
                if page.notification_dropdown is not None and page.notification_dropdown.winfo_ismapped():
                    page.notification_dropdown.refresh()
            elif isinstance(page, AdminPage):
                page._refresh_dashboard()
                shifts = self.attendance_store.list_shift_summaries()
                page._refresh_metrics(shifts)
                page._refresh_shift_table(shifts)
                page._refresh_event_table(page.selected_shift_id)
                page._refresh_employees()
                page._refresh_announcements()
                page._refresh_service_catalog()
                page._refresh_message_templates()
                page._refresh_inventory_items()
                page._refresh_sales_data()
                page._refresh_excel_settings()
        # Checked unconditionally on every sync tick, not only when this
        # particular cycle happened to report a change - otherwise a
        # just-deleted/frozen account stays logged in until some other
        # unrelated change happens to trigger a re-check.
        self._enforce_current_employee_account_status()
        if isinstance(page, AdminPage) and hasattr(page, "set_cloud_sync_status"):
            page.set_cloud_sync_status(result.message, ok=result.ok)

    def _record_successful_sync(self) -> None:
        try:
            self.attendance_store.set_setting("last_successful_sync_at", datetime.now().isoformat(timespec="seconds"))
        except Exception:
            pass

    def _last_successful_sync_note(self) -> str:
        # Surfaced in "user not found"-type login errors so a PC whose
        # cloud sync has been silently failing is obvious from the error
        # message itself, instead of needing remote investigation to find
        # out the account simply never reached this machine.
        try:
            last_sync = self.attendance_store.get_setting("last_successful_sync_at", "")
        except Exception:
            last_sync = ""
        if last_sync:
            return f"\n\n(This PC last synced with the cloud successfully at: {last_sync})"
        return "\n\n(This PC has never successfully synced with the cloud.)"

    def _enforce_current_employee_account_status(self) -> None:
        if self.current_role != "employee" or not self.current_user:
            return
        current_profile = self.auth.get_user(self.current_user)
        if current_profile is not None and current_profile.get("is_active", True):
            return
        if current_profile is None:
            message = "This account could not be found. Please contact the admin."
            title = "Account not found"
        else:
            message = "Your employee account is not active anymore. Please contact the admin."
            title = "Account not active"
        messagebox.showwarning(title, message, parent=self)
        self.logout()

    def start_update_check(self) -> None:
        if self.update_check_started:
            return
        self.update_check_started = True
        worker = threading.Thread(target=self._run_update_check_worker, daemon=True)
        worker.start()
        self._poll_update_check()

    def _run_update_check_worker(self) -> None:
        self.update_check_queue.put(check_for_update())

    def _poll_update_check(self) -> None:
        try:
            update_info = self.update_check_queue.get_nowait()
        except queue.Empty:
            self.update_check_after_id = self.after(250, self._poll_update_check)
            return
        self.update_check_after_id = None
        self._handle_update_check(update_info)

    def _handle_update_check(self, update_info: UpdateInfo) -> None:
        if not update_info.available:
            return
        if not update_info.can_update:
            messagebox.showinfo(
                "Update available",
                (
                    f"A new release is available: {update_info.latest_version}\n\n"
                    f"{update_info.message or 'Open GitHub Releases to download it.'}"
                ),
                parent=self,
            )
            return
        should_update = messagebox.askyesno(
            "Update available",
            (
                "A new app update is available.\n\n"
                f"Current: {update_info.current_version}\n"
                f"Latest: {update_info.latest_version}\n\n"
                "Update now? This downloads the installer and launches it - the app will close "
                "itself automatically once it's ready."
            ),
            parent=self,
        )
        if not should_update:
            return
        self._start_update_download(update_info)

    def _start_update_download(self, update_info: UpdateInfo) -> None:
        self.title(f"{APP_NAME} - Downloading update...")
        worker = threading.Thread(target=self._run_update_download_worker, args=(update_info,), daemon=True)
        worker.start()
        self._poll_update_download()

    def _run_update_download_worker(self, update_info: UpdateInfo) -> None:
        try:
            def report_progress(downloaded: int, total: int) -> None:
                if total:
                    self.update_download_queue.put(("progress", int(downloaded * 100 / total)))

            installer_path = download_update(update_info, progress_callback=report_progress)
            install_update(installer_path)
            try:
                self.attendance_store.set_setting("pending_update_notification", update_info.latest_version)
            except Exception:
                pass
            self.update_download_queue.put(("done", None))
        except Exception as exc:
            self.update_download_queue.put(("error", str(exc)))

    def _poll_update_download(self) -> None:
        latest_percent: int | None = None
        finished: tuple[str, str | None] | None = None
        try:
            while True:
                kind, payload = self.update_download_queue.get_nowait()
                if kind == "progress":
                    latest_percent = payload
                else:
                    finished = (kind, payload)
        except queue.Empty:
            pass
        if finished is None:
            if latest_percent is not None:
                self.title(f"{APP_NAME} - Downloading update... {latest_percent}%")
            self.after(250, self._poll_update_download)
            return
        kind, payload = finished
        if kind == "done":
            # Don't close the window here - /CLOSEAPPLICATIONS on the
            # installer we just launched asks Windows to close this app for
            # us, which arrives through the normal WM_DELETE_WINDOW handler
            # (close_app) exactly like the user clicking the close button,
            # including its "finish the in-flight Excel sync first" wait.
            self.title(f"{APP_NAME} - Update launching...")
            return
        self.title(APP_NAME)
        messagebox.showwarning("Update could not start", payload or "Unknown error.", parent=self)

    def _check_update_notification(self) -> None:
        try:
            version = self.attendance_store.get_setting("pending_update_notification", "")
            if not version:
                return
            self.attendance_store.set_setting("pending_update_notification", "")
            self.after(2000, lambda: messagebox.showinfo(
                "App Updated Successfully",
                f"The app has been updated to version {version}.\n\nYou're now on the latest version!",
                parent=self,
            ))
        except Exception:
            pass

    def load_sales_workbook_settings(self) -> None:
        workbook_path = self.attendance_store.get_setting("sales_workbook_path", "")
        worksheet_name = self.attendance_store.get_setting("sales_worksheet_name", SALES_WORKSHEET_NAME)
        self.sales_workbook = SalesWorkbook(workbook_path, worksheet_name)

    def save_sales_workbook_settings(self, workbook_path: str, worksheet_name: str) -> None:
        self.attendance_store.set_setting("sales_workbook_path", workbook_path)
        self.attendance_store.set_setting("sales_worksheet_name", worksheet_name)
        self.sales_workbook = SalesWorkbook(workbook_path, worksheet_name)

    @property
    def data_user(self) -> str:
        return self.current_user or DEFAULT_USERNAME

    @property
    def display_user(self) -> str:
        return self.current_display_name or self.current_user or DEFAULT_USERNAME


def main() -> None:
    app = EmployeeApp()
    app.mainloop()
