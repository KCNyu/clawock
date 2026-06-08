#!/usr/bin/env python3
"""
brief_watchdog.py — LLM-free safety net for the 08:00 盘前深度简报 cron.

WHY: the brief agent can finish analysis + write pre-open.md + pass postflight,
then stall in a mimo repeat-loop on the WeChat-delivery turn ("Now let me output
the WeChat message…" ×dozens), shipping garbage. openclaw marks delivered=true
regardless, so that field is useless as a signal. (The compact-card Step 6
mostly prevents this now; this is the residual backstop.)

DETECTION (see _watchdog_common.transcript_loop_score): the run-record `summary`
is truncated meta-prose (a clean run's summary is a "✅ done" checklist with NO
card markers — marker-matching there false-positives every day). The real failure
only shows as a repeat-loop in the full session transcript, so we score that
directly: clean run ≈2, looped run ≈7+. Resend only when score ≥ LOOP_THRESHOLD.

On detected failure, re-send a deterministic compact card (book + ≤3 actions from
plan.json + full-brief link) — matches kcn's normal WeChat format, never a 16KB
dump. Dedupe flag prevents double-sends. Exit 0 always; actions → logs/watchdog.jsonl.

Usage: brief_watchdog.py [--dry-run]
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _watchdog_common import (  # noqa: E402
    WS, HKT, log, find_job_id, read_runs, today_runs,
    resolve_target, send_wechat, transcript_loop_score,
)

JOB_NAME = '盘前深度简报'
BRIEF_URL_TMPL = 'https://kcnyu.github.io/clawock/memory/{date}-pre-open.html'
LOOP_THRESHOLD = 5  # transcript loop_score ≥ this ⇒ mimo repeat-loop ⇒ failed delivery
# WeChat contextToken expires server-side at ~160s. If the brief run packs analysis +
# file writes + commit/push into ONE long agent turn (>160s), the final announce uses a
# dead token → Tencent silently drops it while openclaw still reports delivered=true
# (see memory: openclaw-wechat-longturn-token-expiry). This failure has NO repeat-loop
# signature (the turn is doing real, slow work), so loop_score stays ~1 and the old
# detector missed it. durationMs comes from the run record, so this fires even when the
# transcript was GC'd (blob==0).
TOKEN_EXPIRY_MS = 160_000


def build_compact_fallback(today):
    """Deterministic compact card (no LLM): banner + book + ≤3 actions from
    plan.json + full-brief link. Mirrors the normal Step 6 card. Degrades to a
    link-only message if plan.json is missing/unparseable."""
    url = BRIEF_URL_TMPL.format(date=today)
    lines = ['📨 自动补发：今日盘前简报模型投递中断，已生成完整版↓', '',
             f'📊 盘前深度简报｜{today}']
    try:
        plan = json.loads((WS / 'memory' / f'{today}-plan.json').read_text())
        bk = plan.get('book') or {}
        if bk:
            lines.append(f"Book: USD${bk.get('usd_total_pnl', '?')} | "
                         f"HK leg {bk.get('hk_leg_hkd', '?')}HKD | US leg {bk.get('us_leg_usd', '?')}USD")
        acts = [a for a in (plan.get('actions') or []) if isinstance(a, dict)][:3]
        if acts:
            lines.append('今日动作：')
            for i, a in enumerate(acts, 1):
                trig = a.get('trigger_price')
                trig = f"@{trig}" if trig is not None else (a.get('trigger_type') or '')
                conf = a.get('confidence')
                conf = f" conf{round(float(conf) * 100)}%" if conf is not None else ''
                lines.append(f"{i}. {a.get('ticker', '?')} {a.get('bucket', '')} {trig}{conf}")
    except Exception:
        pass  # link-only fallback
    lines += ['', f'📈 完整报告：{url}']
    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    today = datetime.now(HKT).strftime('%Y-%m-%d')
    tag = 'brief'

    # The full brief — if it doesn't exist, the brief never got written (LLM died
    # before Step 4); nothing to resend.
    preopen = WS / 'memory' / f'{today}-pre-open.md'
    if not preopen.exists():
        log({'tag': tag, 'action': 'skip', 'reason': 'no pre-open.md (brief never written)'})
        return 0

    job_id = find_job_id(JOB_NAME)
    if not job_id:
        log({'tag': tag, 'action': 'skip', 'reason': f'job not found: {JOB_NAME}'})
        return 0

    runs_today = today_runs(job_id)
    if not runs_today:
        log({'tag': tag, 'action': 'skip', 'reason': 'no run today (cron did not fire)'})
        return 0
    last = runs_today[-1]
    score, blob = transcript_loop_score(last.get('sessionId'))
    dur_ms = last.get('durationMs') or 0

    # Two independent failure modes the watchdog must catch:
    #   • repeat-loop  — mimo stalls on the delivery turn; only visible in the transcript
    #     (score ≥ LOOP_THRESHOLD, needs blob>0). assume delivered if no transcript.
    #   • long-turn    — run > ~160s in one turn ⇒ WeChat token already expired at announce
    #     ⇒ silent drop despite delivered=true. read straight off durationMs (no transcript
    #     needed), so it fires even when blob==0.
    looped = blob > 0 and score >= LOOP_THRESHOLD
    long_turn = dur_ms > TOKEN_EXPIRY_MS
    if not (looped or long_turn):
        log({'tag': tag, 'action': 'ok',
             'reason': f'delivered (loop_score={score}, blob={blob}, dur_ms={dur_ms})'})
        return 0
    fail_reason = 'long_turn' if long_turn else 'repeat_loop'

    flag = WS / 'memory' / '.tmp' / f'watchdog-brief-{today}.done'
    if flag.exists():
        log({'tag': tag, 'action': 'skip', 'reason': 'already resent (dedupe flag present)'})
        return 0

    channel, to, account = resolve_target(read_runs(job_id))
    if not to:
        log({'tag': tag, 'action': 'fail', 'reason': 'no delivery target resolved from run history'})
        return 0

    message = build_compact_fallback(today)
    sent_ok, out = send_wechat(channel, to, account, message, args.dry_run)
    log({'tag': tag, 'action': 'resend', 'dry_run': args.dry_run, 'sent_ok': sent_ok,
         'job_id': job_id, 'fail_reason': fail_reason, 'loop_score': score, 'blob': blob,
         'dur_ms': dur_ms, 'out': out})
    if sent_ok and not args.dry_run:
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text(datetime.now(HKT).isoformat())

    print(json.dumps({'tag': tag, 'loop_score': score, 'resent': sent_ok,
                      'dry_run': args.dry_run}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
