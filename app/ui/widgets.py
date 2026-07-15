from __future__ import annotations

import re
import tkinter as tk
from tkinter import font as tkfont, ttk

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
        subtitle_id = self.create_text(
            28,
            73,
            anchor="nw",
            text=self.subtitle,
            fill="#d9edff",
            font=(FONT, 10),
            tags="detail",
            width=max(280, int(width * 0.56)),
        )
        # The subtitle can wrap to a second line on a narrow window even
        # though the fixed `height` passed at construction only budgeted for
        # one - measure the actual wrapped text and grow the banner to fit
        # instead of letting the second line clip and overlap whatever sits
        # below it. Only grows, never shrinks, to avoid fighting the next
        # <Configure> this triggers.
        bounds = self.bbox(subtitle_id)
        if bounds is not None:
            needed_height = bounds[3] + 20
            if needed_height > height + 2:
                self.configure(height=needed_height)


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


def add_tooltip(widget: tk.Widget, text_provider) -> None:
    """Show a small dark tooltip beside the widget after a short hover pause.

    text_provider is called at show time; returning an empty string skips
    the tooltip - used for buttons that only need explaining while they are
    icon-only (collapsed sidebar).
    """
    state: dict[str, object] = {"after": None, "window": None}

    def _hide(_event: tk.Event | None = None) -> None:
        if state["after"] is not None:
            try:
                widget.after_cancel(state["after"])
            except tk.TclError:
                pass
            state["after"] = None
        window = state["window"]
        state["window"] = None
        if window is not None:
            try:
                window.destroy()
            except tk.TclError:
                pass

    def _show() -> None:
        state["after"] = None
        try:
            text = str(text_provider() or "")
            if not text or not widget.winfo_ismapped():
                return
        except tk.TclError:
            return
        window = tk.Toplevel(widget)
        try:
            # Hidden until fully positioned - otherwise a failure between
            # creation and geometry leaves a stray unstyled window floating
            # at the top-left of the screen.
            window.withdraw()
            window.overrideredirect(True)
            window.attributes("-topmost", True)
            label = tk.Label(window, text=text, bg=NAVY, fg=WHITE, font=(FONT, 9), padx=10, pady=5)
            label.pack()
            x = widget.winfo_rootx() + widget.winfo_width() + 10
            y = widget.winfo_rooty() + (widget.winfo_height() - label.winfo_reqheight()) // 2
            window.geometry(f"+{x}+{y}")
            window.deiconify()
            state["window"] = window
        except tk.TclError:
            try:
                window.destroy()
            except tk.TclError:
                pass

    def _schedule(_event: tk.Event | None = None) -> None:
        _hide()
        state["after"] = widget.after(450, _show)

    widget.bind("<Enter>", _schedule, add="+")
    widget.bind("<Leave>", _hide, add="+")
    widget.bind("<ButtonPress>", _hide, add="+")


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


def combo_box(
    parent: tk.Misc,
    variable: tk.StringVar,
    values: list[str],
    searchable: bool = False,
) -> ttk.Combobox:
    combo = ttk.Combobox(
        parent,
        values=values,
        textvariable=variable,
        state="normal" if searchable else "readonly",
        font=(FONT, 10),
    )
    # Marker for enable/disable cycles: a searchable combo must come back as
    # "normal" (typeable), not "readonly", or the type-to-filter dies the
    # first time the form is toggled.
    combo.searchable = searchable
    _fit_combo_popdown(combo)
    if searchable:
        _enable_combo_search(combo)
    return combo


