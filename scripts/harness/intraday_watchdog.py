#!/usr/bin/env python3
"""
intraday_watchdog.py — cold-session-drop safety net for Mode 7 (盘中盯盘) crons.

WHY (2026-06-02 incident): the 11:00 + 11:30 盘中盯盘 reports "没出来" on kcn's
WeChat, yet every run finished status=ok with delivered=true and a perfectly
good report. Root cause is the known Tencent cold-session silent drop
(openclaw-wechat-cold-session-drop.md, upstream wontfix #81096/#81316): once the
WeChat session has been idle ~30-60min, Tencent silently stops delivering but
the API still returns delivered=true. So `delivered` is POISONED — the existing
report_watchdog (which trusts delivery telemetry) can't catch this, and 盘中盯盘
had no watchdog at all.

This runs OUT OF BAND (system crontab, a few min after each intraday slot) and,
crucially, does NOT trust `delivered`. Instead it judges drop probability from
session WARMTH — how long since kcn last messaged the bot (the only honest
receipt signal we have). If the WeChat session was cold at send-time
(idle ≥ --cold-min), the push very likely dropped, so we MIRROR the report to
Telegram — the one channel with no cold-session drop. WeChat stays primary;
Telegram only lights up on a suspected miss (no 刷屏).

Healthy-report gate: we only mirror a report that actually got produced and
delivered cleanly (block first-line present AND not a mimo repeat-loop) — never
mirror a stall/garbage turn.

(Shared run-record / warmth / send helpers live in _watchdog_common.py.)

Usage:
    intraday_watchdog.py --job-name "盘中盯盘"   --market hk
    intraday_watchdog.py --job-name "美股盘中盯盘" --market us --cold-min 40
    intraday_watchdog.py --job-name "盘中盯盘"   --market hk --dry-run

Exit 0 always (non-fatal cron); actions logged to logs/watchdog.jsonl.
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _watchdog_common import (  # noqa: E402
    WS, HKT, log, find_job_id, read_runs, today_runs,
    transcript_loop_score, last_human_inbound_ms, last_report_text, send_telegram,
)

LOOP_THRESHOLD = 5       # transcript loop_score ≥ this ⇒ mimo repeat-loop ⇒ garbage
DEFAULT_COLD_MIN = 40    # WeChat session idle ≥ this at send-time ⇒ likely dropped
KCN_TELEGRAM_TARGET = 2033937852  # Shengyu Li's Telegram DM (chat_id == user id)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--job-name', required=True, help='intraday cron job name')
    ap.add_argument('--market', choices=['hk', 'us'], required=True)
    ap.add_argument('--cold-min', type=int, default=DEFAULT_COLD_MIN,
                    help='WeChat idle minutes at send-time to treat as cold/dropped')
    ap.add_argument('--telegram-target', default=str(KCN_TELEGRAM_TARGET))
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    today = datetime.now(HKT).strftime('%Y-%m-%d')
    tag = f'intraday-{args.market}'

    job_id = find_job_id(args.job_name)
    if not job_id:
        log({'tag': tag, 'action': 'skip', 'reason': f'job not found: {args.job_name}'})
        return 0

    runs_today = today_runs(job_id)
    if not runs_today:
        log({'tag': tag, 'action': 'skip', 'reason': 'no run today yet'})
        return 0
    last = runs_today[-1]
    run_at = last.get('runAtMs')
    session_id = last.get('sessionId')

    # Dedupe per slot (one mirror per intraday run, keyed by runAtMs).
    flag = WS / 'memory' / '.tmp' / f'watchdog-{tag}-{run_at}.done'
    if flag.exists():
        log({'tag': tag, 'action': 'skip', 'reason': 'already handled this slot (dedupe flag)'})
        return 0

    # --- Healthy-report gate: never mirror a stall/garbage turn ---------------
    summary = last.get('summary', '')
    raw_block_first = None
    ctx_path = WS / 'memory' / '.tmp' / f'intraday-context-{args.market}-latest.json'
    if ctx_path.exists():
        try:
            raw = (json.loads(ctx_path.read_text()).get('raw_wechat_block') or '').strip()
            raw_block_first = raw.splitlines()[0] if raw else None
        except Exception:
            pass
    sent_via_tool = bool((last.get('delivery') or {}).get('messageToolSentTo'))
    block_present = bool(raw_block_first and raw_block_first in summary)
    delivered_clean = sent_via_tool or block_present
    loop_score, _ = transcript_loop_score(session_id)
    looped = loop_score >= LOOP_THRESHOLD
    if not delivered_clean or looped:
        # Report itself failed/looped — that's report_watchdog's territory, not a
        # cold-drop. Don't mirror garbage; just record it.
        log({'tag': tag, 'action': 'skip', 'reason': 'run unhealthy (stall/loop) — not a cold-drop',
             'delivered_clean': delivered_clean, 'loop_score': loop_score,
             'run_at': run_at})
        return 0

    # --- Warmth judgment (the part that does NOT trust `delivered`) -----------
    inbound_ms = last_human_inbound_ms(before_ms=run_at)
    if inbound_ms is None:
        idle_min = 99999  # no human inbound in 24h ⇒ definitely cold
    else:
        idle_min = int((run_at - inbound_ms) / 60000)
    cold = idle_min >= args.cold_min

    if not cold:
        log({'tag': tag, 'action': 'ok',
             'reason': f'session warm (idle={idle_min}m < {args.cold_min}m) — WeChat likely landed',
             'run_at': run_at, 'loop_score': loop_score})
        return 0

    # --- Cold ⇒ WeChat push probably dropped ⇒ mirror to Telegram ------------
    report = last_report_text(session_id, raw_block_first) if raw_block_first else None
    if not report:
        report = summary  # fallback: run-record summary (usually holds the full block)
    banner = (f'📲 微信备投（盘中盯盘 {datetime.now(HKT):%H:%M} HKT 发出时微信会话已冷 '
              f'{idle_min}min，大概率被腾讯静默吞了，故 Telegram 补一份）\n\n')
    message = banner + report.strip()

    sent_ok, out = send_telegram(args.telegram_target, message, args.dry_run)
    log({'tag': tag, 'action': 'mirror-telegram', 'dry_run': args.dry_run, 'sent_ok': sent_ok,
         'job_id': job_id, 'idle_min': idle_min, 'cold_min': args.cold_min,
         'loop_score': loop_score, 'run_at': run_at, 'out': out})
    if sent_ok and not args.dry_run:
        flag.write_text(datetime.now(HKT).isoformat())

    print(json.dumps({'tag': tag, 'idle_min': idle_min, 'cold': cold,
                      'mirrored': sent_ok, 'dry_run': args.dry_run}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
