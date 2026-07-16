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

TWO MODES (2026-07-16). The delivery backstop above answers "card exists but did it
land?", and it runs at 08:30 — INSIDE the brief's observed landing window (08:13 on
07-14 … 08:49 on 07-15). At 08:30 a missing brief is indistinguishable from a slow
one, so that mode cannot judge a total miss and must stay quiet about it.

  (default)        08:30 — delivery backstop: mirror the card to Telegram if unconfirmed.
  --check-missing  09:05 — miss detector: the landing window has closed, so no brief now
                   means no brief today. Alerts AND fires the off-host GHA fallback.

Why --check-missing had to be added: on 2026-07-16 the 08:00 cron was killed by a hard
reboot at 09:11 (the box thrashes itself to death under this cron) and NOTHING said so
— this watchdog logged `skip` at 08:30 and returned 0, and the GHA fallback skipped on
its lateness gate. kcn found out by asking. A brief that was never written was the one
failure mode with no owner: too early for the 08:30 pass to call, too late for GHA's.

Usage: brief_watchdog.py [--check-missing] [--dry-run]
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _watchdog_common import (  # noqa: E402
    WS, HKT, log, build_brief_card, send_telegram, KCN_TELEGRAM,
    dispatch_brief_fallback,
)

MARKER_FRESH_MS = 30 * 60 * 1000  # postflight send-marker older than this ⇒ not this slot


def alert_brief_missing(today, dry_run):
    """09:05 HKT: window closed, still no brief ⇒ a real miss. Page kcn + self-heal.

    Dispatch has to happen before 10:00 HKT — brief-fallback.yml refuses to generate a
    pre-open brief after HK open. That is why this pass runs at 09:05 and not later.
    We alert even when the dispatch succeeds: the fallback is a single-turn vendor call
    that can itself fail, so kcn should know the 08:00 swarm missed regardless."""
    flag = WS / 'memory' / '.tmp' / f'watchdog-brief-missing-{today}.done'
    if flag.exists():
        log({'tag': 'brief', 'action': 'skip', 'reason': 'brief-missing already handled today'})
        return 0

    dispatched, out = dispatch_brief_fallback(dry_run)
    alert = (
        f'🔴 盘前深度简报缺失 — {today}\n\n'
        f'08:00 的 cron 没有产出 memory/{today}-pre-open.md，plan.json 同样没有。'
        f'到 09:05 仍然没有 = 今天没有 plan。\n\n'
        + ('✅ 已自动 dispatch off-host 兜底 (brief-fallback.yml)，约 5-10 分钟落盘并 push。\n'
           if dispatched else
           '⚠️ 自动 dispatch 兜底失败，需要手动：gh workflow run brief-fallback.yml\n'
           '（10:00 HKT 前有效，之后 workflow 会判定过期跳过）\n')
        + f'\n查因：openclaw cron runs --id $(openclaw cron list | grep 盘前深度简报) '
          f'/ sar -q 看 08:00 起的 blocked'
    )
    tg_ok, tg_out = send_telegram(KCN_TELEGRAM, alert, dry_run)
    log({'tag': 'brief', 'action': 'alert-brief-missing', 'dry_run': dry_run,
         'dispatched_fallback': dispatched, 'dispatch_out': out,
         'sent_ok': tg_ok, 'target': KCN_TELEGRAM, 'out': tg_out})
    if tg_ok and not dry_run:
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text(datetime.now(HKT).isoformat())
    print(json.dumps({'tag': 'brief', 'reason': 'brief never written',
                      'dispatched_fallback': dispatched, 'alerted_telegram': tg_ok,
                      'dry_run': dry_run}, ensure_ascii=False))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--check-missing', action='store_true',
                    help='09:05 miss-detector mode (see module docstring)')
    args = ap.parse_args()

    today = datetime.now(HKT).strftime('%Y-%m-%d')
    tag = 'brief'

    # No brief on disk. There is no card to mirror either way — what differs is whether
    # we can yet call it a miss. At 08:30 we are inside the landing window (08:13-08:49
    # observed) so silence is correct; at 09:05 the window has closed, so it is a miss.
    if not (WS / 'memory' / f'{today}-pre-open.md').exists():
        if args.check_missing:
            return alert_brief_missing(today, args.dry_run)
        log({'tag': tag, 'action': 'skip',
             'reason': 'no pre-open.md yet (inside 08:13-08:49 landing window; '
                       '09:05 --check-missing pass judges the miss)'})
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
