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


def to_cloud_timestamp(value: str) -> str:
    """Attach this PC's UTC offset to a naive local timestamp before pushing it to Supabase.

    Postgres casts a bare (no-offset) string to `timestamptz` by assuming
    it is already UTC. Every locally generated timestamp is naive local
    time (e.g. Karachi, UTC+5), so without this, every push silently shifts
    the stored moment by the local UTC offset - and since a pulled value
    comes back with that offset attached and gets stripped to naive local
    again on import, a row pushed and pulled repeatedly drifts further by
    a full UTC-offset each round trip instead of just once.
    """
    text = (value or "").strip()
    if not text:
        return text
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return text
    if parsed.tzinfo is not None:
        return text
    return parsed.astimezone().isoformat(timespec="microseconds")


def is_timestamp_newer_or_equal(local_value: str, candidate_value: str) -> bool:
    """True if local_value is the same moment as or later than candidate_value.

    Locally generated timestamps use second precision; cloud-roundtripped
    ones use microsecond precision (see normalize_local_timestamp above). A
    fresh local "...:00" and its own cloud reflection "...:00.000000" are
    the exact same moment, but as raw strings the shorter one is treated as
    "less than" the longer one - so a same-moment value never compares as
    equal-or-newer, only ever as stale. Comparing parsed datetimes instead
    of strings makes this an actual chronological comparison.
    """
    if not local_value:
        return False
    if not candidate_value:
        return True
    try:
        return parse_local_datetime(local_value) >= parse_local_datetime(candidate_value)
    except ValueError:
        return local_value >= candidate_value

