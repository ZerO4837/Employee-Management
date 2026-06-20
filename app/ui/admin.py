from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
import os
from pathlib import Path
import queue
import shutil
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from app.config import (
    BG,
    BLUE,
    BLUE_DARK,
    FONT,
    FONT_BOLD,
    LINE,
    MANAGED_SALES_WORKBOOK_PATH,
    MUTED,
    NAVY,
    SALES_SERVICE_NAMES,
    SUCCESS,
    TEAL,
    TEXT,
    WARNING,
    WHITE,
)
from app.excel_sales import ExcelSyncResult
from app.ui.widgets import MetricCard, SurfaceCard, make_button, set_button_enabled, show_app_alert, status_pill
from app.utils import duration_label, money_label, today_label


class AdminPage(tk.Frame):
    def __init__(self, parent: tk.Misc, app) -> None:
        super().__init__(parent, bg=BG)
        self.app = app
        self.selected_shift_id: int | None = None
        self.announcement_category_var = tk.StringVar(value="General")
        self.announcement_title_var = tk.StringVar()
        self.template_service_var = tk.StringVar(value="Capcut Private Monthly")
        self.template_other_service_var = tk.StringVar()
        self.template_other_service_widgets: list[tk.Widget] = []
        self.admin_message_templates: list[dict] = []
        self.selected_template_id: int | None = None
        self.editing_template_id: int | None = None
        self.template_form_title_label: tk.Label | None = None
        self.template_form_status_label: tk.Label | None = None
        self.template_save_button: tk.Button | None = None
        self.excel_path_var = tk.StringVar()
        self.excel_sheet_var = tk.StringVar()
        self.sales_period_var = tk.StringVar(value="Last 5 Days")
        self.admin_sales_entries: list[dict] = []
        self.admin_excel_sync_results: queue.Queue[tuple[dict, ExcelSyncResult]] = queue.Queue()
        self.admin_excel_sync_pending_entry_ids: set[str] = set()
        self.admin_retry_button: tk.Button | None = None
        self._build()
        self.after(250, self._poll_admin_excel_sync_results)

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_header()

        self.notebook = ttk.Notebook(self)
        self.notebook.grid(row=1, column=0, sticky="nsew", padx=18, pady=18)

        attendance_tab = tk.Frame(self.notebook, bg=BG, padx=0, pady=0)
        announcements_tab = tk.Frame(self.notebook, bg=BG, padx=0, pady=0)
        messages_tab = tk.Frame(self.notebook, bg=BG, padx=0, pady=0)
        sales_data_tab = tk.Frame(self.notebook, bg=BG, padx=0, pady=0)
        workbook_tab = tk.Frame(self.notebook, bg=BG, padx=0, pady=0)
        self.notebook.add(attendance_tab, text="Attendance")
        self.notebook.add(announcements_tab, text="Announcements")
        self.notebook.add(messages_tab, text="Service Messages")
        self.notebook.add(sales_data_tab, text="Sales Data")
        self.notebook.add(workbook_tab, text="Sales Workbook")

        self._build_attendance_tab(attendance_tab)
        self._build_announcements_tab(announcements_tab)
        self._build_message_templates_tab(messages_tab)
        self._build_sales_data_tab(sales_data_tab)
        self._build_sales_workbook_tab(workbook_tab)

    def _build_header(self) -> None:
        header = SurfaceCard(self, padx=22, pady=18, accent=True, accent_start=NAVY, accent_end=BLUE)
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(18, 0))
        body = header.body
        body.grid_columnconfigure(0, weight=1)

        tk.Label(body, text="Owner Console", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 20)).grid(
            row=0, column=0, sticky="w"
        )
        self.last_refresh_label = tk.Label(body, text="", bg=WHITE, fg=MUTED, font=(FONT, 10))
        self.last_refresh_label.grid(row=1, column=0, sticky="w", pady=(5, 0))

        self.today_pill = status_pill(body, today_label(), fg=BLUE_DARK, bg="#eef6ff")
        self.today_pill.grid(row=0, column=1, rowspan=2, sticky="e", padx=(12, 10))
        make_button(body, "Refresh", self.refresh_all, "primary").grid(row=0, column=2, rowspan=2, padx=(0, 10))
        make_button(body, "Logout", self.app.logout, "light").grid(row=0, column=3, rowspan=2)

    def _build_attendance_tab(self, parent: tk.Frame) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)

        metrics = tk.Frame(parent, bg=BG)
        metrics.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        metrics.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="admin_metrics")
        self.total_shifts_card = MetricCard(metrics, "Total Shifts", "0", BLUE, "All saved shifts")
        self.total_shifts_card.grid(row=0, column=0, sticky="ew", padx=(0, 9))
        self.active_shift_card = MetricCard(metrics, "Active Shifts", "0", SUCCESS, "Currently checked in")
        self.active_shift_card.grid(row=0, column=1, sticky="ew", padx=3)
        self.breaks_card = MetricCard(metrics, "Breaks Logged", "0", WARNING, "Across visible shifts")
        self.breaks_card.grid(row=0, column=2, sticky="ew", padx=3)
        self.break_time_card = MetricCard(metrics, "Break Time", "0m", TEAL, "Recorded break duration")
        self.break_time_card.grid(row=0, column=3, sticky="ew", padx=(9, 0))

        tables = tk.Frame(parent, bg=BG)
        tables.grid(row=1, column=0, sticky="nsew")
        tables.grid_columnconfigure(0, weight=4)
        tables.grid_columnconfigure(1, weight=2)
        tables.grid_rowconfigure(0, weight=1)

        self._build_shift_table(tables)
        self._build_event_table(tables)

    def _build_shift_table(self, parent: tk.Frame) -> None:
        shifts_card = SurfaceCard(parent, padx=18, pady=16, accent=True, accent_start=BLUE, accent_end=TEAL)
        shifts_card.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        shifts = shifts_card.body
        shifts.grid_columnconfigure(0, weight=1)
        shifts.grid_rowconfigure(2, weight=1)

        header = tk.Frame(shifts, bg=WHITE)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        header.grid_columnconfigure(0, weight=1)
        tk.Label(header, text="Attendance Sheet", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 16)).grid(
            row=0, column=0, sticky="w"
        )
        self.shift_count_label = tk.Label(header, text="", bg=WHITE, fg=MUTED, font=(FONT, 9))
        self.shift_count_label.grid(row=1, column=0, sticky="w", pady=(4, 0))
        status_pill(header, "Local Records", fg=BLUE_DARK, bg="#eef6ff").grid(row=0, column=1, rowspan=2, sticky="e")

        columns = ("id", "date", "employee", "shift", "status", "check_in", "check_out", "breaks", "break_time")
        self.shifts_tree = ttk.Treeview(shifts, columns=columns, show="headings", selectmode="browse")
        headings = {
            "id": "ID",
            "date": "Date",
            "employee": "Employee",
            "shift": "Shift",
            "status": "Status",
            "check_in": "Check In",
            "check_out": "Check Out",
            "breaks": "Breaks",
            "break_time": "Break Time",
        }
        widths = {
            "id": 60,
            "date": 112,
            "employee": 130,
            "shift": 120,
            "status": 100,
            "check_in": 115,
            "check_out": 115,
            "breaks": 80,
            "break_time": 120,
        }
        for column in columns:
            self.shifts_tree.heading(column, text=headings[column])
            self.shifts_tree.column(column, width=widths[column], minwidth=widths[column], anchor="w", stretch=False)
        self.shifts_tree.tag_configure("active", background="#eafaf4", foreground=TEXT)
        self.shifts_tree.tag_configure("closed_even", background=WHITE, foreground=TEXT)
        self.shifts_tree.tag_configure("closed_odd", background="#f8fbff", foreground=TEXT)
        self.shifts_tree.grid(row=2, column=0, sticky="nsew")
        self.shifts_tree.bind("<<TreeviewSelect>>", self._on_shift_selected)

        y_scroll = ttk.Scrollbar(shifts, orient="vertical", command=self.shifts_tree.yview)
        y_scroll.grid(row=2, column=1, sticky="ns")
        x_scroll = ttk.Scrollbar(shifts, orient="horizontal", command=self.shifts_tree.xview)
        x_scroll.grid(row=3, column=0, sticky="ew")
        self.shifts_tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

    def _build_event_table(self, parent: tk.Frame) -> None:
        events_card = SurfaceCard(parent, padx=18, pady=16, accent=True, accent_start=TEAL, accent_end=BLUE)
        events_card.grid(row=0, column=1, sticky="nsew")
        events = events_card.body
        events.grid_columnconfigure(0, weight=1)
        events.grid_rowconfigure(2, weight=1)

        header = tk.Frame(events, bg=WHITE)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        header.grid_columnconfigure(0, weight=1)
        tk.Label(header, text="Shift Timeline", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 16)).grid(
            row=0, column=0, sticky="w"
        )
        self.timeline_context_label = tk.Label(
            header,
            text="Showing all recorded shift events",
            bg=WHITE,
            fg=MUTED,
            font=(FONT, 9),
        )
        self.timeline_context_label.grid(row=1, column=0, sticky="w", pady=(4, 0))

        self.events_tree = ttk.Treeview(events, columns=("date", "time", "shift", "event", "details"), show="headings")
        self.events_tree.heading("date", text="Date")
        self.events_tree.heading("time", text="Time")
        self.events_tree.heading("shift", text="Shift")
        self.events_tree.heading("event", text="Event")
        self.events_tree.heading("details", text="Details")
        self.events_tree.column("date", width=104, minwidth=104, anchor="w", stretch=False)
        self.events_tree.column("time", width=98, minwidth=98, anchor="w", stretch=False)
        self.events_tree.column("shift", width=96, minwidth=96, anchor="w", stretch=False)
        self.events_tree.column("event", width=145, minwidth=145, anchor="w", stretch=False)
        self.events_tree.column("details", width=300, minwidth=220, anchor="w", stretch=True)
        self.events_tree.tag_configure("check_in", background="#eafaf4", foreground=TEXT)
        self.events_tree.tag_configure("break", background="#fff8ea", foreground=TEXT)
        self.events_tree.tag_configure("close", background="#eef6ff", foreground=TEXT)
        self.events_tree.tag_configure("default_even", background=WHITE, foreground=TEXT)
        self.events_tree.tag_configure("default_odd", background="#f8fbff", foreground=TEXT)
        self.events_tree.grid(row=2, column=0, sticky="nsew")

        y_scroll = ttk.Scrollbar(events, orient="vertical", command=self.events_tree.yview)
        y_scroll.grid(row=2, column=1, sticky="ns")
        x_scroll = ttk.Scrollbar(events, orient="horizontal", command=self.events_tree.xview)
        x_scroll.grid(row=3, column=0, sticky="ew")
        self.events_tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

    def _build_announcements_tab(self, parent: tk.Frame) -> None:
        parent.grid_columnconfigure(0, weight=3)
        parent.grid_columnconfigure(1, weight=2)
        parent.grid_rowconfigure(0, weight=1)

        compose_card = SurfaceCard(parent, padx=22, pady=20, accent=True, accent_start=WARNING, accent_end=TEAL)
        compose_card.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        compose = compose_card.body
        compose.grid_columnconfigure(0, weight=1)
        tk.Label(compose, text="Send Announcement", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 18)).grid(
            row=0, column=0, sticky="w", pady=(0, 16)
        )
        tk.Label(compose, text="Category", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 10)).grid(row=1, column=0, sticky="w")
        ttk.Combobox(
            compose,
            values=["General", "Service Available", "Out of Stock", "Urgent", "Reminder"],
            textvariable=self.announcement_category_var,
            state="readonly",
            font=(FONT, 10),
        ).grid(row=2, column=0, sticky="ew", ipady=6, pady=(8, 14))

        tk.Label(compose, text="Title", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 10)).grid(row=3, column=0, sticky="w")
        tk.Entry(
            compose,
            textvariable=self.announcement_title_var,
            bg="#f8fbff",
            fg=TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=LINE,
            highlightcolor=BLUE,
            font=(FONT, 11),
        ).grid(row=4, column=0, sticky="ew", ipady=8, pady=(8, 14))

        tk.Label(compose, text="Message", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 10)).grid(row=5, column=0, sticky="w")
        self.announcement_message_text = tk.Text(
            compose,
            height=8,
            bg="#f8fbff",
            fg=TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=LINE,
            highlightcolor=BLUE,
            font=(FONT, 10),
            wrap="word",
        )
        self.announcement_message_text.grid(row=6, column=0, sticky="nsew", pady=(8, 16))
        compose.grid_rowconfigure(6, weight=1)
        make_button(compose, "Send Announcement", self.send_announcement, "primary").grid(row=7, column=0, sticky="ew")

        recent_card = SurfaceCard(parent, padx=18, pady=16, accent=True, accent_start=BLUE, accent_end=TEAL)
        recent_card.grid(row=0, column=1, sticky="nsew")
        recent = recent_card.body
        recent.grid_columnconfigure(0, weight=1)
        recent.grid_rowconfigure(1, weight=1)
        tk.Label(recent, text="Recent Announcements", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 16)).grid(
            row=0, column=0, sticky="w", pady=(0, 12)
        )
        self.announcements_tree = ttk.Treeview(recent, columns=("time", "category", "title"), show="headings")
        self.announcements_tree.heading("time", text="Time")
        self.announcements_tree.heading("category", text="Category")
        self.announcements_tree.heading("title", text="Title")
        self.announcements_tree.column("time", width=96, anchor="w", stretch=False)
        self.announcements_tree.column("category", width=130, anchor="w", stretch=False)
        self.announcements_tree.column("title", width=260, anchor="w", stretch=True)
        self.announcements_tree.grid(row=1, column=0, sticky="nsew")
        ann_scroll = ttk.Scrollbar(recent, orient="vertical", command=self.announcements_tree.yview)
        ann_scroll.grid(row=1, column=1, sticky="ns")
        self.announcements_tree.configure(yscrollcommand=ann_scroll.set)

    def _build_message_templates_tab(self, parent: tk.Frame) -> None:
        parent.grid_columnconfigure(0, weight=3)
        parent.grid_columnconfigure(1, weight=2)
        parent.grid_rowconfigure(0, weight=1)

        compose_card = SurfaceCard(parent, padx=22, pady=20, accent=True, accent_start=BLUE, accent_end=TEAL)
        compose_card.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        compose = compose_card.body
        compose.grid_columnconfigure(0, weight=1)
        self.template_form_title_label = tk.Label(
            compose,
            text="Add Service Message",
            bg=WHITE,
            fg=TEXT,
            font=(FONT_BOLD, 18),
        )
        self.template_form_title_label.grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )
        self.template_form_status_label = tk.Label(
            compose,
            text="Emoji, line breaks, links, and spacing are kept exactly as typed.",
            bg=WHITE,
            fg=MUTED,
            font=(FONT, 10),
        )
        self.template_form_status_label.grid(row=1, column=0, sticky="w", pady=(0, 16))

        tk.Label(compose, text="Service", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 10)).grid(row=2, column=0, sticky="w")
        service_combo = ttk.Combobox(
            compose,
            values=["General", *SALES_SERVICE_NAMES],
            textvariable=self.template_service_var,
            state="readonly",
            font=(FONT, 10),
        )
        service_combo.grid(row=3, column=0, sticky="ew", ipady=6, pady=(8, 14))
        service_combo.bind("<<ComboboxSelected>>", lambda _event: self._update_template_other_service_visibility())

        self._template_other_service_field(compose, 4, 0)

        tk.Label(compose, text="Message Format", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 10)).grid(
            row=6, column=0, sticky="w"
        )
        self.template_message_text = tk.Text(
            compose,
            height=12,
            bg="#f8fbff",
            fg=TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=LINE,
            highlightcolor=BLUE,
            font=(FONT, 10),
            wrap="word",
            undo=True,
        )
        self.template_message_text.grid(row=7, column=0, sticky="nsew", pady=(8, 16))
        compose.grid_rowconfigure(7, weight=1)

        actions = tk.Frame(compose, bg=WHITE)
        actions.grid(row=8, column=0, sticky="ew")
        actions.grid_columnconfigure((0, 1), weight=1)
        self.template_save_button = make_button(actions, "Save Service Message", self.save_message_template, "primary")
        self.template_save_button.grid(
            row=0, column=0, sticky="ew", padx=(0, 8)
        )
        make_button(actions, "Clear Form", self.clear_message_template_form, "light").grid(
            row=0, column=1, sticky="ew", padx=(8, 0)
        )

        active_card = SurfaceCard(parent, padx=18, pady=16, accent=True, accent_start=SUCCESS, accent_end=TEAL)
        active_card.grid(row=0, column=1, sticky="nsew")
        active = active_card.body
        active.grid_columnconfigure(0, weight=1)
        active.grid_rowconfigure(1, weight=3)
        active.grid_rowconfigure(3, weight=2)
        tk.Label(active, text="Active Service Messages", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 16)).grid(
            row=0, column=0, sticky="w", pady=(0, 12)
        )
        self.templates_tree = ttk.Treeview(active, columns=("service", "updated"), show="headings")
        self.templates_tree.heading("service", text="Service")
        self.templates_tree.heading("updated", text="Updated")
        self.templates_tree.column("service", width=280, anchor="w", stretch=True)
        self.templates_tree.column("updated", width=115, anchor="w", stretch=False)
        self.templates_tree.tag_configure("template_even", background=WHITE, foreground=TEXT)
        self.templates_tree.tag_configure("template_odd", background="#f8fbff", foreground=TEXT)
        self.templates_tree.grid(row=1, column=0, sticky="nsew")
        self.templates_tree.bind("<<TreeviewSelect>>", self._on_template_selected)
        template_scroll = ttk.Scrollbar(active, orient="vertical", command=self.templates_tree.yview)
        template_scroll.grid(row=1, column=1, sticky="ns")
        self.templates_tree.configure(yscrollcommand=template_scroll.set)

        tk.Label(active, text="Selected Preview", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 12)).grid(
            row=2, column=0, sticky="w", pady=(16, 8)
        )
        self.template_preview_text = tk.Text(
            active,
            height=7,
            bg="#fbfdff",
            fg=TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=LINE,
            font=(FONT, 10),
            wrap="word",
        )
        self.template_preview_text.grid(row=3, column=0, sticky="nsew")
        self.template_preview_text.configure(state="disabled")
        preview_scroll = ttk.Scrollbar(active, orient="vertical", command=self.template_preview_text.yview)
        preview_scroll.grid(row=3, column=1, sticky="ns")
        self.template_preview_text.configure(yscrollcommand=preview_scroll.set)

        active_actions = tk.Frame(active, bg=WHITE)
        active_actions.grid(row=4, column=0, sticky="ew", pady=(14, 0))
        active_actions.grid_columnconfigure((0, 1), weight=1)
        make_button(active_actions, "Edit Selected", self.edit_selected_message_template, "primary").grid(
            row=0, column=0, sticky="ew", padx=(0, 8)
        )
        make_button(active_actions, "Deactivate Selected", self.deactivate_selected_message_template, "warning").grid(
            row=0, column=1, sticky="ew", padx=(8, 0)
        )

    def _template_other_service_field(self, parent: tk.Misc, row: int, column: int) -> None:
        label = tk.Label(parent, text="Other Service Name", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 10))
        label.grid(row=row, column=column, sticky="w")
        widget = tk.Entry(
            parent,
            textvariable=self.template_other_service_var,
            bg="#f8fbff",
            fg=TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=LINE,
            highlightcolor=BLUE,
            font=(FONT, 11),
        )
        widget.grid(row=row + 1, column=column, sticky="ew", ipady=8, pady=(8, 14))
        self.template_other_service_widgets = [label, widget]
        self._update_template_other_service_visibility()

    def _update_template_other_service_visibility(self) -> None:
        show_other = self.template_service_var.get() == "Other"
        for widget in self.template_other_service_widgets:
            if show_other:
                widget.grid()
            else:
                widget.grid_remove()

    def _resolved_template_service(self) -> str | None:
        selected_service = self.template_service_var.get().strip()
        if selected_service == "Other":
            service_name = self.template_other_service_var.get().strip()
            return service_name or None
        return selected_service or None

    def _refresh_template_form_state(self) -> None:
        editing = self.editing_template_id is not None
        if self.template_form_title_label is not None:
            self.template_form_title_label.configure(
                text="Edit Service Message" if editing else "Add Service Message"
            )
        if self.template_form_status_label is not None:
            if editing:
                self.template_form_status_label.configure(
                    text="Editing selected service message. Emoji, line breaks, links, and spacing stay intact.",
                    fg=BLUE,
                )
            else:
                self.template_form_status_label.configure(
                    text="Emoji, line breaks, links, and spacing are kept exactly as typed.",
                    fg=MUTED,
                )
        if self.template_save_button is not None:
            self.template_save_button.configure(text="Save Changes" if editing else "Save Service Message")

    def _build_sales_data_tab(self, parent: tk.Frame) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)

        metrics = tk.Frame(parent, bg=BG)
        metrics.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        metrics.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="sales_data_metrics")
        self.sales_entries_card = MetricCard(metrics, "Sales Entries", "0", BLUE, "Last 5 days")
        self.sales_entries_card.grid(row=0, column=0, sticky="ew", padx=(0, 9))
        self.sales_total_card = MetricCard(metrics, "Total Selling", "0", SUCCESS, "Visible entries")
        self.sales_total_card.grid(row=0, column=1, sticky="ew", padx=3)
        self.sales_profit_card = MetricCard(metrics, "Total Profit", "0", TEAL, "Visible entries")
        self.sales_profit_card.grid(row=0, column=2, sticky="ew", padx=3)
        self.sales_retry_card = MetricCard(metrics, "Needs Sync", "0", WARNING, "Excel retry needed")
        self.sales_retry_card.grid(row=0, column=3, sticky="ew", padx=(9, 0))

        table_card = SurfaceCard(parent, padx=18, pady=16, accent=True, accent_start=BLUE, accent_end=SUCCESS)
        table_card.grid(row=1, column=0, sticky="nsew")
        table = table_card.body
        table.grid_columnconfigure(0, weight=1)
        table.grid_rowconfigure(2, weight=1)

        header = tk.Frame(table, bg=WHITE)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        header.grid_columnconfigure(0, weight=1)
        tk.Label(header, text="Employee Sales Data", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 16)).grid(
            row=0, column=0, sticky="w"
        )
        self.sales_data_summary_label = tk.Label(header, text="", bg=WHITE, fg=MUTED, font=(FONT, 9))
        self.sales_data_summary_label.grid(row=1, column=0, sticky="w", pady=(4, 0))

        controls = tk.Frame(header, bg=WHITE)
        controls.grid(row=0, column=1, rowspan=2, sticky="e")
        tk.Label(controls, text="Period", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 9)).pack(side="left", padx=(0, 8))
        self.sales_period_combo = ttk.Combobox(
            controls,
            values=[],
            textvariable=self.sales_period_var,
            state="readonly",
            width=18,
            font=(FONT, 10),
        )
        self.sales_period_combo.pack(side="left", padx=(0, 10), ipady=3)
        self.sales_period_combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh_sales_data())
        self.admin_retry_button = make_button(controls, "Retry Selected Sync", self.retry_selected_admin_sales_sync, "warning")
        self.admin_retry_button.pack(side="left", padx=(0, 10))
        make_button(controls, "Refresh", self.refresh_all, "light").pack(side="left")

        columns = (
            "date",
            "time",
            "employee",
            "customer",
            "service",
            "order",
            "buying",
            "selling",
            "profit",
            "status",
            "sync",
        )
        self.sales_data_tree = ttk.Treeview(table, columns=columns, show="headings", selectmode="browse")
        headings = {
            "date": "Date",
            "time": "Time",
            "employee": "Employee",
            "customer": "Client Name",
            "service": "Service",
            "order": "Email / Order ID",
            "buying": "Buying",
            "selling": "Selling",
            "profit": "Profit",
            "status": "Status",
            "sync": "Excel Sync",
        }
        widths = {
            "date": 110,
            "time": 96,
            "employee": 125,
            "customer": 210,
            "service": 245,
            "order": 245,
            "buying": 88,
            "selling": 88,
            "profit": 88,
            "status": 130,
            "sync": 120,
        }
        for column in columns:
            self.sales_data_tree.heading(column, text=headings[column])
            self.sales_data_tree.column(
                column,
                width=widths[column],
                minwidth=widths[column],
                anchor="w",
                stretch=column in {"customer", "service", "order"},
            )
        self.sales_data_tree.tag_configure("sales_even", background=WHITE, foreground=TEXT)
        self.sales_data_tree.tag_configure("sales_odd", background="#f8fbff", foreground=TEXT)
        self.sales_data_tree.tag_configure("sales_synced", background="#eafaf4", foreground=TEXT)
        self.sales_data_tree.tag_configure("sales_pending", background="#eef6ff", foreground=TEXT)
        self.sales_data_tree.tag_configure("sales_retry", background="#fff8ea", foreground=TEXT)
        self.sales_data_tree.grid(row=2, column=0, sticky="nsew")
        self.sales_data_tree.bind("<<TreeviewSelect>>", lambda _event: self._refresh_admin_retry_action())

        y_scroll = ttk.Scrollbar(table, orient="vertical", command=self.sales_data_tree.yview)
        y_scroll.grid(row=2, column=1, sticky="ns")
        x_scroll = ttk.Scrollbar(table, orient="horizontal", command=self.sales_data_tree.xview)
        x_scroll.grid(row=3, column=0, sticky="ew")
        self.sales_data_tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

    def _build_sales_workbook_tab(self, parent: tk.Frame) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)

        settings = SurfaceCard(parent, padx=22, pady=20, accent=True, accent_start=SUCCESS, accent_end=TEAL)
        settings.grid(row=0, column=0, sticky="ew")
        body = settings.body
        body.grid_columnconfigure(1, weight=1)
        tk.Label(body, text="Sales Excel Workbook", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 18)).grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 16)
        )
        tk.Label(body, text="Workbook", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 10)).grid(row=1, column=0, sticky="w")
        tk.Entry(
            body,
            textvariable=self.excel_path_var,
            bg="#f8fbff",
            fg=TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=LINE,
            highlightcolor=BLUE,
            font=(FONT, 10),
        ).grid(row=2, column=0, columnspan=4, sticky="ew", ipady=8, pady=(8, 14))

        make_button(body, "Browse", self.browse_excel_workbook, "light").grid(row=3, column=0, sticky="ew", padx=(0, 8))
        make_button(body, "Upload Workbook", self.upload_excel_workbook, "light").grid(
            row=3, column=1, sticky="ew", padx=8
        )
        tk.Label(body, text="Worksheet", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 10)).grid(
            row=4, column=0, sticky="w", pady=(16, 0)
        )
        tk.Entry(
            body,
            textvariable=self.excel_sheet_var,
            bg="#f8fbff",
            fg=TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=LINE,
            highlightcolor=BLUE,
            font=(FONT, 10),
        ).grid(row=5, column=0, columnspan=2, sticky="ew", ipady=8, pady=(8, 0), padx=(0, 8))
        make_button(body, "Save Target", self.save_excel_settings, "primary").grid(
            row=5, column=2, columnspan=2, sticky="ew", ipady=1, pady=(8, 0)
        )

        status_card = SurfaceCard(parent, padx=22, pady=20, accent=True, accent_start=BLUE, accent_end=TEAL)
        status_card.grid(row=1, column=0, sticky="nsew", pady=(14, 0))
        status = status_card.body
        status.grid_columnconfigure(0, weight=1)
        tk.Label(status, text="Active Target", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 16)).grid(
            row=0, column=0, sticky="w"
        )
        self.excel_status_label = tk.Label(
            status,
            text="",
            bg=WHITE,
            fg=MUTED,
            font=(FONT, 10),
            anchor="nw",
            justify="left",
            wraplength=820,
        )
        self.excel_status_label.grid(row=1, column=0, sticky="ew", pady=(10, 0))

    def refresh_all(self) -> None:
        self.today_pill.configure(text=today_label())
        self.last_refresh_label.configure(text=f"Last refreshed {datetime.now().strftime('%I:%M %p')}")
        self._refresh_excel_settings()
        shifts = self.app.attendance_store.list_shift_summaries()
        self._refresh_metrics(shifts)
        self._refresh_shift_table(shifts)
        self._refresh_event_table(self.selected_shift_id)
        self._refresh_announcements()
        self._refresh_message_templates()
        self._refresh_sales_data()

    def send_announcement(self) -> None:
        title = self.announcement_title_var.get().strip()
        message = self.announcement_message_text.get("1.0", tk.END).strip()
        if not title:
            show_app_alert(self, "Missing title", "Please add an announcement title before sending.", "warning")
            return
        if not message:
            show_app_alert(self, "Missing message", "Please add a short message for the employee.", "warning")
            return
        self.app.attendance_store.create_announcement(
            self.announcement_category_var.get(),
            title,
            message,
            self.app.display_user,
        )
        self.announcement_title_var.set("")
        self.announcement_message_text.delete("1.0", tk.END)
        self.refresh_all()
        show_app_alert(
            self,
            "Notification has been sent",
            "The employee can now see it in the notification dropdown.",
            "success",
        )

    def save_message_template(self) -> None:
        service_name = self._resolved_template_service()
        message = self.template_message_text.get("1.0", tk.END).strip()
        if not service_name:
            show_app_alert(self, "Missing service", "Please add the service name before saving.", "warning")
            return
        if not message:
            show_app_alert(self, "Missing message", "Please write the message format before saving.", "warning")
            return
        if self.editing_template_id is None:
            saved = self.app.attendance_store.create_service_message_template(
                service_name,
                message,
                self.app.display_user,
            )
            success_title = "Service message saved"
        else:
            saved = self.app.attendance_store.update_service_message_template(
                self.editing_template_id,
                service_name,
                message,
            )
            success_title = "Service message updated"
        self.selected_template_id = int(saved["id"])
        self.clear_message_template_form()
        self.refresh_all()
        show_app_alert(
            self,
            success_title,
            "The employee can now open Client Messages and copy this format.",
            "success",
        )

    def clear_message_template_form(self) -> None:
        self.editing_template_id = None
        self.template_service_var.set("Capcut Private Monthly")
        self.template_other_service_var.set("")
        self.template_message_text.delete("1.0", tk.END)
        self._update_template_other_service_visibility()
        self._refresh_template_form_state()

    def edit_selected_message_template(self) -> None:
        selection = self.templates_tree.selection()
        if not selection:
            show_app_alert(self, "No service selected", "Select a service message first.", "warning")
            return
        template_id = int(selection[0])
        template = self._template_by_id(template_id)
        if template is None:
            show_app_alert(self, "Missing service message", "The selected service message could not be found.", "warning")
            return
        self.editing_template_id = template_id
        service_name = template["service_name"]
        if service_name in {"General", *SALES_SERVICE_NAMES}:
            self.template_service_var.set(service_name)
            self.template_other_service_var.set("")
        else:
            self.template_service_var.set("Other")
            self.template_other_service_var.set(service_name)
        self.template_message_text.delete("1.0", tk.END)
        self.template_message_text.insert("1.0", template["message"])
        self._update_template_other_service_visibility()
        self._refresh_template_form_state()

    def deactivate_selected_message_template(self) -> None:
        selection = self.templates_tree.selection()
        if not selection:
            show_app_alert(self, "No service selected", "Select a service message first.", "warning")
            return
        template_id = int(selection[0])
        template = self._template_by_id(template_id)
        service_name = template["service_name"] if template else "this service message"
        if not messagebox.askyesno(
            "Deactivate service message",
            f"Deactivate '{service_name}' so employees no longer see it?",
            parent=self,
        ):
            return
        self.app.attendance_store.deactivate_service_message_template(template_id)
        self.selected_template_id = None
        if self.editing_template_id == template_id:
            self.clear_message_template_form()
        self.refresh_all()
        show_app_alert(self, "Service message deactivated", "Employees will no longer see this message format.", "success")

    def browse_excel_workbook(self) -> None:
        selected = filedialog.askopenfilename(
            parent=self,
            title="Select sales workbook",
            filetypes=(("Excel workbooks", "*.xlsx *.xlsm"), ("All files", "*.*")),
        )
        if selected:
            self.excel_path_var.set(selected)

    def upload_excel_workbook(self) -> None:
        selected = filedialog.askopenfilename(
            parent=self,
            title="Upload sales workbook",
            filetypes=(("Excel workbooks", "*.xlsx *.xlsm"), ("All files", "*.*")),
        )
        if not selected:
            return
        source = Path(selected)
        if source.suffix.lower() not in {".xlsx", ".xlsm"}:
            show_app_alert(self, "Invalid workbook", "Please select an .xlsx or .xlsm workbook.", "warning")
            return
        target = MANAGED_SALES_WORKBOOK_PATH.with_suffix(source.suffix.lower())
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            if source.resolve() != target.resolve():
                shutil.copy2(source, target)
        except OSError as exc:
            show_app_alert(self, "Upload failed", str(exc), "danger")
            return
        self.excel_path_var.set(str(target))
        self.save_excel_settings(success_title="Workbook uploaded")

    def save_excel_settings(self, success_title: str = "Workbook target saved") -> None:
        workbook_path = self.excel_path_var.get().strip()
        worksheet_name = self.excel_sheet_var.get().strip()
        if not workbook_path:
            show_app_alert(self, "Missing workbook", "Please select or upload an Excel workbook.", "warning")
            return
        if workbook_path.lower().startswith(("http://", "https://")):
            if not workbook_path.lower().startswith("https://d.docs.live.net/"):
                show_app_alert(
                    self,
                    "Use a direct OneDrive file URL",
                    "Use the d.docs.live.net workbook URL or select a local .xlsx/.xlsm file.",
                    "warning",
                )
                return
            if not workbook_path.lower().endswith((".xlsx", ".xlsm")):
                show_app_alert(self, "Invalid workbook", "The cloud workbook URL must end with .xlsx or .xlsm.", "warning")
                return
            saved_path = workbook_path
        else:
            path = Path(os.path.expandvars(workbook_path)).expanduser()
            if path.suffix.lower() not in {".xlsx", ".xlsm"}:
                show_app_alert(self, "Invalid workbook", "The workbook target must be an .xlsx or .xlsm file.", "warning")
                return
            if not path.exists() and not path.parent.exists():
                show_app_alert(self, "Folder not found", "The workbook folder does not exist.", "warning")
                return
            saved_path = str(path)
        self.app.save_sales_workbook_settings(saved_path, worksheet_name)
        self._refresh_excel_settings()
        show_app_alert(self, success_title, "Future sales entries will use this workbook target.", "success")

    def _refresh_excel_settings(self) -> None:
        workbook = self.app.sales_workbook
        self.excel_path_var.set(workbook.display_path)
        self.excel_sheet_var.set(workbook.worksheet_name)
        if workbook.display_path.lower().startswith(("http://", "https://")):
            file_state = "cloud workbook URL"
        else:
            path = Path(workbook.display_path)
            file_state = "file found" if path.exists() else "file will be created"
        sheet_state = workbook.worksheet_name or "active sheet"
        self.excel_status_label.configure(
            text=f"Workbook: {workbook.display_path}\nWorksheet: {sheet_state}\nStatus: {file_state}"
        )

    def _refresh_announcements(self) -> None:
        for item in self.announcements_tree.get_children():
            self.announcements_tree.delete(item)
        announcements = self.app.attendance_store.list_announcements(limit=40)
        for announcement in announcements:
            self.announcements_tree.insert(
                "",
                "end",
                values=(
                    self._format_time(announcement["created_at"]),
                    announcement["category"],
                    announcement["title"],
                ),
            )

    def _refresh_message_templates(self) -> None:
        for item in self.templates_tree.get_children():
            self.templates_tree.delete(item)
        self.admin_message_templates = self.app.attendance_store.list_service_message_templates(limit=200)
        valid_ids: set[int] = set()
        first_id: int | None = None
        for index, template in enumerate(self.admin_message_templates):
            template_id = int(template["id"])
            valid_ids.add(template_id)
            if first_id is None:
                first_id = template_id
            tag = "template_even" if index % 2 == 0 else "template_odd"
            self.templates_tree.insert(
                "",
                "end",
                iid=str(template_id),
                tags=(tag,),
                values=(
                    template["service_name"],
                    self._format_datetime(template["updated_at"]),
                ),
            )
        if self.selected_template_id in valid_ids:
            self.templates_tree.selection_set(str(self.selected_template_id))
            self.templates_tree.focus(str(self.selected_template_id))
            self._set_template_preview(self._template_by_id(self.selected_template_id))
            return
        self.selected_template_id = first_id
        if first_id is not None:
            self.templates_tree.selection_set(str(first_id))
            self.templates_tree.focus(str(first_id))
            self._set_template_preview(self._template_by_id(first_id))
            return
        self._set_template_preview(None)

    def _refresh_sales_data(self) -> None:
        self.app.attendance_store.delete_blocked_sales_entries()
        self._refresh_sales_period_values()
        start_date, end_date, period_label = self._selected_sales_period_range()
        entries = self.app.attendance_store.list_sales_entries_between(start_date, end_date)
        self.admin_sales_entries = entries
        total_selling = sum(self._sales_money_value(entry.get("selling_amount", "")) for entry in entries)
        total_profit = sum(self._sales_money_value(entry.get("profit", "")) for entry in entries)
        retry_count = sum(1 for entry in entries if self._admin_entry_needs_excel_retry(entry))

        self.sales_entries_card.value_label.configure(text=str(len(entries)))
        self.sales_total_card.value_label.configure(text=money_label(str(total_selling)))
        self.sales_profit_card.value_label.configure(text=money_label(str(total_profit)))
        self.sales_retry_card.value_label.configure(text=str(retry_count))
        self.sales_data_summary_label.configure(
            text=f"{period_label} | {self._sales_window_label(start_date, end_date)} | {len(entries)} entries"
        )

        for item in self.sales_data_tree.get_children():
            self.sales_data_tree.delete(item)
        for index, entry in enumerate(entries):
            sync_label = self._sales_sync_label(entry)
            tag = self._sales_sync_tag(sync_label, index)
            self.sales_data_tree.insert(
                "",
                "end",
                iid=str(entry["id"]),
                tags=(tag,),
                values=(
                    self._format_date(entry.get("entry_date", "")),
                    entry.get("entry_time", ""),
                    entry.get("employee_username", ""),
                    entry.get("customer", ""),
                    entry.get("item", ""),
                    entry.get("order_id", ""),
                    money_label(str(entry.get("buying_amount", ""))),
                    money_label(str(entry.get("selling_amount", ""))),
                    money_label(str(entry.get("profit", ""))),
                    entry.get("status", ""),
                    sync_label,
                ),
            )
        self._refresh_admin_retry_action()

    def _refresh_sales_period_values(self) -> None:
        options = self._sales_period_options()
        self.sales_period_combo.configure(values=options)
        if self.sales_period_var.get() not in options:
            self.sales_period_var.set(options[0])

    def _sales_period_options(self) -> list[str]:
        today = date.today()
        month_options = [f"{calendar.month_name[month]} Sales" for month in range(1, today.month + 1)]
        return ["Last 5 Days", *month_options]

    def _selected_sales_period_range(self) -> tuple[str, str, str]:
        selection = self.sales_period_var.get()
        if selection == "Last 5 Days":
            start_date, end_date = self._sales_visible_date_range()
            return start_date, end_date, "Last 5 Days"

        today = date.today()
        month_name = selection.replace(" Sales", "")
        month_number = next(
            (month for month in range(1, 13) if calendar.month_name[month] == month_name),
            today.month,
        )
        start = date(today.year, month_number, 1)
        last_day = calendar.monthrange(today.year, month_number)[1]
        end = date(today.year, month_number, last_day)
        if month_number == today.month:
            end = today
        return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), f"{month_name} {today.year} Sales"

    def _sales_visible_date_range(self) -> tuple[str, str]:
        today = datetime.now().date()
        start = today - timedelta(days=4)
        return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")

    def _sales_window_label(self, start_date: str, end_date: str) -> str:
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d").strftime("%d %b")
            end = datetime.strptime(end_date, "%Y-%m-%d").strftime("%d %b %Y")
            return f"{start} - {end}"
        except ValueError:
            return f"{start_date} - {end_date}"

    def _sales_money_value(self, value: object) -> float:
        try:
            return float(str(value or "0").replace(",", ""))
        except ValueError:
            return 0.0

    def _is_blocked_excel_sync_message(self, message: object) -> bool:
        return "account is full" in str(message or "").lower()

    def _is_blocked_excel_sync_result(self, sync_result: ExcelSyncResult) -> bool:
        return bool(getattr(sync_result, "blocked", False)) or self._is_blocked_excel_sync_message(sync_result.message)

    def _sales_sync_label(self, entry: dict) -> str:
        if str(entry.get("id", "")) in self.admin_excel_sync_pending_entry_ids:
            return "Syncing"
        if entry.get("excel_synced_at"):
            return "Synced"
        error = str(entry.get("excel_sync_error", "")).strip()
        if self._is_blocked_excel_sync_message(error):
            return "Not saved"
        if not error:
            return "Saved locally"
        return "Retry needed"

    def _sales_sync_tag(self, sync_label: str, index: int) -> str:
        if sync_label == "Synced":
            return "sales_synced"
        if sync_label == "Syncing":
            return "sales_pending"
        if sync_label in {"Retry needed", "Not saved"}:
            return "sales_retry"
        return "sales_even" if index % 2 == 0 else "sales_odd"

    def _selected_admin_sales_entry(self) -> dict | None:
        selection = self.sales_data_tree.selection()
        if not selection:
            return None
        entry_id = selection[0]
        for entry in self.admin_sales_entries:
            if str(entry.get("id", "")) == entry_id:
                return entry
        return None

    def _admin_entry_needs_excel_retry(self, entry: dict | None) -> bool:
        if entry is None:
            return False
        if str(entry.get("id", "")) in self.admin_excel_sync_pending_entry_ids:
            return False
        if entry.get("excel_synced_at"):
            return False
        if self._is_blocked_excel_sync_message(entry.get("excel_sync_error", "")):
            return False
        return bool(entry.get("excel_sync_error"))

    def _refresh_admin_retry_action(self) -> None:
        if self.admin_retry_button is None:
            return
        set_button_enabled(self.admin_retry_button, self._admin_entry_needs_excel_retry(self._selected_admin_sales_entry()))

    def retry_selected_admin_sales_sync(self) -> None:
        entry = self._selected_admin_sales_entry()
        if entry is None:
            show_app_alert(self, "No sale selected", "Select a sales row first.", "warning")
            return
        if not self._admin_entry_needs_excel_retry(entry):
            show_app_alert(self, "Excel sync", "This sale is already synced or cannot be retried.", "info")
            self._refresh_admin_retry_action()
            return

        entry_id = str(entry["id"])
        employee_username = str(entry.get("employee_username", ""))
        if not employee_username:
            show_app_alert(self, "Missing employee", "This sale is missing the employee username.", "warning")
            return
        self.admin_excel_sync_pending_entry_ids.add(entry_id)
        pending = self.app.attendance_store.mark_sales_excel_error(
            int(entry["id"]),
            employee_username,
            "Excel sync pending in background.",
        )
        self._refresh_sales_data()
        worker = threading.Thread(
            target=self._run_admin_excel_sync_worker,
            args=(dict(pending),),
            daemon=True,
        )
        worker.start()

    def _run_admin_excel_sync_worker(self, entry: dict) -> None:
        try:
            sync_result = self.app.sales_workbook.sync_entry(entry)
        except Exception as exc:
            sync_result = ExcelSyncResult(False, message=str(exc))
        self.admin_excel_sync_results.put((entry, sync_result))

    def _poll_admin_excel_sync_results(self) -> None:
        while True:
            try:
                entry, sync_result = self.admin_excel_sync_results.get_nowait()
            except queue.Empty:
                break
            self._finish_admin_excel_sync(entry, sync_result)
        self.after(250, self._poll_admin_excel_sync_results)

    def _finish_admin_excel_sync(self, entry: dict, sync_result: ExcelSyncResult) -> None:
        entry_id = str(entry.get("id", ""))
        employee_username = str(entry.get("employee_username", ""))
        self.admin_excel_sync_pending_entry_ids.discard(entry_id)
        try:
            if sync_result.saved and sync_result.row is not None:
                self.app.attendance_store.mark_sales_excel_sync(int(entry["id"]), employee_username, sync_result.row)
                show_app_alert(self, "Excel synced", "Selected sales entry was synced with Excel.", "success")
            else:
                message = sync_result.message or "Excel sync failed."
                if self._is_blocked_excel_sync_result(sync_result):
                    self.app.attendance_store.delete_sales_entry(int(entry["id"]), employee_username)
                    show_app_alert(self, "Account full", f"{message}\n\nThe local retry row was removed.", "warning")
                else:
                    self.app.attendance_store.mark_sales_excel_error(int(entry["id"]), employee_username, message)
                    show_app_alert(self, "Excel sync failed", message, "warning")
        finally:
            self._refresh_sales_data()

    def _on_template_selected(self, _event: tk.Event) -> None:
        selection = self.templates_tree.selection()
        self.selected_template_id = int(selection[0]) if selection else None
        self._set_template_preview(self._template_by_id(self.selected_template_id))

    def _template_by_id(self, template_id: int | None) -> dict | None:
        if template_id is None:
            return None
        for template in self.admin_message_templates:
            if int(template["id"]) == template_id:
                return template
        return None

    def _set_template_preview(self, template: dict | None) -> None:
        self.template_preview_text.configure(state="normal")
        self.template_preview_text.delete("1.0", tk.END)
        if template is None:
            self.template_preview_text.insert("1.0", "No active service messages yet.")
        else:
            self.template_preview_text.insert("1.0", template["message"])
        self.template_preview_text.configure(state="disabled")

    def _refresh_metrics(self, shifts: list[dict]) -> None:
        active_count = sum(1 for shift in shifts if shift["status"] == "active")
        breaks = sum(int(shift["break_count"]) for shift in shifts)
        break_seconds = sum(self._break_seconds(shift) for shift in shifts)
        self.total_shifts_card.value_label.configure(text=str(len(shifts)))
        self.active_shift_card.value_label.configure(text=str(active_count))
        self.breaks_card.value_label.configure(text=str(breaks))
        self.break_time_card.value_label.configure(text=duration_label(break_seconds))

    def _refresh_shift_table(self, shifts: list[dict]) -> None:
        for item in self.shifts_tree.get_children():
            self.shifts_tree.delete(item)
        self.shift_count_label.configure(text=f"{len(shifts)} shift records saved locally")
        valid_ids = set()
        for index, shift in enumerate(shifts):
            shift_id = str(shift["id"])
            valid_ids.add(shift_id)
            tag = "active" if shift["status"] == "active" else ("closed_even" if index % 2 == 0 else "closed_odd")
            self.shifts_tree.insert(
                "",
                "end",
                iid=shift_id,
                tags=(tag,),
                values=(
                    shift["id"],
                    shift["shift_date"],
                    shift["employee_username"],
                    self._shift_label(int(shift["shift_number"])),
                    shift["status"].title(),
                    self._format_time(shift["started_at"]),
                    self._format_time(shift["ended_at"]),
                    shift["break_count"],
                    duration_label(self._break_seconds(shift)),
                ),
            )
        if self.selected_shift_id is not None and str(self.selected_shift_id) not in valid_ids:
            self.selected_shift_id = None

    def _refresh_event_table(self, shift_id: int | None) -> None:
        for item in self.events_tree.get_children():
            self.events_tree.delete(item)
        events = self.app.attendance_store.list_events(shift_id=shift_id, limit=500)
        if shift_id is None:
            events = list(reversed(events))
            self.timeline_context_label.configure(text="Showing all recorded shift events")
        else:
            self.timeline_context_label.configure(text=f"Showing detailed events for shift #{shift_id}")
        for index, event in enumerate(events):
            tag = self._event_tag(event["event_type"], index)
            self.events_tree.insert(
                "",
                "end",
                tags=(tag,),
                values=(
                    event["shift_date"],
                    self._format_time(event["event_time"]),
                    self._shift_label(int(event["shift_number"])),
                    event["event_label"],
                    event["details"],
                ),
            )

    def _on_shift_selected(self, _event: tk.Event) -> None:
        selection = self.shifts_tree.selection()
        self.selected_shift_id = int(selection[0]) if selection else None
        self._refresh_event_table(self.selected_shift_id)

    def _shift_label(self, number: int) -> str:
        if number == 0:
            return "Day"
        if number == 1:
            return "First Shift"
        if number == 2:
            return "Night Shift"
        return f"Shift {number}"

    def _format_time(self, value: str | None) -> str:
        if not value:
            return "-"
        try:
            return datetime.fromisoformat(value).strftime("%I:%M %p")
        except ValueError:
            return value

    def _format_date(self, value: str | None) -> str:
        if not value:
            return "-"
        try:
            return datetime.strptime(value, "%Y-%m-%d").strftime("%d %b %Y")
        except ValueError:
            return value

    def _format_datetime(self, value: str | None) -> str:
        if not value:
            return "-"
        try:
            return datetime.fromisoformat(value).strftime("%d %b, %I:%M %p")
        except ValueError:
            return value

    def _break_seconds(self, shift: dict) -> int:
        total = int(shift["total_break_seconds"])
        if shift["current_break_started_at"]:
            try:
                total += int((datetime.now() - datetime.fromisoformat(shift["current_break_started_at"])).total_seconds())
            except ValueError:
                pass
        return max(total, 0)

    def _event_tag(self, event_type: str, index: int) -> str:
        if event_type == "check_in":
            return "check_in"
        if event_type in {"break_start", "break_end"}:
            return "break"
        if event_type in {"first_shift_close", "check_out", "day_start", "day_end"}:
            return "close"
        return "default_even" if index % 2 == 0 else "default_odd"
