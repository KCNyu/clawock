#!/usr/bin/env python3
"""Generate docs/operations/cron-schedules.md from config/cron-schedules.json."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_CHECKOUT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_CHECKOUT))
sys.path.insert(0, str(_CHECKOUT / "src"))
from clawock.workspace import workspace_root  # noqa: E402
from clawock.scheduling import host_trigger, load_contract, runtime_enabled  # noqa: E402
from clawock.run_budgets import (  # noqa: E402
    POST_DELIVERY_BUDGET_SECONDS, PRE_DELIVERY_RESERVE_SECONDS,
)

WS = workspace_root(_CHECKOUT)
OUTPUT = WS / "docs" / "operations" / "cron-schedules.md"


def schedule_text(item: dict) -> str:
    seasonal = item.get("seasonal_schedules")
    if seasonal:
        day = seasonal["daylight"]["expr"]
        standard = seasonal["standard"]["expr"]
        return f"EDT `{day}`<br>EST `{standard}`"
    schedule = item["schedule"]
    tz = schedule.get("tz") or "host HKT"
    return f"`{schedule['expr']}` · {tz}"


def watchdog_text(job: dict) -> str:
    rendered = []
    watchdogs = []
    if "watchdog" in job:
        watchdogs.append(("primary watchdog", job["watchdog"]))

    extra_watchdogs = job.get("extra_watchdogs")
    if extra_watchdogs is None:
        pass
    elif not isinstance(extra_watchdogs, list):
        rendered.append("⚠ malformed extra_watchdogs: expected a list")
    else:
        watchdogs.extend(
            (f"extra watchdog {index}", watchdog)
            for index, watchdog in enumerate(extra_watchdogs, start=1)
        )

    for label, watchdog in watchdogs:
        if not isinstance(watchdog, dict):
            rendered.append(f"⚠ malformed {label}: expected an object")
            continue
        if "schedule" not in watchdog and not watchdog.get("seasonal_schedules"):
            rendered.append(f"⚠ malformed {label}: missing schedule")
            continue
        try:
            text = schedule_text(watchdog)
        except (AttributeError, KeyError, TypeError) as exc:
            rendered.append(f"⚠ malformed {label}: invalid schedule ({exc})")
            continue
        if purpose := watchdog.get("purpose"):
            text += f" · {purpose}"
        rendered.append(text)
    return "<br>".join(rendered) or "—"


def _clock(expr: str) -> str:
    """`36 8 * * 1-5` → `08:36`. The prose used to hand-copy this and kept
    saying 08:30 after the contract moved to 08:36 (#2288)."""
    minute, hour = expr.split()[:2]
    return f"{int(hour):02d}:{int(minute):02d}"


def _overnight_last_slot(contract: dict) -> str:
    """Last slot of the overnight monitor, read off its expression: the prose
    said 02:30 while the table beside it printed `3,33 0-2` (#2545)."""
    for job in contract["jobs"]:
        if job.get("name", "").endswith("-overnight"):
            minutes, hours = job["schedule"]["expr"].split()[:2]
            last = lambda field: max(int(part) for part in field.replace("-", ",").split(","))
            return f"{last(hours):02d}:{last(minutes):02d}"
    raise SystemExit("contract has no overnight monitor job")


def _brief_watchdog_clocks(contract: dict) -> tuple[str, str]:
    for job in contract["jobs"]:
        extras = job.get("extra_watchdogs") or []
        if "brief-watchdog" in ((job.get("watchdog") or {}).get("command") or "") and extras:
            return (_clock(job["watchdog"]["schedule"]["expr"]),
                    _clock(extras[0]["schedule"]["expr"]))
    raise SystemExit("cron contract has no brief watchdog with a miss detector")


def _fired_by(job: dict) -> str:
    """Who fires the job, when it is not OpenClaw's own scheduler."""
    if not job.get("enabled", True):
        return "<br>disabled"
    return "<br>fired by host crontab; disabled in OpenClaw" if host_trigger(job) else ""


def _job_counts(contract: dict) -> str:
    """The job-count invariant, counted. It was a literal that said 11 enabled
    while `runtime_enabled` held for 10, and no enable/disable moved it (#2614)."""
    jobs = contract["jobs"]
    running = [job for job in jobs if job.get("enabled", True)]
    scheduled = [job for job in running if runtime_enabled(job)]
    hosted = "、".join(job["name"] for job in running if host_trigger(job))
    market = [job for job in scheduled
              if job.get("payload_profile") in {"brief", "report", "intraday"}]
    others = "、".join(job["name"] for job in scheduled if job not in market)
    text = (f"- {len(jobs)} job identities; exactly {len(scheduled)} enabled in OpenClaw's own "
            f"scheduler ({len(market)} market jobs{f' plus {others}' if others else ''}).")
    if hosted:
        text += (f"\n  The host crontab fires {hosted} (`clawock cron-trigger`), which stays\n"
                 "  disabled in OpenClaw so the slot is not fired twice.")
    return text


def _watchdog_counts(contract: dict) -> dict:
    counts = {"report": 0, "intraday": 0, "brief": 0}
    for job in contract["jobs"]:
        for watchdog in [job.get("watchdog"), *(job.get("extra_watchdogs") or [])]:
            for kind in counts:
                if watchdog and f"clawock-{kind}-watchdog" in (watchdog.get("command") or ""):
                    counts[kind] += 1
    return counts


def render(contract: dict) -> str:
    rows = []
    for job in contract["jobs"]:
        rows.append(
            f"| {job['name']} | {schedule_text(job)}{_fired_by(job)} | {job.get('mode', '—')} | "
            f"`{job.get('harness', '—')}` | {watchdog_text(job)} |"
        )
    passes = _watchdog_counts(contract)
    brief_backstop, brief_miss = _brief_watchdog_clocks(contract)
    overnight_last = _overnight_last_slot(contract)
    return "\n".join([
        "# Cron schedule contract / 调度契约",
        "",
        "<!-- GENERATED by ops/host/generate_cron_docs.py; DO NOT EDIT. -->",
        "",
        "This file is the generated human view of `config/cron-schedules.json`. Runtime truth",
        "is `openclaw cron list --json`; `ops/system_check.py` checks runtime schedules,",
        "payload semantics, watchdog crontab lines, and the daily DST synchronizer against",
        "the contract before every push.",
        "",
        "本文由 `config/cron-schedules.json` 自动生成。运行态以 `openclaw cron list --json`",
        "为准；每次 push 前，system check 会同时校验 schedule、payload 语义、watchdog 和 DST",
        "同步任务。禁止手改本表；修改 contract 后运行生成器。",
        "",
        "## DST policy / 夏令时策略",
        "",
        "US market jobs remain expressed in HKT because the daemon's ET timezone parser has",
        "regressed before. `ops/host/sync_us_cron_dst.py --apply` runs daily at **06:20 HKT**, derives",
        "the season from `America/New_York`, and updates both OpenClaw jobs and their system",
        f"watchdogs. The overnight monitor's last slot is {overnight_last} HKT in both seasons, ahead of",
        "03:00 memory dreaming; standard time therefore has two fewer US intraday slots.",
        "",
        "美股 job 继续使用 HKT 表达式，但由每日 06:20 的同步器按纽约真实 UTC offset 自动",
        f"切换。隔夜盯盘无论冬夏令时最后一档都是 {overnight_last} HKT，排在 03:00 dreaming 之前；",
        "因此冬令时比夏令时少两个盘中 slot。",
        "",
        "## Whole-turn budget / 回合预算",
        "",
        "Report and intraday turns allow 28 minutes; the brief allows 30. The shared",
        f"post-delivery network/build retry chain reserves {POST_DELIVERY_BUDGET_SECONDS} seconds plus {PRE_DELIVERY_RESERVE_SECONDS} seconds",
        "for preflight, judgment, delivery and local work. The contract rejects a turn",
        "limit that cannot cover that reservation. These are ceilings, not expected",
        "durations; a late preflight can still consume its own whole-turn deadline.",
        "Report/intraday watchdogs fire 20 minutes after the slot and wait up to 10",
        "minutes for an in-flight attempt, so their verdict clears the 28-minute limit.",
        "The intraday turn plus the 30-second retry backoff still clears the next slot.",
        "",
        "## OpenClaw jobs + watchdogs",
        "",
        "| Job | OpenClaw schedule | Mode | Harness | System watchdog |",
        "|---|---|---|---|---|",
        *rows,
        "",
        "## Operational invariants / 运维不变量",
        "",
        _job_counts(contract),
        f"- {passes['report']} report, {passes['intraday']} intraday and {passes['brief']} brief watchdog passes are tracked; the brief",
        f"  uses an {brief_backstop} delivery backstop plus a {brief_miss} post-window miss detector.",
        "- Market payloads use deterministic preflight/postflight, `delivery.mode=none`,",
        "  a unique WeChat path, Telegram mirror, and an ordered unique subset of the",
        "  fixed model candidates defined by the contract. Runtime rotations must remain",
        "  a prefix of that order; health checks never reorder or skip candidates.",
        "- Mode 7 writes the public `assets/data/cron-heartbeats.json` ledger through the",
        "  existing single publisher; cron health verifies every monitored slot. Delivery",
        "  confirmation cannot clear `publish_failed`; only a successful publication",
        "  verdict can. Health also reads retained publication details in older events",
        "  whose state was overwritten by watchdog delivery success (#2234).",
        "- Cron health uses each report's tracked phase with the same `phase_session`",
        "  calendar gate as preflight/postflight: HK half-days still require the midday",
        "  report, while `pm` and `close` reports are correctly skipped (#2231).",
        "- Mode 7 agent turns run on every scheduled slot. The pre-model delta trigger",
        "  was removed on 2026-07-27: model workload is not the binding constraint, and",
        "  a silently skipped slot is indistinguishable from a dead cron. Closed markets",
        "  are still handled downstream by the preflight/postflight calendar gate.",
        "",
    ])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    content = render(load_contract())
    if args.check:
        current = OUTPUT.read_text() if OUTPUT.exists() else ""
        if current != content:
            print("docs/operations/cron-schedules.md is stale; run generate_cron_docs.py")
            return 1
        print("docs/operations/cron-schedules.md matches contract")
        return 0
    OUTPUT.write_text(content)
    print(f"wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
