#!/usr/bin/env python3
"""
brief_watchdog.py — LLM-free BACKSTOP for the 08:00 盘前深度简报 cron.

ARCHITECTURE (2026-06-08): delivery is decoupled. The cron runs delivery=none;
brief_postflight does the SOLE WeChat send in a short-lived `openclaw message send`
that grabs a FRESH token (the announce-at-end-of-long-turn used a token captured at
turn start → expired mid-turn → silent drop; brief turns are ALWAYS >160s — see
memory: openclaw-wechat-longturn-token-expiry). Postflight records the REAL send
result to memory/.tmp/brief-sent-{date}.json.

This watchdog is now a pure backstop (mirrors intraday_watchdog): it reads that
marker and re-sends ONLY when the postflight send is confirmed failed / never
happened (marker missing, sent_ok false, or stale) — so it never doubles a card the
postflight send already landed. The run-record `delivered` field is useless (byte-
identical for dropped vs landed); we trust the marker instead. Card content comes
from _watchdog_common.build_brief_card (LLM card file → plan.json fallback), the
same builder postflight uses. Dedupe flag prevents double-sends within the slot.

Usage: brief_watchdog.py [--dry-run]
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _watchdog_common import (  # noqa: E402
    WS, HKT, log, resolve_wechat_target, send_wechat, build_brief_card,
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
    if marker and marker.get('sent_ok') and fresh:
        log({'tag': tag, 'action': 'ok',
             'reason': 'postflight already sent (marker sent_ok, fresh) — no resend'})
        return 0

    # Postflight send failed / never ran / stale marker ⇒ re-send via fresh token.
    flag = WS / 'memory' / '.tmp' / f'watchdog-brief-{today}.done'
    if flag.exists():
        log({'tag': tag, 'action': 'skip', 'reason': 'already resent (dedupe flag present)'})
        return 0

    reason = ('postflight marker missing' if not marker
              else 'marker stale' if not fresh
              else 'postflight send failed (sent_ok=false)')

    channel, to, account = resolve_wechat_target()
    if not to:
        log({'tag': tag, 'action': 'fail', 'reason': 'no wechat target resolved'})
        return 0

    message = build_brief_card(today)
    sent_ok, out = send_wechat(channel, to, account, message, args.dry_run)
    log({'tag': tag, 'action': 'resend', 'dry_run': args.dry_run, 'sent_ok': sent_ok,
         'fail_reason': reason, 'marker': marker, 'out': out})
    if sent_ok and not args.dry_run:
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text(datetime.now(HKT).isoformat())

    print(json.dumps({'tag': tag, 'reason': reason, 'resent': sent_ok,
                      'dry_run': args.dry_run}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
