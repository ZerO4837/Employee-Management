from __future__ import annotations

from datetime import datetime, timedelta
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from app.config import (
    BG,
    BLUE,
    BLUE_DARK,
    BUSINESS_NAME,
    DANGER,
    FONT,
    FONT_BOLD,
    LINE,
    MUTED,
    NAVY,
    NAVY_LIGHT,
    SALES_FIELDS,
    SIDEBAR_ACTIVE,
    SIDEBAR_ACTIVE_TEXT,
    SIDEBAR_BG,
    SIDEBAR_BORDER,
    SIDEBAR_HOVER,
    SIDEBAR_MUTED,
    SIDEBAR_SURFACE,
    SIDEBAR_SURFACE_2,
    SIDEBAR_TEXT,
    SUCCESS,
    TEAL,
    TEXT,
    WARNING,
    WHITE,
)
from app.ui.widgets import (
    GradientBand,
    GradientBanner,
    MetricCard,
    SurfaceCard,
    combo_box,
    field_label,
    make_button,
    set_button_enabled,
    status_pill,
    text_entry,
)
from app.excel_sales import ExcelSyncResult
from app.utils import duration_label, money_label, now_label, today_label


def _amount_input_allowed(value: str) -> bool:
    if value == "":
        return True
    if value.count(".") > 1:
        return False
    return all(character.isdigit() or character == "." for character in value)


def _amount_value_valid(value: str) -> bool:
    if not value or value == ".":
        return False
    if not _amount_input_allowed(value):
        return False
    try:
        return float(value) >= 0
    except ValueError:
        return False


