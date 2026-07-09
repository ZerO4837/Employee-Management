from __future__ import annotations

from datetime import datetime, timedelta


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


_SALES_SEARCH_FIELDS = (
    "customer",
    "item",
    "order_id",
    "status",
    "notes",
    "employee_username",
    "entry_date",
    "entry_time",
    "date",
    "time",
    "buying_amount",
    "selling_amount",
    "profit",
)


def sales_entry_matches_search(entry: dict, query: str) -> bool:
    """True if any text field of a sales entry contains the query.

    Plain case-insensitive substring matching on purpose: searching the
    last 4 digits of a phone number stored inside the customer name or
    order id still finds the entry.
    """
    needle = (query or "").strip().casefold()
    if not needle:
        return True
    for field in _SALES_SEARCH_FIELDS:
        value = entry.get(field)
        if value is not None and needle in str(value).casefold():
            return True
    return False


# Allow this much genuine clock difference between the PCs before a
# timestamp is treated as poisoned. Anything further ahead than this can't
# be honest clock skew - it's leftover corruption from the old
# timezone-drift push bug, where every push/pull round trip silently added
# the local UTC offset and snowballed timestamps days into the future.
FUTURE_TIMESTAMP_TOLERANCE_SECONDS = 15 * 60


def is_future_timestamp(value: str, tolerance_seconds: int = FUTURE_TIMESTAMP_TOLERANCE_SECONDS) -> bool:
    """True if value is further in the future than honest clock skew allows.

    Used to quarantine drift-poisoned rows: a record stamped days ahead
    always wins "is it newer?" comparisons, so it silently overwrites every
    legitimate edit and re-pushes itself on every sync cycle. Rejection is
    naturally temporary - once real time passes the stamp, the row compares
    normally again.
    """
    text = (value or "").strip()
    if not text:
        return False
    try:
        parsed = parse_local_datetime(text)
    except ValueError:
        return False
    return parsed > datetime.now() + timedelta(seconds=tolerance_seconds)


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

