#!/usr/bin/env python3
"""
cron_health_check.py — EOD 巡检：报告产出 commit + 盘中逐 slot heartbeat。

本机通过 OpenClaw CLI/SQLite 读取 live schedule；GitHub Actions 通过
`config/cron-schedules.json` 读取同一份受版本控制的 schedule contract。然后按
HKT（不是 runner 本地时区）读取 git commit log；Mode 7 则读取公开 heartbeat
ledger，核对每个已过 slot 是否完成或由 watchdog 接管。

输出：缺失/告警/正常 列表。可作为 GH Action 跑 EOD 一次，或者手动运行。

Exit codes:
  0 — 一切正常
  1 — 有 cron 应该跑但没跑（缺失）
  2 — 只是 warn (delay 等)

Usage:
  python3 ops/host/cron_health_check.py            # human report
  python3 ops/host/cron_health_check.py --json     # machine-readable
  python3 ops/host/cron_health_check.py --silent   # 仅 exit code
  python3 ops/host/cron_health_check.py --jobs-file config/cron-schedules.json
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

_CHECKOUT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_CHECKOUT))
sys.path.insert(0, str(_CHECKOUT / "src"))
from clawock.workspace import workspace_root  # noqa: E402
from clawock.providers import openclaw  # noqa: E402

# Code lives in the checkout; only DATA lives in the workspace. `workspace_root`
# is overridable, so resolving our own modules through WS would read them out of
# someone else's data directory — or silently pick up whatever happens to be
# there. Same expression WS is seeded from, kept separate on purpose (#269).
WS = workspace_root(_CHECKOUT)
# The checkout root, so `clawock` is importable regardless of where the WORKSPACE
# points. WS can be redirected with CLAWOCK_WORKSPACE and is a data directory;
# the package lives in the checkout. Inserting it here rather than inside the
# function is what test_harness_import_independence requires — an import that
# resolves only because some other module happened to widen sys.path first is a
# side effect, not a dependency (#265).
import cron_token_audit  # noqa: E402

HKT = ZoneInfo('Asia/Hong_Kong')
TERMINAL_HEARTBEAT_STATES = {
    'completed', 'watchdog_backstop', 'market_closed', 'no_change'
}
HEARTBEAT_GRACE_MINUTES = 25

# Indexed directly (not .get) so a state added to check_dashboard_build without
# an icon fails here loudly instead of printing a blank cell. Module-level so the
# tests can index the real map rather than restate it.
DASHBOARD_STATE_ICONS = {
    'ok': '✓', 'repaired': '🔧', 'degraded': '⚠', 'stale': '⚠',
    'failed': '✗', 'absent': '·',
}

# Cron name → identifying commit msg patterns
COMMIT_PATTERNS = {
    '港股开盘报告': r'港股开盘',
    '港股午盘报告': r'港股午盘',
    '港股午后快报': r'港股午后',
    '港股收盘报告': r'港股收盘',
    '美股开盘报告': r'美股开盘',
    '美股收盘报告': r'美股收盘',
    '盘前深度简报': r'daily deep brief',
    '盘中盯盘': None,        # Mode 7 dashboard commit 不是 one-per-slot contract
    '美股盘中盯盘': None,    # same
    '美股盘中盯盘-overnight': None,
    'Memory Dreaming Promotion': None,  # 不 commit
}


def parse_cron_slots(expr, tz_name, target_date_utc):
    """Given cron expr like `*/30 10-11,14-15 * * 1-5` + tz, return list of
    HH:MM strings that should fire on `target_date_utc` (UTC datetime).

    Simple parser: handles minute (*/N or list), hour (range,list), DOW.
    """
    parts = expr.split()
    if len(parts) < 5:
        return []
    m_field, h_field, _dom, _mo, dow_field = parts[:5]

    # Minute: */N or list
    def parse_field(field, lo, hi):
        vals = set()
        for tok in field.split(','):
            tok = tok.strip()
            if tok == '*':
                vals.update(range(lo, hi+1))
            elif tok.startswith('*/'):
                step = int(tok[2:])
                vals.update(range(lo, hi+1, step))
            elif '-' in tok:
                a, b = tok.split('-')
                # may have /step
                step = 1
                if '/' in b:
                    b, step = b.split('/')
                    step = int(step)
                vals.update(range(int(a), int(b)+1, step))
            else:
                vals.add(int(tok))
        return sorted(vals)

    mins = parse_field(m_field, 0, 59)
    hours = parse_field(h_field, 0, 23)
    dows = set(parse_field(dow_field, 0, 7))
    # 0 and 7 both = Sunday in cron
    if 7 in dows:
        dows.discard(7); dows.add(0)

    # Get target date in target tz
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name)
    except Exception:
        # fall back: assume UTC
        tz = timezone.utc
    target_local = target_date_utc.astimezone(tz)
    # cron DOW: 0=Sun, 1=Mon, ..., 6=Sat
    py_weekday = target_local.weekday()  # 0=Mon
    cron_dow = (py_weekday + 1) % 7      # convert: Mon→1 ... Sun→0
    if cron_dow not in dows:
        return []

    return [f"{h:02d}:{m:02d}" for h in hours for m in mins]


def runs_finished_today(job_id, provider=None):
    """How many times the job finished OK today, per the run-history provider.

    ADVISORY ONLY. It answers a different question from counting commits — "did
    the job run" rather than "did the job produce" — and the two can legitimately
    disagree: a run that finishes clean but writes nothing is healthy here and
    missing there, and a cron status can itself be falsely red when a mid-run
    failure gets recovered (see the 2026-07-22 false-red postmortem).

    Migrating this check onto the provider is a prerequisite of moving the
    outputs off `master`, because today the commit IS the receipt (#262). But a
    straight swap would silently change what a live alerting path means, so this
    is reported beside the commit count and measured for agreement first.

    Never raises and never influences status: an advisory signal that can fail
    the health check is worse than no advisory signal.
    """
    if not job_id:
        return None
    try:
        if provider is None:
            from clawock.providers.runs import OpenClawRuns
            provider = OpenClawRuns()
        today = datetime.now(HKT).date()
        count = 0
        for run in provider.history(job_id, limit=200):
            if run.status != 'ok' or not run.started_at:
                continue
            try:
                started = datetime.fromisoformat(run.started_at)
            except ValueError:
                continue
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            if started.astimezone(HKT).date() == today:
                count += 1
        return count
    except Exception:
        return None


_commit_log_cache = None


def _commit_log_entries():
    """Fetch (committer-ISO, subject) pairs once per process.

    commit_count_today runs once per enabled job (~11), and each call used to
    re-run the same `git log -n 500` subprocess and re-parse the same lines;
    the job loop now shares a single fetch. A failed fetch degrades to an
    empty list — identical to the old per-call failure path (count 0).
    """
    global _commit_log_cache
    if _commit_log_cache is None:
        entries = []
        try:
            r = subprocess.run(
                ['git', '-C', str(WS), 'log', '-n', '500', '--format=%cI%x00%s'],
                capture_output=True, text=True, timeout=15,
            )
            if r.returncode == 0:
                for line in r.stdout.splitlines():
                    if '\x00' in line:
                        stamp, subject = line.split('\x00', 1)
                        entries.append((stamp, subject))
        except Exception:
            pass
        _commit_log_cache = entries
    return _commit_log_cache


def commit_count_on(commit_pattern, day):
    """Count matching commits whose committer date falls on `day` (HKT date).

    GitHub runners use UTC. `git log --since=<today> 00:00` therefore dropped the
    04:00-HKT US-close commit (20:00 UTC on the prior date) and reported a false
    miss every day. Parse the ISO offset carried by each commit instead.
    """
    if not commit_pattern:
        return None  # Mode 7 uses heartbeats; dream has no output contract
    count = 0
    for stamp, subject in _commit_log_entries():
        try:
            commit_day = datetime.fromisoformat(stamp).astimezone(HKT).date()
        except ValueError:
            continue
        if commit_day == day and re.search(commit_pattern, subject):
            count += 1
    return count


def commit_count_today(commit_pattern):
    return commit_count_on(commit_pattern, datetime.now(HKT).date())


def load_runtime_jobs(jobs_file=None):
    """Load cron jobs from an explicit tracked contract or the live CLI layer."""
    if jobs_file:
        from clawock.scheduling import effective_schedule, load_contract
        data = load_contract(jobs_file)
        jobs = []
        for job in data['jobs']:
            resolved = dict(job)
            resolved['schedule'] = effective_schedule(job)
            jobs.append(resolved)
        return jobs

    jobs = openclaw.read_jobs().entries
    if not jobs:
        raise RuntimeError('OpenClaw CLI returned no cron jobs; run `openclaw doctor --fix`')
    return jobs


def load_heartbeats(path=None):
    """Load the host-local ledger when present, otherwise the published public copy."""
    candidates = ([Path(path)] if path else [
        WS / 'memory' / '.tmp' / 'cron-heartbeats.json',
        WS / 'assets' / 'data' / 'cron-heartbeats.json',
    ])
    for candidate in candidates:
        try:
            data = json.loads(candidate.read_text())
            if data.get('schema_version') == 1:
                return data
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            continue
    return None


def load_workflow_outcomes(path=None):
    """Load the published per-slot product ledger (assets/data/workflow-outcomes.json),
    same host-local-then-published fallback as load_heartbeats. Written by
    `clawock.automation.workflow_outcomes` and, for staged report crons, by the
    Telegram backstop in `report_watchdog.py` (via `_watchdog_common._record_watchdog_outcome`)."""
    candidates = ([Path(path)] if path else [
        WS / 'memory' / '.tmp' / 'workflow-outcomes.json',
        WS / 'assets' / 'data' / 'workflow-outcomes.json',
    ])
    for candidate in candidates:
        try:
            data = json.loads(candidate.read_text())
            if data.get('schema_version') == 1 and isinstance(data.get('records'), list):
                return data
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            continue
    return None


def backstop_covered_slots(job_name, slots, tz_name, outcomes, today=None):
    """Which of `slots` (HH:MM local, today) has a workflow-outcomes record whose
    final_product is 'recovered' — i.e. watchdog_delivery succeeded.

    #696: a staged report cron's Telegram backstop is DELIBERATELY commit-free
    (report_watchdog.py, 2026-07-09 kcn's call: no WeChat resend, Telegram-only
    mirror) — so counting git commits alone reads every backstop-covered slot as
    total non-delivery, the same red as a report kcn genuinely never got. This
    reads the one ledger that already tells the two apart (`final_product.status
    == 'recovered'` is set only when `watchdog_delivery` itself succeeded).

    `today` must be checked, not just HH:MM: the ledger keeps 96h of records
    (workflow_outcomes.KEEP_HOURS), so a same-time slot recovered on an earlier
    day would otherwise silently paper over a genuine miss today.

    Slot-level, not commit-level: `commit_count_today` has no way to say WHICH
    slot a commit belongs to, so this can only compare counts (below), not
    prove a specific gap slot is the one covered. That is the same precision
    the existing commit-count check already operates at.
    """
    if not outcomes:
        return set()
    tz = ZoneInfo(tz_name)
    today = today or datetime.now(tz).date()
    covered = set()
    for record in outcomes.get('records', []):
        if record.get('job') != job_name:
            continue
        if record.get('final_product', {}).get('status') != 'recovered':
            continue
        try:
            slot_dt = datetime.fromisoformat(record['slot'])
            if slot_dt.tzinfo is None:
                slot_dt = slot_dt.replace(tzinfo=HKT)
            slot_local = slot_dt.astimezone(tz)
        except Exception:
            continue
        if slot_local.date() != today:
            continue
        hhmm = slot_local.strftime('%H:%M')
        if hhmm in slots:
            covered.add(hhmm)
    return covered


def heartbeat_coverage(job_name, slots, tz_name, now, ledger, day=None):
    """Return monitored/healthy/missing slot sets for one intraday job.

    `day` overrides the calendar day the slots belong to (#996): post-window
    jobs are verified against YESTERDAY's events, not the run's own day.
    """
    if not ledger:
        return {'monitored': slots, 'healthy': [], 'missing': slots,
                'failed': [], 'pending': []}
    try:
        started = datetime.fromisoformat(ledger['monitoring_started_at'])
        if started.tzinfo is None:
            started = started.replace(tzinfo=HKT)
    except Exception:
        started = datetime.min.replace(tzinfo=timezone.utc)
    tz = ZoneInfo(tz_name)
    local_day = day or now.astimezone(tz).date()
    monitored = []
    for slot in slots:
        hour, minute = map(int, slot.split(':'))
        slot_dt = datetime.combine(local_day, datetime.min.time(), tzinfo=tz).replace(
            hour=hour, minute=minute
        )
        if slot_dt.astimezone(timezone.utc) >= started.astimezone(timezone.utc):
            monitored.append(slot)
    events = {}
    for event in ledger.get('events', []):
        if event.get('job') != job_name:
            continue
        try:
            event_dt = datetime.fromisoformat(event['slot'])
            if event_dt.tzinfo is None:
                event_dt = event_dt.replace(tzinfo=HKT)
            event_local = event_dt.astimezone(tz)
        except Exception:
            continue
        if event_local.date() == local_day:
            events[event_local.strftime('%H:%M')] = event
    healthy, failed, missing, pending = [], [], [], []
    for slot in monitored:
        hour, minute = map(int, slot.split(':'))
        slot_dt = datetime.combine(local_day, datetime.min.time(), tzinfo=tz).replace(
            hour=hour, minute=minute
        )
        within_grace = now.astimezone(tz) - slot_dt < timedelta(
            minutes=HEARTBEAT_GRACE_MINUTES
        )
        event = events.get(slot)
        if not event:
            (pending if within_grace else missing).append(slot)
        elif event.get('state') in TERMINAL_HEARTBEAT_STATES:
            healthy.append(slot)
        elif within_grace:
            pending.append(f"{slot}:{event.get('state', '?')}")
        else:
            failed.append(f"{slot}:{event.get('state', '?')}")
    return {'monitored': monitored, 'healthy': healthy, 'missing': missing,
            'failed': failed, 'pending': pending}


# How long the published generation may sit unchanged on a trading day before
# the scheduled publisher is presumed dead. Deliberately generous: the publisher
# only pushes when the semantic diff says something changed, so a quiet tick
# publishing nothing is healthy. This threshold is not "the cadence" (20 min) —
# it is "nothing has moved in the book for three hours during a session", which
# on a trading day means the 0,20,40 crontab entry stopped running.
PUBLISHER_STALE_HOURS = 3


def check_scheduled_publisher(now=None, path=None):
    """Is the every-20-minutes publisher still reaching the data branch?

    #325 moved the generated outputs off `master`, which removed the
    `dashboard: scheduled publish <ts>` commits — the de-facto liveness signal
    for the crontab entry that produces them (kcn, 2026-08-06: "以前 schedule
    publisher 是不是用来监控…现在也看不到"). Nothing replaced it: the publisher
    writes no heartbeat, appears in no ledger, and does not even write
    logs/dashboard_build_status.json (that file has three postflight writers and
    the publisher is none of them). A dead publisher's only symptom was a site
    quietly frozen on an old generation.

    So ask the published generation itself how old it is. This costs nothing:
    the workflow already materialises the data branch before running this check,
    so `assets/data/dashboard.json` here IS the last generation the site serves.
    Run on a host instead of in CI it answers the weaker local question ("when
    did this host last build"), which is why it never escalates past a warning.
    """
    path = path or (WS / 'assets' / 'data' / 'dashboard.json')
    now = now or datetime.now(timezone.utc)
    if not path.exists():
        return {'state': 'absent', 'detail': 'no published generation to read',
                'age_hours': None}
    try:
        stamp = json.loads(path.read_text()).get('generated_at')
        published = datetime.fromisoformat(str(stamp).replace('Z', '+00:00'))
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
    except Exception as e:
        return {'state': 'failed', 'detail': f'generation stamp unreadable: {e}',
                'age_hours': None}
    age_hours = round((now - published).total_seconds() / 3600, 1)
    local = now.astimezone(HKT)
    # A weekend or a double holiday has no session to publish into, so silence
    # is correct there and must not be reported as a stalled publisher.
    # Same local, fail-open import as _market_closed_today: an unavailable
    # calendar must not turn this into a red, so it falls through to judging.
    try:
        from clawock import sessions as _tc
        trading = any(_tc.is_trading_day(m, local.date()) for m in ('hk', 'us'))
    except Exception:
        trading = True
    if not trading:
        return {'state': 'ok',
                'detail': f'last generation {age_hours}h old · 非交易日不判',
                'age_hours': age_hours}
    if age_hours > PUBLISHER_STALE_HOURS:
        return {'state': 'stale',
                'detail': (f'已发布的那一代已 {age_hours}h 未更新 '
                           f'(> {PUBLISHER_STALE_HOURS}h) — 0,20,40 的 '
                           f'publish_dashboard.sh 大概率没在跑'),
                'age_hours': age_hours}
    return {'state': 'ok', 'detail': f'last generation {age_hours}h old',
            'age_hours': age_hours}


def check_dashboard_build():
    """Read logs/dashboard_build_status.json (written by _harness_common.rebuild_dashboard).

    Returns a dict with keys: state
    ('ok'|'repaired'|'degraded'|'stale'|'failed'|'absent'), detail, ok,
    warn_count, repair_count, age_hours. A failed build or publish means the
    public generation may be frozen while commits keep flowing — the silent-freeze
    case this guards against.
    """
    path = WS / 'logs' / 'dashboard_build_status.json'
    if not path.exists():
        return {'state': 'absent', 'detail': 'no build status file yet', 'ok': None,
                'warn_count': 0, 'repair_count': 0, 'age_hours': None}
    try:
        st = json.loads(path.read_text())
    except Exception as e:
        return {'state': 'failed', 'detail': f'status file unreadable: {e}', 'ok': False,
                'warn_count': 0, 'repair_count': 0, 'age_hours': None}
    age_hours = None
    try:
        ts = datetime.strptime(st['checked_at'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
        age_hours = round((datetime.now(timezone.utc) - ts).total_seconds() / 3600, 1)
    except Exception:
        pass
    if not st.get('ok'):
        build_ok = st.get('build_ok')
        publish_ok = st.get('publish_ok')
        if build_ok is True and publish_ok is False:
            failure = 'data-plane publish FAILED — public generation may be stale'
        elif build_ok is False:
            failure = 'dashboard build FAILED — no generation was produced'
        else:
            # Rolling-upgrade compatibility for the old one-bit status file.
            failure = 'dashboard build/publish FAILED — public generation may be stale'
        return {'state': 'failed', 'detail': f"{failure}. tail: {st.get('tail','')[-500:]}",
                'ok': False, 'warn_count': st.get('warn_count', 0),
                'repair_count': st.get('repair_count', 0), 'age_hours': age_hours,
                'build_ok': build_ok, 'publish_ok': publish_ok}
    if st.get('warn_count'):
        return {'state': 'degraded', 'detail': f"{st['warn_count']} degraded section(s) on last build",
                'ok': True, 'warn_count': st['warn_count'],
                'repair_count': st.get('repair_count', 0), 'age_hours': age_hours}
    # Repairs are reported, never escalated: the sidecar parsed after repair, so
    # every card rendered. This state exists so a producer that ships invalid
    # JSON daily is visible in the review instead of being quietly patched.
    if st.get('repair_count'):
        return {'state': 'repaired',
                'detail': f"{st['repair_count']} sidecar(s) JSON-repaired on last build",
                'ok': True, 'warn_count': 0, 'repair_count': st['repair_count'],
                'age_hours': age_hours}
    # Build OK; flag only if very stale (weekend gaps are normal, so 24h threshold)
    if age_hours is not None and age_hours > 24:
        return {'state': 'stale', 'detail': f'last successful build {age_hours}h ago',
                'ok': True, 'warn_count': 0, 'repair_count': 0, 'age_hours': age_hours}
    return {'state': 'ok', 'detail': f'last build ok ({age_hours}h ago)' if age_hours is not None else 'last build ok',
            'ok': True, 'warn_count': 0, 'repair_count': 0, 'age_hours': age_hours}


def _market_closed_on(market, day=None):
    """True if `market` ('hk'/'us') is closed on `day` (default: today, its own TZ).

    Used to suppress false 'missing commit' reds: a market-report cron on that market's
    holiday is correctly skipped by preflight's holiday gate (memory: openclaw-market-holiday-gate),
    so it produces no commit by design. Fail-open (False) if the calendar is unavailable."""
    try:
        from clawock import sessions as _tc
        return not _tc.is_trading_day(market, day)
    except Exception:
        return False


def _market_closed_today(market):
    return _market_closed_on(market)


# Jobs whose slots exist only because the US session crosses HKT midnight: their
# Tue–Sat slots monitor the PREVIOUS day's US session (#454's rule — a fill typed
# Saturday 01:08 HKT traded Friday). Judging them on the slot's own calendar date
# got both directions wrong at once: every Saturday read as "US closed" (always
# true) so the Friday-session slots were recorded in the ledgers and verified by
# no one, while a US holiday's own skip surfaced as a missing report on the NEXT
# trading morning, whose calendar says open. The holiday gate must ask about the
# session day, not the wall-clock day (#955).
SESSION_DAY_OFFSET_JOBS = frozenset({'美股收盘报告', '美股盘中盯盘-overnight'})

# Jobs whose slots fire AFTER every health window of their own calendar day
# (this check runs 17:17 HKT; the worst observed schedule drift lands ~20:35):
# 美股开盘报告 21:30/22:30 and the 美股盘中盯盘 evening half-hour slots. A same-day
# expectation can never see them — parse_cron_slots only expands the target
# date and the filter keeps only slots already past, so both jobs sat in
# permanent 'idle' while their commits/heartbeats went unverified by anyone,
# the weekday-wide version of #955's Saturday hole (#996). The NEXT day's run
# verifies YESTERDAY's slots instead; unlike SESSION_DAY_OFFSET_JOBS these do
# not cross HKT midnight, so the session day IS the slot's own date.
POST_WINDOW_JOBS = frozenset({'美股开盘报告', '美股盘中盯盘'})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--silent', action='store_true')
    ap.add_argument('--jobs-file', help='tracked cron contract (used by CI)')
    ap.add_argument('--heartbeats-file', help='published heartbeat ledger (used by CI)')
    ap.add_argument('--outcomes-file', help='published workflow-outcomes ledger (used by CI)')
    args = ap.parse_args()

    try:
        jobs = load_runtime_jobs(args.jobs_file)
    except Exception as e:
        if not args.silent:
            print(f'FATAL: cron schedules unavailable: {e}', file=sys.stderr)
        sys.exit(1)

    now = datetime.now(timezone.utc)
    heartbeat_ledger = load_heartbeats(args.heartbeats_file)
    outcomes_ledger = load_workflow_outcomes(args.outcomes_file)

    report = []
    has_missing = False
    has_warn = False

    for job in jobs:
        if not job.get('enabled', True):
            continue
        name = job.get('name', job.get('id','?'))
        sched = job.get('schedule', {})
        expr = sched.get('expr','')
        tz = sched.get('tz') or 'Asia/Shanghai'
        # Post-window jobs (#996) are judged on YESTERDAY's schedule and
        # yesterday's evidence; every other job keeps today.
        post_window = name in POST_WINDOW_JOBS
        expected_day = now - timedelta(days=1) if post_window else now
        expected = parse_cron_slots(expr, tz, expected_day)
        # Only check slots already past
        try:
            from zoneinfo import ZoneInfo
            now_local = now.astimezone(ZoneInfo(tz)).strftime('%H:%M')
        except Exception:
            now_local = now.strftime('%H:%M')
        if post_window:
            # Yesterday's slots are past by construction; the HH:MM filter
            # would wrongly drop the ones firing after 17:17.
            expected_past = list(expected)
        else:
            expected_past = [s for s in expected if s <= now_local]
        commit_pat = COMMIT_PATTERNS.get(name)
        verify_date = expected_day.astimezone(HKT).date()
        commit_n = commit_count_on(commit_pat, verify_date)
        # Advisory second evidence source (#262). Reported, never acted on.
        runs_n = runs_finished_today(job.get('id'))

        # Holiday gate: don't expect a commit from a 港股*/美股* report on that market's
        # holiday — preflight skips the run by design (the 6-19 端午+Juneteenth double
        # close was a false red). 港股→hk, 美股→us; other jobs (brief/dream) unaffected.
        mkt = 'hk' if name.startswith('港股') else ('us' if name.startswith('美股') else None)
        both_closed = name == '盘前深度简报' and all(
            _market_closed_today(m) for m in ('hk', 'us')
        )
        market_closed = False
        if mkt:
            session_day = None
            if name in SESSION_DAY_OFFSET_JOBS:
                try:
                    session_day = (
                        now.astimezone(ZoneInfo(tz)).date() - timedelta(days=1))
                except Exception:
                    session_day = None  # fail open into the same-day gate below
            elif post_window:
                # No midnight crossing here: the slots' own date IS the session
                # day being verified (#996).
                session_day = verify_date
            market_closed = (
                _market_closed_on(mkt, session_day)
                if session_day is not None else _market_closed_today(mkt))
        if expected_past and (market_closed or both_closed):
            label = f'{mkt.upper()} 休市' if mkt else 'HK + US 均休市'
            report.append({
                'name': name, 'schedule': expr, 'tz': tz,
                'expected_today': 0, 'commits_today': commit_n,
                'status': 'holiday', 'detail': f'{label} · 跳过(无需 commit)',
            })
            continue

        status = 'ok'
        detail = ''
        if not expected_past:
            status = 'idle'  # nothing scheduled today yet
            detail = f'next: {expected[0] if expected else "n/a"}'
        elif commit_pat:
            if commit_n < len(expected_past):
                # 缺少 commit — 可能漏跑，也可能是 Telegram backstop 接管（设计上不产
                # 生 commit，见 backstop_covered_slots）。两者是不同的红，分开报（#696）。
                gap = len(expected_past) - commit_n
                covered = backstop_covered_slots(
                    name, expected_past, tz, outcomes_ledger, today=verify_date)
                if len(covered) >= gap:
                    status = 'backstop'
                    detail = (f'expected {len(expected_past)} commits, got {commit_n} — '
                              f'{len(covered)} slot(s) confirmed via Telegram backstop '
                              f'instead (watchdog recovered, no commit by design)')
                    has_warn = True
                else:
                    status = 'missing'
                    detail = f'expected {len(expected_past)} commits, got {commit_n}'
                    if covered:
                        detail += (f'; {len(covered)} of the gap covered by backstop, '
                                  f'{gap - len(covered)} still unaccounted')
                    has_missing = True
            else:
                detail = f'{commit_n}/{len(expected_past)} commits OK'
        elif name in ('盘中盯盘', '美股盘中盯盘', '美股盘中盯盘-overnight'):
            coverage = heartbeat_coverage(name, expected_past, tz, now,
                                          heartbeat_ledger, day=verify_date)
            if not coverage['monitored']:
                detail = f'{len(expected_past)} slot(s) before heartbeat monitoring start'
                status = 'monitoring-grace'
            elif coverage['missing'] or coverage['failed']:
                status = 'missing'
                bits = []
                if coverage['missing']:
                    bits.append('missing=' + ','.join(coverage['missing']))
                if coverage['failed']:
                    bits.append('failed=' + ','.join(coverage['failed']))
                detail = (f"heartbeat {len(coverage['healthy'])}/{len(coverage['monitored'])}; "
                          + '; '.join(bits))
                has_missing = True
            elif coverage['pending']:
                status = 'running'
                detail = 'heartbeat pending within grace: ' + ','.join(coverage['pending'])
            else:
                status = 'ok-heartbeat'
                detail = f"heartbeat {len(coverage['healthy'])}/{len(coverage['monitored'])} slots OK"
        else:
            detail = f'{len(expected_past)} slots expected (no output contract)'
            status = 'ok-no-track'

        report.append({
            'name': name,
            'schedule': expr,
            'tz': tz,
            'expected_today': len(expected_past),
            'commits_today': commit_n,
            # `runs_today` is the run-history provider's answer and is advisory:
            # it is here to be compared with `commits_today` over time, not to
            # decide anything. `None` = the provider had nothing to say.
            'runs_today': runs_n,
            'runs_agree': (None if runs_n is None or commit_n is None
                           else runs_n == commit_n),
            'status': status,
            'detail': detail,
        })

    dash = check_dashboard_build()
    if dash['state'] == 'failed':
        has_missing = True   # critical: frozen dashboard rides exit 1
    elif dash['state'] in ('degraded', 'stale'):
        has_warn = True

    publisher = check_scheduled_publisher(now=now)
    # 'absent' is reported but never escalated, matching check_dashboard_build:
    # it means "no generation was fetched to judge", which is not the same claim
    # as "the publisher is dead". In the workflow the fetch step fails loudly on
    # its own, so absent cannot hide a real stall there.
    if publisher['state'] in ('stale', 'failed'):
        has_warn = True

    # Token regressions surface in the daily review, never as a per-cron alert
    # (feedback_no_individual_cron_alerts) and never as a reason to exit non-zero:
    # a job burning 3x its usual tokens is something to look at, not a failure.
    # A tracked --jobs-file run is CI, where there is no live run store to read.
    token_reports = [] if args.jobs_file else cron_token_audit.audit()
    token_regressions = cron_token_audit.regressions(token_reports)

    summary = {
        'generated_at': now.isoformat(),
        'now_hkt': now.astimezone(HKT).strftime('%Y-%m-%d %H:%M HKT'),
        'jobs': report,
        'dashboard_build': dash,
        'scheduled_publisher': publisher,
        'token_usage': token_reports,
        'has_missing': has_missing,
        'has_warn': has_warn,
    }

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    elif not args.silent:
        print(f"═══ cron health @ {summary['now_hkt']} ═══")
        for r in report:
            icon = {'ok':'✓','idle':'·','missing':'✗','ok-no-track':'~',
                    'ok-heartbeat':'✓','monitoring-grace':'·','running':'…',
                    'holiday':'🏖','backstop':'⚠'}.get(r['status'], '·')
            print(f"  {icon} {r['name']:25s}  {r['detail']}")
        dash_icon = DASHBOARD_STATE_ICONS[dash['state']]
        print(f"  {dash_icon} {'dashboard build':25s}  {dash['detail']}")
        pub_icon = DASHBOARD_STATE_ICONS[publisher['state']]
        print(f"  {pub_icon} {'scheduled publisher':25s}  {publisher['detail']}")
        for line in cron_token_audit.format_lines(token_regressions):
            print(f"  {line}")
        if has_missing:
            print()
            print('🔴 缺漏 — 检查上面 ✗ 行')
        elif has_warn:
            print()
            print('🟡 warn — 检查上面 ⚠ 行')

    if has_missing:
        sys.exit(1)
    if has_warn:
        sys.exit(2)
    sys.exit(0)


if __name__ == '__main__':
    main()
