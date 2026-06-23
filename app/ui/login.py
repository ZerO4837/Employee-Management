from __future__ import annotations

import tkinter as tk

from app.config import (
    BG,
    BLUE,
    BLUE_DARK,
    BUSINESS_NAME,
    CYAN,
    DANGER,
    FONT,
    FONT_BOLD,
    LINE,
    MUTED,
    NAVY,
    NAVY_2,
    SUCCESS,
    TEAL,
    TEXT,
    WHITE,
)
from app.ui.widgets import SurfaceCard, blend, draw_gradient, make_button, set_button_enabled, status_pill
from app.utils import now_label, today_label


class BrandCanvas(tk.Canvas):
    def __init__(self, parent: tk.Misc, app, **kwargs) -> None:
        super().__init__(parent, bg=NAVY, bd=0, highlightthickness=0, relief="flat", **kwargs)
        self.app = app
        self.bind("<Configure>", self._draw)

    def _draw(self, _event: tk.Event | None = None) -> None:
        width = max(self.winfo_width(), 1)
        height = max(self.winfo_height(), 1)
        draw_gradient(self, width, height, NAVY, BLUE_DARK, "horizontal")
        self.delete("brand")

        self.create_rectangle(
            0,
            0,
            width,
            height,
            fill="",
            outline=blend(WHITE, BLUE, 0.7),
            width=1,
            tags="brand",
        )
        self.create_rectangle(
            34,
            34,
            width - 34,
            height - 34,
            fill=blend(NAVY, BLUE_DARK, 0.18),
            outline=blend(BLUE, WHITE, 0.45),
            width=1,
            tags="brand",
        )
        self.create_rectangle(
            35,
            35,
            width - 35,
            41,
            fill=TEAL,
            outline="",
            tags="brand",
        )
        self.create_polygon(
            width * 0.72,
            0,
            width,
            0,
            width,
            height * 0.54,
            width * 0.86,
            height * 0.62,
            fill=blend(BLUE_DARK, CYAN, 0.24),
            outline="",
            tags="brand",
        )
        for index, color in enumerate((TEAL, blend(WHITE, BLUE, 0.36), blend(NAVY_2, BLUE, 0.52))):
            x = width * 0.72 + index * 22
            self.create_line(x, 86, x + 82, height - 104, fill=color, width=2, tags="brand")

        self.create_text(
            62,
            64,
            anchor="nw",
            text="SECURE EMPLOYEE ACCESS",
            fill=TEAL,
            font=(FONT_BOLD, 9),
            tags="brand",
        )

        logo = self.app.get_logo((122, 122))
        if logo:
            self.create_rectangle(
                62,
                96,
                196,
                230,
                fill=blend(NAVY, BLUE, 0.18),
                outline=blend(LINE, BLUE, 0.35),
                width=1,
                tags="brand",
            )
            self.create_image(68, 102, image=logo, anchor="nw", tags="brand")

        self.create_text(
            62,
            264,
            anchor="nw",
            text=BUSINESS_NAME,
            fill=WHITE,
            font=(FONT_BOLD, 24),
            width=max(300, width - 120),
            tags="brand",
        )
        self.create_text(
            64,
            346,
            anchor="nw",
            text="Employee Operations Console",
            fill=TEAL,
            font=(FONT_BOLD, 14),
            tags="brand",
        )
        self.create_text(
            64,
            382,
            anchor="nw",
            text="A focused daily workspace for attendance and order records.",
            fill="#d9edff",
            font=(FONT, 10),
            width=max(300, width - 116),
            tags="brand",
        )

        card_top = max(456, int(height * 0.62))
        card_width = max(142, (width - 146) / 2)
        self._draw_info_card(62, card_top, card_width, "SESSION", "Daily Access")
        self._draw_info_card(82 + card_width, card_top, card_width, "VIEW", "Employee Only")

        self.create_line(62, height - 104, width - 62, height - 104, fill=blend(BLUE, WHITE, 0.32), width=1, tags="brand")
        self.create_text(
            62,
            height - 76,
            anchor="nw",
            text="Workbook visibility stays controlled",
            fill="#eff7ff",
            font=(FONT_BOLD, 10),
            tags="brand",
        )
        self.create_text(
            62,
            height - 52,
            anchor="nw",
            text="Built on your trust",
            fill="#c7daf5",
            font=(FONT, 9),
            tags="brand",
        )

    def _draw_info_card(self, x: float, y: float, width: float, label: str, value: str) -> None:
        self.create_rectangle(
            x,
            y,
            x + width,
            y + 76,
            fill=blend(NAVY_2, BLUE_DARK, 0.18),
            outline=blend(BLUE, WHITE, 0.42),
            width=1,
            tags="brand",
        )
        self.create_text(x + 16, y + 16, anchor="nw", text=label, fill=TEAL, font=(FONT_BOLD, 8), tags="brand")
        self.create_text(x + 16, y + 40, anchor="nw", text=value, fill=WHITE, font=(FONT_BOLD, 11), tags="brand")


