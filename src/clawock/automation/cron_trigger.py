"""Fire an OpenClaw cron job from the host crontab: the host owns *when*.

Upgrading OpenClaw is blocked by its scheduler, not by its agent runtime: from
2026.9.1 cron-expression ticks are silently swallowed (openclaw#139215, still open
on 9.4), and 9.2 can stop firing altogether after a restart (#141633). Every job on
this desk is a cron expression. The multi-turn agent run itself — preflight, model
turns, postflight, delivery settings — is fine and is what the harness needs.

So a job whose contract says `"trigger": {"by": "host", ...}` is disabled in
OpenClaw and fired by a host crontab line running this module, which queues exactly
the same job with `openclaw cron run <id>`. Verified 2026-09-12 on this host: a
job that is disabled in OpenClaw still runs in full when run this way (mode
`force`). The payload, the isolated session and the delivery settings stay the
job's own; only the scheduler that decides "now" changes.

Two refusals keep it from double-firing: the contract must say the host owns this
job, and OpenClaw must have it disabled. Either one missing is exit 2 with the fix.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from clawock.providers import openclaw
from clawock.scheduling import host_trigger, load_contract
from clawock.workspace import workspace_root

EXIT_REFUSED = 2


def _log(entry, workspace=None) -> None:
    path = Path(workspace or workspace_root()) / "logs" / "cron-trigger.jsonl"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"ts": time.time(), **entry}, ensure_ascii=False) + "\n")
    except OSError:
        pass


def trigger(job_name, *, contract=None, live_jobs=None, run=None, workspace=None,
            check=False) -> int:
    contract = contract if contract is not None else load_contract()
    spec = next((job for job in contract["jobs"] if job.get("name") == job_name), None)
    if spec is None:
        print(f"✗ {job_name}: not in the cron contract", file=sys.stderr)
        return EXIT_REFUSED
    if host_trigger(spec) is None:
        print(f"✗ {job_name}: the contract schedules it in OpenClaw; a host trigger "
              "would run it twice", file=sys.stderr)
        return EXIT_REFUSED
    if not spec.get("enabled", True):
        print(f"· {job_name}: disabled in the contract — nothing to fire")
        return 0
    live_jobs = live_jobs if live_jobs is not None else openclaw.read_jobs().entries
    live = next((job for job in live_jobs or [] if job.get("name") == job_name), None)
    if live is None or not live.get("id"):
        print(f"✗ {job_name}: OpenClaw has no such job", file=sys.stderr)
        _log({"job": job_name, "ok": False, "reason": "no live job"}, workspace)
        return 1
    if live.get("enabled", True):
        print(f"✗ {job_name}: still enabled in OpenClaw, so its own scheduler fires it "
              "too — fix: python3 ops/host/sync_cron_payloads.py --apply", file=sys.stderr)
        _log({"job": job_name, "ok": False, "reason": "enabled in openclaw"}, workspace)
        return EXIT_REFUSED
    if check:
        print(f"✓ {job_name}: contract says host, OpenClaw has it disabled — would queue "
              f"{live['id']} (check only, nothing fired)")
        return 0
    ok, out = (run or openclaw.run_cron_job)(live["id"])
    _log({"job": job_name, "id": live["id"], "ok": ok, "out": out[-300:]}, workspace)
    print(("✓" if ok else "✗") + f" {job_name}: queued via `openclaw cron run` — {out[-160:]}")
    return 0 if ok else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--job-name", required=True)
    parser.add_argument("--check", action="store_true",
                        help="validate the contract and the runtime, fire nothing")
    args = parser.parse_args(argv)
    return trigger(args.job_name, check=args.check)


if __name__ == "__main__":
    sys.exit(main())
