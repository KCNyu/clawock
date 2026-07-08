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

This watchdog is now a pure Telegram BACKSTOP (system crontab, ~15min after the
cron): it reads that marker and mirrors the report to Telegram ONLY when the
postflight cosend is not confirmed for this slot (marker missing, tg_ok false, or
stale/mismatched) — so it never doubles a report Telegram already has.

NO WECHAT RESEND (2026-07-09, kcn's call): the watchdog used to also re-send the
report on WeChat via a fresh token. That DUPLICATED reports on WeChat whenever the
marker merely looked stale/mismatched but WeChat had actually landed — and you can't
tell a landed WeChat send from a silently-dropped one (#81096/#81316 wontfix, cold
drop still returns sent_ok=true). Since report_postflight now ALWAYS co-sends the
same body to Telegram (cold-proof, no contextToken-expiry drop), the WeChat retry
bought nothing but duplicates, so it's gone. Telegram is the sole backstop channel:
a report kcn didn't get on WeChat still reaches him on Telegram, without the dupes.

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
    WS, HKT, log, find_job_id, today_runs,
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

    # --- Delivery backstop: Telegram only (no WeChat resend) ------------------
    # WHY NO WECHAT RESEND ANYMORE (2026-07-09, kcn's call): a watchdog WeChat
    # resend DUPLICATED the report on WeChat whenever the postflight marker merely
    # looked stale/mismatched but WeChat had actually landed — and you can't tell a
    # landed WeChat send from a silently-dropped one (#81096/#81316 wontfix, cold
    # drop still returns sent_ok=true). Now that report_postflight ALWAYS co-sends
    # the same body to Telegram (the cold-proof channel, no contextToken drop), the
    # WeChat retry buys nothing but duplicates. So the watchdog's SOLE job is to
    # guarantee Telegram has this report — never touch WeChat.
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
    # TG is covered iff postflight's cosend confirmably delivered THIS report to
    # Telegram this slot (fresh marker, matching first line, tg_ok=true).
    if marker and marker.get('tg_ok') and fresh and matches:
        log({'tag': tag, 'action': 'ok',
             'reason': 'postflight cosend already delivered Telegram this slot — no backstop',
             'run_at': run_at})
        return 0

    # postflight cosend never ran / failed / stale-or-mismatched marker ⇒ Telegram
    # is not confirmed for this report → mirror it now.
    report = last_report_text(session_id, raw_block_first)
    if not report:
        # Fallback: the run summary holds the full report after the "---" checklist.
        report = summary.split('\n---\n', 1)[1].strip() if '\n---\n' in summary else summary.strip()

    reason = ('postflight marker missing' if not marker
              else 'postflight cosend failed' if not marker.get('tg_ok')
              else 'marker stale/mismatch')
    tg_banner = f'📨 自动补发（{reason}，Telegram 兜底一份）\n\n'
    tg_ok, tg_out = send_telegram(KCN_TELEGRAM, tg_banner + report.strip(), args.dry_run)
    log({'tag': tag, 'action': 'mirror-telegram', 'dry_run': args.dry_run, 'sent_ok': tg_ok,
         'job_id': job_id, 'reason': reason, 'loop_score': loop_score,
         'run_at': run_at, 'target': KCN_TELEGRAM, 'out': tg_out})

    # Slot handled once Telegram landed — don't keep retrying a report kcn has.
    if tg_ok and not args.dry_run:
        flag.write_text(datetime.now(HKT).isoformat())

    print(json.dumps({'tag': tag, 'reason': reason, 'mirrored_telegram': tg_ok,
                      'dry_run': args.dry_run}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
