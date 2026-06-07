from __future__ import annotations

import tkinter as tk
from tkinter import ttk

try:
    from PIL import Image, ImageOps, ImageTk
except Exception:  # pragma: no cover - the app can still run without the logo.
    Image = None
    ImageOps = None
    ImageTk = None

from app.auth import AuthStore
from app.config import APP_DB_PATH, APP_ICON_PATH, APP_NAME, AUTH_CONFIG_PATH, BG, DEFAULT_USERNAME, LOGO_PATH
from app.storage import AttendanceStore
from app.ui.admin import AdminPage
from app.ui.dashboard import DashboardPage
from app.ui.login import LoginPage
from app.ui.reset_password import ResetPasswordPage
from app.ui.widgets import configure_treeview


class EmployeeApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1220x780")
        self.minsize(1080, 700)
        self.configure(bg=BG)

        self.auth = AuthStore(AUTH_CONFIG_PATH)
        self.attendance_store = AttendanceStore(APP_DB_PATH)
        self.logo_cache: dict[tuple[int, int], tk.PhotoImage] = {}
        self.current_user = ""
        self.current_role = ""

        self._configure_style()
        self._set_window_icon()
        self._build_pages()
        self.show_page("login")

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
        image = Image.open(LOGO_PATH).convert("RGB")
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
        page = self.pages[name]
        page.pack(fill="both", expand=True)
        if name in {"dashboard", "admin"}:
            self.pages[name].refresh_all()

    def login(self, username: str, password: str) -> None:
        from tkinter import messagebox

        user = self.auth.verify(username, password)
        if user:
            self.current_user = user["username"]
            self.current_role = user["role"]
            self.show_page("admin" if self.current_role == "admin" else "dashboard")
            return
        messagebox.showerror("Login failed", "Username or password is incorrect.")

    def logout(self) -> None:
        self.current_user = ""
        self.current_role = ""
        self.show_page("login")

    @property
    def display_user(self) -> str:
        return self.current_user or DEFAULT_USERNAME


def main() -> None:
    app = EmployeeApp()
    app.mainloop()
