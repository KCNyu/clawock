#!/usr/bin/env python3
"""
report_watchdog.py — LLM-free safety net for staged (Mode 6) report crons.

ROOT CAUSE this guards (2026-06-08, re-diagnosed): staged reports "没出来" on kcn's
WeChat even though the run finished status=ok with delivered=true. Same mechanism
as the intraday drop (#61174, wontfix): a staged cron used to deliver via `announce`
fired at the END of a long agent turn (preflight+LLM+postflight+dashboard ≈ 130-300s)
using a contextToken captured at turn START → Tencent expires it server-side after
~160s → silent drop, run-record `delivered` stays true. The 6-08 美股开盘报告 (133s
turn) landed delivered=true but never reached WeChat.

THE FIX (2026-06-08, mirrors the intraday decouple): report_postflight is now the
PRIMARY sender — it delivers each report via a fresh-token `openclaw message send`
(the path kcn confirmed lands) and the staged crons run --no-deliver (no announce)
→ exactly one send, no long-turn drop, no double. postflight records the REAL send
result to memory/.tmp/report-sent-{market}-{phase}-{date}.json.

This watchdog is now a pure Telegram BACKSTOP (system crontab, ~15min after the
cron): it reads that marker and mirrors the report to Telegram ONLY when the
postflight cosend is not confirmed for this slot (marker missing, tg_ok false, or
stale/mismatched) — so it never doubles a report Telegram already has.

NO WECHAT RESEND (2026-07-09, kcn's call): the watchdog used to also re-send the
report on WeChat via a fresh token. That DUPLICATED reports on WeChat whenever the
marker merely looked stale/mismatched but WeChat had actually landed — and you can't
tell a landed WeChat send from a silently-dropped one (#81096/#81316 wontfix, cold
drop still returns sent_ok=true). Since report_postflight now ALWAYS co-sends the
same body to Telegram (cold-proof, no contextToken-expiry drop), the WeChat retry
bought nothing but duplicates, so it's gone. Telegram is the sole backstop channel:
a report kcn didn't get on WeChat still reaches him on Telegram, without the dupes.

If the LLM stalls or loops after preflight, the watchdog sends the deterministic
preflight block to Telegram. WeChat remains untouched to avoid duplicate sends.

(Shared run-record / target / send helpers live in _watchdog_common.py.)

Usage:
    report_watchdog.py --market hk --phase close --job-name "港股收盘报告"
    report_watchdog.py --market us --phase open  --job-name "美股开盘报告" --dry-run

Exit 0 always (non-fatal cron); actions logged to logs/watchdog.jsonl.
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from ._watchdog_common import (
    WS, HKT, log, find_job_id, today_runs,
    transcript_loop_score, last_report_text, send_telegram, KCN_TELEGRAM,
    same_generation_window,
)

LOOP_THRESHOLD = 5                 # transcript loop_score ≥ this ⇒ mimo repeat-loop ⇒ garbage
MARKER_FRESH_MS = 120 * 60 * 1000  # postflight send-marker older than this ⇒ treat as not-this-slot
REGEN_WINDOW_S = 30 * 60           # context rebuilt within this of the delivered one ⇒ same slot
REGEN_BACKWARD_S = 60              # tolerance for a context timestamped just before the marker's


def deterministic_fallback(raw_block, tag, reason):
    """Pure formatter used by the watchdog and regression tests."""
    return (f'🧯 {tag} 确定性兜底（LLM {reason}）\n'
            '以下内容由 preflight 数据直接生成，未经过模型改写：\n\n'
            + raw_block.strip())


def _same_generation_window(marker, ctx_generated_at):
    """This mode's window on the shared rule — see `same_generation_window`.

    Both 2026-08-03 HK false backstops were exactly the retry case: delivered at
    13:31 from a 13:30 context, watchdog at 13:42 reading the retry's 13:32:59
    context. Report phases sit hours apart, so a 30-minute window cannot reach
    the previous phase.
    """
    return same_generation_window(
        marker, ctx_generated_at,
        window_s=REGEN_WINDOW_S, backward_s=REGEN_BACKWARD_S)


def slot_delivered(marker, ctx_id, raw_block_first, now_ms, ctx_generated_at=None):
    """Did report_postflight confirmably deliver THIS slot's report to Telegram?

    Doubles as the generation gate: in prose mode the model's final answer is a
    postflight status line, not the report, so the transcript no longer contains
    the data block and `raw_block_first in summary` would read as "never ran" on
    every healthy run — firing a deterministic fallback that duplicates a report
    kcn already has.

    Slot identity prefers `context_id` (exact, written by prose mode), then the
    regeneration window when the ids differ because the cron retried, then — only
    for markers predating both fields — the legacy first-line compare. Prose-mode
    bodies start with the TITLE, so that legacy compare reports a false mismatch
    on every healthy prose run and cannot be the primary judge.

    Returns (delivered, judge) — the judge names which rule decided, so the log
    can show why no backstop fired instead of leaving that to a second,
    drift-prone recomputation at the call site.
    """
    if not marker or not marker.get('tg_ok'):
        return False, 'no-marker'
    # An exact context_id match is proof this slot was delivered regardless of age:
    # both ids are per market+phase+date, so a delayed watchdog must NOT re-mirror a
    # confirmed delivery just because the marker is >2h old (2026-07-24 review). The
    # freshness window only guards the fuzzy legacy first-line compare, where a
    # matching first line could otherwise belong to an earlier day's report.
    if marker.get('context_id') and ctx_id:
        if marker['context_id'] == ctx_id:
            return True, 'context_id'
        # Ids differ. That is the normal shape of a cron retry, not of a miss —
        # see _same_generation_window. Markers written before that field existed
        # fall through to the legacy compare below rather than to a false miss.
        if marker.get('context_generated_at'):
            return _same_generation_window(marker, ctx_generated_at), 'regenerated-context'
    if now_ms - (marker.get('ts') or 0) >= MARKER_FRESH_MS:
        return False, 'marker-stale'
    same_line = (marker.get('first_line') or '').strip() == (raw_block_first or '').strip()
    return same_line, 'legacy-first-line'


def wechat_gap_reason(claim):
    """#544: name a holder-died-mid-send WeChat gap explicitly.

    A sender killed between the WeChat send and the Telegram cosend leaves a
    claim with `send_started_at` set and no completion marker — the one case
    where "WeChat delivery unconfirmed" is a fact, not a guess. The Telegram
    backstop must say that out loud instead of reading like a normal mirror.
    Returns (reason, banner) or None when the claim does not show the gap.
    """
    if isinstance(claim, dict) and claim.get('send_started_at'):
        return ('holder-died-mid-send',
                '⚠️ 该槽位 WeChat 送达未被确认：postflight 发送进程在发送中途死亡'
                '（claim 带 send_started_at、无完成 marker）。'
                '仅 Telegram 兜底一份，请留意微信是否已收到。\n\n')
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--market', choices=['hk', 'us'], required=True)
    ap.add_argument('--phase', choices=['open', 'mid', 'pm', 'close'], required=True)
    ap.add_argument('--job-name', required=True, help='cron job name to inspect')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    today = datetime.now(HKT).strftime('%Y-%m-%d')
    tag = f'{args.market}-{args.phase}'

    job_id = find_job_id(args.job_name)
    if not job_id:
        log({'tag': tag, 'action': 'skip', 'reason': f'job not found: {args.job_name}'})
        return 0

    runs_today = today_runs(job_id)
    if not runs_today:
        log({'tag': tag, 'action': 'skip', 'reason': 'no run today yet (cron likely never fired)'})
        return 0
    last = runs_today[-1]
    run_at = last.get('runAtMs')
    session_id = last.get('sessionId')
    summary = last.get('summary', '')

    # Dedupe per slot (one re-send per run, keyed by runAtMs).
    flag = WS / 'memory' / '.tmp' / f'watchdog-{tag}-{run_at}.done'
    if flag.exists():
        log({'tag': tag, 'action': 'skip', 'reason': 'already handled this slot (dedupe flag)'})
        return 0

    # --- Generation gate: generated report or deterministic fallback ----------
    # The clean report block's first line comes from the preflight context. If the
    # context is missing, preflight never ran → nothing to resend.
    ctx_path = WS / 'memory' / '.tmp' / f'report-context-{args.market}-{args.phase}-{today}.json'
    # One read, one generation: a cron retry rewrites this file mid-flight, so
    # re-reading it per field could mix two generations' block and id.
    ctx = {}
    try:
        ctx = json.loads(ctx_path.read_text())
    except Exception:
        ctx = {}
    raw_block = (ctx.get('raw_wechat_block') or '').strip()
    raw_block_first = raw_block.splitlines()[0] if raw_block else None
    if not raw_block_first:
        log({'tag': tag, 'action': 'skip', 'reason': 'no preflight raw_wechat_block (cron likely never ran)'})
        return 0

    ctx_id = ctx.get('context_id')

    marker_path = WS / 'memory' / '.tmp' / f'report-sent-{args.market}-{args.phase}-{today}.json'
    marker = None
    if marker_path.exists():
        try:
            marker = json.loads(marker_path.read_text())
        except Exception:
            marker = None
    now_ms = int(datetime.now(HKT).timestamp() * 1000)
    delivered_this_slot, delivery_judge = slot_delivered(
        marker, ctx_id, raw_block_first, now_ms,
        ctx_generated_at=ctx.get('generated_at'))

    # --- Generation gate ------------------------------------------------------
    # In prose mode the model's final answer is a postflight status line, not the
    # report, so the transcript no longer contains the data block. A confirmed
    # delivery for this slot IS the proof of generation — check it first, or the
    # deterministic fallback fires on every healthy prose run.
    if delivered_this_slot:
        log({'tag': tag, 'action': 'ok',
             'reason': 'postflight cosend already delivered Telegram this slot — no backstop',
             # Which rule accepted it. `regenerated-context` recurring here means
             # the cron keeps retrying — visible instead of inferred.
             'match': delivery_judge,
             'run_at': run_at})
        return 0

    # Extract the real report from the transcript BEFORE the generation gate: the
    # run summary can omit the data block while the actual report sits in the last
    # assistant turn (long runs truncate the summary). Treating "not in summary" as
    # "never generated" would fire the deterministic fallback and drop a report kcn
    # could have received in full (2026-07-24 review). Either source counts.
    report = last_report_text(session_id, raw_block_first)
    block_present = (raw_block_first in summary) or bool(report)
    loop_score, _ = transcript_loop_score(session_id)
    looped = loop_score >= LOOP_THRESHOLD
    if not block_present or looped:
        reason = '循环' if looped else '未完成'
        body = deterministic_fallback(raw_block, tag, reason)
        tg_ok, tg_out = send_telegram(KCN_TELEGRAM, body, args.dry_run)
        log({'tag': tag, 'action': 'deterministic-fallback', 'sent_ok': tg_ok,
             'block_present': block_present, 'loop_score': loop_score, 'run_at': run_at,
             'target': KCN_TELEGRAM, 'out': tg_out})
        if tg_ok and not args.dry_run:
            flag.write_text(datetime.now(HKT).isoformat())
        print(json.dumps({'tag': tag, 'deterministic_fallback': tg_ok,
                          'dry_run': args.dry_run}, ensure_ascii=False))
        return 0

    # --- Delivery backstop: Telegram only (no WeChat resend) ------------------
    # WHY NO WECHAT RESEND ANYMORE (2026-07-09, kcn's call): a watchdog WeChat
    # resend DUPLICATED the report on WeChat whenever the postflight marker merely
    # looked stale/mismatched but WeChat had actually landed — and you can't tell a
    # landed WeChat send from a silently-dropped one (#81096/#81316 wontfix, cold
    # drop still returns sent_ok=true). Now that report_postflight ALWAYS co-sends
    # the same body to Telegram (the cold-proof channel, no contextToken drop), the
    # WeChat retry buys nothing but duplicates. So the watchdog's SOLE job is to
    # guarantee Telegram has this report — never touch WeChat.
    # Not delivered this slot (checked above) ⇒ postflight's cosend never ran,
    # failed, or the marker belongs to a different generation → mirror it now.
    # `report` was already extracted from the transcript above.
    if not report and raw_block_first in summary:
        # Legacy mode: the run summary holds the full report after the "---" checklist.
        report = summary.split('\n---\n', 1)[1].strip() if '\n---\n' in summary else summary.strip()
    if not report:
        # Prose mode: the transcript holds a postflight status line, not a report —
        # mirroring `summary` would send kcn a JSON blob. Rebuild from the context
        # instead; the data block is the part a backstop actually owes him.
        report = deterministic_fallback(raw_block, tag, '报告文本不在会话里')

    reason = ('postflight marker missing' if not marker
              else 'postflight cosend failed' if not marker.get('tg_ok')
              else 'marker stale/mismatch')
    # #544: with no marker, a claim whose holder died mid-send is the explicit
    # "WeChat delivery unconfirmed" case — say it instead of silently mirroring.
    claim_path = WS / 'memory' / '.tmp' / \
        f'report-send-{args.market}-{args.phase}-{today}.claim'
    claim = None
    try:
        if claim_path.exists():
            claim = json.loads(claim_path.read_text())
    except Exception:
        claim = None
    gap = wechat_gap_reason(claim) if not marker else None
    if gap:
        reason = gap[0]
        tg_banner = gap[1]
    else:
        tg_banner = f'📨 自动补发（{reason}，Telegram 兜底一份）\n\n'
    tg_ok, tg_out = send_telegram(KCN_TELEGRAM, tg_banner + report.strip(), args.dry_run)
    log({'tag': tag, 'action': 'mirror-telegram', 'dry_run': args.dry_run, 'sent_ok': tg_ok,
         'job_id': job_id, 'reason': reason, 'loop_score': loop_score,
         'run_at': run_at, 'target': KCN_TELEGRAM, 'out': tg_out})

    # Slot handled once Telegram landed — don't keep retrying a report kcn has.
    if tg_ok and not args.dry_run:
        flag.write_text(datetime.now(HKT).isoformat())

    print(json.dumps({'tag': tag, 'reason': reason, 'mirrored_telegram': tg_ok,
                      'dry_run': args.dry_run}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
