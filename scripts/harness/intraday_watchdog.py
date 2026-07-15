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

This watchdog is now a pure Telegram BACKSTOP: it reads that marker and mirrors the
report to Telegram ONLY when the postflight cosend is not confirmed for this slot
(marker missing, tg_ok false, or stale/mismatched) — so it never doubles a report
Telegram already has.

NO WECHAT RESEND (2026-07-09, kcn's call): the watchdog used to also re-send on
WeChat via a fresh token. That DUPLICATED reports on WeChat whenever the marker
merely looked stale/mismatched but WeChat had actually landed — and you can't tell a
landed WeChat send from a silently-dropped one (#81096/#81316 wontfix, cold drop
still returns sent_ok=true). Since intraday_postflight now ALWAYS co-sends the same
body to Telegram (cold-proof, no contextToken drop), the WeChat retry bought nothing
but duplicates, so it's gone. Telegram is the sole backstop channel.

Healthy runs use their generated report; stalled/looped runs fall back to the
deterministic preflight block on Telegram. Dedupe remains per slot.

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
    transcript_loop_score, last_report_text, send_telegram,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'data'))
import cron_heartbeat  # noqa: E402

LOOP_THRESHOLD = 5         # transcript loop_score ≥ this ⇒ mimo repeat-loop ⇒ garbage
MARKER_FRESH_MS = 25 * 60 * 1000  # postflight send-marker older than this ⇒ treat as not-this-slot


def deterministic_fallback(raw_block, tag, reason):
    """Pure formatter used by the watchdog and regression tests."""
    return (f'🧯 {tag} 确定性兜底（LLM {reason}）\n'
            '以下内容由 preflight 数据直接生成，未经过模型改写：\n\n'
            + raw_block.strip())


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
    run_dt = (datetime.fromtimestamp(run_at / 1000, HKT)
              if isinstance(run_at, (int, float)) else datetime.now(HKT))
    heartbeat_job, heartbeat_slot = cron_heartbeat.slot_for(args.market, run_dt)

    # Dedupe per slot (one re-send per intraday run, keyed by runAtMs).
    flag = WS / 'memory' / '.tmp' / f'watchdog-{tag}-{run_at}.done'
    if flag.exists():
        log({'tag': tag, 'action': 'skip', 'reason': 'already handled this slot (dedupe flag)'})
        return 0

    # --- Generation gate: generated report or deterministic fallback ----------
    summary = last.get('summary', '')
    raw_block = ''
    raw_block_first = None
    ctx_path = WS / 'memory' / '.tmp' / f'intraday-context-{args.market}-latest.json'
    if ctx_path.exists():
        try:
            raw_block = (json.loads(ctx_path.read_text()).get('raw_wechat_block') or '').strip()
            raw_block_first = raw_block.splitlines()[0] if raw_block else None
        except Exception:
            pass
    sent_via_tool = bool((last.get('delivery') or {}).get('messageToolSentTo'))
    block_present = bool(raw_block_first and raw_block_first in summary)
    delivered_clean = sent_via_tool or block_present
    loop_score, _ = transcript_loop_score(session_id)
    looped = loop_score >= LOOP_THRESHOLD
    if not delivered_clean or looped:
        reason = '循环' if looped else '未完成'
        body = deterministic_fallback(raw_block, tag, reason)
        tg_ok, tg_out = send_telegram(KCN_TELEGRAM, body, args.dry_run)
        log({'tag': tag, 'action': 'deterministic-fallback', 'sent_ok': tg_ok,
             'delivered_clean': delivered_clean, 'loop_score': loop_score, 'run_at': run_at,
             'target': KCN_TELEGRAM, 'out': tg_out})
        if tg_ok and not args.dry_run:
            flag.write_text(datetime.now(HKT).isoformat())
            cron_heartbeat.record(
                args.market, 'watchdog_backstop', at=run_dt,
                job_name=heartbeat_job, slot=heartbeat_slot,
                watchdog_state='deterministic_fallback', telegram_sent=True,
            )
        print(json.dumps({'tag': tag, 'deterministic_fallback': tg_ok,
                          'dry_run': args.dry_run}, ensure_ascii=False))
        return 0

    # --- Delivery backstop: Telegram only (no WeChat resend) ------------------
    # WHY NO WECHAT RESEND ANYMORE (2026-07-09, kcn's call): a watchdog WeChat
    # resend DUPLICATED the report on WeChat whenever the marker merely looked
    # stale/mismatched but WeChat had actually landed — and you can't tell a landed
    # WeChat send from a silently-dropped one (#81096/#81316 wontfix, cold drop
    # still returns sent_ok=true). Now that intraday_postflight ALWAYS co-sends the
    # same body to Telegram (cold-proof, no contextToken drop), the WeChat retry
    # bought nothing but duplicates. So the watchdog's SOLE job is to guarantee
    # Telegram has this report — never touch WeChat.
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
    # TG is covered iff postflight's cosend confirmably delivered this report to
    # Telegram this slot (fresh marker, matching first line, tg_ok=true).
    if marker and marker.get('tg_ok') and fresh and matches:
        cron_heartbeat.record(
            args.market, 'completed', at=run_dt,
            job_name=heartbeat_job, slot=heartbeat_slot,
            watchdog_state='ok', telegram_sent=True,
        )
        log({'tag': tag, 'action': 'ok',
             'reason': 'postflight cosend already delivered Telegram this slot — no backstop',
             'run_at': run_at})
        return 0

    # postflight cosend never ran / failed / stale-or-mismatched marker ⇒ Telegram
    # is not confirmed for this report → mirror it now.
    report = last_report_text(session_id, raw_block_first) if raw_block_first else None
    if not report:
        report = summary  # fallback: run-record summary (usually holds the full block)

    reason = ('postflight marker missing' if not marker
              else 'postflight cosend failed' if not marker.get('tg_ok')
              else 'marker stale/mismatch')
    tg_banner = f'📲 补投（{reason}，Telegram 兜底一份）\n\n'
    tg_ok, tg_out = send_telegram(KCN_TELEGRAM, tg_banner + report.strip(), args.dry_run)
    log({'tag': tag, 'action': 'mirror-telegram', 'dry_run': args.dry_run, 'sent_ok': tg_ok,
         'job_id': job_id, 'reason': reason, 'loop_score': loop_score,
         'run_at': run_at, 'target': KCN_TELEGRAM, 'out': tg_out})

    # Slot handled once Telegram landed — don't keep retrying a report kcn has.
    if tg_ok and not args.dry_run:
        flag.write_text(datetime.now(HKT).isoformat())
        cron_heartbeat.record(
            args.market, 'watchdog_backstop', at=run_dt,
            job_name=heartbeat_job, slot=heartbeat_slot,
            watchdog_state='telegram_mirror', telegram_sent=True,
        )
    elif not args.dry_run:
        cron_heartbeat.record(
            args.market, 'watchdog_failed', at=run_dt,
            job_name=heartbeat_job, slot=heartbeat_slot,
            watchdog_state='telegram_mirror_failed', telegram_sent=False,
        )

    print(json.dumps({'tag': tag, 'mirrored_telegram': tg_ok,
                      'reason': reason, 'dry_run': args.dry_run}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
