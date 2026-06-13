from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from app.config import (
    BG,
    BLUE,
    BLUE_DARK,
    CYAN,
    DANGER,
    FONT,
    FONT_BOLD,
    LINE,
    MUTED,
    NAVY,
    NAVY_2,
    NAVY_LIGHT,
    SIDEBAR_ACTIVE_TEXT,
    SIDEBAR_BG,
    SIDEBAR_DISABLED,
    SIDEBAR_DISABLED_TEXT,
    SIDEBAR_HOVER,
    SIDEBAR_SURFACE_2,
    SIDEBAR_TEXT,
    SUCCESS,
    TEAL,
    TEXT,
    WARNING,
    WHITE,
)


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


def blend(start: str, end: str, ratio: float) -> str:
    ratio = max(0.0, min(1.0, ratio))
    start_rgb = _hex_to_rgb(start)
    end_rgb = _hex_to_rgb(end)
    rgb = tuple(round(start_rgb[i] + (end_rgb[i] - start_rgb[i]) * ratio) for i in range(3))
    return _rgb_to_hex(rgb)  # type: ignore[arg-type]


def draw_gradient(
    canvas: tk.Canvas,
    width: int,
    height: int,
    start: str,
    end: str,
    direction: str = "horizontal",
) -> None:
    canvas.delete("gradient")
    steps = max(width if direction == "horizontal" else height, 1)
    for step in range(steps):
        color = blend(start, end, step / max(steps - 1, 1))
        if direction == "horizontal":
            canvas.create_line(step, 0, step, height, fill=color, tags="gradient")
        else:
            canvas.create_line(0, step, width, step, fill=color, tags="gradient")
    canvas.tag_lower("gradient")


class GradientBand(tk.Canvas):
    def __init__(
        self,
        parent: tk.Misc,
        start: str = BLUE,
        end: str = TEAL,
        height: int = 6,
        direction: str = "horizontal",
        **kwargs,
    ) -> None:
        super().__init__(
            parent,
            height=height,
            bg=start,
            bd=0,
            highlightthickness=0,
            relief="flat",
            **kwargs,
        )
        self.start = start
        self.end = end
        self.direction = direction
        self.bind("<Configure>", self._redraw)

    def _redraw(self, _event: tk.Event | None = None) -> None:
        draw_gradient(self, max(self.winfo_width(), 1), max(self.winfo_height(), 1), self.start, self.end, self.direction)


class GradientBanner(tk.Canvas):
    def __init__(
        self,
        parent: tk.Misc,
        title: str,
        subtitle: str,
        height: int = 132,
        start: str = NAVY,
        end: str = BLUE,
        **kwargs,
    ) -> None:
        super().__init__(parent, height=height, bg=start, bd=0, highlightthickness=0, relief="flat", **kwargs)
        self.title = title
        self.subtitle = subtitle
        self.start = start
        self.end = end
        self.bind("<Configure>", self._redraw)

    def set_text(self, title: str, subtitle: str) -> None:
        self.title = title
        self.subtitle = subtitle
        self._redraw()

    def _redraw(self, _event: tk.Event | None = None) -> None:
        width = max(self.winfo_width(), 1)
        height = max(self.winfo_height(), 1)
        draw_gradient(self, width, height, self.start, self.end, "horizontal")
        self.delete("detail")
        self.create_polygon(
            width * 0.62,
            0,
            width,
            0,
            width,
            height,
            width * 0.76,
            height,
            fill=blend(BLUE_DARK, CYAN, 0.32),
            outline="",
            tags="detail",
        )
        for offset, color in ((0, TEAL), (18, blend(WHITE, BLUE, 0.42)), (36, blend(NAVY, BLUE, 0.25))):
            self.create_line(
                width * 0.64 + offset,
                18,
                width * 0.86 + offset,
                height - 18,
                fill=color,
                width=2,
                tags="detail",
            )
        self.create_text(
            26,
            34,
            anchor="nw",
            text=self.title,
            fill=WHITE,
            font=(FONT_BOLD, 20),
            tags="detail",
        )
        self.create_text(
            28,
            73,
            anchor="nw",
            text=self.subtitle,
            fill="#d9edff",
            font=(FONT, 10),
            tags="detail",
            width=max(280, int(width * 0.56)),
        )


class SurfaceCard(tk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        padx: int = 18,
        pady: int = 16,
        accent: bool = True,
        accent_start: str = BLUE,
        accent_end: str = TEAL,
        **kwargs,
    ) -> None:
        super().__init__(
            parent,
            bg=WHITE,
            highlightbackground=LINE,
            highlightthickness=1,
            bd=0,
            **kwargs,
        )
        if accent:
            GradientBand(self, start=accent_start, end=accent_end, height=4).pack(fill="x")
        self.body = tk.Frame(self, bg=WHITE, padx=padx, pady=pady)
        self.body.pack(fill="both", expand=True)


