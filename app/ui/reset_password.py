from __future__ import annotations

import tkinter as tk
from tkinter import messagebox

from app.config import BG, BLUE, BUSINESS_NAME, FONT, FONT_BOLD, MUTED, TEAL, TEXT, WHITE
from app.ui.widgets import GradientBanner, SurfaceCard, field_label, make_button, text_entry


class ResetPasswordPage(tk.Frame):
    def __init__(self, parent: tk.Misc, app) -> None:
        super().__init__(parent, bg=BG)
        self.app = app
        self.code_var = tk.StringVar()
        self.password_var = tk.StringVar()
        self.confirm_var = tk.StringVar()
        self._build()

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        panel = SurfaceCard(self, padx=0, pady=0, accent=False)
        panel.grid(row=0, column=0, sticky="", padx=42, pady=42)
        body = panel.body
        body.configure(padx=0, pady=0)
        body.grid_columnconfigure(0, weight=1)

        banner = GradientBanner(
            body,
            "Password Recovery",
            "Use the private recovery code to reset the employee login password.",
            height=132,
        )
        banner.grid(row=0, column=0, sticky="ew")

        form = tk.Frame(body, bg=WHITE, padx=46, pady=36)
        form.grid(row=1, column=0, sticky="nsew")
        form.grid_columnconfigure(0, weight=1)

        logo = self.app.get_logo((84, 84))
        if logo:
            tk.Label(form, image=logo, bg=WHITE).grid(row=0, column=0, sticky="w", pady=(0, 16))

        tk.Label(form, text="Reset Password", bg=WHITE, fg=TEXT, font=(FONT_BOLD, 24)).grid(row=1, column=0, sticky="w")
        tk.Label(form, text=BUSINESS_NAME, bg=WHITE, fg=MUTED, font=(FONT, 11)).grid(
            row=2, column=0, sticky="w", pady=(6, 24)
        )

        self._entry(form, "Private code", self.code_var, 3, show="*")
        self._entry(form, "New password", self.password_var, 5, show="*")
        confirm_entry = self._entry(form, "Confirm password", self.confirm_var, 7, show="*")

        make_button(form, "Reset Password", self._reset_password, "primary").grid(
            row=9, column=0, sticky="ew", pady=(4, 12)
        )
        make_button(form, "Back to Login", lambda: self.app.show_page("login"), "light").grid(row=10, column=0, sticky="ew")
        confirm_entry.bind("<Return>", lambda _event: self._reset_password())

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

    def _reset_password(self) -> None:
        new_password = self.password_var.get()
        confirm = self.confirm_var.get()
        if new_password != confirm:
            messagebox.showerror("Password mismatch", "New password and confirmation do not match.")
            return
        ok, message = self.app.auth.reset_password(self.code_var.get(), new_password)
        if not ok:
            messagebox.showerror("Reset failed", message)
            return
        messagebox.showinfo("Password reset", message)
        self.code_var.set("")
        self.password_var.set("")
        self.confirm_var.set("")
        self.app.show_page("login")

