from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import shutil
import tkinter as tk
from tkinter import filedialog, ttk

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
    SUCCESS,
    TEAL,
    TEXT,
    WARNING,
    WHITE,
)
from app.ui.widgets import MetricCard, SurfaceCard, make_button, show_app_alert, status_pill
from app.utils import duration_label, today_label


class AdminPage(tk.Frame):
    def __init__(self, parent: tk.Misc, app) -> None:
        super().__init__(parent, bg=BG)
        self.app = app
        self.selected_shift_id: int | None = None
        self.announcement_category_var = tk.StringVar(value="General")
        self.announcement_title_var = tk.StringVar()
        self.excel_path_var = tk.StringVar()
        self.excel_sheet_var = tk.StringVar()
        self._build()

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_header()

        self.notebook = ttk.Notebook(self)
        self.notebook.grid(row=1, column=0, sticky="nsew", padx=18, pady=18)

        attendance_tab = tk.Frame(self.notebook, bg=BG, padx=0, pady=0)
        announcements_tab = tk.Frame(self.notebook, bg=BG, padx=0, pady=0)
        workbook_tab = tk.Frame(self.notebook, bg=BG, padx=0, pady=0)
        self.notebook.add(attendance_tab, text="Attendance")
        self.notebook.add(announcements_tab, text="Announcements")
        self.notebook.add(workbook_tab, text="Sales Workbook")

        self._build_attendance_tab(attendance_tab)
        self._build_announcements_tab(announcements_tab)
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
