#!/usr/bin/env python3
"""
report_watchdog.py — LLM-free safety net for staged (Mode 6) report crons.

ROOT CAUSE this guards (2026-06-08, re-diagnosed): staged reports "没出来" on kcn's
WeChat even though the run finished status=ok with delivered=true. Same mechanism
as the intraday drop (#61174, wontfix): a staged cron used to deliver via `announce`
fired at the END of a long agent turn (preflight+LLM+postflight+dashboard ≈ 130-300s)
using a contextToken captured at turn START → Tencent expires it server-side after
~160s → silent drop, run-record `delivered` stays true. The 6-08 美股开盘报告 (133s
turn) landed delivered=true but never reached WeChat.

THE FIX (2026-06-08, mirrors the intraday decouple): report_postflight is now the
PRIMARY sender — it delivers each report via a fresh-token `openclaw message send`
(the path kcn confirmed lands) and the staged crons run --no-deliver (no announce)
→ exactly one send, no long-turn drop, no double. postflight records the REAL send
result to memory/.tmp/report-sent-{market}-{phase}-{date}.json.

This watchdog is now a pure BACKSTOP (system crontab, ~15min after the cron): it
reads that marker and re-sends ONLY when the postflight send is confirmed failed /
never happened (marker missing, sent_ok false, or stale/mismatched) — so it never
doubles a report that already went out. The old approach (string-match the block's
first line against the run summary) is replaced: it can't tell a landed send from a
silently-dropped one (the summary is byte-identical), which is exactly why the 6-08
drop slipped through.

TELEGRAM MIRROR (2026-07-03, bot @clawock_bot revived): on the same cold-detection
branch (confirmed WeChat send did not land — marker missing/failed/stale, NOT idle
time) we also mirror the report to Telegram (KCN_TELEGRAM), a channel with no
contextToken-expiry drop, so kcn still gets it even if the fresh-token WeChat resend
drops too. Only fires on a cold event — cleanly-delivered reports never hit Telegram.

Healthy-report gate: only re-send a report produced cleanly (block first-line
present AND not a mimo repeat-loop) — never re-send a stall. Dedupe per slot.

(Shared run-record / target / send helpers live in _watchdog_common.py.)

Usage:
    report_watchdog.py --market hk --phase close --job-name "港股收盘报告"
    report_watchdog.py --market us --phase open  --job-name "美股开盘报告" --dry-run

Exit 0 always (non-fatal cron); actions logged to logs/watchdog.jsonl.
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _watchdog_common import (  # noqa: E402
    WS, HKT, log, find_job_id, today_runs, resolve_wechat_target, send_wechat,
    transcript_loop_score, last_report_text, send_telegram, KCN_TELEGRAM,
)

LOOP_THRESHOLD = 5                 # transcript loop_score ≥ this ⇒ mimo repeat-loop ⇒ garbage
MARKER_FRESH_MS = 120 * 60 * 1000  # postflight send-marker older than this ⇒ treat as not-this-slot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--market', choices=['hk', 'us'], required=True)
    ap.add_argument('--phase', choices=['open', 'mid', 'pm', 'close'], required=True)
    ap.add_argument('--job-name', required=True, help='cron job name to inspect')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    today = datetime.now(HKT).strftime('%Y-%m-%d')
    tag = f'{args.market}-{args.phase}'

    job_id = find_job_id(args.job_name)
    if not job_id:
        log({'tag': tag, 'action': 'skip', 'reason': f'job not found: {args.job_name}'})
        return 0

    runs_today = today_runs(job_id)
    if not runs_today:
        log({'tag': tag, 'action': 'skip', 'reason': 'no run today yet (cron likely never fired)'})
        return 0
    last = runs_today[-1]
    run_at = last.get('runAtMs')
    session_id = last.get('sessionId')
    summary = last.get('summary', '')

    # Dedupe per slot (one re-send per run, keyed by runAtMs).
    flag = WS / 'memory' / '.tmp' / f'watchdog-{tag}-{run_at}.done'
    if flag.exists():
        log({'tag': tag, 'action': 'skip', 'reason': 'already handled this slot (dedupe flag)'})
        return 0

    # --- Healthy-report gate: never re-send a stall/garbage turn --------------
    # The clean report block's first line comes from the preflight context. If the
    # context is missing, preflight never ran → nothing to resend.
    ctx_path = WS / 'memory' / '.tmp' / f'report-context-{args.market}-{args.phase}-{today}.json'
    raw_block_first = None
    if ctx_path.exists():
        try:
            raw = (json.loads(ctx_path.read_text()).get('raw_wechat_block') or '').strip()
            raw_block_first = raw.splitlines()[0] if raw else None
        except Exception:
            pass
    if not raw_block_first:
        log({'tag': tag, 'action': 'skip', 'reason': 'no preflight raw_wechat_block (cron likely never ran)'})
        return 0

    block_present = raw_block_first in summary
    loop_score, _ = transcript_loop_score(session_id)
    looped = loop_score >= LOOP_THRESHOLD
    if not block_present or looped:
        # Report itself failed/looped — that's a generation failure, not a
        # long-turn delivery drop. Don't fabricate a resend of garbage.
        log({'tag': tag, 'action': 'skip', 'reason': 'run unhealthy (stall/loop) — not a long-turn drop',
             'block_present': block_present, 'loop_score': loop_score, 'run_at': run_at})
        return 0

    # --- Decision: did report_postflight already send this report? -------------
    # postflight is the PRIMARY sender (fresh token) and records the REAL send
    # result. Trust that marker, not the poisoned run-record `delivered` (which is
    # byte-identical for a dropped vs a landed run). Only re-send on a CONFIRMED
    # failure / missing marker — never double a report the postflight send landed.
    marker_path = WS / 'memory' / '.tmp' / f'report-sent-{args.market}-{args.phase}-{today}.json'
    marker = None
    if marker_path.exists():
        try:
            marker = json.loads(marker_path.read_text())
        except Exception:
            marker = None
    now_ms = int(datetime.now(HKT).timestamp() * 1000)
    fresh = bool(marker) and (now_ms - marker.get('ts', 0)) < MARKER_FRESH_MS
    matches = bool(marker) and (marker.get('first_line') == raw_block_first)
    if marker and marker.get('sent_ok') and fresh and matches:
        log({'tag': tag, 'action': 'ok',
             'reason': 'postflight already sent (marker sent_ok, fresh, matches) — no resend',
             'run_at': run_at})
        return 0

    # postflight send failed / never ran / marker mismatch ⇒ re-send via fresh token.
    report = last_report_text(session_id, raw_block_first)
    if not report:
        # Fallback: the run summary holds the full report after the "---" checklist.
        report = summary.split('\n---\n', 1)[1].strip() if '\n---\n' in summary else summary.strip()
    channel, to, account = resolve_wechat_target(args.market)
    if not (channel and to):
        log({'tag': tag, 'action': 'skip', 'reason': 'no wechat target resolved', 'run_at': run_at})
        return 0

    reason = ('postflight marker missing' if not marker
              else 'postflight send failed' if not marker.get('sent_ok')
              else 'marker stale/mismatch')
    banner = f'📨 自动补发（{reason}，阶段性报告用 fresh-token 补一份）\n\n'
    message = banner + report.strip()

    sent_ok, out = send_wechat(channel, to, account, message, args.dry_run)
    log({'tag': tag, 'action': 'resend', 'dry_run': args.dry_run, 'sent_ok': sent_ok,
         'job_id': job_id, 'reason': reason, 'loop_score': loop_score,
         'run_at': run_at, 'out': out})

    # Cold-session mirror to Telegram (cold-proof channel) on the same branch —
    # the fresh-token WeChat send above may itself drop. Only reached when the
    # postflight WeChat send was NOT confirmed landed, so healthy runs never hit TG.
    tg_banner = f'📨 自动补发（{reason}，微信可能没送达，Telegram 兜底一份）\n\n'
    tg_ok, tg_out = send_telegram(KCN_TELEGRAM, tg_banner + report.strip(), args.dry_run)
    log({'tag': tag, 'action': 'mirror-telegram', 'dry_run': args.dry_run, 'sent_ok': tg_ok,
         'reason': reason, 'run_at': run_at, 'target': KCN_TELEGRAM, 'out': tg_out})

    # Slot handled if EITHER channel landed — don't keep retrying a report kcn
    # already received on Telegram just because WeChat stayed cold.
    if (sent_ok or tg_ok) and not args.dry_run:
        flag.write_text(datetime.now(HKT).isoformat())

    print(json.dumps({'tag': tag, 'reason': reason, 'resent_wechat': sent_ok,
                      'mirrored_telegram': tg_ok, 'dry_run': args.dry_run}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