def _fit_combo_popdown(combo: ttk.Combobox) -> None:
    """Widen the dropdown list to fully show the longest value.

    Tk sizes the popdown list to exactly the combobox's own width, so on a
    narrow field a long value like "Adobe Creative Cloud Monthly Shared"
    gets clipped to "Adobe Creative Cloud Monthly" with no way to tell the
    variants apart. This re-applies the popdown geometry right as it opens,
    widened to fit the longest current value.
    """
    popdown = str(combo.tk.call("ttk::combobox::PopdownWindow", combo))

    def _widen() -> None:
        try:
            values = [str(value) for value in (combo.cget("values") or ())]
            if not values:
                return
            font_spec = str(combo.cget("font")) or "TkTextFont"
            font_obj = tkfont.Font(root=combo, font=font_spec)
            # Longest value plus room for the scrollbar and listbox padding.
            needed = max(font_obj.measure(value) for value in values) + 48
            geometry = str(combo.tk.call("wm", "geometry", popdown))
            match = re.fullmatch(r"(\d+)x(\d+)([+-]-?\d+)([+-]-?\d+)", geometry)
            if match is None:
                return
            width_text, height_text, x_text, y_text = match.groups()
            width = max(int(width_text), needed)
            # Keep the widened list on-screen if the field sits near the
            # right edge.
            x_position = int(x_text.lstrip("+"))
            x_position = max(0, min(x_position, combo.winfo_screenwidth() - width))
            combo.tk.call("wm", "geometry", popdown, f"{width}x{height_text}{x_position:+d}{y_text}")
        except (tk.TclError, ValueError):
            pass

    combo.tk.call("bind", popdown, "<Map>", "+" + str(combo.register(_widen)))
    # Exposed so the type-to-filter logic can re-apply the width after it
    # re-posts an already-open popdown (re-posting re-applies the stock
    # narrow geometry, and <Map> only fires on the first open).
    combo.widen_popdown = _widen