class MetricCard(SurfaceCard):
    def __init__(
        self,
        parent: tk.Misc,
        title: str,
        value: str,
        accent_color: str,
        helper: str = "",
        **kwargs,
    ) -> None:
        super().__init__(parent, padx=18, pady=16, accent=True, accent_start=accent_color, accent_end=TEAL, **kwargs)
        self.body.grid_columnconfigure(0, weight=1)
        tk.Label(self.body, text=title, bg=WHITE, fg=MUTED, font=(FONT_BOLD, 10)).grid(row=0, column=0, sticky="w")
        self.value_label = tk.Label(self.body, text=value, bg=WHITE, fg=accent_color, font=(FONT_BOLD, 22))
        self.value_label.grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.helper_label = tk.Label(self.body, text=helper, bg=WHITE, fg=MUTED, font=(FONT, 9))
        self.helper_label.grid(row=2, column=0, sticky="w", pady=(4, 0))


def make_button(
    parent: tk.Misc,
    text: str,
    command,
    variant: str = "primary",
    width: int | None = None,
    anchor: str = "center",
) -> tk.Button:
    palettes = {
        "primary": (BLUE, BLUE_DARK, WHITE),
        "nav": (NAVY_LIGHT, BLUE, WHITE),
        "sidebar": (SIDEBAR_SURFACE_2, SIDEBAR_HOVER, SIDEBAR_TEXT),
        "sidebar_active": ("#eaf3ff", "#d7e9ff", SIDEBAR_ACTIVE_TEXT),
        "light": ("#eaf2ff", "#dbeaff", BLUE_DARK),
        "danger": (DANGER, "#a8323d", WHITE),
        "success": (SUCCESS, "#0a724f", WHITE),
        "warning": (WARNING, "#98610d", WHITE),
        "ghost": (WHITE, "#eff5ff", TEXT),
    }
    bg, active_bg, fg = palettes.get(variant, palettes["primary"])
    button = tk.Button(
        parent,
        text=text,
        command=command,
        width=width,
        bg=bg,
        fg=fg,
        activebackground=active_bg,
        activeforeground=fg,
        relief="flat",
        bd=0,
        cursor="hand2",
        font=(FONT_BOLD, 10),
        padx=14,
        pady=10,
        disabledforeground="#8b9ab2",
        highlightthickness=0,
        anchor=anchor,
    )
    button.normal_bg = bg  # type: ignore[attr-defined]
    button.hover_bg = active_bg  # type: ignore[attr-defined]
    button.enabled_fg = fg  # type: ignore[attr-defined]
    if variant.startswith("sidebar"):
        button.disabled_bg = SIDEBAR_DISABLED  # type: ignore[attr-defined]
        button.disabled_fg = SIDEBAR_DISABLED_TEXT  # type: ignore[attr-defined]
    else:
        button.disabled_bg = "#e7edf6"  # type: ignore[attr-defined]
        button.disabled_fg = "#8b9ab2"  # type: ignore[attr-defined]
    button.bind(
        "<Enter>",
        lambda _event: button.configure(bg=button.hover_bg) if str(button["state"]) == "normal" else None,  # type: ignore[attr-defined]
    )
    button.bind(
        "<Leave>",
        lambda _event: button.configure(bg=button.normal_bg) if str(button["state"]) == "normal" else None,  # type: ignore[attr-defined]
    )
    return button


def set_button_enabled(button: tk.Button, enabled: bool) -> None:
    if enabled:
        button.configure(
            state="normal",
            cursor="hand2",
            bg=button.normal_bg,  # type: ignore[attr-defined]
            fg=button.enabled_fg,  # type: ignore[attr-defined]
            activeforeground=button.enabled_fg,  # type: ignore[attr-defined]
        )
        return
    button.configure(
        state="disabled",
        cursor="arrow",
        bg=button.disabled_bg,  # type: ignore[attr-defined]
        fg=button.disabled_fg,  # type: ignore[attr-defined]
        activeforeground=button.disabled_fg,  # type: ignore[attr-defined]
    )


