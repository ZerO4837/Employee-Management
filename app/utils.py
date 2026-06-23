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


def parse_local_datetime(value: str) -> datetime:
    """Parse an ISO timestamp as naive local time.

    Locally generated timestamps are naive `datetime.now()` strings, but
    cloud-synced timestamps (Supabase `timestamptz`) come back with a UTC
    offset. Subtracting one from the other raises `TypeError: can't
    subtract offset-naive and offset-aware datetimes`, so any offset is
    converted to local wall-clock time and dropped here before use.
    """
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


def normalize_local_timestamp(value: str) -> str:
    """Reformat a possibly offset-aware ISO timestamp string to naive local time."""
    text = (value or "").strip()
    if not text:
        return text
    try:
        return parse_local_datetime(text).isoformat(timespec="microseconds")
    except ValueError:
        return text

