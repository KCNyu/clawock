#!/usr/bin/env python3
"""Local-to-public heartbeat ledger for intraday cron slots.

Harness/watchdog processes only update the ignored local ledger. The single
dashboard publisher adds its public sidecar to the same data-plane generation
under the same lock, avoiding another independent git writer.
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

from clawock.workspace import workspace_root
from clawock.automation import workflow_outcomes

WS = workspace_root(Path.cwd())
LOCAL_PATH = WS / "memory" / ".tmp" / "cron-heartbeats.json"
PUBLIC_PATH = WS / "assets" / "data" / "cron-heartbeats.json"
HKT = ZoneInfo("Asia/Hong_Kong")
SCHEMA_VERSION = 1
KEEP_HOURS = 72


def _now(at: datetime | None = None) -> datetime:
    at = at or datetime.now(timezone.utc)
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def slot_for(market: str, at: datetime | None = None) -> tuple[str, str]:
    local = _now(at).astimezone(HKT)
    minute = 30 if local.minute >= 30 else 0
    slot = local.replace(minute=minute, second=0, microsecond=0)
    if market == "hk":
        name = "盘中盯盘"
    elif local.hour <= 3:
        name = "美股盘中盯盘-overnight"
    else:
        name = "美股盘中盯盘"
    return name, slot.isoformat()


def _empty(at: datetime | None = None) -> dict:
    now = _now(at)
    return {
        "schema_version": SCHEMA_VERSION,
        "monitoring_started_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "events": [],
    }


def _load() -> tuple[dict, bool]:
    """Return (ledger, from_disk). from_disk is False only when no valid ledger
    file exists yet and a blank one was synthesised."""
    for path in (LOCAL_PATH, PUBLIC_PATH):
        try:
            data = json.loads(path.read_text())
            if data.get("schema_version") == SCHEMA_VERSION:
                return data, True
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            continue
    return _empty(), False


def load_ledger() -> dict:
    return _load()[0]


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    os.replace(tmp, path)


@contextmanager
def _locked():
    """Same convention as workflow_outcomes._locked(): record() is an unlocked
    read-modify-write over a shared ledger and the writers genuinely overlap —
    the intraday watchdog fires slot+10min while the model turn can run ~16min,
    so postflight's 'completed' and a watchdog backstop can race. Without the
    lock one writer's ledger silently erases the other's event (false gap in
    the published coverage sidecar). Derived from LOCAL_PATH so test fixtures
    that redirect it stay isolated."""
    lock_path = LOCAL_PATH.with_suffix(LOCAL_PATH.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        yield


def record(market: str, state: str, *, at: datetime | None = None,
           job_name: str | None = None, slot: str | None = None, **details) -> dict:
    now = _now(at)
    derived_name, derived_slot = slot_for(market, now)
    job_name = job_name or derived_name
    slot = slot or derived_slot
    # Lock spans load→merge→write (same convention as workflow_outcomes).
    with _locked():
        ledger, from_disk = _load()
        # A brand-new ledger gets stamped with real wall-clock now inside _empty();
        # anchor monitoring_started_at to this first record's slot boundary instead,
        # otherwise the current slot (crons fire a few minutes past the boundary)
        # is judged as "before monitoring began" and silently dropped from coverage.
        # Only re-anchor when no ledger existed on disk — a valid ledger that merely
        # has no live events keeps its real monitoring epoch (don't erase earlier gaps).
        was_fresh = not from_disk
        cutoff = now - timedelta(hours=KEEP_HOURS)
        events = []
        current = None
        for event in ledger.get("events", []):
            try:
                event_time = datetime.fromisoformat(event["slot"])
                if event_time.tzinfo is None:
                    event_time = event_time.replace(tzinfo=HKT)
            except Exception:
                continue
            if event_time.astimezone(timezone.utc) < cutoff:
                continue
            if event.get("job") == job_name and event.get("slot") == slot:
                current = dict(event)
            else:
                events.append(event)
        current = current or {"job": job_name, "market": market, "slot": slot}
        current.update({"state": state, "updated_at": now.isoformat()})
        for key, value in details.items():
            if value is not None:
                current[key] = value
        events.append(current)
        events.sort(key=lambda e: (e.get("slot", ""), e.get("job", "")))
        ledger["schema_version"] = SCHEMA_VERSION
        if was_fresh:
            ledger["monitoring_started_at"] = slot
        ledger.setdefault("monitoring_started_at", now.isoformat())
        ledger["updated_at"] = now.isoformat()
        ledger["events"] = events
        _atomic_write(LOCAL_PATH, ledger)
    # Tests and one-off callers redirect LOCAL_PATH to an isolated fixture. Do
    # not let that write a second ledger in the real workspace.
    if LOCAL_PATH == WS / "memory" / ".tmp" / "cron-heartbeats.json":
        try:
            workflow_outcomes.record_from_heartbeat(current)
        except Exception as exc:
            print(f"warn: workflow outcome bridge failed: {exc}", file=sys.stderr)
    return current


def publish() -> bool:
    ledger = load_ledger()
    before = PUBLIC_PATH.read_text() if PUBLIC_PATH.exists() else None
    payload = json.dumps(ledger, ensure_ascii=False, indent=2) + "\n"
    if before == payload:
        return False
    _atomic_write(PUBLIC_PATH, ledger)
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--market", choices=["hk", "us"])
    parser.add_argument("--state")
    args = parser.parse_args()
    if args.publish:
        changed = publish()
        print(json.dumps({"published": changed, "path": str(PUBLIC_PATH)}))
        return 0
    if not args.market or not args.state:
        parser.error("--market and --state are required unless --publish is used")
    print(json.dumps(record(args.market, args.state), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
