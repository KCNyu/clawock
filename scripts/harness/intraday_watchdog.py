#!/usr/bin/env python3
"""
intraday_watchdog.py — long-turn-drop safety net for Mode 7 (盘中盯盘) crons.

ROOT CAUSE (2026-06-04, re-diagnosed + live-confirmed): intraday reports "没出来"
on kcn's WeChat even though every run finished status=ok with delivered=true. The
real mechanism is NOT idle "cold session" — it's the WeChat contextToken expiry
(upstream openclaw/openclaw#61174, closed wontfix): the token is captured from the
inbound poll and held in memory, and Tencent expires it server-side after ~160s.
The intraday cron packs preflight + LLM synthesis + postflight + dashboard build
into ONE timed agent turn; long turns run 200-1000s, so the `announce` delivery
that fires at turn END uses a token that died mid-turn → silent drop, delivered
still returns true (the onError is only logged). Short turns (<160s) deliver fine.

THE FIX (2026-06-04, evolved): the run-record `delivered` is USELESS — a dropped
run and a landed run are byte-identical, and duration is a bad predictor (214s
landed, 282s dropped). So we stopped guessing. intraday_postflight is now the
PRIMARY WeChat sender: it delivers each report via a fresh-token `openclaw message
send` (the path kcn confirmed lands) and the 3 intraday crons run --no-deliver (no
announce) → exactly one send, no long-turn drop, no double. postflight records the
REAL send result to memory/.tmp/intraday-sent-{market}.json.

This watchdog is now a pure BACKSTOP: it reads that marker and re-sends ONLY when
the postflight send is confirmed failed / never happened (marker missing, sent_ok
false, or stale/mismatched) — so it never doubles a report that already went out.

TELEGRAM MIRROR (2026-07-03, bot @clawock_bot revived): "cold session" here means
"the confirmed WeChat send did not land" (marker missing/failed/stale) — NOT idle
time. On exactly that branch we ALSO mirror the report to Telegram (KCN_TELEGRAM),
which has no contextToken-expiry drop, so kcn still gets it even if the fresh-token
WeChat resend drops too. Only fires on a cold event — a cleanly-delivered report
never touches Telegram (no double-channel spam on healthy runs).

Healthy-report gate: only re-send a report produced cleanly (block first-line
present AND not a mimo repeat-loop) — never re-send a stall. Dedupe per slot.

(Shared run-record / send helpers live in _watchdog_common.py.)

Usage:
    intraday_watchdog.py --job-name "盘中盯盘"   --market hk
    intraday_watchdog.py --job-name "美股盘中盯盘" --market us
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
    WS, HKT, log, find_job_id, today_runs, KCN_TELEGRAM,
    transcript_loop_score, last_report_text, send_wechat, send_telegram, resolve_wechat_target,
)

LOOP_THRESHOLD = 5         # transcript loop_score ≥ this ⇒ mimo repeat-loop ⇒ garbage
MARKER_FRESH_MS = 25 * 60 * 1000  # postflight send-marker older than this ⇒ treat as not-this-slot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--job-name', required=True, help='intraday cron job name')
    ap.add_argument('--market', choices=['hk', 'us'], required=True)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

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

    # Dedupe per slot (one re-send per intraday run, keyed by runAtMs).
    flag = WS / 'memory' / '.tmp' / f'watchdog-{tag}-{run_at}.done'
    if flag.exists():
        log({'tag': tag, 'action': 'skip', 'reason': 'already handled this slot (dedupe flag)'})
        return 0

    # --- Healthy-report gate: never re-send a stall/garbage turn --------------
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
        # long-turn drop. Don't re-send garbage; just record it.
        log({'tag': tag, 'action': 'skip', 'reason': 'run unhealthy (stall/loop) — not a long-turn drop',
             'delivered_clean': delivered_clean, 'loop_score': loop_score, 'run_at': run_at})
        return 0

    # --- Decision: did intraday_postflight already send this report? -----------
    # postflight is now the PRIMARY sender (fresh token, see its docstring) and
    # records the REAL send result to intraday-sent-{market}.json. We trust that
    # marker instead of the poisoned run-record `delivered` (which is byte-identical
    # for a dropped vs a landed run). Only re-send on a CONFIRMED failure / missing
    # marker — never double a report the postflight send already landed. This
    # replaces the old duration heuristic that false-doubled every long-but-delivered
    # run (214s landed, 282s dropped — duration can't tell them apart).
    marker_path = WS / 'memory' / '.tmp' / f'intraday-sent-{args.market}.json'
    marker = None
    if marker_path.exists():
        try:
            marker = json.loads(marker_path.read_text())
        except Exception:
            marker = None
    now_ms = int(datetime.now(HKT).timestamp() * 1000)
    fresh   = bool(marker) and (now_ms - marker.get('ts', 0)) < MARKER_FRESH_MS
    # first_line guards against a stale marker from a previous slot; if we can't read
    # the block, trust recency alone (avoid false-double).
    matches = bool(marker) and (not raw_block_first or marker.get('first_line') == raw_block_first)
    if marker and marker.get('sent_ok') and fresh and matches:
        log({'tag': tag, 'action': 'ok',
             'reason': 'postflight already sent (marker sent_ok, fresh, matches) — no resend',
             'run_at': run_at})
        return 0

    # postflight send failed / never ran / marker mismatch ⇒ re-send via fresh token
    report = last_report_text(session_id, raw_block_first) if raw_block_first else None
    if not report:
        report = summary  # fallback: run-record summary (usually holds the full block)
    channel, to, account = resolve_wechat_target(args.market)
    if not (channel and to):
        log({'tag': tag, 'action': 'skip', 'reason': 'no wechat target resolved', 'run_at': run_at})
        return 0

    reason = ('postflight marker missing' if not marker
              else 'postflight send failed' if not marker.get('sent_ok')
              else 'marker stale/mismatch')
    banner = f'📲 补投（{reason}，盘中盯盘用 fresh-token 补一份）\n\n'
    message = banner + report.strip()

    sent_ok, out = send_wechat(channel, to, account, message, args.dry_run)
    log({'tag': tag, 'action': 'resend-wechat', 'dry_run': args.dry_run, 'sent_ok': sent_ok,
         'job_id': job_id, 'reason': reason, 'loop_score': loop_score,
         'run_at': run_at, 'channel': channel, 'out': out})

    # Cold-session mirror: the WeChat send just above may itself drop (same
    # contextToken expiry), so mirror the report to Telegram — a cold-proof
    # channel — on the same cold-detection branch. Only reached when the
    # postflight WeChat send was NOT confirmed landed, so healthy runs never
    # hit Telegram. Dedupe flag guards against re-mirroring the same slot.
    tg_banner = f'📲 补投（{reason}，微信可能没送达，Telegram 兜底一份）\n\n'
    tg_ok, tg_out = send_telegram(KCN_TELEGRAM, tg_banner + report.strip(), args.dry_run)
    log({'tag': tag, 'action': 'mirror-telegram', 'dry_run': args.dry_run, 'sent_ok': tg_ok,
         'reason': reason, 'run_at': run_at, 'target': KCN_TELEGRAM, 'out': tg_out})

    # Slot handled if EITHER channel landed — don't keep retrying a report kcn
    # already received on Telegram just because WeChat stayed cold.
    if (sent_ok or tg_ok) and not args.dry_run:
        flag.write_text(datetime.now(HKT).isoformat())

    print(json.dumps({'tag': tag, 'resent_wechat': sent_ok, 'mirrored_telegram': tg_ok,
                      'reason': reason, 'dry_run': args.dry_run}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
