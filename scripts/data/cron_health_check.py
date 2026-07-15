#!/usr/bin/env python3
"""
cron_health_check.py — EOD 巡检：今日 cron 应该跑了几次 vs 实际跑了几次。

本机通过 OpenClaw CLI/SQLite 读取 live schedule；GitHub Actions 通过
`config/cron-schedules.json` 读取同一份受版本控制的 schedule contract。然后按
HKT（不是 runner 本地时区）读取 git commit log，核对该产出的报告是否落盘。

输出：缺失/告警/正常 列表。可作为 GH Action 跑 EOD 一次，或者手动运行。

Exit codes:
  0 — 一切正常
  1 — 有 cron 应该跑但没跑（缺失）
  2 — 只是 warn (delay 等)

Usage:
  python3 scripts/data/cron_health_check.py            # human report
  python3 scripts/data/cron_health_check.py --json     # machine-readable
  python3 scripts/data/cron_health_check.py --silent   # 仅 exit code
  python3 scripts/data/cron_health_check.py --jobs-file config/cron-schedules.json
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

WS = Path(__file__).resolve().parents[2]
HKT = ZoneInfo('Asia/Hong_Kong')

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


def commit_count_today(commit_pattern):
    """Count matching commits whose committer date falls on today in HKT.

    GitHub runners use UTC. `git log --since=<today> 00:00` therefore dropped the
    04:00-HKT US-close commit (20:00 UTC on the prior date) and reported a false
    miss every day. Parse the ISO offset carried by each commit instead.
    """
    if not commit_pattern:
        return None  # Mode 7 / dream don't commit
    today = datetime.now(HKT).date()
    try:
        r = subprocess.run(
            ['git', '-C', str(WS), 'log', '-n', '500', '--format=%cI%x00%s'],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode != 0:
            return 0
        count = 0
        for line in r.stdout.splitlines():
            if '\x00' not in line:
                continue
            stamp, subject = line.split('\x00', 1)
            try:
                commit_day = datetime.fromisoformat(stamp).astimezone(HKT).date()
            except ValueError:
                continue
            if commit_day == today and re.search(commit_pattern, subject):
                count += 1
        return count
    except Exception:
        return 0


def load_runtime_jobs(jobs_file=None):
    """Load cron jobs from an explicit tracked contract or the live CLI layer."""
    if jobs_file:
        data = json.loads(Path(jobs_file).read_text())
        return data.get('jobs', [])

    sys.path.insert(0, str(WS / 'scripts' / 'harness'))
    from _watchdog_common import load_jobs
    jobs = load_jobs()
    if not jobs:
        raise RuntimeError('OpenClaw CLI returned no cron jobs; run `openclaw doctor --fix`')
    return jobs


def check_dashboard_build():
    """Read logs/dashboard_build_status.json (written by _harness_common.rebuild_dashboard).

    Returns a dict with keys: state ('ok'|'degraded'|'stale'|'failed'|'absent'),
    detail, ok, warn_count, age_hours. A 'failed' build means dashboard.json is
    frozen while commits keep flowing — the silent-freeze case this guards against.
    """
    path = WS / 'logs' / 'dashboard_build_status.json'
    if not path.exists():
        return {'state': 'absent', 'detail': 'no build status file yet', 'ok': None,
                'warn_count': 0, 'age_hours': None}
    try:
        st = json.loads(path.read_text())
    except Exception as e:
        return {'state': 'failed', 'detail': f'status file unreadable: {e}', 'ok': False,
                'warn_count': 0, 'age_hours': None}
    age_hours = None
    try:
        ts = datetime.strptime(st['checked_at'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
        age_hours = round((datetime.now(timezone.utc) - ts).total_seconds() / 3600, 1)
    except Exception:
        pass
    if not st.get('ok'):
        return {'state': 'failed', 'detail': f"build FAILED — dashboard.json frozen. tail: {st.get('tail','')[-160:]}",
                'ok': False, 'warn_count': st.get('warn_count', 0), 'age_hours': age_hours}
    if st.get('warn_count'):
        return {'state': 'degraded', 'detail': f"{st['warn_count']} degraded section(s) on last build",
                'ok': True, 'warn_count': st['warn_count'], 'age_hours': age_hours}
    # Build OK; flag only if very stale (weekend gaps are normal, so 24h threshold)
    if age_hours is not None and age_hours > 24:
        return {'state': 'stale', 'detail': f'last successful build {age_hours}h ago',
                'ok': True, 'warn_count': 0, 'age_hours': age_hours}
    return {'state': 'ok', 'detail': f'last build ok ({age_hours}h ago)' if age_hours is not None else 'last build ok',
            'ok': True, 'warn_count': 0, 'age_hours': age_hours}


def _market_closed_today(market):
    """True if `market` ('hk'/'us') is on holiday/weekend today (its own TZ). Used to
    suppress false 'missing commit' reds: a market-report cron on that market's holiday
    is correctly skipped by preflight's holiday gate (memory: openclaw-market-holiday-gate),
    so it produces no commit by design. Fail-open (False) if the calendar is unavailable."""
    try:
        import trading_calendar as _tc
        return not _tc.is_trading_day(market)
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--silent', action='store_true')
    ap.add_argument('--jobs-file', help='tracked cron contract (used by CI)')
    args = ap.parse_args()

    try:
        jobs = load_runtime_jobs(args.jobs_file)
    except Exception as e:
        if not args.silent:
            print(f'FATAL: cron schedules unavailable: {e}', file=sys.stderr)
        sys.exit(1)

    now = datetime.now(timezone.utc)

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
        expected = parse_cron_slots(expr, tz, now)
        # Only check slots already past
        try:
            from zoneinfo import ZoneInfo
            now_local = now.astimezone(ZoneInfo(tz)).strftime('%H:%M')
        except Exception:
            now_local = now.strftime('%H:%M')
        expected_past = [s for s in expected if s <= now_local]
        commit_pat = COMMIT_PATTERNS.get(name)
        commit_n = commit_count_today(commit_pat)

        # Holiday gate: don't expect a commit from a 港股*/美股* report on that market's
        # holiday — preflight skips the run by design (the 6-19 端午+Juneteenth double
        # close was a false red). 港股→hk, 美股→us; other jobs (brief/dream) unaffected.
        mkt = 'hk' if name.startswith('港股') else ('us' if name.startswith('美股') else None)
        both_closed = name == '盘前深度简报' and all(
            _market_closed_today(m) for m in ('hk', 'us')
        )
        if expected_past and ((mkt and _market_closed_today(mkt)) or both_closed):
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
                # 缺少 commit — 可能漏跑
                status = 'missing'
                detail = f'expected {len(expected_past)} commits, got {commit_n}'
                has_missing = True
            else:
                detail = f'{commit_n}/{len(expected_past)} commits OK'
        else:
            # Intraday/dream jobs do not have a one-commit-per-slot contract.
            detail = f'{len(expected_past)} slots expected (no commit-count contract)'
            status = 'ok-no-track'

        report.append({
            'name': name,
            'schedule': expr,
            'tz': tz,
            'expected_today': len(expected_past),
            'commits_today': commit_n,
            'status': status,
            'detail': detail,
        })

    dash = check_dashboard_build()
    if dash['state'] == 'failed':
        has_missing = True   # critical: frozen dashboard rides exit 1
    elif dash['state'] in ('degraded', 'stale'):
        has_warn = True

    summary = {
        'generated_at': now.isoformat(),
        'now_hkt': now.astimezone(HKT).strftime('%Y-%m-%d %H:%M HKT'),
        'jobs': report,
        'dashboard_build': dash,
        'has_missing': has_missing,
        'has_warn': has_warn,
    }

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    elif not args.silent:
        print(f"═══ cron health @ {summary['now_hkt']} ═══")
        for r in report:
            icon = {'ok':'✓','idle':'·','missing':'✗','ok-no-track':'~','holiday':'🏖'}.get(r['status'], '·')
            print(f"  {icon} {r['name']:25s}  {r['detail']}")
        dash_icon = {'ok':'✓','degraded':'⚠','stale':'⚠','failed':'✗','absent':'·'}[dash['state']]
        print(f"  {dash_icon} {'dashboard build':25s}  {dash['detail']}")
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
