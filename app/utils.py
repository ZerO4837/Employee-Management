from __future__ import annotations

from datetime import datetime


def now_label() -> str:
    return datetime.now().strftime("%I:%M %p")


def today_label() -> str:
    return datetime.now().strftime("%d %b %Y")


def money_label(value: str) -> str:
    if not value.strip():
        return "0"
    try:
        amount = float(value)
    except ValueError:
        return value
    if amount.is_integer():
        return str(int(amount))
    return f"{amount:.2f}"


def duration_label(seconds: int) -> str:
    minutes = max(0, int(seconds // 60))
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"

