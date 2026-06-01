#!/usr/bin/env python3
"""
report_watchdog.py — LLM-free safety net for Mode 6 report crons.

WHY (2026-05-29 incident): a report cron's model stalled mid-turn and openclaw
delivered a one-line stub as the "report" with delivered=true — kcn got garbage
instead of the close briefing, even though preflight had produced a perfectly good
`raw_wechat_block`. postflight can't catch this (LLM died in Step 2, long before
postflight). So this runs OUT OF BAND (system crontab, a few min after the report
cron's expected completion) and asks: did the report actually deliver?

Detection (two independent failure signatures): reports deliver preflight's
`raw_wechat_block` verbatim, so we (a) check whether the target job's latest run
summary contains that block's first line — if not, the LLM stalled/failed; and
(b) score the session transcript for a mimo repeat-loop (transcript_loop_score) —
a high score means the delivery turn degenerated into a repeated sentence and
burned the maxTokens budget on garbage even if the block technically appears
(2026-06-01: an intraday delivery loop scored 49 vs threshold 5). Either signature
→ resend the `raw_wechat_block` directly (data only, banner-flagged auto-resend;
no LLM). Dedupe flag prevents double-sends.

(Shared run-record / target / send / log helpers live in _watchdog_common.py.)

Usage:
    report_watchdog.py --market hk --phase close --job-name "港股收盘报告"
    report_watchdog.py --market us --phase close --job-name "美股收盘报告" --dry-run

Exit 0 always (non-fatal cron); actions logged to logs/watchdog.jsonl.
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _watchdog_common import (  # noqa: E402
    WS, HKT, log, find_job_id, read_runs, today_runs, resolve_target, send_wechat,
    transcript_loop_score,
)

LOOP_THRESHOLD = 5  # transcript loop_score ≥ this ⇒ mimo repeat-loop ⇒ garbage delivery


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--market', choices=['hk', 'us'], required=True)
    ap.add_argument('--phase', choices=['open', 'mid', 'pm', 'close'], required=True)
    ap.add_argument('--job-name', required=True, help='cron job name to inspect')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    today = datetime.now(HKT).strftime('%Y-%m-%d')
    tag = f'{args.market}-{args.phase}'

    # Preflight context (with the canonical raw_wechat_block) must exist — if it
    # doesn't, preflight itself never ran; there's nothing to resend.
    ctx_path = WS / 'memory' / '.tmp' / f'report-context-{args.market}-{args.phase}-{today}.json'
    if not ctx_path.exists():
        log({'tag': tag, 'action': 'skip', 'reason': 'no preflight context (cron likely never ran)'})
        return 0
    ctx = json.loads(ctx_path.read_text())
    raw = (ctx.get('raw_wechat_block') or '').strip()
    if not raw:
        log({'tag': tag, 'action': 'skip', 'reason': 'context has no raw_wechat_block'})
        return 0
    first_line = raw.splitlines()[0]

    job_id = find_job_id(args.job_name)
    if not job_id:
        log({'tag': tag, 'action': 'skip', 'reason': f'job not found: {args.job_name}'})
        return 0

    runs = read_runs(job_id)
    runs_today = today_runs(job_id)
    last = runs_today[-1] if runs_today else {}
    last_summary = last.get('summary', '')

    # Two independent failure signatures:
    #  (a) the report block's first line never made it into the summary → LLM
    #      stalled/failed, or the cron never produced a run (delivery check);
    #  (b) the delivery turn was a mimo repeat-loop (transcript_loop_score high)
    #      that burned the maxTokens budget on one repeated sentence and shipped
    #      garbage even though the block may technically appear (loop check —
    #      see brief_watchdog; 2026-06-01 intraday stall scored 49 vs threshold 5).
    loop_score, blob = transcript_loop_score(last.get('sessionId'))
    # Delivery signal — authoritative first, brittle string-match as fallback.
    # 2026-06-01 false-positive: a healthy run where the model called the send
    # tool fine but its run-record `summary` was meta-prose ("Report sent
    # successfully. Let me provide a summary…") with no block first-line → the
    # old `first_line in last_summary` check fired `not-delivered` and resent a
    # duplicate stub. The run-record's `delivery.messageToolSentTo` records that
    # the model actually invoked the send tool (empty in the 2026-05-29 stall,
    # where core auto-delivered partial prose), so trust that; fall back to the
    # summary match only when telemetry is absent.
    sent_via_tool = bool((last.get('delivery') or {}).get('messageToolSentTo'))
    delivered = sent_via_tool or (first_line in last_summary)
    looped = loop_score >= LOOP_THRESHOLD
    if delivered and not looped:
        log({'tag': tag, 'action': 'ok',
             'reason': f'report delivered normally (loop_score={loop_score})'})
        return 0
    fail_kind = 'not-delivered' if not delivered else f'repeat-loop(score={loop_score})'

    # Resend the clean data block (data only, no LLM).
    flag = WS / 'memory' / '.tmp' / f'watchdog-{tag}-{today}.done'
    if flag.exists():
        log({'tag': tag, 'action': 'skip', 'reason': 'already resent (dedupe flag present)'})
        return 0

    channel, to, account = resolve_target(runs)
    if not to:
        log({'tag': tag, 'action': 'fail', 'reason': 'no delivery target resolved from run history'})
        return 0

    title = ctx.get('title', '').strip()
    banner = ('📨 自动补发（报告模型生成失败/中断，以下为脚本数据直送，'
              '无分析段——可在 dashboard 看完整持仓）\n\n')
    message = banner + (title + '\n\n' if title else '') + raw

    sent_ok, out = send_wechat(channel, to, account, message, args.dry_run)
    log({'tag': tag, 'action': 'resend', 'dry_run': args.dry_run, 'sent_ok': sent_ok,
         'job_id': job_id, 'fail_kind': fail_kind, 'loop_score': loop_score,
         'last_summary_head': last_summary[:80], 'out': out})
    if sent_ok and not args.dry_run:
        flag.write_text(datetime.now(HKT).isoformat())

    print(json.dumps({'tag': tag, 'fail_kind': fail_kind, 'loop_score': loop_score,
                      'resent': sent_ok, 'dry_run': args.dry_run}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
