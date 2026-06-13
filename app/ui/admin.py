from __future__ import annotations

from datetime import datetime
import tkinter as tk
from tkinter import ttk

from app.config import BG, BLUE, BLUE_DARK, FONT, FONT_BOLD, LINE, MUTED, NAVY, SUCCESS, TEAL, TEXT, WARNING, WHITE
from app.ui.widgets import GradientBand, GradientBanner, MetricCard, SurfaceCard, make_button, show_app_alert, status_pill
from app.utils import duration_label, today_label


class AdminPage(tk.Frame):
    def __init__(self, parent: tk.Misc, app) -> None:
        super().__init__(parent, bg=BG)
        self.app = app
        self.selected_shift_id: int | None = None
        self.announcement_category_var = tk.StringVar(value="General")
        self.announcement_title_var = tk.StringVar()
        self._build()

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        header = SurfaceCard(self, padx=0, pady=0, accent=False)
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(18, 0))
        header.body.configure(padx=0, pady=0)
        header.body.grid_columnconfigure(0, weight=1)

        banner = GradientBanner(
            header.body,
            "Admin Attendance Panel",
            "Review employee shift timing, breaks, first-shift closure, night shift activity, and checkout records.",
            height=128,
            start=NAVY,
            end=BLUE,
        )
        banner.grid(row=0, column=0, sticky="ew")

        top_actions = tk.Frame(header.body, bg=WHITE, padx=20, pady=14)
        top_actions.grid(row=1, column=0, sticky="ew")
        top_actions.grid_columnconfigure(0, weight=1)
        identity = tk.Frame(top_actions, bg=WHITE)
        identity.grid(row=0, column=0, sticky="w")
        tk.Label(identity, text="Owner Console", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 12)).pack(anchor="w")
        self.last_refresh_label = tk.Label(identity, text="", bg=WHITE, fg=MUTED, font=(FONT, 9))
        self.last_refresh_label.pack(anchor="w", pady=(3, 0))
        self.today_pill = status_pill(top_actions, today_label(), fg=BLUE_DARK, bg="#eef6ff")
        self.today_pill.grid(row=0, column=1, padx=(12, 10))
        make_button(top_actions, "Refresh", self.refresh_all, "primary").grid(row=0, column=2, padx=(0, 10))
        make_button(top_actions, "Logout", self.app.logout, "light").grid(row=0, column=3)

        metrics = tk.Frame(self, bg=BG)
        metrics.grid(row=1, column=0, sticky="ew", padx=18, pady=18)
        metrics.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="admin_metrics")
        self.total_shifts_card = MetricCard(metrics, "Total Shifts", "0", BLUE, "All saved shifts")
        self.total_shifts_card.grid(row=0, column=0, sticky="ew", padx=(0, 9))
        self.active_shift_card = MetricCard(metrics, "Active Shifts", "0", SUCCESS, "Currently checked in")
        self.active_shift_card.grid(row=0, column=1, sticky="ew", padx=3)
        self.breaks_card = MetricCard(metrics, "Breaks Logged", "0", WARNING, "Across visible shifts")
        self.breaks_card.grid(row=0, column=2, sticky="ew", padx=3)
        self.break_time_card = MetricCard(metrics, "Break Time", "0m", TEAL, "Total recorded break duration")
        self.break_time_card.grid(row=0, column=3, sticky="ew", padx=(9, 0))

        announcements = SurfaceCard(self, padx=18, pady=16, accent=True, accent_start=WARNING, accent_end=TEAL)
        announcements.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 18))
        ann = announcements.body
        ann.grid_columnconfigure(2, weight=1)
        tk.Label(ann, text="Employee Announcements", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 15)).grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 12)
        )
        ttk.Combobox(
            ann,
            values=["General", "Service Available", "Out of Stock", "Urgent", "Reminder"],
            textvariable=self.announcement_category_var,
            state="readonly",
            font=(FONT, 10),
            width=18,
        ).grid(row=1, column=0, sticky="ew", padx=(0, 10))
        tk.Entry(
            ann,
            textvariable=self.announcement_title_var,
            bg="#f8fbff",
            fg=TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=LINE,
            highlightcolor=BLUE,
            font=(FONT, 10),
        ).grid(row=1, column=1, sticky="ew", padx=(0, 10), ipady=8)
        self.announcement_message_text = tk.Text(
            ann,
            height=3,
            bg="#f8fbff",
            fg=TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=LINE,
            highlightcolor=BLUE,
            font=(FONT, 10),
            wrap="word",
        )
        self.announcement_message_text.grid(row=1, column=2, sticky="ew", padx=(0, 10))
        make_button(ann, "Send", self.send_announcement, "primary").grid(row=1, column=3, sticky="ew")
        self.announcement_recent_label = tk.Label(
            ann,
            text="Recent announcements: none",
            bg=WHITE,
            fg=MUTED,
            font=(FONT, 9),
            anchor="w",
            justify="left",
        )
        self.announcement_recent_label.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(10, 0))

        content = tk.Frame(self, bg=BG)
        content.grid(row=3, column=0, sticky="nsew", padx=18, pady=(0, 18))
        content.grid_columnconfigure(0, weight=3)
        content.grid_columnconfigure(1, weight=2)
        content.grid_rowconfigure(0, weight=1)

        shifts_card = SurfaceCard(content, padx=18, pady=16, accent=True, accent_start=BLUE, accent_end=TEAL)
        shifts_card.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        shifts = shifts_card.body
        shifts.grid_columnconfigure(0, weight=1)
        shifts.grid_rowconfigure(2, weight=1)
        shift_header = tk.Frame(shifts, bg=WHITE)
        shift_header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        shift_header.grid_columnconfigure(0, weight=1)
        tk.Label(shift_header, text="Attendance Sheet", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 16)).grid(
            row=0, column=0, sticky="w"
        )
        self.shift_count_label = tk.Label(shift_header, text="", bg=WHITE, fg=MUTED, font=(FONT, 9))
        self.shift_count_label.grid(row=1, column=0, sticky="w", pady=(4, 0))
        status_pill(shift_header, "SQLite Local", fg=BLUE_DARK, bg="#eef6ff").grid(row=0, column=1, rowspan=2, sticky="e")
        GradientBand(shifts, start=BLUE, end=TEAL, height=3).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 12))

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
            "id": 54,
            "date": 100,
            "employee": 110,
            "shift": 100,
            "status": 90,
            "check_in": 95,
            "check_out": 95,
            "breaks": 70,
            "break_time": 96,
        }
        for column in columns:
            self.shifts_tree.heading(column, text=headings[column])
            self.shifts_tree.column(column, width=widths[column], anchor="w")
        self.shifts_tree.tag_configure("active", background="#eafaf4", foreground=TEXT)
        self.shifts_tree.tag_configure("closed_even", background=WHITE, foreground=TEXT)
        self.shifts_tree.tag_configure("closed_odd", background="#f8fbff", foreground=TEXT)
        self.shifts_tree.grid(row=2, column=0, sticky="nsew")
        self.shifts_tree.bind("<<TreeviewSelect>>", self._on_shift_selected)

        shift_scroll = ttk.Scrollbar(shifts, orient="vertical", command=self.shifts_tree.yview)
        shift_scroll.grid(row=2, column=1, sticky="ns")
        self.shifts_tree.configure(yscrollcommand=shift_scroll.set)

        events_card = SurfaceCard(content, padx=18, pady=16, accent=True, accent_start=TEAL, accent_end=BLUE)
        events_card.grid(row=0, column=1, sticky="nsew")
        events = events_card.body
        events.grid_columnconfigure(0, weight=1)
        events.grid_rowconfigure(2, weight=1)
        event_header = tk.Frame(events, bg=WHITE)
        event_header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        event_header.grid_columnconfigure(0, weight=1)
        tk.Label(event_header, text="Shift Timeline", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 16)).grid(
            row=0, column=0, sticky="w"
        )
        self.timeline_context_label = tk.Label(
            event_header,
            text="Showing all recorded shift events",
            bg=WHITE,
            fg=MUTED,
            font=(FONT, 9),
        )
        self.timeline_context_label.grid(row=1, column=0, sticky="w", pady=(4, 0))
        GradientBand(events, start=TEAL, end=BLUE, height=3).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 12))

        self.events_tree = ttk.Treeview(events, columns=("date", "time", "shift", "event", "details"), show="headings")
        self.events_tree.heading("date", text="Date")
        self.events_tree.heading("time", text="Time")
        self.events_tree.heading("shift", text="Shift")
        self.events_tree.heading("event", text="Event")
        self.events_tree.heading("details", text="Details")
        self.events_tree.column("date", width=92, anchor="w")
        self.events_tree.column("time", width=92, anchor="w")
        self.events_tree.column("shift", width=88, anchor="w")
        self.events_tree.column("event", width=130, anchor="w")
        self.events_tree.column("details", width=240, anchor="w")
        self.events_tree.tag_configure("check_in", background="#eafaf4", foreground=TEXT)
        self.events_tree.tag_configure("break", background="#fff8ea", foreground=TEXT)
        self.events_tree.tag_configure("close", background="#eef6ff", foreground=TEXT)
        self.events_tree.tag_configure("default_even", background=WHITE, foreground=TEXT)
        self.events_tree.tag_configure("default_odd", background="#f8fbff", foreground=TEXT)
        self.events_tree.grid(row=2, column=0, sticky="nsew")

        event_scroll = ttk.Scrollbar(events, orient="vertical", command=self.events_tree.yview)
        event_scroll.grid(row=2, column=1, sticky="ns")
        self.events_tree.configure(yscrollcommand=event_scroll.set)

    def refresh_all(self) -> None:
        self.today_pill.configure(text=today_label())
        self.last_refresh_label.configure(text=f"Last refreshed {datetime.now().strftime('%I:%M %p')}")
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

    def _refresh_announcements(self) -> None:
        announcements = self.app.attendance_store.list_announcements(limit=3)
        if not announcements:
            self.announcement_recent_label.configure(text="Recent announcements: none")
            return
        parts = []
        for announcement in announcements:
            created = self._format_time(announcement["created_at"])
            parts.append(f"{created} - {announcement['category']}: {announcement['title']}")
        self.announcement_recent_label.configure(text="Recent announcements: " + "  |  ".join(parts))

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