class LoginPage(tk.Frame):
    def __init__(self, parent: tk.Misc, app) -> None:
        super().__init__(parent, bg=BG)
        self.app = app
        remembered_username = ""
        remember_username = False
        try:
            remember_username = self.app.attendance_store.get_setting("login_remember_username", "0") == "1"
            if remember_username:
                remembered_username = self.app.attendance_store.get_setting("login_last_username", "")
        except Exception:
            remember_username = False
        self.username_var = tk.StringVar(value=remembered_username)
        self.password_var = tk.StringVar()
        self.remember_username_var = tk.BooleanVar(value=remember_username)
        self.show_password_var = tk.BooleanVar(value=False)
        self.error_panel: tk.Frame | None = None
        self.error_message_label: tk.Label | None = None
        self.login_clock_label: tk.Label | None = None
        self.sign_in_button: tk.Button | None = None
        self.password_toggle_button: tk.Button | None = None
        self.field_frames: dict[str, tk.Frame] = {}
        self.field_labels: dict[str, tk.Label] = {}
        self._login_clock_after_id: str | None = None
        self._build()
        self.username_var.trace_add("write", lambda *_args: self._update_submit_state())
        self.password_var.trace_add("write", lambda *_args: self._update_submit_state())
        self._update_submit_state()
        self._tick_login_clock()

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=5, minsize=460)
        self.grid_columnconfigure(1, weight=6)
        self.grid_rowconfigure(0, weight=1)

        BrandCanvas(self, self.app).grid(row=0, column=0, sticky="nsew")

        right = tk.Frame(self, bg=BG)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(0, weight=1)

        panel = SurfaceCard(right, padx=0, pady=0, accent=True, accent_start=BLUE, accent_end=TEAL)
        panel.grid(row=0, column=0, sticky="", padx=64, pady=54)
        body = panel.body
        body.configure(padx=44, pady=38)
        body.grid_columnconfigure(0, weight=1)

        top_row = tk.Frame(body, bg=WHITE)
        top_row.grid(row=0, column=0, sticky="ew")
        top_row.grid_columnconfigure(0, weight=1)
        tk.Label(top_row, text="Welcome Back", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 26)).grid(
            row=0, column=0, sticky="w"
        )
        status_pill(top_row, "Secure Access", fg=SUCCESS, bg="#eafaf4").grid(row=0, column=1, sticky="e", padx=(14, 0))

        tk.Label(
            body,
            text="Sign in to continue your daily workspace.",
            bg=WHITE,
            fg=MUTED,
            font=(FONT, 11),
        ).grid(row=1, column=0, sticky="w", pady=(7, 18))

        session_row = tk.Frame(body, bg="#f8fbff", padx=14, pady=11, highlightbackground=LINE, highlightthickness=1)
        session_row.grid(row=2, column=0, sticky="ew", pady=(0, 22))
        session_row.grid_columnconfigure(1, weight=1)
        tk.Label(session_row, text="TODAY", bg="#f8fbff", fg=BLUE_DARK, font=(FONT_BOLD, 8)).grid(
            row=0, column=0, sticky="w", padx=(0, 12)
        )
        tk.Label(session_row, text=today_label(), bg="#f8fbff", fg=TEXT, font=(FONT_BOLD, 10)).grid(
            row=0, column=1, sticky="w"
        )
        self.login_clock_label = tk.Label(session_row, text="", bg="#f8fbff", fg=MUTED, font=(FONT, 10))
        self.login_clock_label.grid(row=0, column=2, sticky="e")

        tk.Label(body, text="Account Details", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 13)).grid(
            row=3, column=0, sticky="w", pady=(0, 12)
        )

        self.username_entry = self._entry(body, "Username", self.username_var, 4, "username")
        self.password_entry = self._entry(body, "Password", self.password_var, 6, "password", show="*")
        remember_row = tk.Frame(body, bg=WHITE)
        remember_row.grid(row=8, column=0, sticky="ew", pady=(0, 14))
        remember_check = tk.Checkbutton(
            remember_row,
            text="Remember username",
            variable=self.remember_username_var,
            bg=WHITE,
            fg=TEXT,
            activebackground=WHITE,
            activeforeground=TEXT,
            selectcolor=WHITE,
            relief="flat",
            bd=0,
            cursor="hand2",
            font=(FONT_BOLD, 10),
            command=self._handle_remember_toggle,
        )
        remember_check.grid(row=0, column=0, sticky="w")
        if self.username_var.get().strip():
            self.password_entry.focus_set()
        else:
            self.username_entry.focus_set()

        self.error_panel = tk.Frame(
            body,
            bg="#fff3f4",
            padx=14,
            pady=12,
            highlightbackground="#f0c3ca",
            highlightthickness=1,
        )
        self.error_panel.grid(row=9, column=0, sticky="ew", pady=(0, 16))
        self.error_panel.grid_columnconfigure(1, weight=1)
        tk.Label(
            self.error_panel,
            text="!",
            bg=DANGER,
            fg=WHITE,
            font=(FONT_BOLD, 10),
            width=3,
            pady=4,
        ).grid(row=0, column=0, rowspan=2, sticky="nw", padx=(0, 12))
        tk.Label(
            self.error_panel,
            text="Login could not continue",
            bg="#fff3f4",
            fg=DANGER,
            font=(FONT_BOLD, 10),
        ).grid(row=0, column=1, sticky="w")
        self.error_message_label = tk.Label(
            self.error_panel,
            text="",
            bg="#fff3f4",
            fg=TEXT,
            font=(FONT, 10),
            justify="left",
            wraplength=420,
        )
        self.error_message_label.grid(row=1, column=1, sticky="w", pady=(4, 0))
        self.error_panel.grid_remove()

        action_row = tk.Frame(body, bg=WHITE)
        action_row.grid(row=10, column=0, sticky="ew")
        action_row.grid_columnconfigure(0, weight=1)
        self.sign_in_button = make_button(action_row, "Unlock Workspace", self._submit_login, "primary")
        self.sign_in_button.grid(row=0, column=0, sticky="ew", pady=(2, 12))

        bottom_row = tk.Frame(body, bg=WHITE)
        bottom_row.grid(row=11, column=0, sticky="ew")
        bottom_row.grid_columnconfigure(0, weight=1)
        forgot = tk.Button(
            bottom_row,
            text="Forgot password?",
            command=lambda: self.app.show_page("reset"),
            bg=WHITE,
            fg=BLUE,
            activebackground=WHITE,
            activeforeground=BLUE_DARK,
            relief="flat",
            bd=0,
            cursor="hand2",
            font=(FONT_BOLD, 10),
        )
        forgot.grid(row=0, column=0, sticky="w")
        tk.Label(bottom_row, text="Protected company login", bg=WHITE, fg=MUTED, font=(FONT, 9)).grid(
            row=0, column=1, sticky="e"
        )

        self.password_entry.bind("<Return>", lambda _event: self._submit_login())
        self.username_entry.bind("<Return>", lambda _event: self.password_entry.focus_set())

    def _entry(
        self,
        parent: tk.Misc,
        label: str,
        variable: tk.StringVar,
        row: int,
        key: str,
        show: str | None = None,
    ) -> tk.Entry:
        label_widget = tk.Label(parent, text=label, bg=WHITE, fg=TEXT, font=(FONT_BOLD, 10))
        label_widget.grid(row=row, column=0, sticky="w")
        self.field_labels[key] = label_widget

        field = tk.Frame(
            parent,
            bg="#f8fbff",
            padx=12,
            pady=3,
            highlightbackground=LINE,
            highlightthickness=1,
        )
        field.grid(row=row + 1, column=0, sticky="ew", ipady=4, pady=(8, 18))
        field.grid_columnconfigure(0, weight=1)
        field.bind("<Button-1>", lambda _event: entry.focus_set())
        self.field_frames[key] = field

        entry = tk.Entry(
            field,
            textvariable=variable,
            show=show or "",
            bg="#f8fbff",
            fg=TEXT,
            relief="flat",
            bd=0,
            highlightthickness=0,
            font=(FONT, 12),
            insertbackground=TEXT,
        )
        entry.grid(row=0, column=0, sticky="ew", ipady=8)
        entry.bind("<FocusIn>", lambda _event, field_key=key: self._set_field_focus(field_key, True))
        entry.bind("<FocusOut>", lambda _event, field_key=key: self._set_field_focus(field_key, False))

        if key == "password":
            self.password_toggle_button = tk.Button(
                field,
                text="Show",
                command=self._toggle_password,
                bg="#f8fbff",
                fg=BLUE_DARK,
                activebackground="#f8fbff",
                activeforeground=BLUE,
                relief="flat",
                bd=0,
                cursor="hand2",
                font=(FONT_BOLD, 9),
                padx=10,
                pady=4,
                highlightthickness=0,
            )
            self.password_toggle_button.grid(row=0, column=1, sticky="e", padx=(10, 0))
        return entry

    def _set_field_focus(self, key: str, active: bool) -> None:
        frame = self.field_frames.get(key)
        label = self.field_labels.get(key)
        if frame is not None:
            frame.configure(highlightbackground=BLUE if active else LINE)
        if label is not None:
            label.configure(fg=BLUE_DARK if active else TEXT)

    def _toggle_password(self) -> None:
        self.show_password_var.set(not self.show_password_var.get())
        showing = self.show_password_var.get()
        self.password_entry.configure(show="" if showing else "*")
        if self.password_toggle_button is not None:
            self.password_toggle_button.configure(text="Hide" if showing else "Show")

    def _update_submit_state(self) -> None:
        if self.sign_in_button is None:
            return
        ready = bool(self.username_var.get().strip()) and bool(self.password_var.get())
        set_button_enabled(self.sign_in_button, ready)

    def _tick_login_clock(self) -> None:
        if not self.winfo_exists():
            return
        if self.login_clock_label is not None:
            self.login_clock_label.configure(text=now_label())
        self._login_clock_after_id = self.after(1000, self._tick_login_clock)

    def destroy(self) -> None:
        if self._login_clock_after_id is not None:
            try:
                self.after_cancel(self._login_clock_after_id)
            except tk.TclError:
                pass
            self._login_clock_after_id = None
        super().destroy()

    def show_login_error(self, message: str) -> None:
        if self.error_panel is None or self.error_message_label is None:
            return
        self.error_message_label.configure(text=message)
        self.error_panel.grid()
        self.password_entry.focus_set()
        self.password_entry.selection_range(0, tk.END)

    def clear_login_error(self) -> None:
        if self.error_panel is not None:
            self.error_panel.grid_remove()

    def remember_successful_username(self, username: str) -> None:
        try:
            if self.remember_username_var.get():
                self.app.attendance_store.set_setting("login_remember_username", "1")
                self.app.attendance_store.set_setting("login_last_username", username.strip())
            else:
                self.app.attendance_store.set_setting("login_remember_username", "0")
                self.app.attendance_store.set_setting("login_last_username", "")
        except Exception:
            pass

    def _handle_remember_toggle(self) -> None:
        if self.remember_username_var.get():
            return
        try:
            self.app.attendance_store.set_setting("login_remember_username", "0")
            self.app.attendance_store.set_setting("login_last_username", "")
        except Exception:
            pass

    def _submit_login(self) -> None:
        self.clear_login_error()
        if self.sign_in_button is not None and str(self.sign_in_button["state"]) == "disabled":
            return
        self.app.login(self.username_var.get(), self.password_var.get())
