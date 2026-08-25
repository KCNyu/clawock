"""Summarize a run-outcome ledger into the shape the dashboard card reads.

The ledger itself is written by whichever runtime adapter observes the runs —
its records are instance-shaped in their *content* (job names, slots) but not in
their *arithmetic*: counting final states over a window and flagging runs whose
raw execution errored while the product came out usable is the same computation
for anyone. Keeping it here is what lets the projection read a published ledger
as an ordinary workspace input instead of importing the adapter that produced
it (the direction the wheel may never depend in).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# Slots are recorded in the desk's local wall clock and some are written without
# an offset; assuming HKT for those is the ledger's own long-standing rule.
LEDGER_TZ = ZoneInfo("Asia/Hong_Kong")

# A raw error whose final product still shipped is a false red, not a failure.
USABLE_PRODUCT_STATES = {"success", "recovered", "degraded", "artifact_only"}

MAX_RECENT = 16

# A product that shipped but not on the happy path. These are the states the
# health card must be able to name — "1 档恢复或降级" with no name is the
# complaint that produced this list (kcn 2026-08-25).
SOFT_PRODUCT_STATES = ("recovered", "degraded", "artifact_only", "failed")

# Named lists are for reading, not for auditing: the full ledger is published
# on its own. A cap keeps a bad stretch from turning the card into a log.
MAX_NAMED = 8


def summarize_records(records, *, hours: int = 36, now: datetime | None = None) -> dict:
    """Fold ledger records into counts, false-red tally and the recent window."""
    now = now or datetime.now(LEDGER_TZ)
    cutoff = now - timedelta(hours=hours)
    recent = []
    for record in records or []:
        if not isinstance(record, dict):
            continue
        try:
            slot = datetime.fromisoformat(record["slot"])
        except Exception:
            # An unparseable slot cannot be placed in the window. Dropping it is
            # deliberate: dating it "now" would park a broken record at the top
            # of the card for 36 hours.
            continue
        if slot.tzinfo is None:
            slot = slot.replace(tzinfo=LEDGER_TZ)
        if slot.astimezone(timezone.utc) >= cutoff.astimezone(timezone.utc):
            recent.append(record)
    recent.sort(key=lambda record: record.get("slot", ""), reverse=True)

    counts: dict[str, int] = {}
    false_reds = 0
    wechat_dropped = 0
    # Which slots, not just how many. `recent` is capped, so a card that scans
    # it can only name what fits in the tail — on a busy day the answer is
    # "none of them". These two lists are computed over the whole window and
    # are what a reader can actually point at.
    wechat_dropped_slots: list[dict] = []
    degraded_slots: list[dict] = []
    for record in recent:
        final = (record.get("final_product") or {}).get("status", "pending")
        counts[final] = counts.get(final, 0) + 1
        if final in SOFT_PRODUCT_STATES and len(degraded_slots) < MAX_NAMED:
            degraded_slots.append({
                "job": record.get("job"),
                "slot": record.get("slot"),
                "status": final,
            })
        if ((record.get("raw_execution") or {}).get("status") == "error"
                and final in USABLE_PRODUCT_STATES):
            false_reds += 1
        # WeChat drops slots to an upstream-wontfix `ret=-2 prepare failed` and
        # Telegram covers them, so the product is fine and nothing shows it. This
        # is the count, not an alert: kcn has ruled out chasing the failure, and
        # per-run cron alerts are unwanted (feedback_no_individual_cron_alerts).
        # Absent flags are not counted — an old record proves nothing either way.
        delivery = (record.get("stages") or {}).get("primary_delivery") or {}
        if delivery.get("wechat_ok") is False and delivery.get("telegram_ok") is True:
            wechat_dropped += 1
            if len(wechat_dropped_slots) < MAX_NAMED:
                wechat_dropped_slots.append({
                    "job": record.get("job"), "slot": record.get("slot"),
                })

    return {
        "generated_at": now.isoformat(),
        "window_hours": hours,
        "counts": counts,
        "raw_error_but_product_usable": false_reds,
        "wechat_dropped_telegram_covered": wechat_dropped,
        "wechat_dropped_slots": wechat_dropped_slots,
        "degraded_slots": degraded_slots,
        "recent": recent[:MAX_RECENT],
    }