def _enable_combo_search(combo: ttk.Combobox) -> None:
    """Let the user type into the combobox to filter the dropdown list.

    Typing narrows the list to values starting with the typed text
    (case-insensitive) and OPENS the dropdown right away so the matches are
    visible while typing - no need to click the arrow. Clearing the text,
    picking a value, or leaving the field restores the full list. Values
    reconfigured externally (e.g. a service catalog refresh) are picked up
    as the new full list automatically.
    """
    popdown = str(combo.tk.call("ttk::combobox::PopdownWindow", combo))
    popdown_listbox = f"{popdown}.f.l"
    state: dict[str, list[str] | None] = {
        "full": [str(value) for value in (combo.cget("values") or ())],
        "filtered": None,
    }

    def _popdown_open() -> bool:
        try:
            return bool(int(combo.tk.call("winfo", "ismapped", popdown)))
        except tk.TclError:
            return False

    def _sync_full() -> None:
        current = [str(value) for value in (combo.cget("values") or ())]
        if state["filtered"] is None or current != state["filtered"]:
            state["full"] = current

    def _restore_full_values() -> None:
        _sync_full()
        if state["filtered"] is not None:
            # Reconfiguring -values makes Tk rewrite the displayed text to
            # the value at the remembered current INDEX - which points at a
            # different item once the filtered list is swapped for the full
            # one (picking "Capcut..." at filtered index 0 turned into the
            # full list's index 0, "5G IPTV..."). Preserve the text.
            text = combo.get()
            combo.configure(values=state["full"])
            state["filtered"] = None
            if combo.get() != text:
                combo.set(text)

    def _on_selected(_event: tk.Event | None = None) -> None:
        _restore_full_values()

    def _interacting_with_popdown() -> bool:
        # A click inside the suggestion list (or Down-key focus handoff)
        # fires FocusOut on the entry BEFORE the selection completes -
        # closing/restoring at that moment kills the selection mid-click.
        try:
            if str(combo.tk.call("focus")).startswith(popdown):
                return True
            pointer_x = combo.winfo_pointerx()
            pointer_y = combo.winfo_pointery()
            under = str(combo.tk.call("winfo", "containing", pointer_x, pointer_y))
            return under.startswith(popdown)
        except tk.TclError:
            return False

    def _on_focus_out(_event: tk.Event | None = None) -> None:
        # Leaving the field closes the list and brings the full set back
        # for the next open.
        if _interacting_with_popdown():
            return
        if _popdown_open():
            try:
                combo.tk.call("ttk::combobox::Unpost", combo)
            except tk.TclError:
                pass
        _restore_full_values()

    # The popup list normally steals keyboard focus the moment it appears
    # (class binding: <Map> -> focus -force) and cancels itself as soon as
    # it loses that focus again (<FocusOut> -> LBCancel). For a
    # type-to-filter box both behaviors are wrong: focus must STAY in the
    # text entry while the list is open. A widget-level "break" runs before
    # the class binding and stops the focus steal - and with the list never
    # focused, it never self-cancels either. Mouse selection still works
    # (it doesn't need focus), and pressing Down still hands the list focus
    # for arrow-key navigation.
    combo.tk.call("bind", popdown_listbox, "<Map>", "break")

    def _lb_click_select(x: str, y: str) -> None:
        # Select by the TEXT of the clicked item. The stock handler selects
        # by index into the combobox -values, which points at the wrong
        # item whenever the values were swapped between press and release
        # (e.g. clicking "Capcut..." at filtered index 0 used to come back
        # as the full list's index 0, "5G IPTV...").
        try:
            index = combo.tk.call(popdown_listbox, "index", f"@{x},{y}")
            text = str(combo.tk.call(popdown_listbox, "get", index))
        except tk.TclError:
            text = ""
        _close_list()
        if text:
            combo.set(text)
            combo.icursor("end")
            combo.event_generate("<<ComboboxSelected>>")

    # Widget-level binding runs before the class one; the trailing "break"
    # suppresses the stock index-based selection entirely.
    combo.tk.call(
        "bind",
        popdown_listbox,
        "<ButtonRelease-1>",
        f"{combo.register(_lb_click_select)} %x %y\nbreak",
    )

    def _show_matches() -> None:
        # (Re)post on every keystroke: Post copies the combobox's current
        # -values into the popup list AND recomputes the list height and
        # placement. Without the re-post, a popup opened while one item
        # matched stayed one row tall forever - backspacing to a broader
        # search showed just the first match with the rest hidden.
        try:
            combo.tk.call("ttk::combobox::Post", combo)
        except tk.TclError:
            return
        widen = getattr(combo, "widen_popdown", None)
        if callable(widen):
            widen()

    def _filter(event: tk.Event) -> None:
        if event.keysym in {"Up", "Down", "Return", "Escape", "Tab", "Left", "Right", "Home", "End"}:
            return
        _sync_full()
        text = combo.get().strip()
        full = state["full"] or []
        if text:
            lowered = text.lower()
            filtered = [value for value in full if value.lower().startswith(lowered)]
        else:
            filtered = full
        combo.configure(values=filtered)
        state["filtered"] = filtered if filtered != full else None
        _show_matches()

    def _hand_focus_to_list(_event: tk.Event | None = None) -> str | None:
        # Deliberate arrow-key navigation: Down while the list is open moves
        # focus into it, restoring the stock keyboard behavior on demand.
        # "break" stops the class binding from re-posting over the handoff.
        if not _popdown_open():
            return None
        try:
            combo.tk.call("focus", popdown_listbox)
        except tk.TclError:
            return None
        return "break"

    def _close_list(_event: tk.Event | None = None) -> None:
        if _popdown_open():
            try:
                combo.tk.call("ttk::combobox::Unpost", combo)
            except tk.TclError:
                pass

    def _select_first_match(_event: tk.Event | None = None) -> str | None:
        # Enter while the suggestion list is open picks the top match.
        if not _popdown_open():
            return None
        values = [str(value) for value in (combo.cget("values") or ())]
        _close_list()
        if not values:
            return "break"
        combo.set(values[0])
        combo.icursor("end")
        combo.event_generate("<<ComboboxSelected>>")
        return "break"

    combo.bind("<KeyRelease>", _filter, add="+")
    combo.bind("<<ComboboxSelected>>", _on_selected, add="+")
    combo.bind("<FocusOut>", _on_focus_out, add="+")
    combo.bind("<Down>", _hand_focus_to_list, add="+")
    combo.bind("<Escape>", _close_list, add="+")
    combo.bind("<Return>", _select_first_match, add="+")


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
    style.configure("TNotebook", background=BG, borderwidth=0)
    style.configure(
        "TNotebook.Tab",
        font=(FONT_BOLD, 10),
        padding=(18, 10),
        background="#e7f0ff",
        foreground=MUTED,
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", WHITE), ("active", "#eef6ff")],
        foreground=[("selected", TEXT), ("active", BLUE_DARK)],
    )