def show_app_alert(
    parent: tk.Misc,
    title: str,
    message: str,
    kind: str = "success",
    duration_ms: int | None = 3600,
) -> tk.Frame:
    palettes = {
        "success": (SUCCESS, TEAL, "#eafaf4", "SENT"),
        "warning": (WARNING, "#e5a322", "#fff6e8", "CHECK"),
        "danger": (DANGER, "#e05a66", "#fff1f3", "ERROR"),
        "info": (BLUE, TEAL, "#eef6ff", "INFO"),
    }
    accent, accent_end, soft_bg, label = palettes.get(kind, palettes["info"])

    for child in parent.winfo_children():
        if getattr(child, "is_app_alert", False):
            child.destroy()

    alert = tk.Frame(
        parent,
        bg=WHITE,
        highlightbackground=blend(accent, LINE, 0.45),
        highlightthickness=1,
        bd=0,
    )
    alert.is_app_alert = True  # type: ignore[attr-defined]

    def dismiss() -> None:
        if alert.winfo_exists():
            alert.destroy()

    GradientBand(alert, start=accent, end=accent_end, height=4).pack(fill="x")
    body = tk.Frame(alert, bg=WHITE, padx=16, pady=14)
    body.pack(fill="both", expand=True)
    body.grid_columnconfigure(1, weight=1)

    badge = tk.Label(
        body,
        text=label,
        bg=soft_bg,
        fg=accent,
        font=(FONT_BOLD, 8),
        padx=10,
        pady=4,
    )
    badge.grid(row=0, column=0, rowspan=2, sticky="nw", padx=(0, 12))

    tk.Label(body, text=title, bg=WHITE, fg=TEXT, font=(FONT_BOLD, 13)).grid(row=0, column=1, sticky="w")
    tk.Label(
        body,
        text=message,
        bg=WHITE,
        fg=MUTED,
        font=(FONT, 10),
        justify="left",
        wraplength=310,
    ).grid(row=1, column=1, sticky="w", pady=(4, 0))
    tk.Button(
        body,
        text="X",
        command=dismiss,
        bg=WHITE,
        fg=MUTED,
        activebackground="#eff5ff",
        activeforeground=TEXT,
        relief="flat",
        bd=0,
        cursor="hand2",
        font=(FONT_BOLD, 9),
        padx=8,
        pady=3,
        highlightthickness=0,
    ).grid(row=0, column=2, sticky="ne", padx=(12, 0))

    parent.update_idletasks()
    parent_width = max(parent.winfo_width(), 392)
    alert_width = min(460, max(360, parent_width - 48))
    alert.place(relx=1.0, x=-24, y=24, anchor="ne", width=alert_width)
    alert.lift()
    if duration_ms:
        alert.after(duration_ms, dismiss)
    return alert


def field_label(parent: tk.Misc, text: str) -> tk.Label:
    return tk.Label(parent, text=text, bg=WHITE, fg=TEXT, font=(FONT_BOLD, 10))


def text_entry(parent: tk.Misc, variable: tk.StringVar, show: str | None = None) -> tk.Entry:
    return tk.Entry(
        parent,
        textvariable=variable,
        show=show or "",
        bg="#f8fbff",
        fg=TEXT,
        relief="flat",
        highlightthickness=1,
        highlightbackground=LINE,
        highlightcolor=BLUE,
        font=(FONT, 11),
        insertbackground=TEXT,
    )


def combo_box(parent: tk.Misc, variable: tk.StringVar, values: list[str]) -> ttk.Combobox:
    return ttk.Combobox(parent, values=values, textvariable=variable, state="readonly", font=(FONT, 10))


def status_pill(parent: tk.Misc, text: str, fg: str = BLUE, bg: str = "#eef6ff") -> tk.Label:
    return tk.Label(parent, text=text, bg=bg, fg=fg, font=(FONT_BOLD, 9), padx=12, pady=5)


def section_title(parent: tk.Misc, title: str, subtitle: str = "") -> tuple[tk.Label, tk.Label | None]:
    title_label = tk.Label(parent, text=title, bg=WHITE, fg=TEXT, font=(FONT_BOLD, 18))
    subtitle_label = None
    if subtitle:
        subtitle_label = tk.Label(parent, text=subtitle, bg=WHITE, fg=MUTED, font=(FONT, 10))
    return title_label, subtitle_label


def configure_treeview(style: ttk.Style) -> None:
    style.configure("Treeview", font=(FONT, 10), rowheight=32, background=WHITE, fieldbackground=WHITE, borderwidth=0)
    style.configure("Treeview.Heading", font=(FONT_BOLD, 10), background="#e7f0ff", foreground=TEXT, relief="flat")
    style.map("Treeview", background=[("selected", BLUE)], foreground=[("selected", WHITE)])
    style.configure("TCombobox", fieldbackground=WHITE, background=WHITE, foreground=TEXT)
