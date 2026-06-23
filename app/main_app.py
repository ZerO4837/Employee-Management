from __future__ import annotations

import ctypes
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
    SALES_WORKBOOK_PATH,
    SALES_WORKSHEET_NAME,
)
from app.excel_sales import SalesWorkbook
from app.storage import AttendanceStore
from app.updater import UpdateInfo, check_for_update, start_update_and_relaunch
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
        self.cloud_sync_service = CloudSyncService(self.attendance_store, self.load_supabase_config, self.auth)
        self.cloud_sync_queue: queue.Queue[CloudSyncResult] = queue.Queue()
        self.cloud_sync_running = False
        self.cloud_sync_after_id: str | None = None

        self._configure_style()
        self._set_window_icon()
        self._build_pages()
        self.protocol("WM_DELETE_WINDOW", self.close_app)
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
            return
        login_page = self.pages.get("login")
        if hasattr(login_page, "show_login_error"):
            if self.auth.is_user_inactive(username):
                login_page.show_login_error(
                    "Your account is not active. Please contact the admin to reactivate your employee access."
                )
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
        page = self.pages.get(getattr(self, "current_page", ""))
        if result.changed:
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
            if self.current_role == "employee" and self.current_user:
                current_profile = self.auth.get_user(self.current_user)
                if current_profile is None or not current_profile.get("is_active", True):
                    messagebox.showwarning(
                        "Account not active",
                        "Your employee account is not active anymore. Please contact the admin.",
                        parent=self,
                    )
                    self.logout()
        if isinstance(page, AdminPage) and hasattr(page, "set_cloud_sync_status"):
            page.set_cloud_sync_status(result.message, ok=result.ok)

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
                "Update now? The app will close, update, and reopen automatically."
            ),
            parent=self,
        )
        if not should_update:
            return
        started, message = start_update_and_relaunch(update_info)
        if not started:
            messagebox.showwarning("Update could not start", message, parent=self)
            return
        self._finish_close_app()

    def load_sales_workbook_settings(self) -> None:
        workbook_path = self.attendance_store.get_setting("sales_workbook_path", str(SALES_WORKBOOK_PATH))
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
