#!/usr/bin/env python3
"""Carry today's brief catalysts into mover-scoped intraday context.

``mover_news`` intentionally answers a narrow novelty question: what new filing
or flash appeared inside this slot's minute window?  A catalyst announced
yesterday can still drive today's tape, so an empty novelty window must not be
translated into "no known catalyst".  The daily brief already did the expensive
research and wrote structured scheduled events; this module carries only the
flagged names into the intraday context, without another request or a wider news
window.

Everything fails soft.  A missing/corrupt brief leaves an empty mapping and must
never take down a market cron.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

# Resolve the package from the checkout this adapter ships in, not from an
# ambient PYTHONPATH inherited from whichever runtime imported it.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from clawock.workspace import workspace_root


WS = workspace_root(Path(__file__).resolve().parents[2])
TMP = WS / "memory" / ".tmp"
MAX_MOVERS = 4
MAX_EVENTS_PER_TICKER = 2
TEXT_CHARS = 360


def _trim(value, limit=TEXT_CHARS):
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def for_movers(tickers, *, today=None, tmp_dir=None):
    """Return ``ticker -> known events`` from today's brief, mover-scoped.

    A date-exact filename is required.  Falling back to the newest brief could
    silently carry yesterday's thesis after a failed morning run.
    """
    names = list(dict.fromkeys(str(t or "").upper() for t in (tickers or []) if t))
    names = names[:MAX_MOVERS]
    if not names:
        return {}
    try:
        date = today or datetime.now().strftime("%Y-%m-%d")
        root = Path(tmp_dir) if tmp_dir else TMP
        path = root / f"brief-context-{date}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        scheduled = (payload.get("catalysts") or {}).get("scheduled_events") or []
        result = {}
        for ticker in names:
            events = []
            for event in scheduled:
                if str(event.get("ticker") or "").upper() != ticker:
                    continue
                item = {
                    "type": _trim(event.get("type"), 80),
                    "date": event.get("date"),
                    "date_confidence": event.get("date_confidence"),
                    "detail": _trim(event.get("detail")),
                    "source": _trim(event.get("source")),
                    "provenance": "daily_brief",
                }
                # Do not emit a shape that contains no usable claim.
                if item["detail"] or item["source"]:
                    events.append(item)
                if len(events) >= MAX_EVENTS_PER_TICKER:
                    break
            if events:
                result[ticker] = events
        return result
    except (OSError, ValueError, TypeError, AttributeError):
        return {}