class DashboardPage(tk.Frame):
    SHIFT_LOCKED_VIEWS = {"sales", "today"}
    SALES_VISIBLE_DAYS = 5

    def __init__(self, parent: tk.Misc, app) -> None:
        super().__init__(parent, bg=BG)
        self.app = app
        self.current_view = ""
        self.nav_buttons: dict[str, tk.Button] = {}
        self.views: dict[str, tk.Frame] = {}
        self.sales_vars: dict[str, tk.StringVar] = {}
        self.sales_date_var = tk.StringVar()
        self.status_other_var = tk.StringVar()
        self.sales_entries: list[dict[str, str]] = []
        self.sales_selected_date = self._sales_date()
        self.sales_day_card_slots: list[dict[str, tk.Widget]] = []
        self.sync_retry_button: tk.Button | None = None
        self.excel_sync_queue: list[tuple[dict[str, str], str, int | None]] = []
        self.excel_sync_results: queue.Queue[tuple[dict[str, str], str, int | None, ExcelSyncResult]] = queue.Queue()
        self.excel_sync_busy = False
        self.excel_sync_pending_entry_ids: set[str] = set()
        self.next_sales_id = 1
        self.attendance_events: list[dict[str, str]] = []
        self.checked_in = False
        self.on_break = False
        self.break_started_at: datetime | None = None
        self.total_break_seconds = 0
        self.shift_started_at: datetime | None = None
        self.current_shift_id: int | None = None
        self.current_shift_number = 0
        self.day_active = False
        self.current_day_id: int | None = None
        self.current_day_date = ""
        self.day_started_at: datetime | None = None
        self.check_in_buttons: list[tk.Button] = []
        self.start_day_buttons: list[tk.Button] = []
        self.end_day_buttons: list[tk.Button] = []
        self.start_break_buttons: list[tk.Button] = []
        self.end_break_buttons: list[tk.Button] = []
        self.checkout_buttons: list[tk.Button] = []
        self.close_first_shift_buttons: list[tk.Button] = []
        self.shift_required_buttons: list[tk.Button] = []
        self.sales_input_widgets: list[tk.Widget] = []
        self.status_other_widgets: list[tk.Widget] = []
        self.notification_button: tk.Button | None = None
        self.notification_badge: tk.Label | None = None
        self.notification_dropdown: NotificationDropdown | None = None
        self.notification_frame: tk.Frame | None = None
        self.shell: tk.Frame | None = None
        self._build()
        self._tick_clock()
        self._poll_excel_sync_results()

    def _build(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        sidebar = tk.Frame(self, bg=SIDEBAR_BG, width=292, padx=16, pady=20)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)

        brand_card = tk.Frame(
            sidebar,
            bg=SIDEBAR_SURFACE,
            padx=14,
            pady=14,
            highlightbackground=SIDEBAR_BORDER,
            highlightthickness=1,
        )
        brand_card.pack(fill="x", pady=(0, 18))

        GradientBand(brand_card, start=BLUE, end=TEAL, height=3).pack(fill="x", pady=(0, 14))

        brand_row = tk.Frame(brand_card, bg=SIDEBAR_SURFACE)
        brand_row.pack(fill="x")
        logo = self.app.get_logo((58, 58))
        if logo:
            logo_box = tk.Frame(brand_row, bg=SIDEBAR_SURFACE_2, padx=6, pady=6)
            logo_box.pack(side="left")
            tk.Label(logo_box, image=logo, bg=SIDEBAR_SURFACE_2).pack()

        brand_text = tk.Frame(brand_row, bg=SIDEBAR_SURFACE)
        brand_text.pack(side="left", fill="x", expand=True, padx=(12, 0))
        tk.Label(
            brand_text,
            text="Digital Service\nPakistan",
            bg=SIDEBAR_SURFACE,
            fg=WHITE,
            font=(FONT_BOLD, 14),
            justify="left",
        ).pack(anchor="w")
        tk.Label(
            brand_text,
            text="Employee Portal",
            bg=SIDEBAR_SURFACE,
            fg=SIDEBAR_MUTED,
            font=(FONT, 9),
        ).pack(anchor="w", pady=(4, 0))

        tk.Label(
            sidebar,
            text="WORKSPACE",
            bg=SIDEBAR_BG,
            fg=SIDEBAR_MUTED,
            font=(FONT_BOLD, 8),
        ).pack(anchor="w", padx=4, pady=(2, 8))

        nav_container = tk.Frame(sidebar, bg=SIDEBAR_BG)
        nav_container.pack(fill="x")
        nav_container.grid_columnconfigure(0, weight=1)

        nav_items = [
            ("overview", "Dashboard"),
            ("attendance", "Attendance"),
            ("sales", "Sold Item Entry"),
            ("today", "5-Day Data"),
        ]
        for index, (key, label) in enumerate(nav_items):
            button = make_button(nav_container, label, lambda view=key: self.show_view(view), "sidebar", anchor="w")
            button.grid(row=index, column=0, sticky="ew", pady=4)
            self.nav_buttons[key] = button
            if key in {"sales", "today"}:
                self.shift_required_buttons.append(button)

        tk.Frame(sidebar, bg=SIDEBAR_BG).pack(fill="both", expand=True)

        status_card = tk.Frame(
            sidebar,
            bg=SIDEBAR_SURFACE,
            padx=12,
            pady=12,
            highlightbackground=SIDEBAR_BORDER,
            highlightthickness=1,
        )
        status_card.pack(fill="x", pady=(18, 12))
        tk.Label(status_card, text="Shift Status", bg=SIDEBAR_SURFACE, fg=SIDEBAR_MUTED, font=(FONT_BOLD, 8)).pack(
            anchor="w", pady=(0, 8)
        )
        self.shift_pill = status_pill(status_card, "Not checked in", fg=BLUE_DARK, bg="#eaf2ff")
        self.shift_pill.pack(fill="x")
        make_button(sidebar, "Logout", self.app.logout, "sidebar_active").pack(fill="x")

        shell = tk.Frame(self, bg=BG)
        self.shell = shell
        shell.grid(row=0, column=1, sticky="nsew")
        shell.grid_rowconfigure(1, weight=1)
        shell.grid_columnconfigure(0, weight=1)
        shell.bind("<Configure>", self._on_shell_configure)

        topbar = SurfaceCard(shell, padx=28, pady=18, accent=True, accent_start=BLUE, accent_end=TEAL)
        topbar.grid(row=0, column=0, sticky="ew", padx=18, pady=(18, 0))
        top = topbar.body
        top.grid_columnconfigure(0, weight=1)
        tk.Label(top, text="Employee Workspace", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 19)).grid(
            row=0, column=0, sticky="w"
        )
        self.user_label = tk.Label(top, text="", bg=WHITE, fg=MUTED, font=(FONT, 10))
        self.user_label.grid(row=1, column=0, sticky="w", pady=(4, 0))

        self.notification_frame = tk.Frame(top, bg=WHITE)
        self.notification_frame.grid(row=0, column=1, rowspan=2, sticky="e", padx=(0, 12))
        self.notification_button = make_button(
            self.notification_frame,
            "Notifications",
            self.toggle_notifications,
            "light",
        )
        self.notification_button.pack(side="left")
        self.notification_badge = tk.Label(
            self.notification_frame,
            text="",
            bg=WARNING,
            fg=WHITE,
            font=(FONT_BOLD, 8),
            padx=7,
            pady=2,
        )
        self.notification_badge.pack(side="left", padx=(6, 0))

        self.clock_label = tk.Label(top, text="", bg="#eef6ff", fg=NAVY, font=(FONT_BOLD, 11), padx=14, pady=7)
        self.clock_label.grid(row=0, column=2, rowspan=2, sticky="e")

        self.content = tk.Frame(shell, bg=BG, padx=18, pady=18)
        self.content.grid(row=1, column=0, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)
        self.notification_dropdown = NotificationDropdown(shell, self)

        self.views["overview"] = self._build_overview_view()
        self.views["attendance"] = self._build_attendance_view()
        self.views["sales"] = self._build_sales_view()
        self.views["today"] = self._build_today_view()
        self.show_view("overview")

    def _build_overview_view(self) -> tk.Frame:
        view = tk.Frame(self.content, bg=BG)
        view.grid_columnconfigure((0, 1, 2), weight=1, uniform="cards")
        view.grid_rowconfigure(3, weight=1)

        self.welcome_banner = GradientBanner(
            view,
            "Ready for today's work",
            "Check in, manage breaks, and record every sold item without exposing the full workbook.",
            height=136,
        )
        self.welcome_banner.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 16))

        self.status_card = MetricCard(view, "Shift Status", "Not checked in", BLUE, "Attendance will appear here")
        self.status_card.grid(row=1, column=0, sticky="ew", padx=(0, 12), pady=(0, 16))

        self.entries_card = MetricCard(view, "Entries Today", "0", BLUE, "Sold item records")
        self.entries_card.grid(row=1, column=1, sticky="ew", padx=6, pady=(0, 16))

        self.break_card = MetricCard(view, "Break Time", "0m", WARNING, "Tracked during shift")
        self.break_card.grid(row=1, column=2, sticky="ew", padx=(12, 0), pady=(0, 16))

        actions = SurfaceCard(view, padx=20, pady=18, accent=True, accent_start=TEAL, accent_end=BLUE)
        actions.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(0, 16))
        body = actions.body
        body.grid_columnconfigure((0, 1, 2, 3, 4, 5, 6), weight=1)
        tk.Label(body, text="Quick Actions", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 14)).grid(
            row=0, column=0, sticky="w", pady=(0, 12)
        )
        self.access_notice = tk.Label(
            body,
            text="Check in first to unlock sales, break, and 5-day data controls.",
            bg=WHITE,
            fg=WARNING,
            font=(FONT_BOLD, 9),
        )
        self.access_notice.grid(row=0, column=1, columnspan=3, sticky="e", pady=(0, 12))

        start_day_button = make_button(body, "Start Day", self.start_day, "primary")
        start_day_button.grid(row=1, column=0, sticky="ew", padx=(0, 6))
        self.start_day_buttons.append(start_day_button)

        check_in_button = make_button(body, "Check In", self.check_in, "success")
        check_in_button.grid(row=1, column=1, sticky="ew", padx=6)
        self.check_in_buttons.append(check_in_button)

        start_break_button = make_button(body, "Start Break", self.start_break, "primary")
        start_break_button.grid(row=1, column=2, sticky="ew", padx=6)
        self.start_break_buttons.append(start_break_button)

        add_sale_button = make_button(body, "Add Sale", lambda: self.show_view("sales"), "primary")
        add_sale_button.grid(row=1, column=3, sticky="ew", padx=6)
        self.shift_required_buttons.append(add_sale_button)

        view_today_button = make_button(body, "View Today", lambda: self.show_view("today"), "light")
        view_today_button.grid(row=1, column=4, sticky="ew", padx=6)
        self.shift_required_buttons.append(view_today_button)

        close_first_button = make_button(body, "Close First Shift", self.close_first_shift, "warning")
        close_first_button.grid(row=1, column=5, sticky="ew", padx=6)
        self.close_first_shift_buttons.append(close_first_button)

        end_day_button = make_button(body, "End Day", self.end_day, "danger")
        end_day_button.grid(row=1, column=6, sticky="ew", padx=(6, 0))
        self.end_day_buttons.append(end_day_button)

        activity = SurfaceCard(view, padx=20, pady=18, accent=True, accent_start=BLUE, accent_end=TEAL)
        activity.grid(row=3, column=0, columnspan=3, sticky="nsew")
        body = activity.body
        body.grid_rowconfigure(1, weight=1)
        body.grid_columnconfigure(0, weight=1)
        tk.Label(body, text="Recent Activity", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 14)).grid(
            row=0, column=0, sticky="w", pady=(0, 12)
        )
        self.recent_list = tk.Listbox(
            body,
            bg="#fbfdff",
            fg=TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=LINE,
            font=(FONT, 10),
            activestyle="none",
        )
        self.recent_list.grid(row=1, column=0, sticky="nsew")
        return view

    def _build_attendance_view(self) -> tk.Frame:
        view = tk.Frame(self.content, bg=BG)
        view.grid_columnconfigure(0, weight=1)
        view.grid_rowconfigure(2, weight=1)

        banner = GradientBanner(
            view,
            "Attendance Control",
            "Use these controls at the start and end of shift, and whenever a break starts or ends.",
            height=120,
            start=NAVY,
            end=BLUE_DARK,
        )
        banner.grid(row=0, column=0, sticky="ew", pady=(0, 16))

        status = SurfaceCard(view, padx=20, pady=18, accent=True, accent_start=SUCCESS, accent_end=TEAL)
        status.grid(row=1, column=0, sticky="ew", pady=(0, 16))
        body = status.body
        body.grid_columnconfigure((0, 1, 2), weight=1)

        self.attendance_status = tk.Label(body, text="", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 18))
        self.attendance_status.grid(row=0, column=0, sticky="w")
        self.shift_time_label = tk.Label(body, text="", bg=WHITE, fg=MUTED, font=(FONT, 10))
        self.shift_time_label.grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.break_time_label = tk.Label(body, text="", bg=WHITE, fg=MUTED, font=(FONT, 10))
        self.break_time_label.grid(row=1, column=1, sticky="w", pady=(6, 0))
        self.attendance_date_label = status_pill(body, today_label(), fg=BLUE, bg="#eef6ff")
        self.attendance_date_label.grid(row=0, column=2, sticky="e")

        controls = SurfaceCard(view, padx=20, pady=18, accent=True, accent_start=TEAL, accent_end=BLUE)
        controls.grid(row=2, column=0, sticky="ew", pady=(0, 16))
        body = controls.body
        body.grid_columnconfigure((0, 1, 2, 3, 4, 5, 6), weight=1)

        attendance_start_day = make_button(body, "Start Day", self.start_day, "primary")
        attendance_start_day.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.start_day_buttons.append(attendance_start_day)

        attendance_check_in = make_button(body, "Check In", self.check_in, "success")
        attendance_check_in.grid(row=0, column=1, sticky="ew", padx=6)
        self.check_in_buttons.append(attendance_check_in)

        attendance_start_break = make_button(body, "Start Break", self.start_break, "primary")
        attendance_start_break.grid(row=0, column=2, sticky="ew", padx=6)
        self.start_break_buttons.append(attendance_start_break)

        attendance_end_break = make_button(body, "End Break", self.end_break, "light")
        attendance_end_break.grid(row=0, column=3, sticky="ew", padx=6)
        self.end_break_buttons.append(attendance_end_break)

        attendance_check_out = make_button(body, "Check Out", self.check_out, "danger")
        attendance_check_out.grid(row=0, column=4, sticky="ew", padx=6)
        self.checkout_buttons.append(attendance_check_out)

        attendance_close_first = make_button(body, "Close First Shift", self.close_first_shift, "warning")
        attendance_close_first.grid(row=0, column=5, sticky="ew", padx=6)
        self.close_first_shift_buttons.append(attendance_close_first)

        attendance_end_day = make_button(body, "End Day", self.end_day, "danger")
        attendance_end_day.grid(row=0, column=6, sticky="ew", padx=(6, 0))
        self.end_day_buttons.append(attendance_end_day)

        log = SurfaceCard(view, padx=20, pady=18, accent=True, accent_start=BLUE, accent_end=TEAL)
        log.grid(row=3, column=0, sticky="nsew")
        body = log.body
        body.grid_rowconfigure(1, weight=1)
        body.grid_columnconfigure(0, weight=1)
        tk.Label(body, text="Attendance Log", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 14)).grid(
            row=0, column=0, sticky="w", pady=(0, 12)
        )
        self.attendance_tree = ttk.Treeview(body, columns=("time", "event", "details"), show="headings")
        self.attendance_tree.heading("time", text="Time")
        self.attendance_tree.heading("event", text="Event")
        self.attendance_tree.heading("details", text="Details")
        self.attendance_tree.column("time", width=120, anchor="w")
        self.attendance_tree.column("event", width=160, anchor="w")
        self.attendance_tree.column("details", width=520, anchor="w")
        self.attendance_tree.grid(row=1, column=0, sticky="nsew")
        return view

    def _build_sales_view(self) -> tk.Frame:
        view = tk.Frame(self.content, bg=BG)
        view.grid_columnconfigure(0, weight=2)
        view.grid_columnconfigure(1, weight=1)
        view.grid_rowconfigure(0, weight=1)

        form_card = SurfaceCard(view, padx=22, pady=20, accent=True, accent_start=BLUE, accent_end=TEAL)
        form_card.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        form = form_card.body
        form.grid_columnconfigure((0, 1), weight=1)

        tk.Label(form, text="Sold Item Entry", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 18)).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 6)
        )
        tk.Label(
            form,
            text="The last 5 days of entries are visible to the employee.",
            bg=WHITE,
            fg=MUTED,
            font=(FONT, 10),
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 18))

        row = 2
        for index, (key, label, kind, values) in enumerate(SALES_FIELDS):
            column = index % 2
            if column == 0 and index > 0:
                row += 2
            self._sales_field(form, key, label, row, column, kind, values)

        self._sales_date_field(form, row + 2, 0)
        self._status_other_field(form, row + 2, 1)

        self.submit_sales_button = make_button(form, "Save Entry", self.submit_sales_entry, "primary")
        self.submit_sales_button.grid(row=row + 4, column=0, sticky="ew", padx=(0, 8), pady=(8, 0))
        self.shift_required_buttons.append(self.submit_sales_button)

        clear_form_button = make_button(form, "Clear Form", self.clear_sales_form, "light")
        clear_form_button.grid(row=row + 4, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))
        self.shift_required_buttons.append(clear_form_button)

        side_card = SurfaceCard(view, padx=20, pady=20, accent=True, accent_start=SUCCESS, accent_end=TEAL)
        side_card.grid(row=0, column=1, sticky="nsew")
        side = side_card.body
        side.grid_columnconfigure(0, weight=1)
        tk.Label(side, text="Today", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 18)).grid(row=0, column=0, sticky="w")
        self.sales_today_count = tk.Label(side, text="0 entries", bg=WHITE, fg=BLUE, font=(FONT_BOLD, 28))
        self.sales_today_count.grid(row=1, column=0, sticky="w", pady=(8, 28))

        GradientBand(side, start=BLUE, end=TEAL, height=4).grid(row=3, column=0, sticky="ew", pady=(0, 18))
        tk.Label(side, text="Last Saved", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 12)).grid(row=4, column=0, sticky="w", pady=(0, 8))
        self.last_saved_label = tk.Label(
            side,
            text="No entries yet",
            bg=WHITE,
            fg=MUTED,
            font=(FONT, 10),
            wraplength=240,
            justify="left",
        )
        self.last_saved_label.grid(row=5, column=0, sticky="w")
        tk.Frame(side, bg=WHITE).grid(row=6, column=0, sticky="nsew")
        side.grid_rowconfigure(6, weight=1)
        open_today_button = make_button(side, "Open 5-Day Data", lambda: self.show_view("today"), "light")
        open_today_button.grid(row=7, column=0, sticky="ew", pady=(18, 0))
        self.shift_required_buttons.append(open_today_button)
        return view

    def _build_today_view(self) -> tk.Frame:
        view = tk.Frame(self.content, bg=BG)
        view.grid_rowconfigure(2, weight=1)
        view.grid_columnconfigure(0, weight=1)

        summary = SurfaceCard(view, padx=20, pady=16, accent=True, accent_start=BLUE, accent_end=TEAL)
        summary.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        body = summary.body
        body.grid_columnconfigure(0, weight=1)
        tk.Label(body, text="5-Day Sales Data", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 18)).grid(row=0, column=0, sticky="w")
        self.today_summary_label = tk.Label(body, text="", bg=WHITE, fg=MUTED, font=(FONT, 10))
        self.today_summary_label.grid(row=1, column=0, sticky="w", pady=(6, 0))
        today_add_button = make_button(body, "Add New Entry", lambda: self.show_view("sales"), "primary")
        today_add_button.grid(row=0, column=1, rowspan=2, sticky="e", padx=(18, 0))
        self.shift_required_buttons.append(today_add_button)

        days = tk.Frame(view, bg=BG)
        days.grid(row=1, column=0, sticky="ew", pady=(0, 16))
        for index in range(self.SALES_VISIBLE_DAYS):
            days.grid_columnconfigure(index, weight=1, uniform="sales_day")
            self._build_sales_day_card(days, index)

        table_card = SurfaceCard(view, padx=20, pady=18, accent=True, accent_start=TEAL, accent_end=BLUE)
        table_card.grid(row=2, column=0, sticky="nsew")
        body = table_card.body
        body.grid_rowconfigure(1, weight=1)
        body.grid_columnconfigure(0, weight=1)

        table_header = tk.Frame(body, bg=WHITE)
        table_header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 14))
        table_header.grid_columnconfigure(0, weight=1)
        self.selected_day_title_label = tk.Label(
            table_header,
            text="",
            bg=WHITE,
            fg=TEXT,
            font=(FONT_BOLD, 15),
        )
        self.selected_day_title_label.grid(row=0, column=0, sticky="w")
        self.selected_day_meta_label = tk.Label(
            table_header,
            text="",
            bg=WHITE,
            fg=MUTED,
            font=(FONT, 10),
        )
        self.selected_day_meta_label.grid(row=1, column=0, sticky="w", pady=(4, 0))

        columns = ("id", "time", "customer", "item", "email_order", "buying", "selling", "status")
        self.today_tree = ttk.Treeview(body, columns=columns, show="headings", selectmode="browse")
        headings = {
            "id": "ID",
            "time": "Time",
            "customer": "Customer",
            "item": "Items Sold",
            "email_order": "Email/Order ID",
            "buying": "Buying",
            "selling": "Selling",
            "status": "Status",
        }
        widths = {
            "id": 58,
            "time": 96,
            "customer": 170,
            "item": 250,
            "email_order": 250,
            "buying": 105,
            "selling": 105,
            "status": 190,
        }
        for column in columns:
            self.today_tree.heading(column, text=headings[column], anchor="w")
            self.today_tree.column(
                column,
                width=widths[column],
                minwidth=widths[column],
                anchor="w",
                stretch=False,
            )
        self.today_tree.tag_configure("entry_even", background=WHITE, foreground=TEXT)
        self.today_tree.tag_configure("entry_odd", background="#f8fbff", foreground=TEXT)
        self.today_tree.grid(row=1, column=0, sticky="nsew")
        self.today_tree.bind("<<TreeviewSelect>>", lambda _event: self._refresh_sync_retry_action())

        scrollbar = ttk.Scrollbar(body, orient="vertical", command=self.today_tree.yview)
        scrollbar.grid(row=1, column=1, sticky="ns")
        xscrollbar = ttk.Scrollbar(body, orient="horizontal", command=self.today_tree.xview)
        xscrollbar.grid(row=2, column=0, sticky="ew")
        self.today_tree.configure(yscrollcommand=scrollbar.set, xscrollcommand=xscrollbar.set)

        actions = tk.Frame(body, bg=WHITE)
        actions.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        edit_selected_button = make_button(actions, "Edit Selected", self.edit_selected_entry, "primary")
        edit_selected_button.pack(side="left", padx=(0, 10))
        self.shift_required_buttons.append(edit_selected_button)
        self.sync_retry_button = make_button(actions, "Sync Again With Excel", self.retry_selected_excel_sync, "warning")
        return view

    def _build_sales_day_card(self, parent: tk.Misc, index: int) -> None:
        card = tk.Frame(
            parent,
            bg=WHITE,
            padx=14,
            pady=12,
            highlightbackground=LINE,
            highlightthickness=1,
            cursor="hand2",
        )
        card.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 8, 0))
        card.grid_columnconfigure(0, weight=1)
        label = tk.Label(card, text="", bg=WHITE, fg=MUTED, font=(FONT_BOLD, 9), cursor="hand2")
        label.grid(row=0, column=0, sticky="w")
        date_label = tk.Label(card, text="", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 12), cursor="hand2")
        date_label.grid(row=1, column=0, sticky="w", pady=(6, 0))
        count_label = tk.Label(card, text="", bg=WHITE, fg=BLUE, font=(FONT_BOLD, 10), cursor="hand2")
        count_label.grid(row=2, column=0, sticky="w", pady=(10, 0))
        status_label = tk.Label(card, text="", bg=WHITE, fg=MUTED, font=(FONT, 9), cursor="hand2")
        status_label.grid(row=3, column=0, sticky="w", pady=(4, 0))
        slot = {
            "card": card,
            "label": label,
            "date": date_label,
            "count": count_label,
            "status": status_label,
        }
        self.sales_day_card_slots.append(slot)
        for widget in slot.values():
            widget.bind("<Button-1>", lambda _event, slot_index=index: self._select_sales_day_slot(slot_index))

    def _sales_field(
        self,
        parent: tk.Misc,
        key: str,
        label: str,
        row: int,
        column: int,
        kind: str,
        values: list[str] | None,
    ) -> None:
        variable = tk.StringVar()
        if key == "buying_amount":
            variable.set("0")
        if values:
            variable.set(values[0])
        self.sales_vars[key] = variable
        padx = (0 if column == 0 else 12, 0)
        field_label(parent, label).grid(row=row, column=column, sticky="w", padx=padx)
        if kind == "combo" and values:
            widget = combo_box(parent, variable, values)
            widget.grid(row=row + 1, column=column, sticky="ew", ipady=6, padx=padx, pady=(8, 14))
            if key == "status":
                widget.bind("<<ComboboxSelected>>", lambda _event: self._update_status_other_visibility())
            self.sales_input_widgets.append(widget)
            return
        widget = text_entry(parent, variable)
        if key in {"buying_amount", "selling_amount"}:
            widget.configure(
                validate="key",
                validatecommand=(self.register(_amount_input_allowed), "%P"),
            )
        widget.grid(row=row + 1, column=column, sticky="ew", ipady=8, padx=padx, pady=(8, 14))
        self.sales_input_widgets.append(widget)

    def _sales_date_field(self, parent: tk.Misc, row: int, column: int) -> None:
        field_label(parent, "Date").grid(row=row, column=column, sticky="w")
        widget = text_entry(parent, self.sales_date_var)
        widget.configure(
            state="disabled",
            disabledbackground="#eef6ff",
            disabledforeground=TEXT,
        )
        widget.grid(row=row + 1, column=column, sticky="ew", ipady=8, pady=(8, 14))

    def _status_other_field(self, parent: tk.Misc, row: int, column: int) -> None:
        padx = (12, 0)
        label = field_label(parent, "Other Status Reason")
        label.grid(row=row, column=column, sticky="w", padx=padx)
        widget = text_entry(parent, self.status_other_var)
        widget.grid(row=row + 1, column=column, sticky="ew", ipady=8, padx=padx, pady=(8, 14))
        self.status_other_widgets = [label, widget]
        self.sales_input_widgets.append(widget)
        self._update_status_other_visibility()

    def _update_status_other_visibility(self) -> None:
        show_other = self.sales_vars.get("status") is not None and self.sales_vars["status"].get() == "Other"
        for widget in self.status_other_widgets:
            if show_other:
                widget.grid()
            else:
                widget.grid_remove()

    def _resolved_status(self, selected_status: str, other_reason: str) -> str | None:
        if selected_status == "Other":
            status = other_reason.strip()
            return status or None
        return selected_status or "Done"

    def _require_shift_active(self) -> bool:
        if self.checked_in:
            return True
        if self.day_active:
            messagebox.showwarning("Check in required", "Please check in before using this function.")
        else:
            messagebox.showwarning("Start day required", "Please start the day before using this function.")
        if self.current_view in self.SHIFT_LOCKED_VIEWS:
            self.show_view("overview")
        return False

    def _employee_username(self) -> str:
        return self.app.display_user

    def _sales_date(self) -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def _sales_date_display(self) -> str:
        try:
            value = datetime.strptime(self._sales_date(), "%Y-%m-%d")
        except ValueError:
            value = datetime.now()
        return f"{value.day}/{value.month}/{value.year}"

    def _sales_visible_dates(self) -> list[str]:
        today = datetime.now().date()
        first_day = today - timedelta(days=self.SALES_VISIBLE_DAYS - 1)
        return [
            (first_day + timedelta(days=offset)).strftime("%Y-%m-%d")
            for offset in range(self.SALES_VISIBLE_DAYS)
        ]

    def _sales_window_label(self) -> str:
        visible_dates = self._sales_visible_dates()
        first_day = datetime.strptime(visible_dates[0], "%Y-%m-%d")
        last_day = datetime.strptime(visible_dates[-1], "%Y-%m-%d")
        return f"{first_day.strftime('%d %b')} - {last_day.strftime('%d %b %Y')}"

    def _sales_day_title(self, value: str) -> str:
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            return f"Data {value}"
        return f"Data {parsed.strftime('%d %B %Y')}"

    def _sales_day_label(self, value: str) -> str:
        today = datetime.now().strftime("%Y-%m-%d")
        if value == today:
            return "Today"
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            return "Sales Day"
        return parsed.strftime("%A")

    def _entry_count_text(self, count: int) -> str:
        return f"{count} entry" if count == 1 else f"{count} entries"

    def _sales_entries_for_date(self, entry_date: str) -> list[dict[str, str]]:
        return [entry for entry in self.sales_entries if entry["date"] == entry_date]

    def _sales_entry_display_number(self, entry: dict[str, str]) -> int:
        entry_id = str(entry.get("id", ""))
        for index, day_entry in enumerate(self._sales_entries_for_date(entry.get("date", "")), start=1):
            if str(day_entry.get("id", "")) == entry_id:
                return index
        return 1

    def _sales_entry_from_store_row(self, entry: dict[str, str]) -> dict[str, str]:
        item = dict(entry)
        item["id"] = str(item["id"])
        if "entry_date" in item:
            item["date"] = item.pop("entry_date")
        if "entry_time" in item:
            item["time"] = item.pop("entry_time")
        return item

    def _update_sales_entry_cache(self, updated: dict[str, str]) -> dict[str, str]:
        item = self._sales_entry_from_store_row(updated)
        for index, entry in enumerate(self.sales_entries):
            if str(entry.get("id", "")) == item["id"]:
                self.sales_entries[index] = item
                break
        return item

    def _refresh_sales_entries_from_store(self) -> None:
        visible_dates = self._sales_visible_dates()
        self.app.attendance_store.purge_old_synced_sales_entries(self._employee_username(), visible_dates[0])
        if self.sales_selected_date not in visible_dates:
            self.sales_selected_date = visible_dates[-1]
        entries = []
        for entry_date in visible_dates:
            entries.extend(self.app.attendance_store.list_sales_entries(self._employee_username(), entry_date))
        normalized = []
        for entry in entries:
            normalized.append(self._sales_entry_from_store_row(entry))
        self.sales_entries = normalized

    def _select_sales_day_slot(self, index: int) -> None:
        visible_dates = self._sales_visible_dates()
        if index < 0 or index >= len(visible_dates):
            return
        self.select_sales_date(visible_dates[index])

    def select_sales_date(self, entry_date: str) -> None:
        if entry_date not in self._sales_visible_dates():
            return
        self.sales_selected_date = entry_date
        self._refresh_sales_day_cards()
        self._refresh_selected_sales_day_header()
        self._refresh_today_table()

    def _refresh_sales_day_cards(self) -> None:
        visible_dates = self._sales_visible_dates()
        for index, slot in enumerate(self.sales_day_card_slots):
            if index >= len(visible_dates):
                continue
            entry_date = visible_dates[index]
            day_entries = self._sales_entries_for_date(entry_date)
            selected = entry_date == self.sales_selected_date
            card_bg = "#eaf2ff" if selected else WHITE
            border = BLUE if selected else LINE
            title_fg = BLUE_DARK if selected else TEXT
            muted_fg = BLUE_DARK if selected else MUTED
            count_fg = BLUE if selected else NAVY
            slot["card"].configure(bg=card_bg, highlightbackground=border)
            slot["label"].configure(text=self._sales_day_label(entry_date), bg=card_bg, fg=muted_fg)
            slot["date"].configure(text=self._sales_day_title(entry_date), bg=card_bg, fg=title_fg)
            slot["count"].configure(text=self._entry_count_text(len(day_entries)), bg=card_bg, fg=count_fg)
            slot["status"].configure(text="Selected" if selected else "", bg=card_bg, fg=SUCCESS)

    def _refresh_selected_sales_day_header(self) -> None:
        selected_entries = self._sales_entries_for_date(self.sales_selected_date)
        self.selected_day_title_label.configure(text=self._sales_day_title(self.sales_selected_date))
        self.selected_day_meta_label.configure(
            text=f"{self._entry_count_text(len(selected_entries))} saved for this date"
        )

    def _sync_attendance_state(self) -> None:
        active_day = self.app.attendance_store.get_active_day(self._employee_username())
        self.current_day_id = int(active_day["id"]) if active_day else None
        self.current_day_date = active_day["day_date"] if active_day else ""
        self.day_active = active_day is not None
        self.day_started_at = datetime.fromisoformat(active_day["started_at"]) if active_day else None

        active = self.app.attendance_store.get_active_shift(self._employee_username())
        self.current_shift_id = int(active["id"]) if active else None
        self.current_shift_number = int(active["shift_number"]) if active else 0
        self.checked_in = active is not None
        self.on_break = bool(active and active["current_break_started_at"])
        self.total_break_seconds = int(active["total_break_seconds"]) if active else 0
        self.shift_started_at = datetime.fromisoformat(active["started_at"]) if active else None
        if active and active["current_break_started_at"]:
            self.break_started_at = datetime.fromisoformat(active["current_break_started_at"])
        else:
            self.break_started_at = None

    def _format_event_time(self, value: str) -> str:
        try:
            return datetime.fromisoformat(value).strftime("%I:%M %p")
        except ValueError:
            return value

    def _shift_label(self, shift_number: int | None = None) -> str:
        number = shift_number if shift_number is not None else self.current_shift_number
        if number == 0:
            return "Day"
        if number == 1:
            return "First Shift"
        if number == 2:
            return "Night Shift"
        if number:
            return f"Shift {number}"
        return "No active shift"

    def _day_label(self) -> str:
        if not self.day_active:
            return "Day not started"
        if self.day_started_at:
            return f"Day started {self.day_started_at.strftime('%d %b %Y, %I:%M %p')}"
        return "Day active"

    def _set_sales_inputs_enabled(self, enabled: bool) -> None:
        for widget in self.sales_input_widgets:
            if isinstance(widget, ttk.Combobox):
                widget.configure(state="readonly" if enabled else "disabled")
            elif isinstance(widget, tk.Text):
                widget.configure(state="normal" if enabled else "disabled")
            else:
                widget.configure(state="normal" if enabled else "disabled")
        self._update_status_other_visibility()

    def _apply_access_state(self) -> None:
        shift_active = self.checked_in
        can_start_day = not self.day_active and not shift_active
        can_check_in = self.day_active and not shift_active
        can_start_break = shift_active and not self.on_break
        can_end_break = shift_active and self.on_break
        can_check_out = shift_active and not self.on_break
        can_close_first_shift = shift_active and self.current_shift_number == 1 and not self.on_break
        can_end_day = self.day_active and not shift_active and not self.on_break

        for button in self.start_day_buttons:
            set_button_enabled(button, can_start_day)
        for button in self.check_in_buttons:
            set_button_enabled(button, can_check_in)
        for button in self.start_break_buttons:
            set_button_enabled(button, can_start_break)
        for button in self.end_break_buttons:
            set_button_enabled(button, can_end_break)
        for button in self.checkout_buttons:
            set_button_enabled(button, can_check_out)
        for button in self.close_first_shift_buttons:
            set_button_enabled(button, can_close_first_shift)
        for button in self.end_day_buttons:
            set_button_enabled(button, can_end_day)
        for button in self.shift_required_buttons:
            set_button_enabled(button, shift_active)

        self._set_sales_inputs_enabled(shift_active)
        if shift_active:
            self.access_notice.configure(text="Sales, breaks, and 5-day data controls are unlocked.", fg=SUCCESS)
        elif self.day_active:
            self.access_notice.configure(text="Day is started. Check in to unlock work controls.", fg=BLUE)
        else:
            self.access_notice.configure(
                text="Start day first, then check in to unlock sales and break controls.",
                fg=WARNING,
            )

    def show_view(self, name: str) -> None:
        if name in self.SHIFT_LOCKED_VIEWS and not self.checked_in:
            messagebox.showwarning("Check in required", "Please check in before using this function.")
            name = "overview"
        for view in self.views.values():
            view.grid_remove()
        self.views[name].grid(row=0, column=0, sticky="nsew")
        self.current_view = name
        for key, button in self.nav_buttons.items():
            if key == name:
                button.normal_bg = SIDEBAR_ACTIVE  # type: ignore[attr-defined]
                button.hover_bg = "#d7e9ff"  # type: ignore[attr-defined]
                button.enabled_fg = SIDEBAR_ACTIVE_TEXT  # type: ignore[attr-defined]
                button.configure(bg=SIDEBAR_ACTIVE, fg=SIDEBAR_ACTIVE_TEXT, activeforeground=SIDEBAR_ACTIVE_TEXT)
            else:
                button.normal_bg = SIDEBAR_SURFACE_2  # type: ignore[attr-defined]
                button.hover_bg = SIDEBAR_HOVER  # type: ignore[attr-defined]
                button.enabled_fg = SIDEBAR_TEXT  # type: ignore[attr-defined]
                button.configure(bg=SIDEBAR_SURFACE_2, fg=SIDEBAR_TEXT, activeforeground=SIDEBAR_TEXT)
        self.refresh_all()

    def refresh_all(self) -> None:
        self._sync_attendance_state()
        self.sales_date_var.set(self._sales_date_display())
        self._refresh_sales_entries_from_store()
        self.user_label.configure(text=f"Signed in as {self.app.display_user}")
        self.welcome_banner.set_text(
            f"Welcome, {self.app.display_user}",
            f"{self._day_label()} | {self._shift_label()} status is tracked with breaks and sold-item entries.",
        )
        self._refresh_stats()
        self._refresh_attendance_log()
        self._refresh_today_table()
        self._refresh_recent_activity()
        self._refresh_notification_badge()

    def _tick_clock(self) -> None:
        self.clock_label.configure(text=f"{today_label()}  |  {now_label()}")
        self.after(1000, self._tick_clock)

    def _refresh_stats(self) -> None:
        if self.on_break:
            shift_status = "On break"
            accent = WARNING
            pill_bg = "#fff5e6"
        elif self.checked_in:
            shift_status = "Checked in"
            accent = SUCCESS
            pill_bg = "#eafaf4"
        elif self.day_active:
            shift_status = "Day started"
            accent = BLUE
            pill_bg = "#eef6ff"
        else:
            shift_status = "Not checked in"
            accent = MUTED
            pill_bg = "#eaf2ff"

        self.shift_pill.configure(text=shift_status, fg=accent if accent != MUTED else BLUE_DARK, bg=pill_bg)
        self.status_card.value_label.configure(text=shift_status, fg=accent)
        self.status_card.helper_label.configure(text=self._shift_label() if self.checked_in else self._day_label())
        today_entries = self._sales_entries_for_date(self._sales_date())
        self.entries_card.value_label.configure(text=str(len(today_entries)))
        self.break_card.value_label.configure(text=duration_label(self.current_break_seconds()))

        self.attendance_status.configure(text=shift_status, fg=accent)
        if self.shift_started_at:
            self.shift_time_label.configure(text=f"{self._shift_label()} started: {self.shift_started_at.strftime('%I:%M %p')}")
        else:
            self.shift_time_label.configure(text="Shift started: -")
        self.break_time_label.configure(text=f"Break time: {duration_label(self.current_break_seconds())}")
        self.attendance_date_label.configure(text=today_label())

        self.sales_today_count.configure(text=self._entry_count_text(len(today_entries)))
        self.today_summary_label.configure(
            text=f"{self._sales_window_label()} | {self._entry_count_text(len(self.sales_entries))} visible for 5 days"
        )
        self._refresh_sales_day_cards()
        self._refresh_selected_sales_day_header()
        self._apply_access_state()

    def _refresh_attendance_log(self) -> None:
        self.attendance_events = self.app.attendance_store.list_employee_events(self._employee_username())
        for item in self.attendance_tree.get_children():
            self.attendance_tree.delete(item)
        for event in self.attendance_events:
            self.attendance_tree.insert(
                "",
                "end",
                values=(
                    self._format_event_time(event["event_time"]),
                    event["event_label"],
                    f"{self._shift_label(int(event['shift_number']))} - {event['details']}",
                ),
            )

    def _refresh_today_table(self) -> None:
        for item in self.today_tree.get_children():
            self.today_tree.delete(item)
        for index, entry in enumerate(self._sales_entries_for_date(self.sales_selected_date)):
            tag = "entry_even" if index % 2 == 0 else "entry_odd"
            self.today_tree.insert(
                "",
                "end",
                iid=str(entry["id"]),
                tags=(tag,),
                values=(
                    str(index + 1),
                    entry["time"],
                    entry["customer"],
                    entry["item"],
                    entry["order_id"],
                    money_label(entry["buying_amount"]),
                    money_label(entry["selling_amount"]),
                    entry["status"],
                ),
            )
        self._refresh_sync_retry_action()

    def _selected_entry_for_sync_action(self) -> dict[str, str] | None:
        selection = self.today_tree.selection()
        if not selection:
            return None
        entry_id = selection[0]
        for entry in self.sales_entries:
            if entry["id"] == entry_id:
                return entry
        return None

    def _entry_needs_excel_retry(self, entry: dict[str, str] | None) -> bool:
        if entry is None:
            return False
        if str(entry.get("id", "")) in self.excel_sync_pending_entry_ids:
            return False
        return not entry.get("excel_synced_at") and bool(entry.get("excel_sync_error"))

    def _refresh_sync_retry_action(self) -> None:
        if self.sync_retry_button is None:
            return
        entry = self._selected_entry_for_sync_action()
        if self._entry_needs_excel_retry(entry):
            if not self.sync_retry_button.winfo_ismapped():
                self.sync_retry_button.pack(side="left", padx=(0, 10))
        else:
            self.sync_retry_button.pack_forget()

    def _queue_excel_sync(self, entry: dict[str, str], source: str, display_number: int | None = None) -> bool:
        entry_id = str(entry.get("id", ""))
        if not entry_id or entry_id in self.excel_sync_pending_entry_ids:
            return False
        pending_entry = self._mark_excel_sync_pending(entry)
        self.excel_sync_pending_entry_ids.add(entry_id)
        self.excel_sync_queue.append((pending_entry, source, display_number))
        self._refresh_sync_retry_action()
        self._start_next_excel_sync()
        return True

    def _mark_excel_sync_pending(self, entry: dict[str, str]) -> dict[str, str]:
        updated = self.app.attendance_store.mark_sales_excel_error(
            int(entry["id"]),
            self._employee_username(),
            "Excel sync pending in background.",
        )
        return self._update_sales_entry_cache(updated)

    def _start_next_excel_sync(self) -> None:
        if self.excel_sync_busy or not self.excel_sync_queue:
            return
        entry, source, display_number = self.excel_sync_queue.pop(0)
        self.excel_sync_busy = True
        worker = threading.Thread(
            target=self._run_excel_sync_worker,
            args=(entry, source, display_number),
            daemon=True,
        )
        worker.start()

    def _run_excel_sync_worker(self, entry: dict[str, str], source: str, display_number: int | None) -> None:
        try:
            sync_result = self.app.sales_workbook.sync_entry(entry)
        except Exception as exc:
            sync_result = ExcelSyncResult(False, message=str(exc))
        self.excel_sync_results.put((entry, source, display_number, sync_result))

    def _poll_excel_sync_results(self) -> None:
        while True:
            try:
                entry, source, display_number, sync_result = self.excel_sync_results.get_nowait()
            except queue.Empty:
                break
            try:
                self._finish_excel_sync(entry, source, display_number, sync_result)
            except Exception as exc:
                messagebox.showwarning("Excel sync", f"Excel sync status could not be updated:\n{exc}")
        self.after(250, self._poll_excel_sync_results)

    def _finish_excel_sync(
        self,
        entry: dict[str, str],
        source: str,
        display_number: int | None,
        sync_result: ExcelSyncResult,
    ) -> None:
        entry_id = str(entry.get("id", ""))
        self.excel_sync_busy = False
        self.excel_sync_pending_entry_ids.discard(entry_id)

        try:
            if sync_result.saved and sync_result.row is not None:
                updated = self.app.attendance_store.mark_sales_excel_sync(
                    int(entry["id"]),
                    self._employee_username(),
                    sync_result.row,
                )
                self._update_sales_entry_cache(updated)
                if source == "edit":
                    self.last_saved_label.configure(text="Data updated and synced with Excel.")
                elif source == "retry":
                    self.last_saved_label.configure(text="Data synced with Excel.")
                else:
                    self.last_saved_label.configure(text="Data added and synced with Excel.")
                if source == "retry":
                    messagebox.showinfo("Excel synced", "Data synced with Excel.")
            else:
                message = sync_result.message or "Excel sync failed."
                updated = self.app.attendance_store.mark_sales_excel_error(
                    int(entry["id"]),
                    self._employee_username(),
                    message,
                )
                self._update_sales_entry_cache(updated)
                self.last_saved_label.configure(
                    text="Data saved locally. Excel sync failed; use Sync Again With Excel."
                )
                if source in {"retry", "edit"}:
                    messagebox.showwarning("Excel sync failed", f"Excel sync still failed:\n{message}")
        finally:
            self.refresh_all()
            self._start_next_excel_sync()

    def _refresh_recent_activity(self) -> None:
        self.recent_list.delete(0, tk.END)
        items: list[str] = []
        for entry in self.sales_entries[-5:]:
            display_number = self._sales_entry_display_number(entry)
            items.append(
                f"{entry['time']} - Sale #{display_number}: {entry['item']} - Rs. {money_label(entry['selling_amount'])}"
            )
        for event in self.attendance_events[-5:]:
            items.append(f"{self._format_event_time(event['event_time'])} - {event['event_label']}")
        if not items:
            self.recent_list.insert(tk.END, "No activity yet today.")
            return
        for item in items[-8:][::-1]:
            self.recent_list.insert(tk.END, item)

    def _refresh_notification_badge(self) -> None:
        if self.notification_badge is None:
            return
        unread_count = self.app.attendance_store.unread_announcement_count(self._employee_username())
        if unread_count:
            self.notification_badge.configure(text=str(unread_count))
            self.notification_badge.pack(side="left", padx=(6, 0))
            return
        self.notification_badge.configure(text="")
        self.notification_badge.pack_forget()

    def _on_shell_configure(self, _event: tk.Event | None = None) -> None:
        if self.notification_dropdown is not None and self.notification_dropdown.winfo_ismapped():
            self._place_notification_dropdown()

    def _place_notification_dropdown(self) -> None:
        if self.shell is None or self.notification_frame is None or self.notification_dropdown is None:
            return
        self.shell.update_idletasks()
        self.notification_frame.update_idletasks()
        dropdown_width = min(460, max(360, self.shell.winfo_width() - 48))
        frame_right = self.notification_frame.winfo_rootx() + self.notification_frame.winfo_width()
        shell_left = self.shell.winfo_rootx()
        x_position = min(frame_right - shell_left, self.shell.winfo_width() - 20)
        y_position = self.notification_frame.winfo_rooty() - self.shell.winfo_rooty() + self.notification_frame.winfo_height() + 10
        dropdown_height = min(430, max(300, self.shell.winfo_height() - y_position - 24))
        self.notification_dropdown.place(
            x=x_position,
            y=y_position,
            anchor="ne",
            width=dropdown_width,
            height=dropdown_height,
        )
        self.notification_dropdown.lift()

    def toggle_notifications(self) -> None:
        if self.notification_dropdown is None:
            return
        if self.notification_dropdown.winfo_ismapped():
            self.notification_dropdown.hide()
            return
        self.notification_dropdown.refresh()
        self._place_notification_dropdown()

    def open_notifications(self) -> None:
        self.toggle_notifications()

    def current_break_seconds(self) -> int:
        total = self.total_break_seconds
        if self.on_break and self.break_started_at is not None:
            total += int((datetime.now() - self.break_started_at).total_seconds())
        return total

    def add_attendance_event(self, event: str, details: str = "") -> None:
        if self.current_shift_id is not None:
            self.app.attendance_store.add_event(self.current_shift_id, event.lower().replace(" ", "_"), event, details)
        self.refresh_all()

    def start_day(self) -> None:
        day = self.app.attendance_store.start_day(self._employee_username())
        if day["status"] == "closed":
            messagebox.showinfo("Day already ended", "Today's attendance day has already been ended.")
            self.refresh_all()
            return
        self.refresh_all()

    def end_day(self) -> None:
        self._sync_attendance_state()
        if not self.day_active:
            messagebox.showinfo("Day not started", "Please start the day first.")
            return
        if self.checked_in:
            messagebox.showwarning("Shift active", "Please check out or close the active shift before ending the day.")
            return
        ended = self.app.attendance_store.end_day(self._employee_username())
        if ended is None:
            messagebox.showinfo("Day not started", "Please start the day first.")
            return
        self.refresh_all()
        self.show_view("overview")

    def check_in(self) -> None:
        self._sync_attendance_state()
        if not self.day_active:
            messagebox.showwarning("Start day required", "Please click Start Day before checking in.")
            return
        if self.checked_in:
            messagebox.showinfo("Already checked in", "You are already checked in.")
            return
        shift = self.app.attendance_store.start_shift(self._employee_username())
        self.current_shift_id = int(shift["id"])
        self.refresh_all()

    def start_break(self) -> None:
        if not self._require_shift_active():
            return
        if self.on_break:
            messagebox.showinfo("Break active", "A break is already active.")
            return
        if self.current_shift_id is not None:
            self.app.attendance_store.start_break(self.current_shift_id)
        self.refresh_all()

    def end_break(self) -> None:
        if not self._require_shift_active():
            return
        if not self.on_break or self.break_started_at is None:
            messagebox.showinfo("No active break", "There is no active break to end.")
            return
        if self.current_shift_id is not None:
            self.app.attendance_store.end_break(self.current_shift_id)
        self.refresh_all()

    def close_first_shift(self) -> None:
        if not self._require_shift_active():
            return
        if self.current_shift_number != 1:
            messagebox.showinfo("First shift already closed", "The active shift is not the first shift.")
            return
        if self.on_break:
            messagebox.showwarning("Break active", "Please end the active break before closing the first shift.")
            return
        if self.current_shift_id is not None:
            self.app.attendance_store.close_shift(
                self.current_shift_id,
                "first_shift_close",
                "First Shift Closed",
                "First shift ended; night shift can be started later.",
            )
        self.refresh_all()
        self.show_view("overview")

    def check_out(self) -> None:
        if not self._require_shift_active():
            return
        if self.on_break:
            messagebox.showwarning("Break active", "Please end the active break before checking out.")
            return
        shift_label = self._shift_label()
        if self.current_shift_id is not None:
            self.app.attendance_store.close_shift(
                self.current_shift_id,
                "check_out",
                "Check Out",
                f"{shift_label} ended.",
            )
        self.refresh_all()
        if self.current_view in self.SHIFT_LOCKED_VIEWS:
            self.show_view("overview")

    def clear_sales_form(self) -> None:
        if not self._require_shift_active():
            return
        for key, variable in self.sales_vars.items():
            if key == "buying_amount":
                variable.set("0")
            elif key == "status":
                variable.set("Done")
            else:
                variable.set("")
        self.status_other_var.set("")
        self._update_status_other_visibility()

    def submit_sales_entry(self) -> None:
        if not self._require_shift_active():
            return
        entry = {key: variable.get().strip() for key, variable in self.sales_vars.items()}

        if not entry["customer"]:
            messagebox.showerror("Missing customer", "Customer Name is required.")
            return
        if not entry["item"]:
            messagebox.showerror("Missing item", "Items Sold is required.")
            return
        if not entry["buying_amount"]:
            entry["buying_amount"] = "0"
        if not entry["selling_amount"]:
            messagebox.showerror("Missing selling amount", "Selling Amount is required.")
            return
        for key, label in (("buying_amount", "Buying Amount"), ("selling_amount", "Selling Amount")):
            if not _amount_value_valid(entry[key]):
                messagebox.showerror("Invalid amount", f"{label} must be a number.")
                return
        resolved_status = self._resolved_status(entry["status"], self.status_other_var.get())
        if resolved_status is None:
            messagebox.showerror("Missing status reason", "Please write the reason for Other status.")
            return
        entry["status"] = resolved_status

        entry["date"] = self._sales_date()
        entry["time"] = now_label()
        saved = self.app.attendance_store.create_sales_entry(self._employee_username(), entry["date"], entry)
        daily_number = len(self.app.attendance_store.list_sales_entries(self._employee_username(), entry["date"]))
        self.last_saved_label.configure(text="Data added. Excel syncing...")
        self.clear_sales_form()
        self.refresh_all()
        self._queue_excel_sync(self._sales_entry_from_store_row(saved), "new", daily_number)

    def selected_entry(self) -> dict[str, str] | None:
        selection = self.today_tree.selection()
        if not selection:
            messagebox.showinfo("No selection", "Select an entry first.")
            return None
        entry_id = selection[0]
        for entry in self.sales_entries:
            if entry["id"] == entry_id:
                return entry
        messagebox.showerror("Missing entry", "Selected entry could not be found.")
        return None

    def edit_selected_entry(self) -> None:
        if not self._require_shift_active():
            return
        entry = self.selected_entry()
        if entry is None:
            return
        EditEntryWindow(self, entry)

    def retry_selected_excel_sync(self) -> None:
        entry = self.selected_entry()
        if entry is None:
            return
        if not self._entry_needs_excel_retry(entry):
            messagebox.showinfo("Excel sync", "This entry is already synced or currently syncing.")
            self._refresh_sync_retry_action()
            return

        display_number = self._sales_entry_display_number(entry)
        if self._queue_excel_sync(entry, "retry", display_number):
            self.last_saved_label.configure(text="Excel sync retry started...")
            self.refresh_all()


