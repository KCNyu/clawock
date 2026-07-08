#!/usr/bin/env python3
"""
brief_watchdog.py — LLM-free BACKSTOP for the 08:00 盘前深度简报 cron.

ARCHITECTURE (2026-06-08): delivery is decoupled. The cron runs delivery=none;
brief_postflight does the SOLE WeChat send in a short-lived `openclaw message send`
that grabs a FRESH token (the announce-at-end-of-long-turn used a token captured at
turn start → expired mid-turn → silent drop; brief turns are ALWAYS >160s — see
memory: openclaw-wechat-longturn-token-expiry). Postflight records the REAL send
result to memory/.tmp/brief-sent-{date}.json.

This watchdog is now a pure Telegram BACKSTOP (mirrors intraday/report_watchdog):
it reads that marker and mirrors the card to Telegram ONLY when the postflight
cosend is not confirmed for today (marker missing, tg_ok false, or stale) — so it
never doubles a card Telegram already has.

NO WECHAT RESEND (2026-07-09, kcn's call): the watchdog used to re-send the card on
WeChat via a fresh token. That DUPLICATED the card on WeChat whenever the marker
merely looked stale but WeChat had actually landed — and you can't tell a landed
WeChat send from a silently-dropped one (#81096/#81316 wontfix). Since brief_postflight
now ALWAYS co-sends the card to Telegram (cold-proof), the WeChat retry bought
nothing but duplicates, so it's gone. Telegram is the sole backstop channel.

Card content comes from _watchdog_common.build_brief_card (LLM card file → plan.json
fallback), the same builder postflight uses. Dedupe flag prevents double-sends.

Usage: brief_watchdog.py [--dry-run]
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _watchdog_common import (  # noqa: E402
    WS, HKT, log, build_brief_card, send_telegram, KCN_TELEGRAM,
)

MARKER_FRESH_MS = 30 * 60 * 1000  # postflight send-marker older than this ⇒ not this slot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    today = datetime.now(HKT).strftime('%Y-%m-%d')
    tag = 'brief'

    # If the brief was never written, the LLM died before Step 4 — nothing to send.
    if not (WS / 'memory' / f'{today}-pre-open.md').exists():
        log({'tag': tag, 'action': 'skip', 'reason': 'no pre-open.md (brief never written)'})
        return 0

    # Trust the postflight send-marker, not the poisoned run-record `delivered`.
    marker_path = WS / 'memory' / '.tmp' / f'brief-sent-{today}.json'
    marker = None
    if marker_path.exists():
        try:
            marker = json.loads(marker_path.read_text())
        except Exception:
            marker = None
    now_ms = int(datetime.now(HKT).timestamp() * 1000)
    fresh = bool(marker) and (now_ms - marker.get('ts', 0)) < MARKER_FRESH_MS
    # TG is covered iff postflight's cosend confirmably delivered today's card to
    # Telegram (fresh marker, tg_ok=true). No WeChat resend — Telegram is the backstop.
    if marker and marker.get('tg_ok') and fresh:
        log({'tag': tag, 'action': 'ok',
             'reason': 'postflight cosend already delivered Telegram today — no backstop'})
        return 0

    # Postflight cosend failed / never ran / stale marker ⇒ mirror the card to Telegram.
    flag = WS / 'memory' / '.tmp' / f'watchdog-brief-{today}.done'
    if flag.exists():
        log({'tag': tag, 'action': 'skip', 'reason': 'already mirrored (dedupe flag present)'})
        return 0

    reason = ('postflight marker missing' if not marker
              else 'marker stale' if not fresh
              else 'postflight cosend failed (tg_ok=false)')

    message = build_brief_card(today)
    tg_banner = f'📨 自动补发（{reason}，Telegram 兜底一份）\n\n'
    tg_ok, out = send_telegram(KCN_TELEGRAM, tg_banner + message, args.dry_run)
    log({'tag': tag, 'action': 'mirror-telegram', 'dry_run': args.dry_run, 'sent_ok': tg_ok,
         'fail_reason': reason, 'marker': marker, 'target': KCN_TELEGRAM, 'out': out})
    if tg_ok and not args.dry_run:
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text(datetime.now(HKT).isoformat())

    print(json.dumps({'tag': tag, 'reason': reason, 'mirrored_telegram': tg_ok,
                      'dry_run': args.dry_run}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
