#!/usr/bin/env python3
"""
cron_timeline.py — single forward-looking view of EVERY scheduled job, across all
three schedulers, normalized to HKT.

Unlike cron_runs.py (which tails *run history*), this answers "what fires when, on
which day" — by merging:
  1. openclaw  CLI / SQLite runtime state         (tz = Asia/Shanghai ≈ HKT, or none → HKT)
  2. GitHub Actions  .github/workflows/*.yml      (cron is ALWAYS UTC → +8h to HKT)
  3. system crontab  `crontab -l`                 (host local = HKT)

The UTC→HKT shift is applied to BOTH the time AND the day-of-week, so a GH Action
written `* * 1-5` (Mon–Fri UTC) correctly shows as its real HKT firing days — this
is the view that catches "I thought macro ran before Monday's brief" timezone traps.

Usage:
  python3 cron_timeline.py            # full merged timeline, sorted by HKT fire time
  python3 cron_timeline.py --source gha|openclaw|crontab
  python3 cron_timeline.py --json
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

_CHECKOUT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_CHECKOUT))
sys.path.insert(0, str(_CHECKOUT / "src"))
from clawock.workspace import workspace_root  # noqa: E402
from clawock.providers import openclaw  # noqa: E402

WS = workspace_root(_CHECKOUT)
WORKFLOWS = WS / '.github' / 'workflows'

DOW_SHORT = ['日', '一', '二', '三', '四', '五', '六']  # 0=Sun .. 6=Sat


# ── cron-field parsing (5-field: min hour dom mon dow) ──────────────────────

def _expand(field, lo, hi):
    """Expand a cron field into a sorted set of ints, or None for '*'."""
    if field == '*':
        return None
    vals = set()
    for part in field.split(','):
        step = 1
        if '/' in part:
            part, s = part.split('/')
            step = int(s)
        if part == '*':
            a, b = lo, hi
        elif '-' in part:
            a, b = (int(x) for x in part.split('-'))
        else:
            a = b = int(part)
        vals.update(range(a, b + 1, step))
    return sorted(vals)


def parse_cron(expr):
    """→ (minutes:set|None, hours:set|None, dow:set|None) ; None means 'every'."""
    f = expr.split()
    if len(f) != 5:
        return None
    mins = _expand(f[0], 0, 59)
    hours = _expand(f[1], 0, 23)
    dow = _expand(f[4], 0, 7)
    if dow is not None:
        dow = sorted({0 if d == 7 else d for d in dow})  # cron 7 == Sunday == 0
    return mins, hours, dow


def shift_to_hkt(mins, hours, dow, utc_offset):
    """Shift hours by utc_offset, carrying day-of-week when an hour wraps past 24.

    Returns a LIST of (mins, hours, dow) groups. A cron whose hours have MIXED wrap
    behaviour (e.g. `0 9,23 * * 1-5`: 09:00 stays same HKT day, 23:00 wraps to next)
    can't be one row — the two hour-groups fire on different HKT weekdays — so it's
    split into one group per wrap class. Uniform crons (the common case) return one
    group, identical to the old behaviour."""
    if utc_offset == 0 or hours is None:
        return [(mins, hours, dow)]
    same, wrapped = [], []
    for h in hours:
        nh = h + utc_offset
        (wrapped if nh >= 24 else same).append(nh % 24)
    groups = []
    if same:
        groups.append((mins, sorted(same), dow))
    if wrapped:
        wdow = sorted({(d + 1) % 7 for d in dow}) if dow is not None else dow
        groups.append((mins, sorted(wrapped), wdow))
    return groups


# ── label rendering ─────────────────────────────────────────────────────────

def days_label(dow):
    if dow is None:
        return '每日'
    s = set(dow)
    presets = {
        frozenset({1, 2, 3, 4, 5}): '工作日 一–五',
        frozenset({2, 3, 4, 5, 6}): '二–六',
        frozenset({0, 1, 2, 3, 4, 5, 6}): '每日',
    }
    if frozenset(s) in presets:
        return presets[frozenset(s)]
    return '周' + '·'.join(DOW_SHORT[d] for d in dow)


def time_label(mins, hours):
    if hours is None:
        if not mins:
            return '— 事件触发'
        if len(mins) > 1:
            step = mins[1] - mins[0]
            if all(b - a == step for a, b in zip(mins, mins[1:])):
                return f'每{step}分钟'
        return '每小时 ' + ','.join(f':{m:02d}' for m in mins)
    # contiguous-range + step-minute → compact "HH:MM–HH:MM /Nm"
    is_step = mins is not None and len(mins) > 1
    if is_step and len(hours) > 1:
        segs, run = [], [hours[0]]
        for h in hours[1:]:
            if h == run[-1] + 1:
                run.append(h)
            else:
                segs.append(run); run = [h]
        segs.append(run)
        first_m, last_m = mins[0], mins[-1]
        parts = [f'{seg[0]:02d}:{first_m:02d}–{seg[-1]:02d}:{last_m:02d}' for seg in segs]
        step = mins[1] - mins[0]
        return ', '.join(parts) + f' /{step}m'
    out = [f'{h:02d}:{m:02d}' for h in hours for m in (mins if mins else [0])]
    return ', '.join(out)


def sort_key(mins, hours):
    if hours is None and mins is None:
        return 99999  # event-triggered (push/PR/dispatch) → sort last
    h0 = hours[0] if hours else 0
    m0 = mins[0] if mins else 0
    return h0 * 60 + m0


# ── source loaders ──────────────────────────────────────────────────────────

LAST_OPENCLAW_SOURCE = None


def load_openclaw(backend='auto'):
    global LAST_OPENCLAW_SOURCE
    rows = []
    try:
        # 6.1 moved cron storage into SQLite — read via the storage-agnostic CLI
        # layer (the dead jobs.json silently returned [] and dropped all 11
        # openclaw jobs from the timeline, found 2026-06-10).
        result = openclaw.read_jobs(backend)
        jobs = result.entries
        LAST_OPENCLAW_SOURCE = result.source
    except Exception:
        LAST_OPENCLAW_SOURCE = 'empty'
        return rows
    for j in jobs:
        sch = j.get('schedule') or {}
        expr = sch.get('expr')
        if not expr:
            continue
        # Asia/Shanghai and a missing tz both resolve to HKT (UTC+8) → no shift.
        parsed = parse_cron(expr)
        if not parsed:
            continue
        mins, hours, dow = parsed
        if not j.get('enabled', True):
            continue
        rows.append(('openclaw', j.get('name', j['id'][:8]), expr,
                     sch.get('tz') or 'HKT', mins, hours, dow))
    return rows


def load_gha():
    rows = []
    if not WORKFLOWS.is_dir():
        return rows
    for f in sorted(WORKFLOWS.glob('*.yml')):
        text = f.read_text(errors='replace')
        m = re.search(r'^name:\s*(.+)$', text, re.M)
        name = m.group(1).strip() if m else f.stem
        crons = re.findall(r'-\s*cron:\s*[\'"]([^\'"]+)[\'"]', text)
        if not crons:
            if 'workflow_dispatch' in text or 'push:' in text or 'pull_request' in text:
                rows.append(('gha', name, '(on push/PR/dispatch)', 'UTC', None, None, None))
            continue
        for expr in crons:
            parsed = parse_cron(expr)
            if not parsed:
                continue
            for mins, hours, dow in shift_to_hkt(*parsed, utc_offset=8):
                rows.append(('gha', name, expr + ' UTC', 'UTC→HKT', mins, hours, dow))
    return rows


def load_crontab():
    rows = []
    try:
        out = subprocess.run(['crontab', '-l'], capture_output=True, text=True).stdout
    except Exception:
        return rows
    for line in out.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if 'stargate' in line:
            continue
        f = line.split(None, 5)
        if len(f) < 6:
            continue
        expr = ' '.join(f[:5])
        cmd = f[5]
        parsed = parse_cron(expr)
        if not parsed:
            continue
        # label = the script + its distinguishing args
        if 'report_watchdog' in cmd:
            ph = re.search(r'--phase (\w+)', cmd)
            mk = re.search(r'--market (\w+)', cmd)
            name = f"watchdog {mk.group(1) if mk else '?'} {ph.group(1) if ph else '?'}"
        elif 'intraday_watchdog' in cmd:
            mk = re.search(r'--market (\w+)', cmd)
            name = f"watchdog {mk.group(1) if mk else '?'} intraday"
        elif 'brief_watchdog' in cmd:
            name = 'watchdog brief'
        elif 'commit_dreaming' in cmd:
            name = 'commit_dreaming'
        elif 'gc_sessions' in cmd:
            name = 'gc_sessions'
        elif 'publish_dashboard' in cmd:
            name = 'publish_dashboard'
        elif 'sync_us_cron_dst' in cmd:
            name = 'sync_us_dst'
        elif 'gold_dca_refresh' in cmd:
            name = 'gold_dca_refresh'
        elif re.search(r'(^|/)git\b', cmd) and re.search(r'\bgc\b', cmd):
            name = 'git gc'
        else:
            name = (cmd.split('/')[-1])[:24]
        rows.append(('crontab', name, expr, 'HKT', *parsed))
    return rows


# ── main ────────────────────────────────────────────────────────────────────

TAG = {'openclaw': '🦞 openclaw', 'gha': '🐙 GH Action', 'crontab': '🛡 crontab'}


def main():
    p = argparse.ArgumentParser(description='Merged HKT schedule timeline (openclaw + GHA + crontab)')
    p.add_argument('--source', choices=['openclaw', 'gha', 'crontab', 'all'], default='all')
    p.add_argument(
        '--openclaw-backend',
        choices=['auto', 'cli', 'sqlite', 'fossil'],
        default='auto',
        help='OpenClaw state backend (sqlite is a read-only gateway-independent view)',
    )
    p.add_argument('--json', action='store_true')
    args = p.parse_args()

    rows = []
    if args.source in ('all', 'openclaw'):
        rows += load_openclaw(args.openclaw_backend)
    if args.source in ('all', 'gha'):
        rows += load_gha()
    if args.source in ('all', 'crontab'):
        rows += load_crontab()

    rows.sort(key=lambda r: (sort_key(r[4], r[5]), r[0]))

    if args.json:
        print(json.dumps([{
            'source': r[0], 'name': r[1], 'expr': r[2], 'tz': r[3],
            'hkt_time': time_label(r[4], r[5]), 'hkt_days': days_label(r[6]),
        } for r in rows], ensure_ascii=False, indent=2))
        if LAST_OPENCLAW_SOURCE in {'fossil', 'empty'}:
            detail = ('stale pre-6.1 fossil' if LAST_OPENCLAW_SOURCE == 'fossil'
                      else 'no live CLI/SQLite state')
            print(f'error: OpenClaw schedule unavailable ({detail})', file=sys.stderr)
            return 2
        return 0

    print('📆 合并调度时间线（全部归一到 HKT，按当日触发时刻排序）')
    print(f'   来源: openclaw cron(CLI/SQLite) · GH Actions(UTC→HKT) · 系统 crontab(HKT)\n')
    print(f'{"HKT 触发":<22}  {"来源":<12}  {"任务":<22}  {"星期":<12}  原始 cron')
    print('─' * 108)

    def vpad(s, width):
        vw = sum(2 if ord(c) > 127 else 1 for c in s)
        return s + ' ' * max(0, width - vw)

    for src, name, expr, tz, mins, hours, dow in rows:
        print(f'{vpad(time_label(mins, hours), 22)}  {vpad(TAG[src], 12)}  '
              f'{vpad(name, 22)}  {vpad(days_label(dow), 12)}  {expr}')
    print(f'\n共 {len(rows)} 个调度项。GH Action cron 是 UTC，已 +8h 折算并修正跨日星期。')
    if LAST_OPENCLAW_SOURCE in {'fossil', 'empty'}:
        detail = ('rows came from a stale pre-6.1 fossil'
                  if LAST_OPENCLAW_SOURCE == 'fossil'
                  else 'live CLI and SQLite state were both unavailable')
        print(f'❌ OpenClaw schedule unavailable: {detail}; '
              'contract/model/delivery inspection is invalid.', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