def bind_mousewheel_scroll(canvas: tk.Canvas) -> None:
    """Scroll `canvas` with the mouse wheel, but only while the pointer is over it."""

    def _can_scroll() -> bool:
        # When the content fits inside the viewport, yview is (0.0, 1.0) and
        # there is nothing to scroll - but Tk's yview_scroll would still
        # happily slide the view into blank space beyond the scrollregion,
        # which is exactly the "scrolls up into emptiness" bug.
        first, last = canvas.yview()
        return first > 0.0 or last < 1.0

    def _on_mousewheel(event: tk.Event) -> None:
        if not _can_scroll():
            return
        delta = event.delta
        steps = -1 * (delta // 120) if abs(delta) >= 120 else -1 * delta
        canvas.yview_scroll(int(steps), "units")

    def _on_mousewheel_linux(event: tk.Event) -> None:
        if not _can_scroll():
            return
        canvas.yview_scroll(-1 if event.num == 4 else 1, "units")

    def _bind(_event: tk.Event | None = None) -> None:
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        canvas.bind_all("<Button-4>", _on_mousewheel_linux)
        canvas.bind_all("<Button-5>", _on_mousewheel_linux)

    def _unbind(_event: tk.Event | None = None) -> None:
        canvas.unbind_all("<MouseWheel>")
        canvas.unbind_all("<Button-4>")
        canvas.unbind_all("<Button-5>")

    canvas.bind("<Enter>", _bind)
    canvas.bind("<Leave>", _unbind)


def make_scrollable_region(parent: tk.Misc, bg: str = BG) -> tuple[tk.Frame, tk.Frame]:
    """Build a vertically scrollable area inside `parent`.

    Returns `(container, body)`. Place `container` with pack/grid as needed,
    then build content into `body` exactly as if it were a plain frame.
    """
    container = tk.Frame(parent, bg=bg)
    container.grid_columnconfigure(0, weight=1)
    container.grid_rowconfigure(0, weight=1)

    canvas = tk.Canvas(container, bg=bg, highlightthickness=0, bd=0)
    canvas.grid(row=0, column=0, sticky="nsew")
    scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
    scrollbar.grid(row=0, column=1, sticky="ns")
    canvas.configure(yscrollcommand=scrollbar.set)

    body = tk.Frame(canvas, bg=bg)
    window_id = canvas.create_window((0, 0), window=body, anchor="nw")

    def _sync_scrollregion(_event: tk.Event | None = None) -> None:
        canvas.configure(scrollregion=canvas.bbox("all"))
        # If everything now fits in the viewport, force the view back to the
        # top - otherwise a view that was previously scrolled (or nudged into
        # blank space) stays displaced, showing emptiness above the content.
        first, last = canvas.yview()
        if first <= 0.0 and last >= 1.0 and canvas.canvasy(0) != 0:
            canvas.yview_moveto(0)

    def _sync_width(event: tk.Event) -> None:
        canvas.itemconfigure(window_id, width=event.width)
        # Changing the embedded window's width can reflow body's content
        # (wraplength labels, stretch columns) and change its height, but
        # body's own <Configure> doesn't reliably fire just because the
        # canvas told it to resize - without this, the scrollregion can go
        # stale at whatever size it last fired at (observed: bbox width
        # 1166 vs. a scrollregion still configured at 787), leaving the
        # canvas scrollable past where the real content actually ends.
        canvas.after_idle(_sync_scrollregion)

    body.bind("<Configure>", _sync_scrollregion)
    canvas.bind("<Configure>", _sync_width)
    bind_mousewheel_scroll(canvas)

    return container, body


def fill_with_scrollable_region(parent: tk.Misc, bg: str = BG) -> tk.Frame:
    """Convenience wrapper for `make_scrollable_region` that fills the whole `parent`."""
    container, body = make_scrollable_region(parent, bg=bg)
    container.pack(fill="both", expand=True)
    return body
