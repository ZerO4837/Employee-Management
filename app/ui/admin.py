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

from app.cloud_sync import SupabaseConfig
from app.config import (
    BG,
    BLUE,
    BLUE_DARK,
    DANGER,
    FONT,
    FONT_BOLD,
    LINE,
    MANAGED_SALES_WORKBOOK_PATH,
    MUTED,
    NAVY,
    SUCCESS,
    TEAL,
    TEXT,
    WARNING,
    WHITE,
)
from app.excel_sales import ExcelSyncResult
from app.ui.widgets import (
    MetricCard,
    SurfaceCard,
    fill_with_scrollable_region,
    make_button,
    set_button_enabled,
    show_app_alert,
    status_pill,
)
from app.utils import duration_label, money_label, parse_local_datetime, today_label


class AdminPage(tk.Frame):
    def __init__(self, parent: tk.Misc, app) -> None:
        super().__init__(parent, bg=BG)
        self.app = app
        self.selected_shift_id: int | None = None
        self.announcement_category_var = tk.StringVar(value="General")
        self.announcement_title_var = tk.StringVar()
        self.employee_name_var = tk.StringVar()
        self.employee_username_var = tk.StringVar()
        self.employee_password_var = tk.StringVar()
        self.admin_current_password_var = tk.StringVar()
        self.admin_new_password_var = tk.StringVar()
        self.admin_confirm_password_var = tk.StringVar()
        self.employee_active_var = tk.BooleanVar(value=True)
        self.selected_employee_username: str | None = None
        self.employee_active_status_label: tk.Label | None = None
        self.employee_password_status_label: tk.Label | None = None
        self.employee_form_title_label: tk.Label | None = None
        self.employee_form_hint_label: tk.Label | None = None
        self.employee_count_label: tk.Label | None = None
        self.employee_name_entry: tk.Entry | None = None
        self.employee_save_button: tk.Button | None = None
        self.admin_password_status_label: tk.Label | None = None
        self.template_service_var = tk.StringVar(value="Capcut Private Monthly")
        self.template_other_service_var = tk.StringVar()
        self.template_other_service_widgets: list[tk.Widget] = []
        self.admin_message_templates: list[dict] = []
        self.selected_template_id: int | None = None
        self.editing_template_id: int | None = None
        self.template_form_title_label: tk.Label | None = None
        self.template_form_status_label: tk.Label | None = None
        self.template_save_button: tk.Button | None = None
        self.template_service_combo: ttk.Combobox | None = None
        self.service_catalog_name_var = tk.StringVar()
        self.admin_service_catalog_items: list[dict] = []
        self.selected_service_catalog_id: int | None = None
        self.editing_service_catalog_id: int | None = None
        self.service_catalog_tree: ttk.Treeview | None = None
        self.service_catalog_form_title_label: tk.Label | None = None
        self.service_catalog_form_status_label: tk.Label | None = None
        self.service_catalog_save_button: tk.Button | None = None
        self.inventory_service_var = tk.StringVar(value="")
        self.inventory_email_var = tk.StringVar()
        self.inventory_password_var = tk.StringVar()
        self.admin_inventory_items: list[dict] = []
        self.selected_inventory_id: int | None = None
        self.editing_inventory_id: int | None = None
        self.inventory_form_title_label: tk.Label | None = None
        self.inventory_form_status_label: tk.Label | None = None
        self.inventory_save_button: tk.Button | None = None
        self.inventory_comment_text: tk.Text | None = None
        self.inventory_tree: ttk.Treeview | None = None
        self.inventory_preview_text: tk.Text | None = None
        self.inventory_service_combo: ttk.Combobox | None = None
        self.supabase_enabled_var = tk.BooleanVar(value=False)
        self.supabase_url_var = tk.StringVar()
        self.supabase_anon_key_var = tk.StringVar()
        self.supabase_admin_secret_var = tk.StringVar()
        self.supabase_employee_sync_secret_var = tk.StringVar()
        self.cloud_sync_status_label: tk.Label | None = None
        self.excel_path_var = tk.StringVar()
        self.excel_sheet_var = tk.StringVar()
        self.sales_period_var = tk.StringVar(value="Last 5 Days")
        self.admin_sales_entries: list[dict] = []
        self.admin_excel_sync_results: queue.Queue[tuple[dict, ExcelSyncResult]] = queue.Queue()
        self.admin_excel_sync_pending_entry_ids: set[str] = set()
        self.admin_retry_button: tk.Button | None = None
        self.dashboard_daily_sales_points: list[dict] = []
        self.dashboard_best_sales_date = ""
        self._admin_excel_poll_after_id: str | None = None
        self._build()
        self._admin_excel_poll_after_id = self.after(250, self._poll_admin_excel_sync_results)

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_header()

        self.notebook = ttk.Notebook(self)
        self.notebook.grid(row=1, column=0, sticky="nsew", padx=18, pady=18)

        dashboard_tab = tk.Frame(self.notebook, bg=BG, padx=0, pady=0)
        employees_tab = tk.Frame(self.notebook, bg=BG, padx=0, pady=0)
        security_tab = tk.Frame(self.notebook, bg=BG, padx=0, pady=0)
        attendance_tab = tk.Frame(self.notebook, bg=BG, padx=0, pady=0)
        announcements_tab = tk.Frame(self.notebook, bg=BG, padx=0, pady=0)
        messages_tab = tk.Frame(self.notebook, bg=BG, padx=0, pady=0)
        inventory_tab = tk.Frame(self.notebook, bg=BG, padx=0, pady=0)
        service_catalog_tab = tk.Frame(self.notebook, bg=BG, padx=0, pady=0)
        cloud_tab = tk.Frame(self.notebook, bg=BG, padx=0, pady=0)
        sales_data_tab = tk.Frame(self.notebook, bg=BG, padx=0, pady=0)
        workbook_tab = tk.Frame(self.notebook, bg=BG, padx=0, pady=0)
        self.notebook.add(dashboard_tab, text="Dashboard")
        self.notebook.add(employees_tab, text="Registered Employees")
        self.notebook.add(security_tab, text="Admin Security")
        self.notebook.add(attendance_tab, text="Attendance")
        self.notebook.add(announcements_tab, text="Announcements")
        self.notebook.add(messages_tab, text="Service Messages")
        self.notebook.add(inventory_tab, text="Inventory")
        self.notebook.add(service_catalog_tab, text="Items Sold List")
        self.notebook.add(cloud_tab, text="Cloud Sync")
        self.notebook.add(sales_data_tab, text="Sales Data")
        self.notebook.add(workbook_tab, text="Sales Workbook")

        self._build_dashboard_tab(fill_with_scrollable_region(dashboard_tab, bg=BG))
        self._build_employees_tab(fill_with_scrollable_region(employees_tab, bg=BG))
        self._build_security_tab(fill_with_scrollable_region(security_tab, bg=BG))
        self._build_attendance_tab(fill_with_scrollable_region(attendance_tab, bg=BG))
        self._build_announcements_tab(fill_with_scrollable_region(announcements_tab, bg=BG))
        self._build_message_templates_tab(fill_with_scrollable_region(messages_tab, bg=BG))
        self._build_inventory_tab(fill_with_scrollable_region(inventory_tab, bg=BG))
        self._build_service_catalog_tab(fill_with_scrollable_region(service_catalog_tab, bg=BG))
        self._build_cloud_sync_tab(fill_with_scrollable_region(cloud_tab, bg=BG))
        self._build_sales_data_tab(fill_with_scrollable_region(sales_data_tab, bg=BG))
        self._build_sales_workbook_tab(fill_with_scrollable_region(workbook_tab, bg=BG))

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

    def _build_dashboard_tab(self, parent: tk.Frame) -> None:
        parent.grid_columnconfigure(0, weight=3)
        parent.grid_columnconfigure(1, weight=2)
        parent.grid_rowconfigure(1, weight=1)

        metrics = tk.Frame(parent, bg=BG)
        metrics.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 14))
        metrics.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="admin_dashboard_metrics")
        self.dashboard_entries_card = MetricCard(metrics, "Total Entries", "0", BLUE, "All saved sales")
        self.dashboard_entries_card.grid(row=0, column=0, sticky="ew", padx=(0, 9))
        self.dashboard_total_sales_card = MetricCard(metrics, "Total Sales", "0", SUCCESS, "All time selling")
        self.dashboard_total_sales_card.grid(row=0, column=1, sticky="ew", padx=3)
        self.dashboard_month_sales_card = MetricCard(metrics, "This Month", "0", TEAL, "Current month selling")
        self.dashboard_month_sales_card.grid(row=0, column=2, sticky="ew", padx=3)
        self.dashboard_best_day_card = MetricCard(metrics, "Best Sales Day", "0", WARNING, "No sales yet")
        self.dashboard_best_day_card.grid(row=0, column=3, sticky="ew", padx=(9, 0))

        chart_card = SurfaceCard(parent, padx=18, pady=16, accent=True, accent_start=BLUE, accent_end=SUCCESS)
        chart_card.grid(row=1, column=0, sticky="nsew", padx=(0, 12))
        chart = chart_card.body
        chart.grid_columnconfigure(0, weight=1)
        chart.grid_rowconfigure(1, weight=1)

        chart_header = tk.Frame(chart, bg=WHITE)
        chart_header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        chart_header.grid_columnconfigure(0, weight=1)
        tk.Label(chart_header, text="Daily Sales Performance", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 16)).grid(
            row=0, column=0, sticky="w"
        )
        self.dashboard_chart_subtitle = tk.Label(chart_header, text="", bg=WHITE, fg=MUTED, font=(FONT, 9))
        self.dashboard_chart_subtitle.grid(row=1, column=0, sticky="w", pady=(4, 0))
        make_button(chart_header, "Refresh", self.refresh_all, "light").grid(row=0, column=1, rowspan=2, sticky="e")

        self.dashboard_sales_canvas = tk.Canvas(chart, bg=WHITE, height=310, bd=0, highlightthickness=0)
        self.dashboard_sales_canvas.grid(row=1, column=0, sticky="nsew")
        self.dashboard_sales_canvas.bind("<Configure>", lambda _event: self._draw_dashboard_sales_graph())

        insight_card = SurfaceCard(parent, padx=18, pady=16, accent=True, accent_start=NAVY, accent_end=TEAL)
        insight_card.grid(row=1, column=1, sticky="nsew")
        insight = insight_card.body
        insight.grid_columnconfigure(0, weight=1)
        insight.grid_rowconfigure(3, weight=1)
        tk.Label(insight, text="Sales Highlights", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 16)).grid(
            row=0, column=0, sticky="w"
        )

        highlight = tk.Frame(insight, bg="#f8fbff", highlightbackground=LINE, highlightthickness=1, padx=14, pady=12)
        highlight.grid(row=1, column=0, sticky="ew", pady=(12, 14))
        highlight.grid_columnconfigure(0, weight=1)
        self.dashboard_best_day_label = tk.Label(
            highlight,
            text="No sales recorded yet",
            bg="#f8fbff",
            fg=TEXT,
            font=(FONT_BOLD, 13),
            anchor="w",
            justify="left",
            wraplength=320,
        )
        self.dashboard_best_day_label.grid(row=0, column=0, sticky="ew")
        self.dashboard_best_day_meta_label = tk.Label(
            highlight,
            text="Add sales entries to build the daily performance graph.",
            bg="#f8fbff",
            fg=MUTED,
            font=(FONT, 9),
            anchor="w",
            justify="left",
            wraplength=320,
        )
        self.dashboard_best_day_meta_label.grid(row=1, column=0, sticky="ew", pady=(6, 0))

        self.dashboard_monthly_summary_label = tk.Label(insight, text="", bg=WHITE, fg=MUTED, font=(FONT, 9))
        self.dashboard_monthly_summary_label.grid(row=2, column=0, sticky="w", pady=(0, 8))

        columns = ("month", "entries", "sales", "profit", "best")
        self.dashboard_monthly_tree = ttk.Treeview(insight, columns=columns, show="headings", height=10, selectmode="none")
        headings = {
            "month": "Month",
            "entries": "Entries",
            "sales": "Sales",
            "profit": "Profit",
            "best": "Best Day",
        }
        widths = {"month": 105, "entries": 70, "sales": 95, "profit": 90, "best": 92}
        for column in columns:
            self.dashboard_monthly_tree.heading(column, text=headings[column], anchor="w")
            self.dashboard_monthly_tree.column(
                column,
                width=widths[column],
                minwidth=widths[column],
                anchor="w",
                stretch=column == "month",
            )
        self.dashboard_monthly_tree.tag_configure("month_even", background=WHITE, foreground=TEXT)
        self.dashboard_monthly_tree.tag_configure("month_odd", background="#f8fbff", foreground=TEXT)
        self.dashboard_monthly_tree.tag_configure("month_best", background="#eafaf4", foreground=TEXT)
        self.dashboard_monthly_tree.grid(row=3, column=0, sticky="nsew")
        monthly_scroll = ttk.Scrollbar(insight, orient="vertical", command=self.dashboard_monthly_tree.yview)
        monthly_scroll.grid(row=3, column=1, sticky="ns")
        self.dashboard_monthly_tree.configure(yscrollcommand=monthly_scroll.set)

    def _build_employees_tab(self, parent: tk.Frame) -> None:
        parent.grid_columnconfigure(0, weight=2)
        parent.grid_columnconfigure(1, weight=3)
        parent.grid_rowconfigure(0, weight=1)

        form_card = SurfaceCard(parent, padx=22, pady=20, accent=True, accent_start=BLUE, accent_end=TEAL)
        form_card.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        form = form_card.body
        form.grid_columnconfigure(0, weight=1)
        form_header = tk.Frame(form, bg=WHITE)
        form_header.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        form_header.grid_columnconfigure(0, weight=1)
        self.employee_form_title_label = tk.Label(
            form_header,
            text="Add New Employee",
            bg=WHITE,
            fg=TEXT,
            font=(FONT_BOLD, 18),
        )
        self.employee_form_title_label.grid(row=0, column=0, sticky="w")
        self.employee_form_hint_label = tk.Label(
            form,
            text="Create a new employee login. Leave password blank to auto-generate one.",
            bg=WHITE,
            fg=MUTED,
            font=(FONT, 10),
            wraplength=340,
            justify="left",
        )
        self.employee_form_hint_label.grid(row=1, column=0, sticky="w", pady=(0, 16))

        self.employee_name_entry = self._employee_entry(form, "Employee Name", self.employee_name_var, 2)
        self._employee_entry(form, "Username", self.employee_username_var, 4)
        self._employee_entry(form, "Password", self.employee_password_var, 6)
        tk.Label(form, text="Account Status", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 10)).grid(
            row=8, column=0, sticky="w"
        )
        self.employee_active_status_label = tk.Label(
            form,
            text="",
            bg="#eafaf4",
            fg=SUCCESS,
            font=(FONT_BOLD, 10),
            padx=12,
            pady=7,
            anchor="w",
        )
        self.employee_active_status_label.grid(row=9, column=0, sticky="ew", pady=(8, 14))
        self._refresh_employee_active_status_label()

        self.employee_password_status_label = tk.Label(
            form,
            text="Leave password blank to auto-generate one for new employees.",
            bg=WHITE,
            fg=MUTED,
            font=(FONT, 10),
            wraplength=340,
            justify="left",
        )
        self.employee_password_status_label.grid(row=10, column=0, sticky="w", pady=(0, 14))

        actions = tk.Frame(form, bg=WHITE)
        actions.grid(row=11, column=0, sticky="ew")
        actions.grid_columnconfigure(0, weight=1)
        self.employee_save_button = make_button(actions, "Add Employee", self.save_employee_user, "primary")
        self.employee_save_button.grid(row=0, column=0, sticky="ew")

        more_actions = tk.Frame(form, bg=WHITE)
        more_actions.grid(row=12, column=0, sticky="ew", pady=(14, 0))
        more_actions.grid_columnconfigure((0, 1, 2), weight=1)
        make_button(more_actions, "Freeze / Unfreeze", self.toggle_selected_employee_active, "light").grid(
            row=0, column=0, sticky="ew", padx=(0, 6)
        )
        make_button(more_actions, "Reset Password", self.reset_selected_employee_password, "warning").grid(
            row=0, column=1, sticky="ew", padx=6
        )
        make_button(more_actions, "Remove Employee", self.remove_selected_employee, "danger").grid(
            row=0, column=2, sticky="ew", padx=(6, 0)
        )

        list_card = SurfaceCard(parent, padx=18, pady=16, accent=True, accent_start=SUCCESS, accent_end=TEAL)
        list_card.grid(row=0, column=1, sticky="nsew")
        listing = list_card.body
        listing.grid_columnconfigure(0, weight=1)
        listing.grid_rowconfigure(1, weight=1)
        listing_header = tk.Frame(listing, bg=WHITE)
        listing_header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        listing_header.grid_columnconfigure(0, weight=1)
        tk.Label(listing_header, text="Registered Employees", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 16)).grid(
            row=0, column=0, sticky="w"
        )
        self.employee_count_label = tk.Label(listing_header, text="", bg=WHITE, fg=MUTED, font=(FONT, 9))
        self.employee_count_label.grid(row=1, column=0, sticky="w", pady=(4, 0))
        make_button(listing_header, "New Employee", self.start_new_employee_form, "success").grid(
            row=0, column=1, rowspan=2, sticky="e"
        )
        self.employees_tree = ttk.Treeview(
            listing,
            columns=("name", "username", "password", "status"),
            show="headings",
            selectmode="browse",
        )
        self.employees_tree.heading("name", text="Name", anchor="w")
        self.employees_tree.heading("username", text="Username", anchor="w")
        self.employees_tree.heading("password", text="Password", anchor="w")
        self.employees_tree.heading("status", text="Status", anchor="w")
        self.employees_tree.column("name", width=260, minwidth=180, anchor="w", stretch=True)
        self.employees_tree.column("username", width=170, minwidth=140, anchor="w", stretch=False)
        self.employees_tree.column("password", width=150, minwidth=130, anchor="w", stretch=False)
        self.employees_tree.column("status", width=130, minwidth=110, anchor="w", stretch=False)
        self.employees_tree.tag_configure("employee_active", background="#eafaf4", foreground=TEXT)
        self.employees_tree.tag_configure("employee_frozen", background="#fff1f3", foreground=TEXT)
        self.employees_tree.grid(row=1, column=0, sticky="nsew")
        self.employees_tree.bind("<<TreeviewSelect>>", self._on_employee_selected)
        employee_scroll = ttk.Scrollbar(listing, orient="vertical", command=self.employees_tree.yview)
        employee_scroll.grid(row=1, column=1, sticky="ns")
        self.employees_tree.configure(yscrollcommand=employee_scroll.set)

    def _employee_entry(self, parent: tk.Misc, label: str, variable: tk.StringVar, row: int) -> tk.Entry:
        tk.Label(parent, text=label, bg=WHITE, fg=TEXT, font=(FONT_BOLD, 10)).grid(row=row, column=0, sticky="w")
        entry = tk.Entry(
            parent,
            textvariable=variable,
            bg="#f8fbff",
            fg=TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=LINE,
            highlightcolor=BLUE,
            font=(FONT, 11),
        )
        entry.grid(row=row + 1, column=0, sticky="ew", ipady=8, pady=(8, 14))
        return entry

    def _password_entry(self, parent: tk.Misc, label: str, variable: tk.StringVar, row: int) -> tk.Entry:
        tk.Label(parent, text=label, bg=WHITE, fg=TEXT, font=(FONT_BOLD, 10)).grid(row=row, column=0, sticky="w")
        entry = tk.Entry(
            parent,
            textvariable=variable,
            show="*",
            bg="#f8fbff",
            fg=TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=LINE,
            highlightcolor=BLUE,
            font=(FONT, 11),
        )
        entry.grid(row=row + 1, column=0, sticky="ew", ipady=8, pady=(8, 14))
        return entry

    def _build_security_tab(self, parent: tk.Frame) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_columnconfigure(1, weight=1)
        parent.grid_rowconfigure(0, weight=1)

        card = SurfaceCard(parent, padx=24, pady=22, accent=True, accent_start=NAVY, accent_end=BLUE)
        card.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        body = card.body
        body.grid_columnconfigure(0, weight=1)

        tk.Label(body, text="Admin Password", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 18)).grid(
            row=0, column=0, sticky="w"
        )
        tk.Label(
            body,
            text="Change the owner/admin login password for this device. Use your current admin password first.",
            bg=WHITE,
            fg=MUTED,
            font=(FONT, 10),
            wraplength=440,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(6, 18))

        self._password_entry(body, "Current Admin Password", self.admin_current_password_var, 2)
        self._password_entry(body, "New Admin Password", self.admin_new_password_var, 4)
        self._password_entry(body, "Confirm New Password", self.admin_confirm_password_var, 6)

        self.admin_password_status_label = tk.Label(
            body,
            text="After changing it, the generated bootstrap admin password will no longer be used.",
            bg=WHITE,
            fg=MUTED,
            font=(FONT, 10),
            wraplength=440,
            justify="left",
        )
        self.admin_password_status_label.grid(row=8, column=0, sticky="w", pady=(0, 14))
        make_button(body, "Update Admin Password", self.change_admin_password, "primary").grid(
            row=9, column=0, sticky="ew"
        )

        info = SurfaceCard(parent, padx=24, pady=22, accent=True, accent_start=SUCCESS, accent_end=TEAL)
        info.grid(row=0, column=1, sticky="nsew")
        info_body = info.body
        info_body.grid_columnconfigure(0, weight=1)
        tk.Label(info_body, text="Employee Passwords", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 18)).grid(
            row=0, column=0, sticky="w"
        )
        tk.Label(
            info_body,
            text=(
                "Employee logins are managed from Registered Employees. Select an employee there to set, reset, "
                "freeze, edit, or remove the employee account."
            ),
            bg=WHITE,
            fg=MUTED,
            font=(FONT, 11),
            wraplength=440,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(8, 18))
        status_pill(info_body, "Employee passwords stay protected", fg=SUCCESS, bg="#eafaf4").grid(
            row=2, column=0, sticky="w"
        )

    def change_admin_password(self) -> None:
        current_password = self.admin_current_password_var.get()
        new_password = self.admin_new_password_var.get()
        confirm_password = self.admin_confirm_password_var.get()
        if not current_password or not new_password or not confirm_password:
            show_app_alert(self, "Missing password", "Fill current password, new password, and confirmation.", "warning")
            return
        if new_password != confirm_password:
            show_app_alert(self, "Password mismatch", "New password and confirmation do not match.", "warning")
            return
        ok, message = self.app.auth.change_own_password(self.app.current_user, current_password, new_password)
        if not ok:
            show_app_alert(self, "Password not changed", message, "warning")
            return
        self.admin_current_password_var.set("")
        self.admin_new_password_var.set("")
        self.admin_confirm_password_var.set("")
        if self.admin_password_status_label is not None:
            self.admin_password_status_label.configure(
                text="Admin password updated. Use the new password next time you log in.",
                fg=SUCCESS,
            )
        show_app_alert(self, "Admin password updated", "Use the new password next time you log in.", "success")

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

    def _active_service_names(self, include_other: bool = True) -> list[str]:
        return self.app.attendance_store.list_service_names(include_other=include_other)

    def _template_service_values(self) -> list[str]:
        values = ["General", *self._active_service_names(include_other=True)]
        if "Other" not in values:
            values.append("Other")
        return values

    def _inventory_service_values(self) -> list[str]:
        return self._active_service_names(include_other=False)

    def _refresh_service_dropdown_values(self) -> None:
        template_values = self._template_service_values()
        if self.template_service_combo is not None:
            self.template_service_combo.configure(values=template_values)
            if self.template_service_var.get() not in template_values:
                fallback = "Other"
                if len(template_values) > 1:
                    fallback = template_values[1]
                self.template_service_var.set(fallback)
                self.template_other_service_var.set("")
                self._update_template_other_service_visibility()
        if self.inventory_service_combo is not None:
            self.inventory_service_combo.configure(values=self._inventory_service_values())
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
        self.template_service_combo = ttk.Combobox(
            compose,
            values=self._template_service_values(),
            textvariable=self.template_service_var,
            state="readonly",
            font=(FONT, 10),
        )
        self.template_service_combo.grid(row=3, column=0, sticky="ew", ipady=6, pady=(8, 14))
        self.template_service_combo.bind("<<ComboboxSelected>>", lambda _event: self._update_template_other_service_visibility())

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

    def _build_inventory_tab(self, parent: tk.Frame) -> None:
        parent.grid_columnconfigure(0, weight=2)
        parent.grid_columnconfigure(1, weight=3)
        parent.grid_rowconfigure(0, weight=1)

        form_card = SurfaceCard(parent, padx=22, pady=20, accent=True, accent_start=BLUE, accent_end=TEAL)
        form_card.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        form = form_card.body
        form.grid_columnconfigure(0, weight=1)
        self.inventory_form_title_label = tk.Label(
            form,
            text="Add Inventory Item",
            bg=WHITE,
            fg=TEXT,
            font=(FONT_BOLD, 18),
        )
        self.inventory_form_title_label.grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.inventory_form_status_label = tk.Label(
            form,
            text="Add service credentials employees can view and copy from their Inventory panel.",
            bg=WHITE,
            fg=MUTED,
            font=(FONT, 10),
            wraplength=430,
            justify="left",
        )
        self.inventory_form_status_label.grid(row=1, column=0, sticky="w", pady=(0, 16))

        tk.Label(form, text="Service Name", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 10)).grid(row=2, column=0, sticky="w")
        self.inventory_service_combo = ttk.Combobox(
            form,
            values=self._inventory_service_values(),
            textvariable=self.inventory_service_var,
            font=(FONT, 10),
        )
        self.inventory_service_combo.grid(row=3, column=0, sticky="ew", ipady=6, pady=(8, 14))

        tk.Label(form, text="Email / Account", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 10)).grid(row=4, column=0, sticky="w")
        tk.Entry(
            form,
            textvariable=self.inventory_email_var,
            bg="#f8fbff",
            fg=TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=LINE,
            highlightcolor=BLUE,
            font=(FONT, 11),
        ).grid(row=5, column=0, sticky="ew", ipady=8, pady=(8, 14))

        tk.Label(form, text="Password", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 10)).grid(row=6, column=0, sticky="w")
        tk.Entry(
            form,
            textvariable=self.inventory_password_var,
            bg="#f8fbff",
            fg=TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=LINE,
            highlightcolor=BLUE,
            font=(FONT, 11),
        ).grid(row=7, column=0, sticky="ew", ipady=8, pady=(8, 14))

        tk.Label(form, text="Comment", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 10)).grid(row=8, column=0, sticky="w")
        self.inventory_comment_text = tk.Text(
            form,
            height=8,
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
        self.inventory_comment_text.grid(row=9, column=0, sticky="nsew", pady=(8, 16))
        form.grid_rowconfigure(9, weight=1)

        actions = tk.Frame(form, bg=WHITE)
        actions.grid(row=10, column=0, sticky="ew")
        actions.grid_columnconfigure((0, 1), weight=1)
        self.inventory_save_button = make_button(actions, "Save Inventory", self.save_inventory_item, "primary")
        self.inventory_save_button.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        make_button(actions, "Clear Form", self.clear_inventory_form, "light").grid(
            row=0, column=1, sticky="ew", padx=(8, 0)
        )

        list_card = SurfaceCard(parent, padx=18, pady=16, accent=True, accent_start=SUCCESS, accent_end=TEAL)
        list_card.grid(row=0, column=1, sticky="nsew")
        body = list_card.body
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(1, weight=3)
        body.grid_rowconfigure(3, weight=2)
        tk.Label(body, text="Active Inventory", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 16)).grid(
            row=0, column=0, sticky="w", pady=(0, 12)
        )

        self.inventory_tree = ttk.Treeview(body, columns=("service", "email", "updated"), show="headings", selectmode="browse")
        self.inventory_tree.heading("service", text="Service", anchor="w")
        self.inventory_tree.heading("email", text="Email / Account", anchor="w")
        self.inventory_tree.heading("updated", text="Updated", anchor="w")
        self.inventory_tree.column("service", width=230, minwidth=190, anchor="w", stretch=True)
        self.inventory_tree.column("email", width=340, minwidth=240, anchor="w", stretch=True)
        self.inventory_tree.column("updated", width=150, minwidth=135, anchor="w", stretch=False)
        self.inventory_tree.tag_configure("inventory_even", background=WHITE, foreground=TEXT)
        self.inventory_tree.tag_configure("inventory_odd", background="#f8fbff", foreground=TEXT)
        self.inventory_tree.grid(row=1, column=0, sticky="nsew")
        self.inventory_tree.bind("<<TreeviewSelect>>", self._on_inventory_selected)
        inventory_scroll = ttk.Scrollbar(body, orient="vertical", command=self.inventory_tree.yview)
        inventory_scroll.grid(row=1, column=1, sticky="ns")
        self.inventory_tree.configure(yscrollcommand=inventory_scroll.set)

        tk.Label(body, text="Selected Preview", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 12)).grid(
            row=2, column=0, sticky="w", pady=(16, 8)
        )
        self.inventory_preview_text = tk.Text(
            body,
            height=7,
            bg="#fbfdff",
            fg=TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=LINE,
            font=(FONT, 10),
            wrap="word",
        )
        self.inventory_preview_text.grid(row=3, column=0, sticky="nsew")
        self.inventory_preview_text.configure(state="disabled")
        preview_scroll = ttk.Scrollbar(body, orient="vertical", command=self.inventory_preview_text.yview)
        preview_scroll.grid(row=3, column=1, sticky="ns")
        self.inventory_preview_text.configure(yscrollcommand=preview_scroll.set)

        list_actions = tk.Frame(body, bg=WHITE)
        list_actions.grid(row=4, column=0, sticky="ew", pady=(14, 0))
        list_actions.grid_columnconfigure((0, 1), weight=1)
        make_button(list_actions, "Edit Selected", self.edit_selected_inventory_item, "primary").grid(
            row=0, column=0, sticky="ew", padx=(0, 8)
        )
        make_button(list_actions, "Deactivate Selected", self.deactivate_selected_inventory_item, "warning").grid(
            row=0, column=1, sticky="ew", padx=(8, 0)
        )
    def _build_service_catalog_tab(self, parent: tk.Frame) -> None:
        parent.grid_columnconfigure(0, weight=2)
        parent.grid_columnconfigure(1, weight=3)
        parent.grid_rowconfigure(0, weight=1)

        form_card = SurfaceCard(parent, padx=22, pady=20, accent=True, accent_start=BLUE, accent_end=TEAL)
        form_card.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        form = form_card.body
        form.grid_columnconfigure(0, weight=1)
        self.service_catalog_form_title_label = tk.Label(
            form,
            text="Add Item Sold",
            bg=WHITE,
            fg=TEXT,
            font=(FONT_BOLD, 18),
        )
        self.service_catalog_form_title_label.grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.service_catalog_form_status_label = tk.Label(
            form,
            text="Manage the services shown in the employee Items Sold dropdown.",
            bg=WHITE,
            fg=MUTED,
            font=(FONT, 10),
            wraplength=420,
            justify="left",
        )
        self.service_catalog_form_status_label.grid(row=1, column=0, sticky="w", pady=(0, 16))

        tk.Label(form, text="Service Name", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 10)).grid(row=2, column=0, sticky="w")
        tk.Entry(
            form,
            textvariable=self.service_catalog_name_var,
            bg="#f8fbff",
            fg=TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=LINE,
            highlightcolor=BLUE,
            font=(FONT, 11),
        ).grid(row=3, column=0, sticky="ew", ipady=8, pady=(8, 16))

        actions = tk.Frame(form, bg=WHITE)
        actions.grid(row=4, column=0, sticky="ew")
        actions.grid_columnconfigure((0, 1), weight=1)
        self.service_catalog_save_button = make_button(actions, "Add Item", self.save_service_catalog_item, "primary")
        self.service_catalog_save_button.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        make_button(actions, "Clear Form", self.clear_service_catalog_form, "light").grid(
            row=0, column=1, sticky="ew", padx=(8, 0)
        )

        list_card = SurfaceCard(parent, padx=18, pady=16, accent=True, accent_start=SUCCESS, accent_end=TEAL)
        list_card.grid(row=0, column=1, sticky="nsew")
        body = list_card.body
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(1, weight=1)
        tk.Label(body, text="Active Items Sold", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 16)).grid(
            row=0, column=0, sticky="w", pady=(0, 12)
        )
        self.service_catalog_tree = ttk.Treeview(body, columns=("service", "updated"), show="headings", selectmode="browse")
        self.service_catalog_tree.heading("service", text="Service", anchor="w")
        self.service_catalog_tree.heading("updated", text="Updated", anchor="w")
        self.service_catalog_tree.column("service", width=360, minwidth=240, anchor="w", stretch=True)
        self.service_catalog_tree.column("updated", width=145, minwidth=130, anchor="w", stretch=False)
        self.service_catalog_tree.tag_configure("service_even", background=WHITE, foreground=TEXT)
        self.service_catalog_tree.tag_configure("service_odd", background="#f8fbff", foreground=TEXT)
        self.service_catalog_tree.grid(row=1, column=0, sticky="nsew")
        self.service_catalog_tree.bind("<<TreeviewSelect>>", self._on_service_catalog_selected)
        service_scroll = ttk.Scrollbar(body, orient="vertical", command=self.service_catalog_tree.yview)
        service_scroll.grid(row=1, column=1, sticky="ns")
        self.service_catalog_tree.configure(yscrollcommand=service_scroll.set)

        list_actions = tk.Frame(body, bg=WHITE)
        list_actions.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        list_actions.grid_columnconfigure((0, 1), weight=1)
        make_button(list_actions, "Edit Selected", self.edit_selected_service_catalog_item, "primary").grid(
            row=0, column=0, sticky="ew", padx=(0, 8)
        )
        make_button(list_actions, "Remove Selected", self.remove_selected_service_catalog_item, "warning").grid(
            row=0, column=1, sticky="ew", padx=(8, 0)
        )
    def _build_cloud_sync_tab(self, parent: tk.Frame) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)

        card = SurfaceCard(parent, padx=22, pady=20, accent=True, accent_start=NAVY, accent_end=TEAL)
        card.grid(row=0, column=0, sticky="ew")
        body = card.body
        body.grid_columnconfigure(1, weight=1)
        tk.Label(body, text="Supabase Cloud Sync", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 18)).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 8)
        )
        tk.Label(
            body,
            text="Sync employee accounts, announcements, inventory, and service message designs between PCs.",
            bg=WHITE,
            fg=MUTED,
            font=(FONT, 10),
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 16))

        tk.Checkbutton(
            body,
            text="Enable cloud sync on this device",
            variable=self.supabase_enabled_var,
            bg=WHITE,
            fg=TEXT,
            activebackground=WHITE,
            font=(FONT_BOLD, 10),
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(0, 14))

        tk.Label(body, text="Project URL", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 10)).grid(row=3, column=0, sticky="w")
        tk.Entry(
            body,
            textvariable=self.supabase_url_var,
            bg="#f8fbff",
            fg=TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=LINE,
            highlightcolor=BLUE,
            font=(FONT, 10),
        ).grid(row=4, column=0, columnspan=3, sticky="ew", ipady=8, pady=(8, 14))

        tk.Label(body, text="Anon Public Key", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 10)).grid(row=5, column=0, sticky="w")
        tk.Entry(
            body,
            textvariable=self.supabase_anon_key_var,
            bg="#f8fbff",
            fg=TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=LINE,
            highlightcolor=BLUE,
            font=(FONT, 10),
            show="*",
        ).grid(row=6, column=0, columnspan=3, sticky="ew", ipady=8, pady=(8, 14))

        tk.Label(body, text="Admin Write Secret", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 10)).grid(row=7, column=0, sticky="w")
        tk.Entry(
            body,
            textvariable=self.supabase_admin_secret_var,
            bg="#f8fbff",
            fg=TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=LINE,
            highlightcolor=BLUE,
            font=(FONT, 10),
            show="*",
        ).grid(row=8, column=0, columnspan=3, sticky="ew", ipady=8, pady=(8, 14))

        tk.Label(body, text="Employee Sync Secret", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 10)).grid(row=9, column=0, sticky="w")
        tk.Entry(
            body,
            textvariable=self.supabase_employee_sync_secret_var,
            bg="#f8fbff",
            fg=TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=LINE,
            highlightcolor=BLUE,
            font=(FONT, 10),
            show="*",
        ).grid(row=10, column=0, columnspan=3, sticky="ew", ipady=8, pady=(8, 14))

        actions = tk.Frame(body, bg=WHITE)
        actions.grid(row=11, column=0, columnspan=3, sticky="ew")
        actions.grid_columnconfigure((0, 1), weight=1)
        make_button(actions, "Save Cloud Settings", self.save_cloud_settings, "primary").grid(
            row=0, column=0, sticky="ew", padx=(0, 8)
        )
        make_button(actions, "Sync Now", self.run_cloud_sync_now, "success").grid(
            row=0, column=1, sticky="ew", padx=(8, 0)
        )

        status_card = SurfaceCard(parent, padx=22, pady=20, accent=True, accent_start=BLUE, accent_end=TEAL)
        status_card.grid(row=1, column=0, sticky="nsew", pady=(14, 0))
        status = status_card.body
        status.grid_columnconfigure(0, weight=1)
        tk.Label(status, text="Cloud Status", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 16)).grid(row=0, column=0, sticky="w")
        self.cloud_sync_status_label = tk.Label(
            status,
            text="",
            bg=WHITE,
            fg=MUTED,
            font=(FONT, 10),
            anchor="nw",
            justify="left",
            wraplength=850,
        )
        self.cloud_sync_status_label.grid(row=1, column=0, sticky="ew", pady=(10, 0))

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
        self._refresh_cloud_settings()
        self._refresh_dashboard()
        self._refresh_employees()
        shifts = self.app.attendance_store.list_shift_summaries()
        self._refresh_metrics(shifts)
        self._refresh_shift_table(shifts)
        self._refresh_event_table(self.selected_shift_id)
        self._refresh_announcements()
        self._refresh_service_catalog()
        self._refresh_message_templates()
        self._refresh_inventory_items()
        self._refresh_sales_data()

    def _refresh_dashboard(self) -> None:
        if not hasattr(self, "dashboard_sales_canvas"):
            return
        today = date.today()
        today_text = today.strftime("%Y-%m-%d")
        all_entries = self.app.attendance_store.list_sales_entries_between("1900-01-01", today_text)
        total_sales = sum(self._sales_money_value(entry.get("selling_amount", "")) for entry in all_entries)

        month_start = date(today.year, today.month, 1)
        month_entries = [
            entry
            for entry in all_entries
            if (entry_date := self._sales_entry_date(entry)) is not None
            and month_start <= entry_date <= today
        ]
        month_sales = sum(self._sales_money_value(entry.get("selling_amount", "")) for entry in month_entries)
        month_profit = sum(self._sales_money_value(entry.get("profit", "")) for entry in month_entries)

        daily_totals = self._sales_daily_totals(month_entries)
        best_day, best_day_data = self._best_sales_day(daily_totals)
        best_day_sales = float(best_day_data.get("sales", 0)) if best_day_data else 0.0
        best_day_entries = int(best_day_data.get("entries", 0)) if best_day_data else 0

        self.dashboard_entries_card.value_label.configure(text=str(len(all_entries)))
        self.dashboard_total_sales_card.value_label.configure(text=self._dashboard_money_label(total_sales))
        self.dashboard_month_sales_card.value_label.configure(text=self._dashboard_money_label(month_sales))
        self.dashboard_month_sales_card.helper_label.configure(
            text=f"{calendar.month_name[today.month]} profit {self._dashboard_money_label(month_profit)}"
        )
        self.dashboard_best_day_card.value_label.configure(text=self._dashboard_money_label(best_day_sales))
        self.dashboard_best_day_card.helper_label.configure(
            text=f"{self._format_date(best_day)} | {best_day_entries} entries" if best_day else "No sales yet"
        )

        if best_day:
            self.dashboard_best_day_label.configure(
                text=f"Highest sales day: {self._format_date(best_day)}",
                fg=TEXT,
            )
            self.dashboard_best_day_meta_label.configure(
                text=f"{self._dashboard_money_label(best_day_sales)} from {best_day_entries} entries this month.",
                fg=MUTED,
            )
        else:
            self.dashboard_best_day_label.configure(text="No sales recorded yet", fg=TEXT)
            self.dashboard_best_day_meta_label.configure(
                text="Add sales entries to build the daily performance graph.",
                fg=MUTED,
            )

        self.dashboard_best_sales_date = best_day or ""
        self.dashboard_daily_sales_points = self._dashboard_daily_points(today, daily_totals)
        self.dashboard_chart_subtitle.configure(
            text=f"{calendar.month_name[today.month]} {today.year} daily selling amount | highest day is highlighted"
        )
        self._refresh_dashboard_monthly_table(all_entries, today)
        self._draw_dashboard_sales_graph()

    def _sales_entry_date(self, entry: dict) -> date | None:
        try:
            return datetime.strptime(str(entry.get("entry_date", "")), "%Y-%m-%d").date()
        except ValueError:
            return None

    def _sales_daily_totals(self, entries: list[dict]) -> dict[str, dict[str, float | int]]:
        totals: dict[str, dict[str, float | int]] = {}
        for entry in entries:
            entry_date = str(entry.get("entry_date", ""))
            if not entry_date:
                continue
            data = totals.setdefault(entry_date, {"sales": 0.0, "profit": 0.0, "entries": 0})
            data["sales"] = float(data["sales"]) + self._sales_money_value(entry.get("selling_amount", ""))
            data["profit"] = float(data["profit"]) + self._sales_money_value(entry.get("profit", ""))
            data["entries"] = int(data["entries"]) + 1
        return totals

    def _best_sales_day(self, daily_totals: dict[str, dict[str, float | int]]) -> tuple[str, dict[str, float | int]] | tuple[None, None]:
        if not daily_totals:
            return None, None
        best_day = max(
            daily_totals,
            key=lambda day: (float(daily_totals[day].get("sales", 0)), int(daily_totals[day].get("entries", 0))),
        )
        return best_day, daily_totals[best_day]

    def _dashboard_daily_points(self, today: date, daily_totals: dict[str, dict[str, float | int]]) -> list[dict]:
        points = []
        for day in range(1, today.day + 1):
            current = date(today.year, today.month, day)
            key = current.strftime("%Y-%m-%d")
            data = daily_totals.get(key, {"sales": 0.0, "profit": 0.0, "entries": 0})
            points.append(
                {
                    "date": key,
                    "day": day,
                    "sales": float(data.get("sales", 0)),
                    "profit": float(data.get("profit", 0)),
                    "entries": int(data.get("entries", 0)),
                }
            )
        return points

    def _refresh_dashboard_monthly_table(self, all_entries: list[dict], today: date) -> None:
        if not hasattr(self, "dashboard_monthly_tree"):
            return
        month_entries: dict[int, list[dict]] = {month: [] for month in range(1, today.month + 1)}
        for entry in all_entries:
            entry_date = self._sales_entry_date(entry)
            if entry_date is None or entry_date.year != today.year or entry_date.month > today.month:
                continue
            month_entries.setdefault(entry_date.month, []).append(entry)

        for item in self.dashboard_monthly_tree.get_children():
            self.dashboard_monthly_tree.delete(item)

        month_rows = []
        for month in range(1, today.month + 1):
            entries = month_entries.get(month, [])
            sales = sum(self._sales_money_value(entry.get("selling_amount", "")) for entry in entries)
            profit = sum(self._sales_money_value(entry.get("profit", "")) for entry in entries)
            daily_totals = self._sales_daily_totals(entries)
            best_day, best_day_data = self._best_sales_day(daily_totals)
            best_label = "-"
            if best_day and best_day_data:
                best_label = datetime.strptime(best_day, "%Y-%m-%d").strftime("%d %b")
            month_rows.append((month, entries, sales, profit, best_label))

        best_month_row = max((row for row in month_rows if row[2] > 0), key=lambda row: row[2], default=None)
        for index, (month, entries, sales, profit, best_label) in enumerate(month_rows):
            tag = "month_best" if best_month_row and month == best_month_row[0] else (
                "month_even" if index % 2 == 0 else "month_odd"
            )
            self.dashboard_monthly_tree.insert(
                "",
                "end",
                iid=str(month),
                tags=(tag,),
                values=(
                    calendar.month_name[month],
                    str(len(entries)),
                    self._dashboard_money_label(sales),
                    self._dashboard_money_label(profit),
                    best_label,
                ),
            )
        self.dashboard_monthly_summary_label.configure(text=f"Monthly sales overview for {today.year}")

    def _dashboard_money_label(self, amount: float) -> str:
        return f"Rs. {money_label(str(amount))}"

    def _draw_dashboard_sales_graph(self) -> None:
        canvas = getattr(self, "dashboard_sales_canvas", None)
        if canvas is None:
            return
        canvas.delete("all")
        width = max(canvas.winfo_width(), 1)
        height = max(canvas.winfo_height(), 1)
        points = self.dashboard_daily_sales_points
        if not points:
            canvas.create_text(
                width / 2,
                height / 2,
                text="No sales data yet",
                fill=MUTED,
                font=(FONT_BOLD, 12),
            )
            return

        left = 54
        right = 22
        top = 28
        bottom = 44
        chart_width = max(width - left - right, 1)
        chart_height = max(height - top - bottom, 1)
        max_sales = max((float(point["sales"]) for point in points), default=0.0)
        if max_sales <= 0:
            canvas.create_text(
                width / 2,
                height / 2,
                text="No selling amount recorded for this month yet",
                fill=MUTED,
                font=(FONT_BOLD, 12),
            )
            return

        for step in range(5):
            ratio = step / 4
            y = top + chart_height - (chart_height * ratio)
            value = max_sales * ratio
            canvas.create_line(left, y, width - right, y, fill="#e8eef6", width=1)
            canvas.create_text(left - 10, y, text=money_label(str(value)), fill=MUTED, font=(FONT, 8), anchor="e")

        canvas.create_line(left, top, left, top + chart_height, fill=LINE)
        canvas.create_line(left, top + chart_height, width - right, top + chart_height, fill=LINE)

        slot = chart_width / max(len(points), 1)
        bar_width = max(6, min(26, slot * 0.58))
        label_interval = max(1, len(points) // 6)
        for index, point in enumerate(points):
            sales = float(point["sales"])
            bar_height = (sales / max_sales) * chart_height
            x_center = left + slot * index + slot / 2
            x1 = x_center - bar_width / 2
            x2 = x_center + bar_width / 2
            y1 = top + chart_height - bar_height
            y2 = top + chart_height
            is_best = point["date"] == self.dashboard_best_sales_date
            fill = SUCCESS if is_best else BLUE
            canvas.create_rectangle(x1, y1, x2, y2, fill=fill, outline="")
            if is_best:
                canvas.create_text(
                    x_center,
                    max(top + 10, y1 - 14),
                    text="Best",
                    fill=SUCCESS,
                    font=(FONT_BOLD, 8),
                )
            day_number = int(point["day"])
            if index == 0 or index == len(points) - 1 or day_number % label_interval == 0:
                canvas.create_text(x_center, y2 + 16, text=str(day_number), fill=MUTED, font=(FONT, 8))

        canvas.create_text(
            left,
            8,
            text="Selling amount by day",
            fill=TEXT,
            font=(FONT_BOLD, 10),
            anchor="nw",
        )

    def _refresh_employee_form_mode(self) -> None:
        editing = self.selected_employee_username is not None
        if self.employee_form_title_label is not None:
            self.employee_form_title_label.configure(text="Edit Employee" if editing else "Add New Employee")
        if self.employee_form_hint_label is not None:
            self.employee_form_hint_label.configure(
                text=(
                    "Editing selected employee. Type a password only if you want to replace it."
                    if editing
                    else "Create a new employee login. Leave password blank to auto-generate one."
                ),
                fg=BLUE if editing else MUTED,
            )
        if self.employee_save_button is not None:
            self.employee_save_button.configure(text="Save Employee" if editing else "Add Employee")

    def start_new_employee_form(self) -> None:
        self.clear_employee_form(focus_name=True)

    def _refresh_employee_active_status_label(self) -> None:
        label = self.employee_active_status_label
        if label is None:
            return
        if self.employee_active_var.get():
            label.configure(text="Employee Account is Active", fg=SUCCESS, bg="#eafaf4")
        else:
            label.configure(text="Employee Account is Not Active", fg=DANGER, bg="#fff1f3")

    def _refresh_employees(self) -> None:
        for item in self.employees_tree.get_children():
            self.employees_tree.delete(item)
        users = self.app.auth.list_users(include_admin=False)
        if self.employee_count_label is not None:
            employee_text = "employee" if len(users) == 1 else "employees"
            self.employee_count_label.configure(text=f"{len(users)} registered {employee_text}")
        valid_usernames = set()
        for user in users:
            username = user["username"]
            valid_usernames.add(username)
            status = "Active" if user["is_active"] else "Not Active"
            tag = "employee_active" if user["is_active"] else "employee_frozen"
            self.employees_tree.insert(
                "",
                "end",
                iid=username,
                tags=(tag,),
                values=(
                    user["display_name"],
                    username,
                    "Protected",
                    status,
                ),
            )
        if self.selected_employee_username not in valid_usernames:
            self.clear_employee_form()

    def _on_employee_selected(self, _event: tk.Event) -> None:
        selection = self.employees_tree.selection()
        if not selection:
            return
        username = selection[0]
        user = self.app.auth.get_user(username)
        if user is None:
            return
        self.selected_employee_username = username
        self.employee_name_var.set(user["display_name"])
        self.employee_username_var.set(user["username"])
        self.employee_password_var.set("")
        self.employee_active_var.set(bool(user["is_active"]))
        self._refresh_employee_active_status_label()
        self._refresh_employee_form_mode()
        if self.employee_password_status_label is not None:
            self.employee_password_status_label.configure(
                text="Password is protected. Use Reset Password to generate or set a new one.",
                fg=MUTED,
            )

    def clear_employee_form(self, focus_name: bool = False) -> None:
        self.selected_employee_username = None
        self.employee_name_var.set("")
        self.employee_username_var.set("")
        self.employee_password_var.set("")
        self.employee_active_var.set(True)
        self._refresh_employee_active_status_label()
        self._refresh_employee_form_mode()
        if self.employee_password_status_label is not None:
            self.employee_password_status_label.configure(
                text="Leave password blank to auto-generate one for new employees.",
                fg=MUTED,
            )
        if hasattr(self, "employees_tree"):
            self.employees_tree.selection_remove(*self.employees_tree.selection())
        if focus_name and self.employee_name_entry is not None:
            self.employee_name_entry.focus_set()

    def save_employee_user(self) -> None:
        name = self.employee_name_var.get().strip()
        username = self.employee_username_var.get().strip()
        password = self.employee_password_var.get().strip()
        if not username:
            show_app_alert(self, "Missing username", "Please add a username.", "warning")
            return
        if self.selected_employee_username is None:
            ok, message, created_password = self.app.auth.create_user(name, username, password or None)
            if not ok:
                show_app_alert(self, "Employee not saved", message, "warning")
                return
            self.employee_password_var.set(created_password)
            if self.employee_password_status_label is not None:
                self.employee_password_status_label.configure(
                    text=f"New password: {created_password}",
                    fg=SUCCESS,
                )
            self.selected_employee_username = username
            self.employee_active_var.set(True)
            self._refresh_employee_active_status_label()
            self._refresh_employee_form_mode()
            self._refresh_employees()
            self.employees_tree.selection_set(username)
            self.app.request_cloud_sync(push_local=True)
            show_app_alert(self, "Employee added", "Employee can now log in with the shown password.", "success")
            return

        if password and len(password) < 8:
            show_app_alert(self, "Password too short", "Password must be at least 8 characters.", "warning")
            return
        ok, message = self.app.auth.update_user(
            self.selected_employee_username,
            name,
            username,
            self.employee_active_var.get(),
        )
        if not ok:
            show_app_alert(self, "Employee not saved", message, "warning")
            return
        password_changed = False
        if password:
            ok, password_message, saved_password = self.app.auth.reset_user_password(username, password)
            if not ok:
                show_app_alert(self, "Password not saved", password_message, "warning")
                return
            self.employee_password_var.set(saved_password)
            password_changed = True
            if self.employee_password_status_label is not None:
                self.employee_password_status_label.configure(text=f"New password: {saved_password}", fg=SUCCESS)
        else:
            self.employee_password_var.set("")
        self.selected_employee_username = username
        self._refresh_employee_active_status_label()
        self._refresh_employee_form_mode()
        self._refresh_employees()
        self.employees_tree.selection_set(username)
        self.app.request_cloud_sync(push_local=True)
        alert_message = "Employee details and password were updated." if password_changed else message
        show_app_alert(self, "Employee updated", alert_message, "success")

    def reset_selected_employee_password(self) -> None:
        username = self.selected_employee_username
        if not username:
            show_app_alert(self, "No employee selected", "Select an employee first.", "warning")
            return
        requested_password = self.employee_password_var.get().strip() or None
        ok, message, new_password = self.app.auth.reset_user_password(username, requested_password)
        if not ok:
            show_app_alert(self, "Password not reset", message, "warning")
            return
        self.employee_password_var.set(new_password)
        if self.employee_password_status_label is not None:
            self.employee_password_status_label.configure(text=f"New password: {new_password}", fg=SUCCESS)
        self.app.request_cloud_sync(push_local=True)
        show_app_alert(self, "Password reset", "Give the shown password to the employee.", "success")

    def toggle_selected_employee_active(self) -> None:
        username = self.selected_employee_username
        if not username:
            show_app_alert(self, "No employee selected", "Select an employee first.", "warning")
            return
        user = self.app.auth.get_user(username)
        if user is None:
            show_app_alert(self, "Missing employee", "The selected employee could not be found.", "warning")
            return
        new_state = not bool(user["is_active"])
        ok, message = self.app.auth.set_user_active(username, new_state)
        if not ok:
            show_app_alert(self, "Status not changed", message, "warning")
            return
        self.employee_active_var.set(new_state)
        self._refresh_employee_active_status_label()
        self._refresh_employees()
        self.employees_tree.selection_set(username)
        self.app.request_cloud_sync(push_local=True)
        status = "active" if new_state else "frozen"
        show_app_alert(self, "Employee updated", f"Employee is now {status}.", "success")

    def remove_selected_employee(self) -> None:
        username = self.selected_employee_username
        if not username:
            show_app_alert(self, "No employee selected", "Select an employee first.", "warning")
            return
        if not messagebox.askyesno(
            "Remove employee",
            f"Remove '{username}' from the application login list?",
            parent=self,
        ):
            return
        ok, message = self.app.auth.delete_user(username)
        if not ok:
            show_app_alert(self, "Employee not removed", message, "warning")
            return
        self.clear_employee_form()
        self._refresh_employees()
        self.app.request_cloud_sync(push_local=True)
        show_app_alert(self, "Employee removed", message, "success")

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
        self.app.request_cloud_sync(push_local=True)
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
        self.app.request_cloud_sync(push_local=True)
        show_app_alert(
            self,
            success_title,
            "The employee can now open Client Messages and copy this format.",
            "success",
        )

    def clear_message_template_form(self) -> None:
        self.editing_template_id = None
        values = self._template_service_values()
        fallback = "Other"
        if len(values) > 1:
            fallback = values[1]
        self.template_service_var.set(fallback)
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
        if service_name in self._template_service_values():
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
        self.app.request_cloud_sync(push_local=True)
        show_app_alert(self, "Service message deactivated", "Employees will no longer see this message format.", "success")

    def _refresh_service_catalog_form_state(self) -> None:
        editing = self.editing_service_catalog_id is not None
        if self.service_catalog_form_title_label is not None:
            self.service_catalog_form_title_label.configure(text="Edit Item Sold" if editing else "Add Item Sold")
        if self.service_catalog_form_status_label is not None:
            if editing:
                self.service_catalog_form_status_label.configure(
                    text="Editing selected service. Existing sales rows stay unchanged.",
                    fg=BLUE,
                )
            else:
                self.service_catalog_form_status_label.configure(
                    text="Manage the services shown in the employee Items Sold dropdown.",
                    fg=MUTED,
                )
        if self.service_catalog_save_button is not None:
            self.service_catalog_save_button.configure(text="Save Changes" if editing else "Add Item")

    def save_service_catalog_item(self) -> None:
        service_name = self.service_catalog_name_var.get().strip()
        if not service_name:
            show_app_alert(self, "Missing service", "Please add the service name.", "warning")
            return
        try:
            if self.editing_service_catalog_id is None:
                saved = self.app.attendance_store.create_service_catalog_item(service_name, self.app.display_user)
                title = "Item added"
            else:
                saved = self.app.attendance_store.update_service_catalog_item(self.editing_service_catalog_id, service_name)
                title = "Item updated"
        except ValueError as exc:
            show_app_alert(self, "Item not saved", str(exc), "warning")
            return
        self.selected_service_catalog_id = int(saved["id"])
        self.clear_service_catalog_form(clear_selection=False)
        self._refresh_service_catalog()
        if self.service_catalog_tree is not None:
            self.service_catalog_tree.selection_set(str(saved["id"]))
            self.service_catalog_tree.focus(str(saved["id"]))
        self.app.request_cloud_sync(push_local=True)
        show_app_alert(self, title, "Employee Items Sold dropdown will use the updated list.", "success")

    def clear_service_catalog_form(self, clear_selection: bool = True) -> None:
        self.editing_service_catalog_id = None
        self.service_catalog_name_var.set("")
        if clear_selection and self.service_catalog_tree is not None:
            self.service_catalog_tree.selection_remove(*self.service_catalog_tree.selection())
            self.selected_service_catalog_id = None
        self._refresh_service_catalog_form_state()

    def edit_selected_service_catalog_item(self) -> None:
        item = self._service_catalog_by_id(self.selected_service_catalog_id)
        if item is None:
            show_app_alert(self, "No item selected", "Select an item sold first.", "warning")
            return
        self.editing_service_catalog_id = int(item["id"])
        self.service_catalog_name_var.set(item["service_name"])
        self._refresh_service_catalog_form_state()

    def remove_selected_service_catalog_item(self) -> None:
        item = self._service_catalog_by_id(self.selected_service_catalog_id)
        if item is None:
            show_app_alert(self, "No item selected", "Select an item sold first.", "warning")
            return
        service_name = item["service_name"]
        if not messagebox.askyesno(
            "Remove item sold",
            f"Remove '{service_name}' from the employee Items Sold dropdown? Existing sales entries will stay unchanged.",
            parent=self,
        ):
            return
        self.app.attendance_store.deactivate_service_catalog_item(int(item["id"]))
        if self.editing_service_catalog_id == int(item["id"]):
            self.clear_service_catalog_form(clear_selection=False)
        self.selected_service_catalog_id = None
        self._refresh_service_catalog()
        self.app.request_cloud_sync(push_local=True)
        show_app_alert(self, "Item removed", "Employees will no longer see this item in the dropdown.", "success")
    def _inventory_comment_value(self) -> str:
        if self.inventory_comment_text is None:
            return ""
        return self.inventory_comment_text.get("1.0", tk.END).strip()

    def _refresh_inventory_form_state(self) -> None:
        editing = self.editing_inventory_id is not None
        if self.inventory_form_title_label is not None:
            self.inventory_form_title_label.configure(text="Edit Inventory Item" if editing else "Add Inventory Item")
        if self.inventory_form_status_label is not None:
            if editing:
                self.inventory_form_status_label.configure(
                    text="Editing selected inventory item. Employees will see the update after cloud sync.",
                    fg=BLUE,
                )
            else:
                self.inventory_form_status_label.configure(
                    text="Add service credentials employees can view and copy from their Inventory panel.",
                    fg=MUTED,
                )
        if self.inventory_save_button is not None:
            self.inventory_save_button.configure(text="Save Changes" if editing else "Save Inventory")

    def save_inventory_item(self) -> None:
        service_name = self.inventory_service_var.get().strip()
        account_email = self.inventory_email_var.get().strip()
        account_password = self.inventory_password_var.get().strip()
        comment = self._inventory_comment_value()
        if not service_name:
            show_app_alert(self, "Missing service", "Please add the service name before saving.", "warning")
            return
        if not account_email:
            show_app_alert(self, "Missing email", "Please add the inventory email/account.", "warning")
            return
        if not account_password:
            show_app_alert(self, "Missing password", "Please add the inventory password.", "warning")
            return
        if self.editing_inventory_id is None:
            saved = self.app.attendance_store.create_inventory_item(
                service_name,
                account_email,
                account_password,
                comment,
                self.app.display_user,
            )
            success_title = "Inventory saved"
        else:
            saved = self.app.attendance_store.update_inventory_item(
                self.editing_inventory_id,
                service_name,
                account_email,
                account_password,
                comment,
            )
            success_title = "Inventory updated"
        self.selected_inventory_id = int(saved["id"])
        self.clear_inventory_form(clear_selection=False)
        self._refresh_inventory_items()
        if self.inventory_tree is not None:
            self.inventory_tree.selection_set(str(saved["id"]))
            self.inventory_tree.focus(str(saved["id"]))
        self.app.request_cloud_sync(push_local=True)
        show_app_alert(self, success_title, "Employees can now see this item in Inventory.", "success")

    def clear_inventory_form(self, clear_selection: bool = True) -> None:
        self.editing_inventory_id = None
        self.inventory_service_var.set("")
        self.inventory_email_var.set("")
        self.inventory_password_var.set("")
        if self.inventory_comment_text is not None:
            self.inventory_comment_text.delete("1.0", tk.END)
        if clear_selection and self.inventory_tree is not None:
            self.inventory_tree.selection_remove(*self.inventory_tree.selection())
            self.selected_inventory_id = None
            self._set_inventory_preview(None)
        self._refresh_inventory_form_state()

    def edit_selected_inventory_item(self) -> None:
        item = self._inventory_by_id(self.selected_inventory_id)
        if item is None:
            show_app_alert(self, "No inventory selected", "Select an inventory item first.", "warning")
            return
        self.editing_inventory_id = int(item["id"])
        self.inventory_service_var.set(item["service_name"])
        self.inventory_email_var.set(item["account_email"])
        self.inventory_password_var.set(item["account_password"])
        if self.inventory_comment_text is not None:
            self.inventory_comment_text.delete("1.0", tk.END)
            self.inventory_comment_text.insert("1.0", item.get("comment", ""))
        self._refresh_inventory_form_state()

    def deactivate_selected_inventory_item(self) -> None:
        item = self._inventory_by_id(self.selected_inventory_id)
        if item is None:
            show_app_alert(self, "No inventory selected", "Select an inventory item first.", "warning")
            return
        label = f"{item['service_name']} / {item['account_email']}"
        if not messagebox.askyesno(
            "Deactivate inventory item",
            f"Deactivate '{label}' so employees no longer see it?",
            parent=self,
        ):
            return
        self.app.attendance_store.deactivate_inventory_item(int(item["id"]))
        if self.editing_inventory_id == int(item["id"]):
            self.clear_inventory_form(clear_selection=False)
        self.selected_inventory_id = None
        self._refresh_inventory_items()
        self.app.request_cloud_sync(push_local=True)
        show_app_alert(self, "Inventory deactivated", "Employees will no longer see this item.", "success")
    def _refresh_cloud_settings(self) -> None:
        config = self.app.load_supabase_config()
        self.supabase_enabled_var.set(config.enabled)
        self.supabase_url_var.set(config.url)
        self.supabase_anon_key_var.set(config.anon_key)
        self.supabase_admin_secret_var.set(config.admin_secret)
        self.supabase_employee_sync_secret_var.set(config.employee_sync_secret)
        if self.cloud_sync_status_label is not None:
            if config.is_ready:
                if config.can_push:
                    message = "Cloud sync is enabled. This admin device can push employee accounts, announcements, inventory, and service messages."
                else:
                    message = "Cloud sync is enabled for reading. Add the admin write secret to push admin changes."
                if not config.can_pull_users:
                    message += " Add the employee sync secret to receive employee account updates."
                self.cloud_sync_status_label.configure(text=message, fg=SUCCESS)
            else:
                self.cloud_sync_status_label.configure(
                    text="Cloud sync is not configured yet. Paste the Supabase Project URL and anon public key, then save.",
                    fg=MUTED,
                )

    def set_cloud_sync_status(self, message: str, ok: bool = True) -> None:
        if self.cloud_sync_status_label is not None:
            self.cloud_sync_status_label.configure(text=message, fg=SUCCESS if ok else DANGER)

    def save_cloud_settings(self) -> None:
        config = SupabaseConfig(
            enabled=self.supabase_enabled_var.get(),
            url=self.supabase_url_var.get().strip(),
            anon_key=self.supabase_anon_key_var.get().strip(),
            admin_secret=self.supabase_admin_secret_var.get().strip(),
            employee_sync_secret=self.supabase_employee_sync_secret_var.get().strip(),
        )
        if config.enabled and (not config.url or not config.anon_key):
            show_app_alert(self, "Missing Supabase settings", "Project URL and anon public key are required.", "warning")
            return
        path = self.app.save_supabase_config(config, write_file=True)
        self._refresh_cloud_settings()
        message = "Cloud sync settings were saved for this device."
        if path is not None:
            message += f"\nConfig file: {path}"
        show_app_alert(self, "Cloud settings saved", message, "success")
        self.app.request_cloud_sync(push_local=True)

    def run_cloud_sync_now(self) -> None:
        self.set_cloud_sync_status("Cloud sync is running...", ok=True)
        self.app.request_cloud_sync(push_local=True)

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

        # The workbook target is a local setting per installation - a fresh
        # install (or a packaged .exe, which uses a different data folder
        # than running from source) starts with no target saved and silently
        # falls back to a private local file. Flag that clearly instead of
        # letting it look identical to a real configured target.
        configured_path = self.app.attendance_store.get_setting("sales_workbook_path", "")
        if not configured_path:
            self.excel_status_label.configure(
                text=(
                    "Status: NOT CONFIGURED on this install.\n"
                    f"Sales entries are being saved only to a private local file on this PC ({workbook.display_path}), "
                    "not your shared workbook. Set the workbook above and click Save Target to fix this."
                ),
                fg=DANGER,
            )
            return

        if workbook.display_path.lower().startswith(("http://", "https://")):
            file_state = "cloud workbook URL"
        else:
            path = Path(workbook.display_path)
            file_state = "file found" if path.exists() else "file will be created"
        sheet_state = workbook.worksheet_name or "active sheet"
        self.excel_status_label.configure(
            text=f"Workbook: {workbook.display_path}\nWorksheet: {sheet_state}\nStatus: {file_state}",
            fg=TEXT,
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

    def _refresh_service_catalog(self) -> None:
        self._refresh_service_dropdown_values()
        if self.service_catalog_tree is None:
            return
        for item in self.service_catalog_tree.get_children():
            self.service_catalog_tree.delete(item)
        self.admin_service_catalog_items = self.app.attendance_store.list_service_catalog(limit=500, active_only=True)
        valid_ids: set[int] = set()
        first_id: int | None = None
        for index, item in enumerate(self.admin_service_catalog_items):
            item_id = int(item["id"])
            valid_ids.add(item_id)
            if first_id is None:
                first_id = item_id
            tag = "service_even" if index % 2 == 0 else "service_odd"
            self.service_catalog_tree.insert(
                "",
                "end",
                iid=str(item_id),
                tags=(tag,),
                values=(item["service_name"], self._format_datetime(item["updated_at"])),
            )
        if self.selected_service_catalog_id in valid_ids:
            self.service_catalog_tree.selection_set(str(self.selected_service_catalog_id))
            self.service_catalog_tree.focus(str(self.selected_service_catalog_id))
            return
        self.selected_service_catalog_id = first_id
        if first_id is not None:
            self.service_catalog_tree.selection_set(str(first_id))
            self.service_catalog_tree.focus(str(first_id))
    def _refresh_inventory_items(self) -> None:
        if self.inventory_tree is None:
            return
        for item in self.inventory_tree.get_children():
            self.inventory_tree.delete(item)
        self.admin_inventory_items = self.app.attendance_store.list_inventory_items(limit=500)
        valid_ids: set[int] = set()
        first_id: int | None = None
        for index, item in enumerate(self.admin_inventory_items):
            item_id = int(item["id"])
            valid_ids.add(item_id)
            if first_id is None:
                first_id = item_id
            tag = "inventory_even" if index % 2 == 0 else "inventory_odd"
            self.inventory_tree.insert(
                "",
                "end",
                iid=str(item_id),
                tags=(tag,),
                values=(
                    item["service_name"],
                    item["account_email"],
                    self._format_datetime(item["updated_at"]),
                ),
            )
        if self.selected_inventory_id in valid_ids:
            self.inventory_tree.selection_set(str(self.selected_inventory_id))
            self.inventory_tree.focus(str(self.selected_inventory_id))
            self._set_inventory_preview(self._inventory_by_id(self.selected_inventory_id))
            return
        self.selected_inventory_id = first_id
        if first_id is not None:
            self.inventory_tree.selection_set(str(first_id))
            self.inventory_tree.focus(str(first_id))
            self._set_inventory_preview(self._inventory_by_id(first_id))
            return
        self._set_inventory_preview(None)
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
        if not self.winfo_exists():
            return
        while True:
            try:
                entry, sync_result = self.admin_excel_sync_results.get_nowait()
            except queue.Empty:
                break
            self._finish_admin_excel_sync(entry, sync_result)
        self._admin_excel_poll_after_id = self.after(250, self._poll_admin_excel_sync_results)

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

    def destroy(self) -> None:
        if self._admin_excel_poll_after_id is not None:
            try:
                self.after_cancel(self._admin_excel_poll_after_id)
            except tk.TclError:
                pass
            self._admin_excel_poll_after_id = None
        super().destroy()

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

    def _on_service_catalog_selected(self, _event: tk.Event) -> None:
        if self.service_catalog_tree is None:
            return
        selection = self.service_catalog_tree.selection()
        self.selected_service_catalog_id = int(selection[0]) if selection else None

    def _service_catalog_by_id(self, item_id: int | None) -> dict | None:
        if item_id is None:
            return None
        for item in self.admin_service_catalog_items:
            if int(item["id"]) == item_id:
                return item
        return None
    def _on_inventory_selected(self, _event: tk.Event) -> None:
        if self.inventory_tree is None:
            return
        selection = self.inventory_tree.selection()
        self.selected_inventory_id = int(selection[0]) if selection else None
        self._set_inventory_preview(self._inventory_by_id(self.selected_inventory_id))

    def _inventory_by_id(self, item_id: int | None) -> dict | None:
        if item_id is None:
            return None
        for item in self.admin_inventory_items:
            if int(item["id"]) == item_id:
                return item
        return None

    def _inventory_preview(self, item: dict) -> str:
        parts = [
            f"Service: {item.get('service_name', '')}",
            f"Email: {item.get('account_email', '')}",
            f"Password: {item.get('account_password', '')}",
        ]
        comment = str(item.get("comment", "")).strip()
        if comment:
            parts.extend(["", "Comment:", comment])
        return "\n".join(parts)

    def _set_inventory_preview(self, item: dict | None) -> None:
        if self.inventory_preview_text is None:
            return
        self.inventory_preview_text.configure(state="normal")
        self.inventory_preview_text.delete("1.0", tk.END)
        if item is None:
            self.inventory_preview_text.insert("1.0", "No active inventory items yet.")
        else:
            self.inventory_preview_text.insert("1.0", self._inventory_preview(item))
        self.inventory_preview_text.configure(state="disabled")
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
            return parse_local_datetime(value).strftime("%I:%M %p")
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
            return parse_local_datetime(value).strftime("%d %b, %I:%M %p")
        except ValueError:
            return value

    def _break_seconds(self, shift: dict) -> int:
        total = int(shift["total_break_seconds"])
        if shift["current_break_started_at"]:
            try:
                total += int((datetime.now() - parse_local_datetime(shift["current_break_started_at"])).total_seconds())
            except (ValueError, TypeError):
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
