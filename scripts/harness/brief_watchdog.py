#!/usr/bin/env python3
"""
brief_watchdog.py — LLM-free safety net for the 08:00 盘前深度简报 cron.

WHY (2026-05-31 incident): the brief agent finished analysis, wrote a perfectly
good memory/{date}-pre-open.md, passed postflight — then **stalled in a reasoning
loop on Step 6 delivery** ("should I use the message tool or reply directly?",
repeated verbatim ~4×, 16min run vs ~8min normal). openclaw core still marked the
run delivered=true, but the delivered content was the deliberation stub, not the
brief — kcn received nothing usable. (Same failure shape as the Mode-6 report
incident that motivated report_watchdog.py.)

So delivered=true is NOT a reliable signal. This watchdog runs OUT OF BAND (system
crontab, a few min after the brief's expected completion) and asks:

    Did the brief cron actually deliver today's brief?

Decision: the delivered brief always carries the header "盘前深度简报" (and the
WeChat TL;DR "▎TL;DR"). If today's run summary contains neither, the LLM
stalled/looped on delivery. Since the agent already WROTE the full brief to
pre-open.md, we resend THAT (the real brief, sized to WeChat's 16KB limit) via
`openclaw message send` — no LLM, banner-flagged as an auto-resend. Dedupe flag
prevents double-sends.

This is a data-delivery safety net, NOT a per-cron failure alert (see
feedback_no_individual_cron_alerts); it only ever fires to deliver content kcn was
supposed to receive. Exit 0 always (non-fatal cron); actions logged to
logs/watchdog.jsonl.

Usage:
    brief_watchdog.py
    brief_watchdog.py --dry-run
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

WS = Path(__file__).resolve().parents[2]
OC = Path('/root/.openclaw')
RUNS_DIR = OC / 'cron' / 'runs'
JOBS_JSON = OC / 'cron' / 'jobs.json'
LOG = WS / 'logs' / 'watchdog.jsonl'
HKT = timezone(timedelta(hours=8))
OPENCLAW_BIN = '/root/.local/share/pnpm/openclaw'

JOB_NAME = '盘前深度简报'
# Markers that appear in the delivered compact card (not in a deliberation loop).
DELIVERED_MARKERS = ('盘前深度简报', '▎核心结论', '▎今日动作')
BRIEF_URL_TMPL = 'https://kcnyu.github.io/clawock/memory/{date}-pre-open.html'


def log(event):
    try:
        event['ts'] = datetime.now(HKT).isoformat()
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open('a') as f:
            f.write(json.dumps(event, ensure_ascii=False) + '\n')
    except Exception as e:
        print(f'(watchdog log failed: {e})', file=sys.stderr)


def load_jobs():
    data = json.loads(JOBS_JSON.read_text())
    return data if isinstance(data, list) else data.get('jobs', data.get('items', []))


def find_job_id(job_name):
    for j in load_jobs():
        if isinstance(j, dict) and j.get('name') == job_name:
            return j.get('id')
    return None


def read_runs(job_id):
    path = RUNS_DIR / f'{job_id}.jsonl'
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def is_today_hkt(ts_ms):
    if not isinstance(ts_ms, (int, float)):
        return False
    return datetime.fromtimestamp(ts_ms / 1000, HKT).date() == datetime.now(HKT).date()


def resolve_target(runs):
    """WeChat target from this job's most recent successful delivery resolution
    (no hardcoded account that rots when the bot is re-paired)."""
    for r in reversed(runs):
        d = (r.get('delivery') or {}).get('resolved') or {}
        if d.get('ok') and d.get('to'):
            return d.get('channel'), d.get('to'), d.get('accountId')
    return None, None, None


def send_wechat(channel, to, account, message, dry_run):
    cmd = [OPENCLAW_BIN, 'message', 'send',
           '--channel', channel, '--target', to, '-m', message, '--json']
    if account:
        cmd[3:3] = ['--account', account]
    if dry_run:
        cmd.append('--dry-run')
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    return r.returncode == 0, (r.stdout + r.stderr)[-400:]


def build_compact_fallback(today):
    """Deterministic compact card (no LLM) = banner + book + ≤3 actions from
    plan.json + link to the full brief MD page. Mirrors the normal Step 6 card so
    the resend matches kcn's expected format (short + link), not a 16KB dump.
    Degrades to a link-only message if plan.json is missing/unparseable."""
    url = BRIEF_URL_TMPL.format(date=today)
    lines = ['📨 自动补发：今日盘前简报模型投递中断，已生成完整版↓', '',
             f'📊 盘前深度简报｜{today}']
    try:
        plan = json.loads((WS / 'memory' / f'{today}-plan.json').read_text())
        bk = plan.get('book') or {}
        if bk:
            lines.append(f"Book: USD${bk.get('usd_total_pnl','?')} | "
                         f"HK leg {bk.get('hk_leg_hkd','?')}HKD | US leg {bk.get('us_leg_usd','?')}USD")
        acts = [a for a in (plan.get('actions') or []) if isinstance(a, dict)][:3]
        if acts:
            lines.append('今日动作：')
            for i, a in enumerate(acts, 1):
                trig = a.get('trigger_price')
                trig = f"@{trig}" if trig is not None else (a.get('trigger_type') or '')
                conf = a.get('confidence')
                conf = f" conf{round(float(conf)*100)}%" if conf is not None else ''
                lines.append(f"{i}. {a.get('ticker','?')} {a.get('bucket','')} {trig}{conf}")
    except Exception:
        pass  # link-only fallback
    lines += ['', f'📈 完整报告：{url}']
    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    today = datetime.now(HKT).strftime('%Y-%m-%d')
    tag = 'brief'

    # The agent's full brief — if it doesn't exist, the brief never got written
    # (LLM died before Step 4), so there's nothing to resend.
    preopen = WS / 'memory' / f'{today}-pre-open.md'
    if not preopen.exists():
        log({'tag': tag, 'action': 'skip', 'reason': 'no pre-open.md (brief never written)'})
        return 0

    job_id = find_job_id(JOB_NAME)
    if not job_id:
        log({'tag': tag, 'action': 'skip', 'reason': f'job not found: {JOB_NAME}'})
        return 0

    runs = read_runs(job_id)
    today_runs = [r for r in runs if is_today_hkt(r.get('ts'))]
    if not today_runs:
        log({'tag': tag, 'action': 'skip', 'reason': 'no run today (cron did not fire)'})
        return 0
    last_summary = today_runs[-1].get('summary', '') or ''

    delivered_ok = any(m in last_summary for m in DELIVERED_MARKERS)
    if delivered_ok:
        log({'tag': tag, 'action': 'ok', 'reason': 'brief delivered normally'})
        return 0

    flag = WS / 'memory' / '.tmp' / f'watchdog-brief-{today}.done'
    if flag.exists():
        log({'tag': tag, 'action': 'skip', 'reason': 'already resent (dedupe flag present)'})
        return 0

    channel, to, account = resolve_target(runs)
    if not to:
        log({'tag': tag, 'action': 'fail', 'reason': 'no delivery target resolved from run history'})
        return 0

    message = build_compact_fallback(today)

    sent_ok, out = send_wechat(channel, to, account, message, args.dry_run)
    log({'tag': tag, 'action': 'resend', 'dry_run': args.dry_run, 'sent_ok': sent_ok,
         'job_id': job_id, 'last_summary_head': last_summary[:80], 'out': out})
    if sent_ok and not args.dry_run:
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text(datetime.now(HKT).isoformat())

    print(json.dumps({'tag': tag, 'delivered_ok': delivered_ok,
                      'resent': sent_ok, 'dry_run': args.dry_run}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
