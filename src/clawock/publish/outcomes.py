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

import re
from datetime import datetime, timedelta, timezone
from enum import StrEnum

from clawock.sessions import HKT

# Slots are recorded in the desk's local wall clock and some are written without
# an offset; assuming HKT for those is the ledger's own long-standing rule.
LEDGER_TZ = HKT

class ProductStatus(StrEnum):
    """Final product states stored in the workflow outcome ledger."""

    SUCCESS = 'success'
    DEGRADED = 'degraded'
    RECOVERED = 'recovered'
    FAILED = 'failed'
    PENDING = 'pending'
    SKIPPED = 'skipped'
    NO_CHANGE = 'no_change'
    ARTIFACT_ONLY = 'artifact_only'


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


DEGRADATIONS_KEY = "degradations"

# The timetable gives records and missing slots a bounded time to settle.
GRACE_MINUTES = 20
_MISSING_STAGE = re.compile(r"(?:llm|postflight|preflight)(?: / (?:llm|postflight|preflight))* 未记录结果")


def displayed_product(record, now):
    """Give a fresh successful receipt time for the remaining stage writes."""
    final = record.get("final_product") or {}
    if (final.get("status") != ProductStatus.DEGRADED or final.get("fallback_only")
            or not _MISSING_STAGE.fullmatch(str(final.get("reason") or ""))):
        return final
    primary = (record.get("stages") or {}).get("primary_delivery") or {}
    if primary.get("status") != "success":
        return final
    try:
        delivered_at = datetime.fromisoformat(primary.get("at"))
    except (TypeError, ValueError):
        return final
    if delivered_at.tzinfo is not None:
        age = now.astimezone(timezone.utc) - delivered_at.astimezone(timezone.utc)
        if timedelta(0) <= age < timedelta(minutes=GRACE_MINUTES):
            return {"status": ProductStatus.PENDING.value, "reason": "主投已送达，等待阶段结果"}
    return final


def delivered_data_only_fallback(record) -> bool:
    """The watchdog delivered a data block and the product still needs attention."""
    final = record.get('final_product') or {}
    watchdog = (record.get('stages') or {}).get('watchdog_delivery') or {}
    return (final.get('status') == ProductStatus.DEGRADED and final.get('fallback_only') is True
            and watchdog.get('status') == 'success')


def backstop_delivered(record) -> bool:
    """Whether the ledger confirms recovery, including a data-only fallback."""
    final = record.get('final_product') or {}
    return final.get('status') == ProductStatus.RECOVERED or delivered_data_only_fallback(record)


def degradations_of(payload) -> list:
    """The observation chain's own faults, out of a ledger payload (#1214).

    Lives here rather than in `automation.workflow_outcomes` for the reason
    `summarize_records` does: the dashboard folds the *published* copy and the
    desk folds the local one, and two readings of "what went wrong with the
    bookkeeping" would drift the moment either side changed.
    """
    if not isinstance(payload, dict):
        return []
    rows = payload.get(DEGRADATIONS_KEY)
    return [row for row in rows or [] if isinstance(row, dict)]


def _product_evidence(records):
    delivery = dict(both=0, wechat_only=0, telegram_only=0, neither=0, unknown=0, not_required=0,
                    wechat=0, telegram=0, any_channel=0)
    judgment = dict(valid=0, flagged=0, unavailable=0, unknown=0, not_required=0)
    action = dict(changed=0, unchanged=0, unknown=0)
    for record in records:
        if (record.get("final_product") or {}).get("status") == "skipped":
            continue
        stages = record.get("stages") or {}
        primary = stages.get("primary_delivery") or {}
        wechat, telegram = primary.get("wechat_ok"), primary.get("telegram_ok")
        if primary.get("status") == "not_required":
            channel = "not_required"
        elif wechat is True:
            channel = "both" if telegram is True else ("wechat_only" if telegram is False else "unknown")
        elif telegram is True:
            channel = "telegram_only" if wechat is False else "unknown"
        else:
            channel = "neither" if wechat is False and telegram is False else "unknown"
        delivery[channel] += 1
        if channel != "not_required":
            delivery["wechat"] += wechat is True
            delivery["telegram"] += telegram is True
            delivery["any_channel"] += wechat is True or telegram is True

        llm = stages.get("llm") or {}
        status = llm.get("status")
        if status == "not_required":
            quality = "not_required"
        elif status == "failed" or (record.get("final_product") or {}).get("fallback_only"):
            quality = "unavailable"
        elif status == "success" or (status == "warning" and llm.get("escalating_count") == 0):
            quality = "valid"
        elif status == "warning":
            quality = "flagged"
        else:
            quality = "unknown"
        judgment[quality] += 1

        count = (stages.get("preflight") or {}).get("actionable_changes")
        action[("changed" if count else "unchanged") if type(count) is int and count >= 0 else "unknown"] += 1
    return {"primary_delivery": delivery, "judgment": judgment, "actionable": action}


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
            product = displayed_product(record, now)
            if product and product is not record.get("final_product"):
                record = {**record, "final_product": product}
            recent.append(record)
    recent.sort(key=lambda record: record.get("slot", ""), reverse=True)

    counts: dict[str, int] = {}
    false_reds = 0
    fallback_only = 0
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
        only_fallback = bool((record.get("final_product") or {}).get("fallback_only"))
        fallback_only += int(only_fallback)
        if final in SOFT_PRODUCT_STATES and len(degraded_slots) < MAX_NAMED:
            degraded_slots.append({
                "job": record.get("job"),
                "slot": record.get("slot"),
                "status": final,
                **({"fallback_only": True} if only_fallback else {}),
                "reason": str((record.get("final_product") or {}).get("reason") or "")[:120],
            })
        if ((record.get("raw_execution") or {}).get("status") == "error"
                and final in USABLE_PRODUCT_STATES and not only_fallback):
            false_reds += 1
        # WeChat drops slots to an upstream-wontfix `ret=-2 prepare failed` and
        # Telegram covers them, so the product is fine and nothing shows it. This
        # is the count, not an alert: kcn has ruled out chasing the failure, and
        # per-run cron alerts are unwanted (feedback_no_individual_cron_alerts).
        # Absent flags are not counted — an old record proves nothing either way.
        delivery = (record.get("stages") or {}).get("primary_delivery") or {}
        # A slot the watchdog's WeChat retry did land is not a dropped one (#2272).
        if (delivery.get("wechat_ok") is False and delivery.get("telegram_ok") is True
                and delivery.get("wechat_backstop_ok") is not True):
            wechat_dropped += 1
            if len(wechat_dropped_slots) < MAX_NAMED:
                wechat_dropped_slots.append({
                    "job": record.get("job"), "slot": record.get("slot"),
                })

    return {
        "generated_at": now.isoformat(),
        "window_hours": hours,
        "counts": counts,
        "fallback_only": fallback_only,
        "raw_error_but_product_usable": false_reds,
        "wechat_dropped_telegram_covered": wechat_dropped,
        "wechat_dropped_slots": wechat_dropped_slots,
        "degraded_slots": degraded_slots,
        "product_evidence": _product_evidence(recent),
        "recent": recent[:MAX_RECENT],
    }
