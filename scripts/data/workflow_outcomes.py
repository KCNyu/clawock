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

# The checkout root, so `clawock` resolves from the tree this file ships
# in. Reached through the scripts/data/workspace shim until #267 step 3,
# whose only remaining job was inserting this path as a side effect.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from clawock.workspace import workspace_root  # noqa: E402

# Code lives in the checkout; only DATA lives in the workspace. `workspace_root`
# is overridable, so resolving our own modules through WS would read them out of
# someone else's data directory — or silently pick up whatever happens to be
# there. Same expression WS is seeded from, kept separate on purpose (#269).
_CHECKOUT = Path(__file__).resolve().parents[2]
WS = workspace_root(Path(__file__).resolve().parents[2])
LOCAL_PATH = WS / "memory" / ".tmp" / "workflow-outcomes.json"
PUBLIC_PATH = WS / "assets" / "data" / "workflow-outcomes.json"
LOCK_PATH = WS / "memory" / ".tmp" / "workflow-outcomes.lock"
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
    sys.path.insert(0, str(_CHECKOUT / "scripts" / "data"))
    from cron_contract import effective_schedule, load_contract

    expected = next(
        (job for job in load_contract()["jobs"] if job["name"] == job_name),
        None,
    )
    if not expected:
        raise ValueError(f"job is absent from cron contract: {job_name}")
    schedule = effective_schedule(expected, at)
    expr = (schedule.get("expr") or "").split()
    if len(expr) != 5 or not expr[0].isdigit() or not expr[1].isdigit():
        raise ValueError(f"job does not have a single fixed slot: {job_name}")
    tz = ZoneInfo(schedule.get("tz") or "Asia/Shanghai")
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


def load_ledger():
    return _read_path(LOCAL_PATH) or _read_path(PUBLIC_PATH) or _empty()


def _atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    os.replace(tmp, path)


@contextmanager
def _locked():
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        yield


def _stage(status="unknown", **details):
    out = {"status": status}
    out.update({key: value for key, value in details.items() if value is not None})
    return out


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
            llm in {"failed", "warning"}
            or postflight == "warning"
            or preflight == "warning"
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


def _prune(records, now):
    cutoff = now - timedelta(hours=KEEP_HOURS)
    kept = []
    for record in records:
        try:
            slot = datetime.fromisoformat(record["slot"])
            if slot.tzinfo is None:
                slot = slot.replace(tzinfo=HKT)
        except Exception:
            continue
        if slot.astimezone(timezone.utc) >= cutoff:
            kept.append(record)
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
            records = _prune(ledger.get("records", []), now)
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
            _atomic_write(LOCAL_PATH, ledger)
        return current
    except Exception as exc:
        print(f"warn: workflow outcome stage not recorded: {exc}", file=sys.stderr)
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
    elif state == "completed":
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
        delivered = event.get("wechat_sent") is True or event.get("telegram_sent") is True
        record_stage(
            job,
            "primary_delivery",
            "success" if delivered else "failed",
            slot=slot,
            **details,
        )
    elif state == "watchdog_backstop":
        record_stage(job, "watchdog_delivery", "success", slot=slot, **details)
    elif state in {"watchdog_failed", "watchdog_rejected"}:
        record_stage(job, "watchdog_delivery", "failed", slot=slot, **details)


def _match_run(record, entries):
    try:
        slot_ms = datetime.fromisoformat(record["slot"]).timestamp() * 1000
    except Exception:
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
        sys.path.insert(0, str(_CHECKOUT / "scripts" / "harness"))
        import _watchdog_common as common

        jobs = common.load_jobs("sqlite")
        if common.LAST_LOAD_SOURCE != "sqlite" or not jobs:
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
                run_cache[job_id] = common.read_runs(job_id, "sqlite")
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
                _atomic_write(LOCAL_PATH, latest)
        return changed
    except Exception as exc:
        print(f"warn: raw workflow status reconciliation skipped: {exc}", file=sys.stderr)
        return False


def summarize(*, reconcile=False, hours=36):
    if reconcile:
        reconcile_raw_execution()
    ledger = load_ledger()
    cutoff = _now() - timedelta(hours=hours)
    recent = []
    for record in ledger.get("records", []):
        try:
            slot = datetime.fromisoformat(record["slot"])
            if slot.tzinfo is None:
                slot = slot.replace(tzinfo=HKT)
        except Exception:
            continue
        if slot.astimezone(timezone.utc) >= cutoff:
            recent.append(record)
    recent.sort(key=lambda record: record.get("slot", ""), reverse=True)
    counts = {}
    false_reds = 0
    for record in recent:
        final = (record.get("final_product") or {}).get("status", "pending")
        counts[final] = counts.get(final, 0) + 1
        if (
            (record.get("raw_execution") or {}).get("status") == "error"
            and final in {"success", "recovered", "degraded", "artifact_only"}
        ):
            false_reds += 1
    return {
        "generated_at": _now().isoformat(),
        "window_hours": hours,
        "counts": counts,
        "raw_error_but_product_usable": false_reds,
        "recent": recent[:16],
    }


def publish():
    reconcile_raw_execution()
    ledger = load_ledger()
    before = PUBLIC_PATH.read_text() if PUBLIC_PATH.exists() else None
    payload = json.dumps(ledger, ensure_ascii=False, indent=2) + "\n"
    if before == payload:
        return False
    _atomic_write(PUBLIC_PATH, ledger)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    if args.publish:
        print(json.dumps({"published": publish(), "path": str(PUBLIC_PATH)}))
    else:
        print(json.dumps(summarize(reconcile=True), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
