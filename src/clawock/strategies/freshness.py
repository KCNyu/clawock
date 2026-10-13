"""Freshness of scan payloads, measured by producer stamps, never file mtime.

Checkout renews file mtimes even for old committed scans. Unknown or materially
future producer stamps therefore cannot establish a fresh reading.
"""
from datetime import datetime, timezone

DEFAULT_STALE_AFTER_HOURS = 36
CLOCK_SKEW_HOURS = 2


def payload_age_hours(payload, now=None):
    """Hours since the payload's own `generated_at`; None when it has no readable one."""
    stamp = (payload or {}).get('generated_at')
    if not stamp:
        return None
    try:
        at = datetime.fromisoformat(str(stamp).replace('Z', '+00:00'))
    except ValueError:
        return None
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return ((now or datetime.now(timezone.utc)) - at).total_seconds() / 3600


def is_stale(age, cutoff_h):
    return age is None or age > cutoff_h or age < -CLOCK_SKEW_HOURS
