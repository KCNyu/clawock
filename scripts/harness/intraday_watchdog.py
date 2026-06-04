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

THE FIX (live-validated 2026-06-04): a fresh `openclaw message send` runs as a
short-lived op (<1s), captures a CURRENT token, and lands reliably — kcn confirmed
receipt of a re-sent report that the long-turn announce had dropped. So this
watchdog runs OUT OF BAND (system crontab, a few min after each intraday slot) and,
when the run's agent turn exceeded the token-expiry threshold (durationMs >
LONG_TURN_MS), RE-SENDS the report to WeChat via fast-send. WeChat stays the only
channel (Telegram is dead — do not route here). Short turns are left alone (their
announce already landed) so we don't double-send.

Healthy-report gate: only re-send a report that was actually produced cleanly
(block first-line present AND not a mimo repeat-loop) — never re-send a stall.
Dedupe per slot so a given run is re-sent at most once.

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
    WS, HKT, log, find_job_id, today_runs,
    transcript_loop_score, last_report_text, send_wechat,
)

LOOP_THRESHOLD = 5         # transcript loop_score ≥ this ⇒ mimo repeat-loop ⇒ garbage
DEFAULT_LONG_TURN_MS = 160000  # agent turn ≥ this ⇒ WeChat contextToken expired mid-turn
                               #   (#61174 ~160s; observed: 142s landed, ≥217s dropped)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--job-name', required=True, help='intraday cron job name')
    ap.add_argument('--market', choices=['hk', 'us'], required=True)
    ap.add_argument('--long-turn-ms', type=int, default=DEFAULT_LONG_TURN_MS,
                    help='agent-turn ms above which the WeChat token likely expired mid-turn')
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
    duration_ms = last.get('durationMs') or 0

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

    # --- Long-turn judgment (the part that does NOT trust `delivered`) ---------
    # Short turns: the announce fired with a still-valid token → it landed. Leave
    # them alone so we never double-send a report kcn already has.
    if duration_ms < args.long_turn_ms:
        log({'tag': tag, 'action': 'ok',
             'reason': f'turn {duration_ms}ms < {args.long_turn_ms}ms — token alive, announce landed',
             'run_at': run_at, 'loop_score': loop_score})
        return 0

    # --- Long turn ⇒ contextToken expired mid-turn ⇒ announce dropped ⇒ fast re-send to WeChat
    report = last_report_text(session_id, raw_block_first) if raw_block_first else None
    if not report:
        report = summary  # fallback: run-record summary (usually holds the full block)
    deliv = last.get('delivery') or {}
    target = deliv.get('intended') or deliv.get('resolved') or {}
    channel = target.get('channel')
    to = target.get('to')
    account = target.get('accountId')
    if not (channel and to):
        log({'tag': tag, 'action': 'skip', 'reason': 'no delivery target in run record',
             'run_at': run_at, 'delivery': deliv})
        return 0

    secs = round(duration_ms / 1000)
    banner = (f'📲 补投（盘中盯盘本次 turn 跑了 {secs}s > 160s，微信 token 已在 turn 中过期、'
              f'原投递大概率被静默吞，故用 fresh-token 补一份）\n\n')
    message = banner + report.strip()

    sent_ok, out = send_wechat(channel, to, account, message, args.dry_run)
    log({'tag': tag, 'action': 'resend-wechat', 'dry_run': args.dry_run, 'sent_ok': sent_ok,
         'job_id': job_id, 'duration_ms': duration_ms, 'long_turn_ms': args.long_turn_ms,
         'loop_score': loop_score, 'run_at': run_at, 'channel': channel, 'out': out})
    if sent_ok and not args.dry_run:
        flag.write_text(datetime.now(HKT).isoformat())

    print(json.dumps({'tag': tag, 'duration_ms': duration_ms,
                      'long_turn': True, 'resent': sent_ok, 'dry_run': args.dry_run},
                     ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