class EditEntryWindow(tk.Toplevel):
    def __init__(self, dashboard: DashboardPage, entry: dict[str, str]) -> None:
        super().__init__(dashboard)
        self.dashboard = dashboard
        self.entry = entry
        self.display_number = dashboard._sales_entry_display_number(entry)
        self.title(f"Edit Entry #{self.display_number}")
        self.geometry("760x560")
        self.minsize(720, 540)
        self.configure(bg=BG)
        self.transient(dashboard.app)
        self._set_window_icon()
        self.grab_set()
        self.vars: dict[str, tk.StringVar] = {}
        self.status_other_var = tk.StringVar()
        self.status_other_widgets: list[tk.Widget] = []
        self._build()
        self._center_on_parent()

    def _set_window_icon(self) -> None:
        logo = self.dashboard.app.get_logo((96, 96))
        if logo is not None:
            self.iconphoto(False, logo)

    def _build(self) -> None:
        panel = SurfaceCard(self, padx=24, pady=22, accent=True, accent_start=BLUE, accent_end=TEAL)
        panel.pack(fill="both", expand=True, padx=20, pady=20)
        body = panel.body
        body.grid_columnconfigure((0, 1), weight=1)

        tk.Label(body, text=f"Edit Entry #{self.display_number}", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 18)).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 18)
        )

        row = 1
        for index, (key, label, kind, values) in enumerate(SALES_FIELDS):
            column = index % 2
            if column == 0 and index > 0:
                row += 2
            self._field(body, key, label, row, column, kind, values)

        self._status_other_field(body, row + 2, 0)

        make_button(body, "Save Changes", self.save, "primary").grid(row=row + 4, column=0, sticky="ew", padx=(0, 8), pady=(8, 0))
        make_button(body, "Cancel", self.destroy, "light").grid(row=row + 4, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))

    def _field(
        self,
        parent: tk.Misc,
        key: str,
        label: str,
        row: int,
        column: int,
        kind: str,
        values: list[str] | None,
    ) -> None:
        value = self.entry.get(key, "")
        if key == "status" and values and value not in values:
            variable = tk.StringVar(value="Other")
            self.status_other_var.set(value)
        else:
            variable = tk.StringVar(value=value)
        self.vars[key] = variable
        padx = (0 if column == 0 else 12, 0)
        field_label(parent, label).grid(row=row, column=column, sticky="w", padx=padx)
        if kind == "combo" and values:
            widget = combo_box(parent, variable, values)
            widget.grid(row=row + 1, column=column, sticky="ew", ipady=6, padx=padx, pady=(8, 14))
            if key == "status":
                widget.bind("<<ComboboxSelected>>", lambda _event: self._update_status_other_visibility())
            return
        widget = text_entry(parent, variable)
        if key in {"buying_amount", "selling_amount"}:
            widget.configure(
                validate="key",
                validatecommand=(self.register(_amount_input_allowed), "%P"),
            )
        widget.grid(row=row + 1, column=column, sticky="ew", ipady=8, padx=padx, pady=(8, 14))

    def _center_on_parent(self) -> None:
        self.update_idletasks()
        parent = self.dashboard.app
        parent.update_idletasks()
        width = max(self.winfo_width(), 760)
        height = max(self.winfo_height(), 560)
        x_position = parent.winfo_rootx() + max((parent.winfo_width() - width) // 2, 0)
        y_position = parent.winfo_rooty() + max((parent.winfo_height() - height) // 2, 0)
        self.geometry(f"{width}x{height}+{x_position}+{y_position}")

    def _status_other_field(self, parent: tk.Misc, row: int, column: int) -> None:
        label = field_label(parent, "Other Status Reason")
        label.grid(row=row, column=column, columnspan=2, sticky="w")
        widget = text_entry(parent, self.status_other_var)
        widget.grid(row=row + 1, column=column, columnspan=2, sticky="ew", ipady=8, pady=(8, 14))
        self.status_other_widgets = [label, widget]
        self._update_status_other_visibility()

    def _update_status_other_visibility(self) -> None:
        show_other = self.vars.get("status") is not None and self.vars["status"].get() == "Other"
        for widget in self.status_other_widgets:
            if show_other:
                widget.grid()
            else:
                widget.grid_remove()

    def _resolved_status(self, selected_status: str, other_reason: str) -> str | None:
        if selected_status == "Other":
            status = other_reason.strip()
            return status or None
        return selected_status or "Done"

    def save(self) -> None:
        updates = {key: variable.get().strip() for key, variable in self.vars.items()}
        if not updates["customer"]:
            messagebox.showerror("Missing customer", "Customer Name is required.")
            return
        if not updates["item"]:
            messagebox.showerror("Missing item", "Items Sold is required.")
            return
        if not updates["buying_amount"]:
            updates["buying_amount"] = "0"
        if not updates["selling_amount"]:
            messagebox.showerror("Missing selling amount", "Selling Amount is required.")
            return
        for key, label in (("buying_amount", "Buying Amount"), ("selling_amount", "Selling Amount")):
            if not _amount_value_valid(updates[key]):
                messagebox.showerror("Invalid amount", f"{label} must be a number.")
                return
        resolved_status = self._resolved_status(updates["status"], self.status_other_var.get())
        if resolved_status is None:
            messagebox.showerror("Missing status reason", "Please write the reason for Other status.")
            return
        updates["status"] = resolved_status
        updated = self.dashboard.app.attendance_store.update_sales_entry(
            int(self.entry["id"]),
            self.dashboard._employee_username(),
            updates,
        )
        updated_entry = self.dashboard._sales_entry_from_store_row(updated)
        self.entry.update(updated_entry)
        self.dashboard._update_sales_entry_cache(updated)
        self.dashboard.last_saved_label.configure(
            text="Data updated. Excel syncing..."
        )
        self.dashboard.refresh_all()
        self.dashboard._queue_excel_sync(updated_entry, "edit", self.display_number)
        self.destroy()


class NotificationDropdown(tk.Frame):
    def __init__(self, parent: tk.Misc, dashboard: DashboardPage) -> None:
        super().__init__(
            parent,
            bg=WHITE,
            highlightbackground="#c7d8ee",
            highlightthickness=1,
            bd=0,
        )
        self.dashboard = dashboard
        self.announcements: list[dict] = []
        self._build()

    def _build(self) -> None:
        GradientBand(self, start=WARNING, end=TEAL, height=4).pack(fill="x")
        body = tk.Frame(self, bg=WHITE, padx=14, pady=12)
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(2, weight=1)

        header = tk.Frame(body, bg=WHITE)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        tk.Label(header, text="Notifications", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 16)).grid(row=0, column=0, sticky="w")
        self.summary_label = tk.Label(header, text="", bg=WHITE, fg=MUTED, font=(FONT, 9))
        self.summary_label.grid(row=1, column=0, sticky="w", pady=(4, 0))
        actions = tk.Frame(header, bg=WHITE)
        actions.grid(row=0, column=1, rowspan=2, sticky="e")
        self.mark_read_button = make_button(actions, "Mark All Read", self.mark_all_read, "light")
        self.mark_read_button.pack(side="left", padx=(0, 8))
        tk.Button(
            actions,
            text="X",
            command=self.hide,
            bg=WHITE,
            fg=MUTED,
            activebackground="#eff5ff",
            activeforeground=TEXT,
            relief="flat",
            bd=0,
            cursor="hand2",
            font=(FONT_BOLD, 10),
            padx=8,
            pady=5,
            highlightthickness=0,
        ).pack(side="left")

        tk.Frame(body, bg=LINE, height=1).grid(row=1, column=0, sticky="ew", pady=14)

        self.scroll_canvas = tk.Canvas(
            body,
            bg="#fbfdff",
            highlightthickness=1,
            highlightbackground=LINE,
        )
        self.scroll_canvas.grid(row=2, column=0, sticky="nsew")
        self.scrollbar = ttk.Scrollbar(body, orient="vertical", command=self.scroll_canvas.yview)
        self.scrollbar.grid(row=2, column=1, sticky="ns")
        self.scroll_canvas.configure(yscrollcommand=self.scrollbar.set)

        self.notification_container = tk.Frame(self.scroll_canvas, bg="#fbfdff", padx=12, pady=12)
        self.notification_window = self.scroll_canvas.create_window(
            (0, 0),
            window=self.notification_container,
            anchor="nw",
        )
        self.notification_container.bind("<Configure>", self._on_notifications_configure)
        self.scroll_canvas.bind("<Configure>", self._on_canvas_configure)
        self.scroll_canvas.bind("<Enter>", self._bind_mousewheel)
        self.scroll_canvas.bind("<Leave>", self._unbind_mousewheel)

        footer = tk.Label(
            body,
            text="Visible for 3 days from the time they are sent.",
            bg=WHITE,
            fg=MUTED,
            font=(FONT, 9),
        )
        footer.grid(row=3, column=0, sticky="w", pady=(12, 0))

    def refresh(self) -> None:
        self.announcements = self.dashboard.app.attendance_store.list_employee_announcements(
            self.dashboard._employee_username(),
            limit=20,
        )
        unread = sum(1 for item in self.announcements if not item["is_read"])
        self.summary_label.configure(text=f"{unread} unread | {len(self.announcements)} active")
        set_button_enabled(self.mark_read_button, bool(self.announcements))
        for child in self.notification_container.winfo_children():
            child.destroy()
        if not self.announcements:
            empty = tk.Label(
                self.notification_container,
                text="No active notifications.",
                bg="#fbfdff",
                fg=MUTED,
                font=(FONT, 10),
            )
            empty.pack(anchor="w", pady=10)
            self.scroll_canvas.yview_moveto(0)
            return
        for announcement in self.announcements:
            self._add_notification_bubble(announcement)
        self._on_notifications_configure()
        self.scroll_canvas.yview_moveto(0)

    def _add_notification_bubble(self, announcement: dict) -> None:
        unread = not announcement["is_read"]
        bubble_bg = "#eef6ff" if unread else WHITE
        border = BLUE if unread else LINE
        bubble = tk.Frame(
            self.notification_container,
            bg=bubble_bg,
            padx=14,
            pady=12,
            highlightbackground=border,
            highlightthickness=1,
        )
        bubble.pack(fill="x", pady=(0, 10))
        bubble.grid_columnconfigure(0, weight=1)

        meta = tk.Frame(bubble, bg=bubble_bg)
        meta.grid(row=0, column=0, sticky="ew")
        meta.grid_columnconfigure(2, weight=1)

        status_dot = tk.Canvas(meta, width=12, height=12, bg=bubble_bg, bd=0, highlightthickness=0)
        dot_color = BLUE if unread else "#b8c7dc"
        status_dot.create_oval(2, 2, 10, 10, fill=dot_color, outline="")
        status_dot.grid(row=0, column=0, sticky="w", padx=(0, 7))

        category = tk.Label(
            meta,
            text=announcement["category"],
            bg=BLUE if unread else "#eaf2ff",
            fg=WHITE if unread else BLUE,
            font=(FONT_BOLD, 8),
            padx=9,
            pady=3,
        )
        category.grid(row=0, column=1, sticky="w")

        created = self.dashboard._format_event_time(announcement["created_at"])
        status = "Unread" if unread else "Read"
        tk.Label(
            meta,
            text=f"{status} | {created}",
            bg=bubble_bg,
            fg=MUTED,
            font=(FONT, 8),
        ).grid(row=0, column=2, sticky="e")

        tk.Label(
            bubble,
            text=announcement["title"],
            bg=bubble_bg,
            fg=TEXT,
            font=(FONT_BOLD, 12),
            wraplength=360,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(10, 4))

        tk.Label(
            bubble,
            text=announcement["message"],
            bg=bubble_bg,
            fg=TEXT,
            font=(FONT, 10),
            wraplength=370,
            justify="left",
        ).grid(row=2, column=0, sticky="w")

    def _on_notifications_configure(self, _event: tk.Event | None = None) -> None:
        self.scroll_canvas.configure(scrollregion=self.scroll_canvas.bbox("all") or (0, 0, 0, 0))

    def _on_canvas_configure(self, event: tk.Event) -> None:
        self.scroll_canvas.itemconfigure(self.notification_window, width=max(event.width - 4, 1))
        self._on_notifications_configure()

    def _bind_mousewheel(self, _event: tk.Event) -> None:
        self.scroll_canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _unbind_mousewheel(self, _event: tk.Event | None = None) -> None:
        self.scroll_canvas.unbind_all("<MouseWheel>")

    def _on_mousewheel(self, event: tk.Event) -> str:
        bbox = self.scroll_canvas.bbox("all")
        if bbox is None:
            self.scroll_canvas.yview_moveto(0)
            return "break"
        content_height = bbox[3] - bbox[1]
        visible_height = max(self.scroll_canvas.winfo_height(), 1)
        if content_height <= visible_height:
            self.scroll_canvas.yview_moveto(0)
            return "break"
        top, bottom = self.scroll_canvas.yview()
        direction = -1 if event.delta > 0 else 1
        if direction < 0 and top <= 0:
            self.scroll_canvas.yview_moveto(0)
            return "break"
        if direction > 0 and bottom >= 1:
            self.scroll_canvas.yview_moveto(max(0, 1 - (visible_height / content_height)))
            return "break"
        self.scroll_canvas.yview_scroll(direction, "units")
        return "break"

    def hide(self) -> None:
        self._unbind_mousewheel()
        self.place_forget()

    def mark_all_read(self) -> None:
        ids = [int(item["id"]) for item in self.announcements]
        self.dashboard.app.attendance_store.mark_announcements_read(self.dashboard._employee_username(), ids)
        self.refresh()
        self.dashboard._refresh_notification_badge()
