#!/usr/bin/env python3
"""
cron_runs.py — aggregate openclaw cron run history across ALL jobs.

`openclaw cron runs` requires --id, and there is no built-in cross-job view.
This script tails the per-job JSONL files under ~/.openclaw/cron/runs/ and
prints a single time-sorted feed of recent runs (auto-scheduled + manual).

Usage:
  python3 cron_runs.py [N]                # last N entries (default 20)
  python3 cron_runs.py --job 港股开盘      # filter by job name substring
  python3 cron_runs.py --status error      # filter by status
  python3 cron_runs.py --kind cron         # cron | manual | both (default both)
  python3 cron_runs.py --full              # full summary (no truncation)
"""

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Storage-agnostic cron readers (6.1 moved jobs.json/runs/*.jsonl into SQLite —
# direct file reads silently return nothing).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from clawock.providers import openclaw  # noqa: E402

CRON_DIR = Path.home() / '.openclaw' / 'cron'
RUNS_DIR = CRON_DIR / 'runs'
HKT = timezone(timedelta(hours=8))


def load_job_map(backend='auto'):
    try:
        result = openclaw.read_jobs(backend)
        return {
            j['id']: j.get('name', j['id'][:8])
            for j in result.entries
        }, result.source
    except Exception:
        return {}, 'empty'


def kind_of(entry):
    rid = entry.get('runId', '') or ''
    return 'manual' if rid.startswith('manual:') else 'cron'


def load_entries(kind_filter, job_id_filter, status_filter, job_map, backend='auto'):
    out = []
    sources = set()
    for job_id in sorted(job_map):
        if job_id_filter and job_id not in job_id_filter:
            continue
        result = openclaw.read_runs(job_id, backend)
        sources.add(result.source)
        for d in result.entries:
            if status_filter and d.get('status') != status_filter:
                continue
            k = kind_of(d)
            if kind_filter != 'both' and k != kind_filter:
                continue
            d['_kind'] = k
            d['_jobId'] = job_id
            out.append(d)
    out.sort(key=lambda x: x.get('ts', 0) or 0, reverse=True)
    return out, sources


def fmt_ts(ms):
    if not ms:
        return '         —'
    return datetime.fromtimestamp(ms / 1000, HKT).strftime('%m-%d %H:%M')


def fmt_dur(ms):
    if not ms:
        return '   —'
    s = ms / 1000
    if s < 60:
        return f'{s:5.1f}s'
    return f'{s/60:4.1f}m'


def status_glyph(status):
    return {'ok': '✅', 'error': '🔴', 'warn': '⚠️'}.get(status, '❓')


def summarize(entry, full=False):
    if entry.get('status') == 'error':
        return ('ERR: ' + (entry.get('error') or 'unknown'))[: None if full else 80]
    s = entry.get('summary') or ''
    s = s.replace('\n', ' ⏎ ')
    return s if full else s[:80]


def main():
    p = argparse.ArgumentParser(description='Aggregate openclaw cron run history')
    p.add_argument('n', nargs='?', type=int, default=20, help='show last N runs (default 20)')
    p.add_argument('--job', help='filter by job name substring (case-insensitive)')
    p.add_argument('--status', choices=['ok', 'error', 'warn'])
    p.add_argument('--kind', choices=['cron', 'manual', 'both'], default='both')
    p.add_argument('--full', action='store_true', help='no summary truncation')
    p.add_argument('--json', action='store_true', help='emit JSON instead of table')
    p.add_argument(
        '--openclaw-backend',
        choices=['auto', 'cli', 'sqlite', 'fossil'],
        default='auto',
        help='state backend (sqlite is read-only and does not require the gateway)',
    )
    args = p.parse_args()

    jobs, jobs_source = load_job_map(args.openclaw_backend)
    if not jobs:
        print('❌ no live cron jobs visible (OpenClaw CLI/SQLite unavailable)',
              file=sys.stderr)
        return 2
    if jobs_source == 'fossil':
        print('❌ refusing stale pre-6.1 job metadata; use live CLI or SQLite',
              file=sys.stderr)
        return 2
    job_id_filter = None
    if args.job:
        needle = args.job.lower()
        job_id_filter = {jid for jid, name in jobs.items() if needle in name.lower()}
        if not job_id_filter:
            print(f'❌ no job matches "{args.job}". Known: ' +
                  ', '.join(sorted(jobs.values())), file=sys.stderr)
            return 2

    entries, run_sources = load_entries(
        args.kind, job_id_filter, args.status, jobs, args.openclaw_backend
    )
    entries = entries[: args.n]
    if 'fossil' in run_sources:
        print('❌ refusing stale pre-6.1 run history; use live CLI or SQLite',
              file=sys.stderr)
        return 2

    if args.json:
        slim = [{
            'ts':      e.get('ts'),
            'time_hkt': fmt_ts(e.get('ts')),
            'job':     jobs.get(e['_jobId'], e['_jobId'][:8]),
            'kind':    e['_kind'],
            'status':  e.get('status'),
            'duration_ms': e.get('durationMs'),
            'model':   e.get('model'),
            'delivered': e.get('delivered'),
            'summary': summarize(e, full=True),
        } for e in entries]
        print(json.dumps(slim, ensure_ascii=False, indent=2))
        return 0

    if not entries:
        print('(no matching runs)')
        return 0

    print(f'最近 {len(entries)} 次 cron 运行（HKT，按时间倒序，kind={args.kind}）')
    print(f'{"时间":<11}  {"Job":<14}  S  K   {"用时":>5}  Deliv  摘要')
    print('-' * 110)
    for e in entries:
        name = jobs.get(e['_jobId'], e['_jobId'][:8])
        # truncate name to visual width 14 (CJK = 2)
        vw = 0
        out = []
        for ch in name:
            w = 2 if ord(ch) > 127 else 1
            if vw + w > 14:
                break
            out.append(ch); vw += w
        name_pad = ''.join(out) + ' ' * (14 - vw)
        deliv = '—'
        if e.get('delivered') is True:
            deliv = '✓   '
        elif e.get('delivered') is False:
            deliv = '✗   '
        elif e.get('deliveryStatus'):
            deliv = (e['deliveryStatus'][:4]).ljust(4)
        print(f"{fmt_ts(e.get('ts')):<11}  {name_pad}  {status_glyph(e.get('status'))}  "
              f"{e['_kind'][:4]:<4}  {fmt_dur(e.get('durationMs')):>5}  {deliv:<5}  "
              f"{summarize(e, args.full)}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
