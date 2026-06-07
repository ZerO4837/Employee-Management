from __future__ import annotations

from datetime import datetime
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
from app.utils import duration_label, money_label, now_label, today_label


class DashboardPage(tk.Frame):
    SHIFT_LOCKED_VIEWS = {"sales", "today"}

    def __init__(self, parent: tk.Misc, app) -> None:
        super().__init__(parent, bg=BG)
        self.app = app
        self.current_view = ""
        self.nav_buttons: dict[str, tk.Button] = {}
        self.views: dict[str, tk.Frame] = {}
        self.sales_vars: dict[str, tk.StringVar] = {}
        self.sales_entries: list[dict[str, str]] = []
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
        self._build()
        self._tick_clock()

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
            ("today", "Today's Data"),
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
        shell.grid(row=0, column=1, sticky="nsew")
        shell.grid_rowconfigure(1, weight=1)
        shell.grid_columnconfigure(0, weight=1)

        topbar = SurfaceCard(shell, padx=28, pady=18, accent=True, accent_start=BLUE, accent_end=TEAL)
        topbar.grid(row=0, column=0, sticky="ew", padx=18, pady=(18, 0))
        top = topbar.body
        top.grid_columnconfigure(0, weight=1)
        tk.Label(top, text="Employee Workspace", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 19)).grid(
            row=0, column=0, sticky="w"
        )
        self.user_label = tk.Label(top, text="", bg=WHITE, fg=MUTED, font=(FONT, 10))
        self.user_label.grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.clock_label = tk.Label(top, text="", bg="#eef6ff", fg=NAVY, font=(FONT_BOLD, 11), padx=14, pady=7)
        self.clock_label.grid(row=0, column=1, rowspan=2, sticky="e")

        self.content = tk.Frame(shell, bg=BG, padx=18, pady=18)
        self.content.grid(row=1, column=0, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

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
            text="Check in first to unlock sales, break, and today-data controls.",
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
        tk.Label(form, text="Only today's entries are visible to the employee.", bg=WHITE, fg=MUTED, font=(FONT, 10)).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(0, 18)
        )

        row = 2
        for index, (key, label, kind, values) in enumerate(SALES_FIELDS):
            column = index % 2
            if column == 0 and index > 0:
                row += 2
            self._sales_field(form, key, label, row, column, kind, values)

        tk.Label(form, text="Notes", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 10)).grid(
            row=row + 2, column=0, columnspan=2, sticky="w", pady=(8, 0)
        )
        self.notes_text = tk.Text(
            form,
            height=5,
            bg="#f8fbff",
            fg=TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=LINE,
            highlightcolor=BLUE,
            font=(FONT, 10),
            wrap="word",
        )
        self.notes_text.grid(row=row + 3, column=0, columnspan=2, sticky="ew", pady=(8, 16))
        self.sales_input_widgets.append(self.notes_text)

        self.submit_sales_button = make_button(form, "Save Entry", self.submit_sales_entry, "primary")
        self.submit_sales_button.grid(row=row + 4, column=0, sticky="ew", padx=(0, 8))
        self.shift_required_buttons.append(self.submit_sales_button)

        clear_form_button = make_button(form, "Clear Form", self.clear_sales_form, "light")
        clear_form_button.grid(row=row + 4, column=1, sticky="ew", padx=(8, 0))
        self.shift_required_buttons.append(clear_form_button)

        side_card = SurfaceCard(view, padx=20, pady=20, accent=True, accent_start=SUCCESS, accent_end=TEAL)
        side_card.grid(row=0, column=1, sticky="nsew")
        side = side_card.body
        side.grid_columnconfigure(0, weight=1)
        tk.Label(side, text="Today", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 18)).grid(row=0, column=0, sticky="w")
        self.sales_today_count = tk.Label(side, text="0 entries", bg=WHITE, fg=BLUE, font=(FONT_BOLD, 28))
        self.sales_today_count.grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.sales_today_amount = tk.Label(side, text="Rs. 0", bg=WHITE, fg=SUCCESS, font=(FONT_BOLD, 16))
        self.sales_today_amount.grid(row=2, column=0, sticky="w", pady=(6, 28))

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
        open_today_button = make_button(side, "Open Today's Data", lambda: self.show_view("today"), "light")
        open_today_button.grid(row=7, column=0, sticky="ew", pady=(18, 0))
        self.shift_required_buttons.append(open_today_button)
        return view

    def _build_today_view(self) -> tk.Frame:
        view = tk.Frame(self.content, bg=BG)
        view.grid_rowconfigure(1, weight=1)
        view.grid_columnconfigure(0, weight=1)

        summary = SurfaceCard(view, padx=20, pady=16, accent=True, accent_start=BLUE, accent_end=TEAL)
        summary.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        body = summary.body
        body.grid_columnconfigure(0, weight=1)
        tk.Label(body, text="Today's Data", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 18)).grid(row=0, column=0, sticky="w")
        self.today_summary_label = tk.Label(body, text="", bg=WHITE, fg=MUTED, font=(FONT, 10))
        self.today_summary_label.grid(row=1, column=0, sticky="w", pady=(6, 0))
        today_add_button = make_button(body, "Add New Entry", lambda: self.show_view("sales"), "primary")
        today_add_button.grid(row=0, column=1, rowspan=2, sticky="e", padx=(18, 0))
        self.shift_required_buttons.append(today_add_button)

        table_card = SurfaceCard(view, padx=20, pady=18, accent=True, accent_start=TEAL, accent_end=BLUE)
        table_card.grid(row=1, column=0, sticky="nsew")
        body = table_card.body
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=1)

        columns = ("id", "time", "customer", "source", "item", "qty", "amount", "payment", "status")
        self.today_tree = ttk.Treeview(body, columns=columns, show="headings", selectmode="browse")
        headings = {
            "id": "ID",
            "time": "Time",
            "customer": "Customer",
            "source": "Source",
            "item": "Item / Service",
            "qty": "Qty",
            "amount": "Amount",
            "payment": "Payment",
            "status": "Status",
        }
        widths = {
            "id": 54,
            "time": 92,
            "customer": 150,
            "source": 100,
            "item": 190,
            "qty": 60,
            "amount": 92,
            "payment": 120,
            "status": 110,
        }
        for column in columns:
            self.today_tree.heading(column, text=headings[column])
            self.today_tree.column(column, width=widths[column], anchor="w")
        self.today_tree.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(body, orient="vertical", command=self.today_tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.today_tree.configure(yscrollcommand=scrollbar.set)

        actions = tk.Frame(body, bg=WHITE)
        actions.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        edit_selected_button = make_button(actions, "Edit Selected", self.edit_selected_entry, "primary")
        edit_selected_button.pack(side="left", padx=(0, 10))
        self.shift_required_buttons.append(edit_selected_button)

        remove_selected_button = make_button(actions, "Remove Selected", self.delete_selected_entry, "danger")
        remove_selected_button.pack(side="left")
        self.shift_required_buttons.append(remove_selected_button)
        return view

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
        if key == "quantity":
            variable.set("1")
        if values:
            variable.set(values[0])
        self.sales_vars[key] = variable
        padx = (0 if column == 0 else 12, 0)
        field_label(parent, label).grid(row=row, column=column, sticky="w", padx=padx)
        if kind == "combo" and values:
            widget = combo_box(parent, variable, values)
            widget.grid(row=row + 1, column=column, sticky="ew", ipady=6, padx=padx, pady=(8, 14))
            self.sales_input_widgets.append(widget)
            return
        widget = text_entry(parent, variable)
        widget.grid(row=row + 1, column=column, sticky="ew", ipady=8, padx=padx, pady=(8, 14))
        self.sales_input_widgets.append(widget)

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
            self.access_notice.configure(text="Sales, breaks, and today-data controls are unlocked.", fg=SUCCESS)
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
        self.user_label.configure(text=f"Signed in as {self.app.display_user}")
        self.welcome_banner.set_text(
            f"Welcome, {self.app.display_user}",
            f"{self._day_label()} | {self._shift_label()} status is tracked with breaks and sold-item entries.",
        )
        self._refresh_stats()
        self._refresh_attendance_log()
        self._refresh_today_table()
        self._refresh_recent_activity()

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
        self.entries_card.value_label.configure(text=str(len(self.sales_entries)))
        self.break_card.value_label.configure(text=duration_label(self.current_break_seconds()))

        self.attendance_status.configure(text=shift_status, fg=accent)
        if self.shift_started_at:
            self.shift_time_label.configure(text=f"{self._shift_label()} started: {self.shift_started_at.strftime('%I:%M %p')}")
        else:
            self.shift_time_label.configure(text="Shift started: -")
        self.break_time_label.configure(text=f"Break time: {duration_label(self.current_break_seconds())}")
        self.attendance_date_label.configure(text=today_label())

        total = 0.0
        for entry in self.sales_entries:
            try:
                total += float(entry.get("amount", "0") or 0)
            except ValueError:
                pass
        self.sales_today_count.configure(text=f"{len(self.sales_entries)} entries")
        self.sales_today_amount.configure(text=f"Rs. {money_label(str(total))}")
        self.today_summary_label.configure(text=f"{today_label()} | {len(self.sales_entries)} entries | Rs. {money_label(str(total))}")
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
        for entry in self.sales_entries:
            self.today_tree.insert(
                "",
                "end",
                iid=str(entry["id"]),
                values=(
                    entry["id"],
                    entry["time"],
                    entry["customer"],
                    entry["platform"],
                    entry["item"],
                    entry["quantity"],
                    money_label(entry["amount"]),
                    entry["payment"],
                    entry["status"],
                ),
            )

    def _refresh_recent_activity(self) -> None:
        self.recent_list.delete(0, tk.END)
        items: list[str] = []
        for entry in self.sales_entries[-5:]:
            items.append(f"{entry['time']} - Sale #{entry['id']}: {entry['item']} ({entry['quantity']})")
        for event in self.attendance_events[-5:]:
            items.append(f"{self._format_event_time(event['event_time'])} - {event['event_label']}")
        if not items:
            self.recent_list.insert(tk.END, "No activity yet today.")
            return
        for item in items[-8:][::-1]:
            self.recent_list.insert(tk.END, item)

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
            if key == "quantity":
                variable.set("1")
            elif key == "platform":
                variable.set("WhatsApp")
            elif key == "payment":
                variable.set("Cash")
            elif key == "status":
                variable.set("Completed")
            else:
                variable.set("")
        self.notes_text.delete("1.0", tk.END)

    def submit_sales_entry(self) -> None:
        if not self._require_shift_active():
            return
        entry = {key: variable.get().strip() for key, variable in self.sales_vars.items()}
        entry["notes"] = self.notes_text.get("1.0", tk.END).strip()

        if not entry["item"]:
            messagebox.showerror("Missing item", "Item / Service is required.")
            return
        try:
            quantity = int(entry["quantity"])
            if quantity <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid quantity", "Quantity must be a whole number greater than zero.")
            return
        if entry["amount"]:
            try:
                float(entry["amount"])
            except ValueError:
                messagebox.showerror("Invalid amount", "Sale Amount must be a number.")
                return

        entry["id"] = str(self.next_sales_id)
        entry["date"] = datetime.now().strftime("%Y-%m-%d")
        entry["time"] = now_label()
        self.next_sales_id += 1
        self.sales_entries.append(entry)
        self.last_saved_label.configure(text=f"#{entry['id']} {entry['item']} saved at {entry['time']}")
        self.clear_sales_form()
        self.refresh_all()
        messagebox.showinfo("Entry saved", "Sold item entry saved for today.")

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

    def delete_selected_entry(self) -> None:
        if not self._require_shift_active():
            return
        entry = self.selected_entry()
        if entry is None:
            return
        if not messagebox.askyesno("Remove entry", f"Remove entry #{entry['id']} from today's data?"):
            return
        self.sales_entries = [item for item in self.sales_entries if item["id"] != entry["id"]]
        self.refresh_all()


class EditEntryWindow(tk.Toplevel):
    def __init__(self, dashboard: DashboardPage, entry: dict[str, str]) -> None:
        super().__init__(dashboard)
        self.dashboard = dashboard
        self.entry = entry
        self.title(f"Edit Entry #{entry['id']}")
        self.geometry("640x580")
        self.minsize(580, 540)
        self.configure(bg=BG)
        self.transient(dashboard.app)
        self.grab_set()
        self.vars: dict[str, tk.StringVar] = {}
        self._build()

    def _build(self) -> None:
        panel = SurfaceCard(self, padx=24, pady=22, accent=True, accent_start=BLUE, accent_end=TEAL)
        panel.pack(fill="both", expand=True, padx=20, pady=20)
        body = panel.body
        body.grid_columnconfigure((0, 1), weight=1)

        tk.Label(body, text=f"Edit Entry #{self.entry['id']}", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 18)).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 18)
        )

        row = 1
        for index, (key, label, kind, values) in enumerate(SALES_FIELDS):
            column = index % 2
            if column == 0 and index > 0:
                row += 2
            self._field(body, key, label, row, column, kind, values)

        tk.Label(body, text="Notes", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 10)).grid(
            row=row + 2, column=0, columnspan=2, sticky="w", pady=(8, 0)
        )
        self.notes_text = tk.Text(
            body,
            height=5,
            bg="#f8fbff",
            fg=TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=LINE,
            highlightcolor=BLUE,
            font=(FONT, 10),
            wrap="word",
        )
        self.notes_text.insert("1.0", self.entry.get("notes", ""))
        self.notes_text.grid(row=row + 3, column=0, columnspan=2, sticky="ew", pady=(8, 16))

        make_button(body, "Save Changes", self.save, "primary").grid(row=row + 4, column=0, sticky="ew", padx=(0, 8))
        make_button(body, "Cancel", self.destroy, "light").grid(row=row + 4, column=1, sticky="ew", padx=(8, 0))

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
        variable = tk.StringVar(value=self.entry.get(key, ""))
        self.vars[key] = variable
        padx = (0 if column == 0 else 12, 0)
        field_label(parent, label).grid(row=row, column=column, sticky="w", padx=padx)
        if kind == "combo" and values:
            widget = combo_box(parent, variable, values)
            widget.grid(row=row + 1, column=column, sticky="ew", ipady=6, padx=padx, pady=(8, 14))
            return
        widget = text_entry(parent, variable)
        widget.grid(row=row + 1, column=column, sticky="ew", ipady=8, padx=padx, pady=(8, 14))

    def save(self) -> None:
        updates = {key: variable.get().strip() for key, variable in self.vars.items()}
        updates["notes"] = self.notes_text.get("1.0", tk.END).strip()
        if not updates["item"]:
            messagebox.showerror("Missing item", "Item / Service is required.")
            return
        try:
            quantity = int(updates["quantity"])
            if quantity <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid quantity", "Quantity must be a whole number greater than zero.")
            return
        if updates["amount"]:
            try:
                float(updates["amount"])
            except ValueError:
                messagebox.showerror("Invalid amount", "Sale Amount must be a number.")
                return
        self.entry.update(updates)
        self.dashboard.last_saved_label.configure(text=f"#{self.entry['id']} updated at {now_label()}")
        self.dashboard.refresh_all()
        self.destroy()
