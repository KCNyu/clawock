#!/usr/bin/env python3
"""
cron_health_check.py — EOD 巡检：今日 cron 应该跑了几次 vs 实际跑了几次。

读 `/root/.openclaw/cron/jobs.json` 的每个 cron schedule，跟今天日期对照算出"应该跑次数"。
然后读 git commit log 数实际今日的产出（每个 Mode 6 cron 都会产出 portfolio commit）。

输出：缺失/告警/正常 列表。可作为 GH Action 跑 EOD 一次，或者手动运行。

Exit codes:
  0 — 一切正常
  1 — 有 cron 应该跑但没跑（缺失）
  2 — 只是 warn (delay 等)

Usage:
  python3 scripts/data/cron_health_check.py            # human report
  python3 scripts/data/cron_health_check.py --json     # machine-readable
  python3 scripts/data/cron_health_check.py --silent   # 仅 exit code
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

WS = '/root/.openclaw/workspace'
JOBS_PATH = '/root/.openclaw/cron/jobs.json'

# Cron name → identifying commit msg patterns
COMMIT_PATTERNS = {
    '港股开盘报告': r'港股开盘',
    '港股午盘报告': r'港股午盘',
    '港股午后快报': r'港股午后',
    '港股收盘报告': r'港股收盘',
    '美股开盘报告': r'美股开盘',
    '美股收盘报告': r'美股收盘',
    '盘前深度简报': r'daily deep brief',
    '盘中盯盘': None,        # Mode 7 不 commit
    '美股盘中盯盘': None,    # Mode 7 不 commit
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


def fired_slots_today_from_log(tz_name='Asia/Hong_Kong'):
    """Read openclaw log file for today, count 'embedded run agent end' events."""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc
    today_local = datetime.now(tz).strftime('%Y-%m-%d')
    log_path = f'/tmp/openclaw/openclaw-{today_local}.log'
    if not os.path.exists(log_path):
        return []
    times = []
    with open(log_path) as f:
        for line in f:
            try:
                d = json.loads(line)
                if 'embedded run agent end' in d.get('message',''):
                    ts = d.get('time','')[:19]
                    if ts:
                        times.append(ts)
            except Exception:
                continue
    return times


def commit_count_today(commit_pattern):
    """Count today's commits matching pattern. Use LC_ALL=C.UTF-8 for grep CJK."""
    if not commit_pattern:
        return None  # Mode 7 / dream don't commit
    today = datetime.now().strftime('%Y-%m-%d')
    env = os.environ.copy()
    env['LC_ALL'] = 'C.UTF-8'
    env['LANG'] = 'C.UTF-8'
    try:
        r = subprocess.run(['git', '-C', WS, 'log', f'--since={today} 00:00',
                            f'--grep={commit_pattern}', '--oneline'],
                           capture_output=True, text=True, timeout=15, env=env)
        if r.returncode != 0:
            return 0
        return len([l for l in r.stdout.splitlines() if l.strip()])
    except Exception:
        return 0


def check_dashboard_build():
    """Read logs/dashboard_build_status.json (written by _harness_common.rebuild_dashboard).

    Returns a dict with keys: state ('ok'|'degraded'|'stale'|'failed'|'absent'),
    detail, ok, warn_count, age_hours. A 'failed' build means dashboard.json is
    frozen while commits keep flowing — the silent-freeze case this guards against.
    """
    path = os.path.join(WS, 'logs', 'dashboard_build_status.json')
    if not os.path.exists(path):
        return {'state': 'absent', 'detail': 'no build status file yet', 'ok': None,
                'warn_count': 0, 'age_hours': None}
    try:
        st = json.load(open(path))
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
    args = ap.parse_args()

    if not os.path.exists(JOBS_PATH):
        if not args.silent:
            print('FATAL: openclaw cron jobs.json not found', file=sys.stderr)
        sys.exit(1)

    now = datetime.now(timezone.utc)
    jobs = json.load(open(JOBS_PATH))['jobs']
    log_fires = fired_slots_today_from_log()
    log_fires_hhmm = [t[11:16] for t in log_fires]  # extract HH:MM

    report = []
    has_missing = False
    has_warn = False

    for job in jobs:
        name = job.get('name', job.get('id','?'))
        sched = job.get('schedule', {})
        expr = sched.get('expr','')
        tz = sched.get('tz', 'UTC')
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
        if mkt and expected_past and _market_closed_today(mkt):
            report.append({
                'name': name, 'schedule': expr, 'tz': tz,
                'expected_today': 0, 'commits_today': commit_n,
                'status': 'holiday', 'detail': f'{mkt.upper()} 休市 · 跳过(无需 commit)',
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
            # Mode 7 / dream — 不 commit，只能看 log
            detail = f'{len(expected_past)} slots expected (Mode 7: no commit tracking)'
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
        'now_hkt': now.astimezone().strftime('%Y-%m-%d %H:%M HKT'),
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
