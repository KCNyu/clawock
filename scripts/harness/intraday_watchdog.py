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
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'data'))  # render_holdings_card
from _watchdog_common import (  # noqa: E402
    WS, HKT, log, find_job_id, read_runs, today_runs,
    transcript_loop_score, last_human_inbound_ms, last_report_text, send_telegram,
)

LOOP_THRESHOLD = 5       # transcript loop_score ≥ this ⇒ mimo repeat-loop ⇒ garbage
DEFAULT_COLD_MIN = 40    # WeChat session idle ≥ this at send-time ⇒ likely dropped
KCN_TELEGRAM_TARGET = 2033937852  # Shengyu Li's Telegram DM (chat_id == user id)
GAIN, LOSS, NEUTRAL = '#3fb950', '#f85149', '#c9d1d9'


def build_card(report_text):
    """Parse the announced report (8-col holdings block + index/summary/narrative)
    into (card_data, caption_tail) for the matplotlib card renderer. The image
    shows title+index+summary+table; the caption carries everything AFTER the
    table (signals + ▎我的看法). Returns None if the canonical 8-col table isn't
    found → caller falls back to a plain-text mirror."""
    lines = report_text.splitlines()
    tbl = [l for l in lines if l.strip().startswith('|')]
    if len(tbl) < 3:
        return None
    header = [c.strip() for c in tbl[0].strip().strip('|').split('|')]
    if len(header) != 8:
        return None
    rows = []
    for l in tbl[1:]:
        cells = [c.strip() for c in l.strip().strip('|').split('|')]
        if len(cells) != 8:
            continue
        if cells[0] == '代码' or set(cells[0]) <= set('-: '):  # header / separator
            continue
        rows.append(cells)
    if not rows:
        return None
    first_tbl = next(i for i, l in enumerate(lines) if l.strip().startswith('|'))
    last_tbl = max(i for i, l in enumerate(lines) if l.strip().startswith('|'))
    pre = [l.strip() for l in lines[:first_tbl] if l.strip()]
    title = pre[0] if pre else '持仓盯盘'
    for ch in ('🇭🇰', '🇺🇸', '📊', '📉'):
        title = title.replace(ch, '')
    summary = next((l for l in pre if '市值' in l), '')
    summary = summary.replace('📊', '').strip()
    index = next((l for l in pre[1:] if l != summary and '市值' not in l), '')
    card = {
        'title':         title.strip(),
        'index':         index,
        'index_color':   GAIN if '▲' in index else (LOSS if '▼' in index else NEUTRAL),
        'summary':       summary,
        'summary_color': LOSS if ('浮盈 -' in summary or '浮盈 −' in summary) else GAIN,
        'cols':          header,
        'aligns':        ['l'] + ['r'] * 7,
        'xs':            [2.5, 29, 41, 53, 65, 78, 89, 99],
        'signed_cols':   [i for i, h in enumerate(header) if '%' in h or '$' in h],
        'rows':          rows,
    }
    tail = '\n'.join(lines[last_tbl + 1:]).strip()
    return card, tail


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
              f'{idle_min}min，大概率被腾讯静默吞了，故 Telegram 补一份）')

    # Preferred: render the holdings table as a broker-style PNG (mobile WeChat
    # users hate monospace pipes) and send it as a photo with signals+看法 as
    # the caption. Any failure (bad table parse, render error) falls back to the
    # plain-text mirror so kcn never gets nothing.
    mode, png = 'text', None
    try:
        from render_holdings_card import render as render_card  # noqa: E402
        built = build_card(report)
        if built:
            card_data, tail = built
            png = WS / 'memory' / '.tmp' / f'tg-card-{tag}-{run_at}.png'
            render_card(card_data, str(png))
            caption = (banner + '\n\n' + tail).strip()[:1000]
            sent_ok, out = send_telegram(args.telegram_target, caption, args.dry_run, media=str(png))
            mode = 'photo'
        else:
            raise ValueError('canonical 8-col table not found in report')
    except Exception as e:
        out_note = f'card render fell back to text: {e}'
        sent_ok, out = send_telegram(args.telegram_target, banner + '\n\n' + report.strip(), args.dry_run)
        out = f'[{out_note}] {out}'

    log({'tag': tag, 'action': 'mirror-telegram', 'mode': mode, 'dry_run': args.dry_run,
         'sent_ok': sent_ok, 'job_id': job_id, 'idle_min': idle_min, 'cold_min': args.cold_min,
         'loop_score': loop_score, 'run_at': run_at, 'out': out})
    if sent_ok and not args.dry_run:
        flag.write_text(datetime.now(HKT).isoformat())

    print(json.dumps({'tag': tag, 'idle_min': idle_min, 'cold': cold, 'mode': mode,
                      'mirrored': sent_ok, 'dry_run': args.dry_run}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
