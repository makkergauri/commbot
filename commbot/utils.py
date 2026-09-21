"""Small helpers that don't really belong anywhere else."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))


def now_utc() -> datetime:
    # Everything is stored in UTC. We only convert to IST when showing
    # times to people, which avoids a whole class of "why is this alert
    # expired already?" bugs.
    return datetime.now(timezone.utc).replace(microsecond=0)


def parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp. Returns None instead of blowing up."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        # CAP says timestamps must carry an offset, but not every feed
        # follows the spec. Indian feeds without one are nearly always IST.
        dt = dt.replace(tzinfo=IST)
    return dt.astimezone(timezone.utc)


def to_iso(dt: datetime) -> str:
    # Same format everywhere so SQLite string comparison works for dates.
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def fmt_local(value, fmt: str = "%d/%m %H:%M") -> str:
    """Format a timestamp in IST for humans, e.g. '20/09 18:00'."""
    dt = parse_iso(value) if isinstance(value, str) else value
    return dt.astimezone(IST).strftime(fmt) if dt else ""
