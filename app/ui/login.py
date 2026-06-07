from __future__ import annotations

import tkinter as tk

from app.config import (
    BG,
    BLUE,
    BLUE_DARK,
    BUSINESS_NAME,
    CYAN,
    DEFAULT_USERNAME,
    FONT,
    FONT_BOLD,
    LINE,
    MUTED,
    NAVY,
    NAVY_2,
    TEAL,
    TEXT,
    WHITE,
)
from app.ui.widgets import SurfaceCard, blend, draw_gradient, field_label, make_button, text_entry
from app.utils import today_label


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
        self.username_var = tk.StringVar(value=DEFAULT_USERNAME)
        self.password_var = tk.StringVar()
        self.show_password_var = tk.BooleanVar(value=False)
        self._build()

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1, minsize=470)
        self.grid_columnconfigure(1, weight=2)
        self.grid_rowconfigure(0, weight=1)

        BrandCanvas(self, self.app).grid(row=0, column=0, sticky="nsew")

        right = tk.Frame(self, bg=BG)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(0, weight=1)

        panel = SurfaceCard(right, padx=48, pady=42, accent=True, accent_start=BLUE, accent_end=TEAL)
        panel.grid(row=0, column=0, sticky="", padx=62, pady=54)
        body = panel.body
        body.grid_columnconfigure(0, weight=1)

        tk.Label(body, text="Employee Login", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 26)).grid(row=0, column=0, sticky="w")
        tk.Label(body, text=today_label(), bg=WHITE, fg=MUTED, font=(FONT, 11)).grid(
            row=1, column=0, sticky="w", pady=(7, 28)
        )

        self.username_entry = self._entry(body, "Username", self.username_var, 2)
        self.password_entry = self._entry(body, "Password", self.password_var, 4, show="*")
        self.username_entry.focus_set()

        tk.Checkbutton(
            body,
            text="Show password",
            variable=self.show_password_var,
            command=self._toggle_password,
            bg=WHITE,
            fg=MUTED,
            activebackground=WHITE,
            font=(FONT, 10),
        ).grid(row=6, column=0, sticky="w", pady=(0, 18))

        make_button(body, "Sign In", self._submit_login, "primary").grid(row=7, column=0, sticky="ew", pady=(2, 12))

        forgot = tk.Button(
            body,
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
        forgot.grid(row=8, column=0, sticky="w")

        self.password_entry.bind("<Return>", lambda _event: self._submit_login())
        self.username_entry.bind("<Return>", lambda _event: self.password_entry.focus_set())

    def _entry(
        self,
        parent: tk.Misc,
        label: str,
        variable: tk.StringVar,
        row: int,
        show: str | None = None,
    ) -> tk.Entry:
        field_label(parent, label).grid(row=row, column=0, sticky="w")
        entry = text_entry(parent, variable, show=show)
        entry.configure(font=(FONT, 12))
        entry.grid(row=row + 1, column=0, sticky="ew", ipady=10, pady=(8, 18))
        return entry

    def _toggle_password(self) -> None:
        self.password_entry.configure(show="" if self.show_password_var.get() else "*")

    def _submit_login(self) -> None:
        self.app.login(self.username_var.get(), self.password_var.get())
