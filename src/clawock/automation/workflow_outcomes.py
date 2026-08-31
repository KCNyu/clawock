#!/usr/bin/env python3
"""Durable per-slot workflow outcome state.

OpenClaw's raw run status answers whether every agent/tool step completed. It
does not answer whether the user ultimately received a usable product. This
ledger keeps those concerns independent:

* raw_execution: reconciled from live OpenClaw run history
* preflight
* llm
* postflight
* primary_delivery
* watchdog_delivery
* final_product: derived only from the five product stages

Writers update one stage at a time under a file lock. A watchdog can therefore
record recovery without erasing the preflight/postflight evidence that preceded
it, and a raw ``error`` can coexist with a final ``success``/``recovered``.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from clawock.providers import openclaw
from clawock.publish.outcomes import summarize_records
from clawock.workspace import workspace_root
from clawock import scheduling as schedule

# Code lives in the checkout; only DATA lives in the workspace. `workspace_root`
# is overridable, so resolving our own modules through WS would read them out of
# someone else's data directory — or silently pick up whatever happens to be
# there. Same expression WS is seeded from, kept separate on purpose (#269).
def _ws() -> Path:
    """The workspace, resolved per call rather than frozen at import.

    These were module constants computed from `Path.cwd()` when the module was
    first imported. `clawock.workspace` documents `CLAWOCK_WORKSPACE` as the way
    to point the computation at a different workspace "without touching the
    modules" — and for this module that override did nothing, because by the
    time anything could set it the paths were already decided.

    The visible cost was a test: #816 traced an order-dependent failure to
    `rebuild_dashboard(tmp_path)` writing `assets/data/workflow-outcomes.json`
    into the real checkout. The test passed a workspace; the ledger ignored it,
    wrote to wherever pytest happened to be started from, and left an untracked
    file behind that armed a dormant assertion in a different module.

    Resolved per call, `CLAWOCK_WORKSPACE` reaches this module like the
    docstring always claimed. Unset, behaviour is unchanged.
    """
    return workspace_root(Path.cwd())


def local_path() -> Path:
    return _ws() / "memory" / ".tmp" / "workflow-outcomes.json"


def public_path() -> Path:
    return _ws() / "assets" / "data" / "workflow-outcomes.json"


def lock_path() -> Path:
    return _ws() / "memory" / ".tmp" / "workflow-outcomes.lock"


def tmp_dir() -> Path:
    return _ws() / "memory" / ".tmp"
SCHEMA_VERSION = 1
KEEP_HOURS = 96
HKT = ZoneInfo("Asia/Hong_Kong")

STAGES = (
    "preflight",
    "llm",
    "postflight",
    "primary_delivery",
    "watchdog_delivery",
)
STAGE_STATUSES = {
    "unknown", "pending", "success", "warning", "failed", "skipped", "not_required",
}

REPORT_JOBS = {
    ("hk", "open"): "港股开盘报告",
    ("hk", "mid"): "港股午盘报告",
    ("hk", "pm"): "港股午后快报",
    ("hk", "close"): "港股收盘报告",
    ("us", "open"): "美股开盘报告",
    ("us", "close"): "美股收盘报告",
}


def _now(at=None):
    at = at or datetime.now(timezone.utc)
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def job_for(market=None, phase=None, *, brief=False):
    if brief:
        return "盘前深度简报"
    try:
        return REPORT_JOBS[(market, phase)]
    except KeyError as exc:
        raise ValueError(f"unknown workflow identity: market={market}, phase={phase}") from exc


def slot_for_job(job_name, at=None):
    """Return today's configured slot as an aware ISO timestamp.

    The tracked cron contract owns DST-sensitive schedules, so US slots remain
    correct across daylight/standard transitions.
    """
    at = _now(at)
    expected = next(
        (job for job in schedule.load_contract()["jobs"] if job["name"] == job_name),
        None,
    )
    if not expected:
        raise ValueError(f"job is absent from cron contract: {job_name}")
    resolved = schedule.effective_schedule(expected, at)
    expr = (resolved.get("expr") or "").split()
    if len(expr) != 5 or not expr[0].isdigit() or not expr[1].isdigit():
        raise ValueError(f"job does not have a single fixed slot: {job_name}")
    tz = ZoneInfo(resolved.get("tz") or "Asia/Shanghai")
    local = at.astimezone(tz)
    slot = local.replace(
        hour=int(expr[1]), minute=int(expr[0]), second=0, microsecond=0
    )
    return slot.isoformat()


def _empty(now=None):
    now = _now(now).isoformat()
    return {
        "schema_version": SCHEMA_VERSION,
        "monitoring_started_at": now,
        "updated_at": now,
        "records": [],
    }


# ── When the observer is the thing that broke (#1214) ────────────────────────
# Five `except Exception` blocks covered this chain end to end — prune, load,
# the raw-execution reconcile, the delivery-receipt reconcile, and the heartbeat
# bridge — and every one of them failed open onto stderr. Each was individually
# defensible: observation must not interrupt the desk. Composed, they mean a
# fault in the observation system is invisible to the observation system, which
# is the failure #776 already demonstrated can run for eight days.
#
# Two changes, and neither is "stop failing open".
#
# 1. The excepts name what they expect. A corrupt file, a missing key, a bad
#    timestamp — those are the conditions these paths exist for, and they still
#    degrade quietly. A TypeError is a bug in this module, and a bug that
#    silently returns 0 is how "delivery is still `unknown`" becomes permanent.
#
# 2. The degradation records itself IN the ledger, which is published and folded
#    by `summarize`. Not `logs/watchdog.jsonl`: `intraday_watchdog` already
#    settled that question — "a line in watchdog.jsonl is not something kcn
#    reads, so treating it as surfaced would be exactly the silent downgrade
#    that is forbidden here". stderr is worse. The ledger is the one surface
#    that already reaches the dashboard card and the health check.
#
# The counter is deliberately not a raise: a delivery that happened must not be
# reported as failed because the bookkeeping tripped. It makes the fail-open
# countable, which is the difference between degrading and disappearing.
DEGRADATIONS_KEY = "degradations"
MAX_DEGRADATIONS = 20


def note_degradation(ledger, kind, detail, *, at=None):
    """Record, in the ledger, that this ledger could not be trusted somewhere.

    Mutates and returns `ledger` so a caller that is already holding it under
    the lock writes the note in the same atomic write as its own change; a
    caller with no ledger to hand passes None and gets a standalone record.
    """
    standalone = ledger is None
    if standalone:
        # Read the file, not `load_ledger` (#1214). The most important caller is
        # the one whose failure *was* `load_ledger`, and routing the note back
        # through it would raise from inside the handler that exists to keep
        # this non-fatal. `_read_path` already swallows a torn or missing file.
        ledger = _read_path(local_path()) or _empty()
    rows = ledger.get(DEGRADATIONS_KEY)
    if not isinstance(rows, list):
        rows = []
    now = _now(at).isoformat()
    for row in rows:
        if row.get("kind") == kind and row.get("detail") == str(detail):
            row["count"] = int(row.get("count") or 0) + 1
            row["last_at"] = now
            break
    else:
        rows.append({"kind": kind, "detail": str(detail), "count": 1,
                     "first_at": now, "last_at": now})
    # Newest last, oldest evicted: a chain that is failing now matters more than
    # one that failed three days ago and has not recurred.
    ledger[DEGRADATIONS_KEY] = rows[-MAX_DEGRADATIONS:]
    print(f"warn: {kind}: {detail}", file=sys.stderr)
    if standalone:
        try:
            _atomic_write(local_path(), ledger)
        except OSError as exc:
            # The one place with nowhere left to write. Say so on stderr and
            # carry on: this is the observer failing to observe its own failure,
            # not a reason to take the desk down.
            print(f"warn: could not record degradation {kind}: {exc}",
                  file=sys.stderr)
    return ledger


def _read_path(path):
    try:
        data = json.loads(path.read_text())
        if data.get("schema_version") == SCHEMA_VERSION and isinstance(
            data.get("records"), list
        ):
            return data
    except (FileNotFoundError, json.JSONDecodeError, OSError, AttributeError):
        pass
    return None


def load_ledger(*, note_fallback=True):
    """Local ledger first; the published copy is a last resort, never a silent one.

    Falling back to public_path() and then writing that content back to local_path()
    would roll the local ledger back to whatever was last published. It has not
    been observed happening, but a data-losing path must not be invisible.

    "Not invisible" used to mean a line on stderr, which no gate reads. The
    fallback now rides in the returned ledger's own `degradations` list, so the
    published copy and the dashboard card carry the fact that every stage
    recorded since the last publish may be missing. `note_fallback=False` is for
    `note_degradation` itself, which would otherwise recurse.
    """
    local = _read_path(local_path())
    if local is not None:
        return local
    public = _read_path(public_path())
    if public is not None:
        if note_fallback:
            note_degradation(
                public, "ledger_fallback_to_published",
                f"{local_path()} unreadable; stages recorded since the last "
                f"publish may be missing")
        return public
    return _empty()


def _atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    os.replace(tmp, path)


@contextmanager
def _locked():
    lock_path().parent.mkdir(parents=True, exist_ok=True)
    with lock_path().open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        yield


def delivery_channel(wechat_ok, telegram_ok):
    """Name which channel actually carried a slot, rather than which two could.

    The ledger used to store the constant string "wechat_or_telegram", which is
    a description of the design, not an observation. WeChat drops a handful of
    slots a week to an upstream-wontfix `ret=-2 prepare failed`, Telegram covers
    them, and nothing anywhere recorded that it happened — the send receipts are
    pruned within days (#771).
    """
    if wechat_ok and telegram_ok:
        return "wechat+telegram"
    if wechat_ok:
        return "wechat"
    if telegram_ok:
        return "telegram"
    return "none"


def _stage(status="unknown", **details):
    out = {"status": status}
    out.update({key: value for key, value in details.items() if value is not None})
    return out


def _advisory_only(stage):
    """True when a stage's only findings were advisory ones.

    `validation.split_advisory` already guarantees advisory findings never reach
    the delivered banner — the reader gets a clean report plus one non-blocking
    `ℹ️` line. Counting them as a degraded product made this ledger contradict
    what was actually delivered on 21 of 64 slots over 2026-08-17..19 (#764).

    They are still recorded, and still countable, via `issue_count` /
    `advisory_count` on the stage — detected, never silenced. What changes is
    only whether they drag `final_product` down.

    A writer that does not report `escalating_count` gets the old, conservative
    reading, so this can never quietly upgrade a stage nobody has audited.
    """
    return stage.get("escalating_count") == 0


def _derive_final(record):
    stages = record["stages"]
    preflight = stages["preflight"]["status"]
    llm = stages["llm"]["status"]
    postflight = stages["postflight"]["status"]
    primary = stages["primary_delivery"]["status"]
    watchdog = stages["watchdog_delivery"]["status"]

    if preflight == "skipped":
        status, reason = "skipped", "market/session closed"
    elif watchdog == "success":
        status, reason = "recovered", "watchdog delivered a usable product"
    elif primary == "success":
        degraded = (
            llm == "failed"
            or (llm == "warning" and not _advisory_only(stages["llm"]))
            or (
                postflight == "warning"
                and not (
                    _advisory_only(stages["postflight"])
                    and stages["postflight"].get("data_plane_status")
                    in {None, "published", "current", "skipped"}
                )
            )
            or preflight in {"warning", "failed"}
        )
        status = "degraded" if degraded else "success"
        reason = (
            "primary delivery succeeded with degraded generation/input"
            if degraded
            else "primary delivery succeeded"
        )
    elif postflight in {"success", "warning"}:
        status, reason = "artifact_only", "usable artifact exists; delivery unconfirmed"
    elif (
        preflight == "failed"
        or postflight == "failed"
        or (primary == "failed" and watchdog == "failed")
    ):
        status, reason = "failed", "no successful product recovery stage"
    else:
        status, reason = "pending", "terminal product evidence not recorded yet"
    return {"status": status, "reason": reason}


def _prune(records, now, ledger=None):
    """Drop records older than the window — and count the ones it cannot read.

    An unparseable `slot` used to delete the whole record silently, taking that
    slot's preflight, LLM, delivery and watchdog stages with it. A missing or
    malformed timestamp is a real condition this has to survive; it is not a
    reason for the row to leave no trace of having existed.
    """
    cutoff = now - timedelta(hours=KEEP_HOURS)
    kept = []
    unparseable = 0
    for record in records:
        try:
            slot = datetime.fromisoformat(record["slot"])
            if slot.tzinfo is None:
                slot = slot.replace(tzinfo=HKT)
        except (KeyError, TypeError, ValueError):
            unparseable += 1
            continue
        if slot.astimezone(timezone.utc) >= cutoff:
            kept.append(record)
    if unparseable:
        note_degradation(
            ledger, "prune_dropped_unparseable_slot",
            f"{unparseable} record(s) had no readable slot timestamp and were "
            f"dropped with every stage they carried")
    return kept


def record_stage(job_name, stage, status, *, slot=None, at=None, dry_run=False, **details):
    """Atomically update one product stage; never lets observability break a job."""
    if dry_run:
        return {}
    try:
        if stage not in STAGES:
            raise ValueError(f"unknown workflow stage: {stage}")
        if status not in STAGE_STATUSES:
            raise ValueError(f"unknown workflow stage status: {status}")
        now = _now(at)
        slot = slot or slot_for_job(job_name, now)
        with _locked():
            ledger = load_ledger()
            records = _prune(ledger.get("records", []), now, ledger)
            current = next(
                (
                    dict(record)
                    for record in records
                    if record.get("job") == job_name and record.get("slot") == slot
                ),
                None,
            )
            records = [
                record
                for record in records
                if not (record.get("job") == job_name and record.get("slot") == slot)
            ]
            current = current or {
                "job": job_name,
                "slot": slot,
                "stages": {name: _stage() for name in STAGES},
                "raw_execution": {"status": "unknown"},
            }
            current.setdefault("stages", {name: _stage() for name in STAGES})
            for name in STAGES:
                current["stages"].setdefault(name, _stage())
            current["stages"][stage] = _stage(
                status, at=now.isoformat(), **details
            )
            current["updated_at"] = now.isoformat()
            current["final_product"] = _derive_final(current)
            records.append(current)
            records.sort(key=lambda record: (record.get("slot", ""), record.get("job", "")))
            ledger.update(
                {
                    "schema_version": SCHEMA_VERSION,
                    "updated_at": now.isoformat(),
                    "records": records,
                }
            )
            if not ledger.get("monitoring_started_at"):
                ledger["monitoring_started_at"] = slot
            _atomic_write(local_path(), ledger)
        return current
    except Exception as exc:
        # Still broad, deliberately (#1214). Narrowing this was the first thing
        # tried and it is wrong: `publish()` runs inside `rebuild_dashboard`'s
        # own try, so an unnamed exception here would stop the dashboard being
        # built at all. Trading "a stage was not recorded" for "nothing was
        # published" is a worse failure, and it breaks the rule this module
        # exists under — observation must not interrupt the desk.
        #
        # What changes is that it is no longer silent. The exception type goes
        # into the ledger, so a defect looks like a defect (`RecursionError` in
        # `stage_not_recorded`) instead of like a quiet nothing.
        note_degradation(
            None, "stage_not_recorded",
            f"{job_name}/{stage}: {type(exc).__name__}: {exc}")
        return {}


def record_from_heartbeat(event):
    """Bridge the existing intraday slot ledger into explicit independent stages."""
    job = event.get("job")
    slot = event.get("slot")
    state = event.get("state")
    if not job or not slot:
        return
    details = {key: value for key, value in event.items() if key not in {"job", "slot", "state"}}
    if state == "started":
        record_stage(job, "preflight", "pending", slot=slot, **details)
    elif state == "market_closed":
        record_stage(job, "preflight", "skipped", slot=slot, **details)
    elif state == "preflight_failed":
        record_stage(job, "preflight", "failed", slot=slot, **details)
    elif state == "preflight_ok":
        record_stage(job, "preflight", "success", slot=slot, **details)
    elif state == "postflight_failed":
        if event.get("failure_stage") == "input":
            record_stage(job, "llm", "failed", slot=slot, **details)
        record_stage(job, "postflight", "failed", slot=slot, **details)
    elif state in {"completed", "publish_failed"}:
        # `publish_failed` is the heartbeat intraday_postflight emits when the
        # sends succeeded but the dashboard data plane did not publish. It used
        # to fall through every branch here, so a slot kcn actually received
        # kept no llm/postflight/primary evidence at all and its final_product
        # stayed pending forever (#1005) — #765's "delivered report filed as
        # pending" through the data-plane door. The completed mapping below
        # already grades it honestly: data_plane_status outside the ok set
        # makes postflight `warning`, not `success`.
        postflight = event.get("postflight_status")
        data_plane = event.get("data_plane_status")
        data_plane_ok = data_plane in {None, "published", "current"}
        llm_status = {
            "pass": "success",
            "warn": "warning",
            "fail": "failed",
        }.get(postflight, "warning")
        record_stage(job, "llm", llm_status, slot=slot, **details)
        record_stage(
            job,
            "postflight",
            "success" if postflight == "pass" and data_plane_ok else "warning",
            slot=slot,
            **details,
        )
        wechat_ok = event.get("wechat_sent") is True
        telegram_ok = event.get("telegram_sent") is True
        if event.get("send_claim_declined") and not (wechat_ok or telegram_ok):
            # This process was REFUSED the send right by claim_send, so it is
            # not a witness of this slot's delivery — recording its
            # wechat_sent=False as a verdict overwrote the concurrent claim
            # holder's success whenever the declined process's slow
            # commit/publish work let it write last (#1006). The holder owns
            # the verdict; if it died, receipt reconciliation fills the unknown
            # stage and the watchdog backstop still fires. Detect-but-never-
            # silence is intact: nothing is downgraded, only left to the one
            # process that actually sent.
            pass
        else:
            record_stage(
                job,
                "primary_delivery",
                "success" if (wechat_ok or telegram_ok) else "failed",
                slot=slot,
                **{**details,
                   "channel": delivery_channel(wechat_ok, telegram_ok),
                   "wechat_ok": wechat_ok,
                   "telegram_ok": telegram_ok},
            )
    elif state == "watchdog_backstop":
        record_stage(job, "watchdog_delivery", "success", slot=slot, **details)
    elif state in {"watchdog_failed", "watchdog_rejected"}:
        record_stage(job, "watchdog_delivery", "failed", slot=slot, **details)


def _match_run(record, entries):
    try:
        slot_ms = datetime.fromisoformat(record["slot"]).timestamp() * 1000
    except (KeyError, TypeError, ValueError):
        # No usable slot means no window to match a run against. Counted by
        # `_prune`, which sees the same records; not counted twice here.
        return None
    candidates = []
    for entry in entries:
        run_at = entry.get("runAtMs")
        if not isinstance(run_at, (int, float)):
            ts, duration = entry.get("ts"), entry.get("durationMs")
            if isinstance(ts, (int, float)):
                run_at = ts - (duration or 0)
        if not isinstance(run_at, (int, float)):
            continue
        delta = abs(run_at - slot_ms)
        if delta <= 20 * 60 * 1000:
            candidates.append((delta, -(entry.get("ts") or 0), entry, run_at))
    if not candidates:
        return None
    _, _, entry, run_at = min(candidates, key=lambda row: (row[0], row[1]))
    return entry, run_at


def reconcile_raw_execution():
    """Overlay raw run status from live SQLite without changing final product."""
    try:
        jobs_result = openclaw.read_jobs("sqlite")
        jobs = jobs_result.entries
        if jobs_result.source != "sqlite" or not jobs:
            return False
        job_ids = {job.get("name"): job.get("id") for job in jobs}
        ledger = load_ledger()
        run_cache = {}
        changed = False
        for record in ledger.get("records", []):
            job_id = job_ids.get(record.get("job"))
            if not job_id:
                continue
            if job_id not in run_cache:
                run_cache[job_id] = openclaw.read_runs(job_id, "sqlite").entries
            matched = _match_run(record, run_cache[job_id])
            if not matched:
                continue
            entry, run_at = matched
            raw = {
                "status": entry.get("status") or "unknown",
                "run_at_ms": int(run_at),
                "finished_at_ms": entry.get("ts"),
                "run_id": entry.get("runId"),
                # The ledger is published. Keep the failure signal without copying
                # provider/tool error text that may contain private paths or inputs.
                "error_present": bool(entry.get("error")),
            }
            if record.get("raw_execution") != raw:
                record["raw_execution"] = raw
                changed = True
        if changed:
            ledger["updated_at"] = _now().isoformat()
            with _locked():
                # Stage writers may have added records during reconciliation.
                latest = load_ledger()
                by_key = {
                    (record.get("job"), record.get("slot")): record
                    for record in ledger.get("records", [])
                }
                for record in latest.get("records", []):
                    key = (record.get("job"), record.get("slot"))
                    if key in by_key:
                        record["raw_execution"] = by_key[key].get(
                            "raw_execution", {"status": "unknown"}
                        )
                latest["updated_at"] = ledger["updated_at"]
                _atomic_write(local_path(), latest)
        return changed
    except Exception as exc:
        # Broad for the reason above, and counted for this one: skipping leaves
        # `raw_execution.status` at "unknown", and the false-red
        # detector in `publish.outcomes` requires status == "error" — so a
        # silent skip here does not degrade that detector, it disables it. That
        # is the single most important thing in this module to be able to see
        # having failed.
        note_degradation(None, "raw_execution_reconcile_skipped",
                         f"{type(exc).__name__}: {exc}; raw_execution stays "
                         f"unknown and false-red detection cannot fire for "
                         f"those slots")
        return False


# ── Delivery-receipt reconciliation ──────────────────────────────────────────
# The postflights record their terminal stages at the very end of main(), after
# send + commit + dashboard + data-plane publish. On 2026-08-19 the 港股午后快报
# slot was SIGTERM'd by the model's 60s `exec` timeout 35s *after* the WeChat
# send had already landed, so the ledger kept claiming `pending` for a report
# the user had received. Recording earlier (see report_postflight) narrows that
# window; it cannot close it, and it does nothing for slots already stuck.
#
# The senders leave a durable receipt at send time. That receipt — not the
# process exit — is what actually proves delivery, so the ledger reconciles
# against it. Absent a receipt this must leave the record alone: `pending` is
# the honest answer when nothing proves otherwise.


def _receipt_delivered(payload):
    """A receipt proves delivery when either channel reports a real send."""
    return payload.get("sent_ok") is True or payload.get("tg_ok") is True


def _receipt_claims(path):
    """Yield (job, slot_date_or_none, slot_or_none, receipt) for one receipt."""
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    name = path.name
    # The whole receipt travels, not a pre-computed verdict: the caller needs
    # the per-channel flags too (#968), and `_receipt_delivered` is applied at
    # the point of use.
    if name.startswith("report-sent-"):
        try:
            job = job_for(payload.get("market"), payload.get("phase"))
        except ValueError:
            return None
        # report-sent-{market}-{phase}-{YYYY-MM-DD}.json
        return job, name[: -len(".json")].rsplit("-", 3)[-3:], None, payload
    if name.startswith("intraday-sent-"):
        # The intraday receipt names its own job and slot, so it needs no parsing.
        job, slot = payload.get("job"), payload.get("slot")
        if not job or not slot:
            return None
        return job, None, slot, payload
    if name.startswith("brief-sent-"):
        return (
            job_for(brief=True),
            name[len("brief-sent-"): -len(".json")].split("-"),
            None,
            payload,
        )
    return None


def reconcile_delivery_receipts():
    """Fill in `primary_delivery` for slots whose sender died before recording it.

    Only ever fills an `unknown` stage, and only for a record that already
    exists: a receipt is evidence about a slot the ledger is tracking, not
    licence to invent slots. An existing verdict is never overwritten — a
    watchdog or a later run knows more than a receipt file does.
    """
    try:
        if not tmp_dir().is_dir():
            return 0
        claims = {}
        for path in sorted(tmp_dir().glob("*-sent-*.json")):
            parsed = _receipt_claims(path)
            if not parsed:
                continue
            job, date_parts, slot, receipt = parsed
            claims[(job, slot, tuple(date_parts) if date_parts else None)] = receipt
        if not claims:
            return 0
        filled = 0
        with _locked():
            ledger = load_ledger()
            for record in ledger.get("records", []):
                stage = record.get("stages", {}).get("primary_delivery", {})
                if stage.get("status") != "unknown":
                    continue
                job, slot = record.get("job"), record.get("slot")
                receipt = claims.get((job, slot, None))
                if receipt is None:
                    receipt = claims.get(
                        (job, None, tuple(str(slot)[:10].split("-")))
                    )
                if receipt is None:
                    continue
                delivered = _receipt_delivered(receipt)
                # The receipt carries the per-channel facts (#771): write them
                # through instead of the old constant "wechat_or_telegram",
                # which made every reconciled slot invisible to the
                # wechat-dropped / telegram-covered count.
                wechat_ok = receipt.get("sent_ok") is True
                telegram_ok = receipt.get("tg_ok") is True
                record["stages"]["primary_delivery"] = _stage(
                    "success" if delivered else "failed",
                    at=_now().isoformat(),
                    channel=delivery_channel(wechat_ok, telegram_ok),
                    wechat_ok=wechat_ok,
                    telegram_ok=telegram_ok,
                    source="delivery_receipt",
                )
                record["final_product"] = _derive_final(record)
                filled += 1
            if filled:
                ledger["updated_at"] = _now().isoformat()
                _atomic_write(local_path(), ledger)
        return filled
    except Exception as exc:
        note_degradation(None, "delivery_reconcile_skipped",
                         f"{type(exc).__name__}: {exc}; terminal delivery "
                         f"stays unknown for any slot whose receipt this pass "
                         f"would have read")
        return 0


def summarize(*, reconcile=False, hours=36):
    """Reconcile, then fold this desk's ledger with the portable arithmetic.

    The fold lives in `clawock.publish.outcomes` because the dashboard has to
    perform the identical one over the published copy; two implementations of
    "what does the card count" would drift the moment either side changed.
    """
    if reconcile:
        reconcile_raw_execution()
        reconcile_delivery_receipts()
    return summarize_records(load_ledger().get("records", []),
                             hours=hours, now=_now())


def publish():
    reconcile_raw_execution()
    reconcile_delivery_receipts()
    ledger = load_ledger()
    before = public_path().read_text() if public_path().exists() else None
    payload = json.dumps(ledger, ensure_ascii=False, indent=2) + "\n"
    if before == payload:
        return False
    _atomic_write(public_path(), ledger)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    if args.publish:
        print(json.dumps({"published": publish(), "path": str(public_path())}))
    else:
        print(json.dumps(summarize(reconcile=True), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
