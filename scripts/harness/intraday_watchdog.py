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
from datetime import datetime, timedelta
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
WATCHDOG_DELAY_MINUTES = 10


def deterministic_fallback(raw_block, tag, reason):
    """Pure formatter used by the watchdog and regression tests."""
    return (f'🧯 {tag} 确定性兜底（LLM {reason}）\n'
            '以下内容由 preflight 数据直接生成，未经过模型改写：\n\n'
            + raw_block.strip())


def watchdog_target(market, now=None):
    """Return the exact cron slot this watchdog invocation owns.

    Watchdogs run ten minutes after each half-hour Mode 7 slot. Subtracting that
    delay before applying the canonical slot mapping also handles midnight and a
    modestly delayed system-cron invocation without selecting an adjacent run.
    """
    wall_now = now or datetime.now(HKT)
    target_at = wall_now - timedelta(minutes=WATCHDOG_DELAY_MINUTES)
    job_name, slot = cron_heartbeat.slot_for(market, target_at)
    return wall_now, job_name, slot


def run_for_slot(runs, market, job_name, slot):
    """Select the newest completed run belonging to exactly ``job_name/slot``."""
    matches = []
    for run in runs:
        run_at = run.get('runAtMs')
        if not isinstance(run_at, (int, float)):
            continue
        run_dt = datetime.fromtimestamp(run_at / 1000, HKT)
        if cron_heartbeat.slot_for(market, run_dt) == (job_name, slot):
            matches.append(run)
    return matches[-1] if matches else None


def context_for_slot(path, job_name, slot):
    """Load a preflight context only when its heartbeat identifies this slot."""
    try:
        context = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    heartbeat = context.get('heartbeat') or {}
    if (heartbeat.get('job'), heartbeat.get('slot')) != (job_name, slot):
        return None
    return context


def marker_covers_slot(marker, job_name, slot, raw_block_first, now_ms):
    """Whether postflight confirmed Telegram delivery for this exact slot."""
    if not isinstance(marker, dict) or not marker.get('tg_ok'):
        return False
    if (marker.get('job'), marker.get('slot')) != (job_name, slot):
        return False
    ts = marker.get('ts')
    if not isinstance(ts, (int, float)) or now_ms - ts >= MARKER_FRESH_MS:
        return False
    return not raw_block_first or marker.get('first_line') == raw_block_first


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--job-name', required=True, help='intraday cron job name')
    ap.add_argument('--market', choices=['hk', 'us'], required=True)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    tag = f'intraday-{args.market}'
    watchdog_now, expected_job, expected_slot = watchdog_target(args.market)
    if expected_job != args.job_name:
        log({'tag': tag, 'action': 'skip', 'reason': 'watchdog invoked outside job window',
             'expected_job': expected_job, 'configured_job': args.job_name,
             'expected_slot': expected_slot})
        return 0

    job_id = find_job_id(args.job_name)
    if not job_id:
        log({'tag': tag, 'action': 'skip', 'reason': f'job not found: {args.job_name}'})
        return 0

    runs_today = today_runs(job_id)
    if not runs_today:
        log({'tag': tag, 'action': 'skip', 'reason': 'no run today yet'})
        return 0
    last = run_for_slot(runs_today, args.market, expected_job, expected_slot)
    if not last:
        log({'tag': tag, 'action': 'skip', 'reason': 'expected slot has no completed run',
             'expected_job': expected_job, 'expected_slot': expected_slot})
        return 0
    run_at = last.get('runAtMs')
    session_id = last.get('sessionId')

    # Dedupe by the schedule slot, not by retry attempt/runAtMs.
    slot_key = datetime.fromisoformat(expected_slot).strftime('%Y%m%d-%H%M')
    flag = WS / 'memory' / '.tmp' / f'watchdog-{tag}-{slot_key}.done'
    if flag.exists():
        log({'tag': tag, 'action': 'skip', 'reason': 'already handled this slot (dedupe flag)'})
        return 0

    # --- Generation gate: generated report or deterministic fallback ----------
    summary = last.get('summary', '')
    ctx_path = WS / 'memory' / '.tmp' / f'intraday-context-{args.market}-latest.json'
    context = context_for_slot(ctx_path, expected_job, expected_slot)
    if context is None:
        cron_heartbeat.record(
            args.market, 'watchdog_rejected', at=watchdog_now,
            job_name=expected_job, slot=expected_slot,
            watchdog_state='stale_context_rejected', telegram_sent=False,
        )
        log({'tag': tag, 'action': 'stale-backstop-rejected',
             'reason': 'latest preflight context does not match expected slot',
             'expected_job': expected_job, 'expected_slot': expected_slot,
             'run_at': run_at})
        return 0
    raw_block = (context.get('raw_wechat_block') or '').strip()
    raw_block_first = raw_block.splitlines()[0] if raw_block else None
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
            flag.write_text(watchdog_now.isoformat())
            cron_heartbeat.record(
                args.market, 'watchdog_backstop', at=watchdog_now,
                job_name=expected_job, slot=expected_slot,
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
    now_ms = int(watchdog_now.timestamp() * 1000)
    # TG is covered iff postflight's cosend confirmably delivered this report to
    # Telegram this exact slot (slot identity, freshness, first line, tg_ok=true).
    if marker_covers_slot(
            marker, expected_job, expected_slot, raw_block_first, now_ms):
        cron_heartbeat.record(
            args.market, 'completed', at=watchdog_now,
            job_name=expected_job, slot=expected_slot,
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
              else 'marker slot stale/mismatch')
    tg_banner = f'📲 补投（{reason}，Telegram 兜底一份）\n\n'
    tg_ok, tg_out = send_telegram(KCN_TELEGRAM, tg_banner + report.strip(), args.dry_run)
    log({'tag': tag, 'action': 'mirror-telegram', 'dry_run': args.dry_run, 'sent_ok': tg_ok,
         'job_id': job_id, 'reason': reason, 'loop_score': loop_score,
         'run_at': run_at, 'target': KCN_TELEGRAM, 'out': tg_out})

    # Slot handled once Telegram landed — don't keep retrying a report kcn has.
    if tg_ok and not args.dry_run:
        flag.write_text(watchdog_now.isoformat())
        cron_heartbeat.record(
            args.market, 'watchdog_backstop', at=watchdog_now,
            job_name=expected_job, slot=expected_slot,
            watchdog_state='telegram_mirror', telegram_sent=True,
        )
    elif not args.dry_run:
        cron_heartbeat.record(
            args.market, 'watchdog_failed', at=watchdog_now,
            job_name=expected_job, slot=expected_slot,
            watchdog_state='telegram_mirror_failed', telegram_sent=False,
        )

    print(json.dumps({'tag': tag, 'mirrored_telegram': tg_ok,
                      'reason': reason, 'dry_run': args.dry_run}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
