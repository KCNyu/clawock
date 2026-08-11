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
import os
import sys
from datetime import datetime
from pathlib import Path

from ._watchdog_common import (
    WS, HKT, log, build_brief_card, send_telegram, KCN_TELEGRAM,
    dispatch_brief_fallback, await_brief_fallback_outcome,
)

MARKER_FRESH_MS = 30 * 60 * 1000  # postflight send-marker older than this ⇒ not this slot
MISSING_STATE_VERSION = 1
NOTIFICATION_ATTEMPTS_PER_RUN = 2


def inspect_brief_artifacts(today):
    """Return concrete 09:05 artifact failures; an empty list means usable.

    Current plans are v2 and store action records under ``decisions``.  The
    legacy ``actions`` spelling is accepted here only so the miss detector can
    describe old artifacts accurately; postflight remains the schema authority.
    """
    brief_path = WS / 'memory' / f'{today}-pre-open.md'
    plan_path = WS / 'memory' / f'{today}-plan.json'
    issues = []
    if not brief_path.exists():
        issues.append('brief_missing')
    if not plan_path.exists():
        issues.append('plan_missing')
        return issues
    try:
        plan = json.loads(plan_path.read_text())
    except Exception:
        issues.append('plan_invalid')
        return issues
    actions = plan.get('decisions')
    if actions is None:
        actions = plan.get('actions')
    if (not isinstance(actions, list) or not actions
            or not all(isinstance(row, dict) and row.get('action') for row in actions)):
        issues.append('plan_invalid')
    return issues


def missing_state_path(today):
    return WS / 'memory' / '.tmp' / f'watchdog-brief-missing-{today}.json'


def load_missing_state(today):
    """Load durable 09:05 recovery state without risking a duplicate dispatch."""
    path = missing_state_path(today)
    base = {
        'schema_version': MISSING_STATE_VERSION,
        'date': today,
        'issues': [],
        'fallback_dispatch_attempted': False,
        'fallback_dispatch_succeeded': False,
        'dispatch_attempted_at': None,
        'dispatch_out': None,
        'notification_attempts': 0,
        'notification_succeeded': False,
        'notification_last_attempt_at': None,
        'notification_out': None,
    }
    if not path.exists():
        return base
    try:
        stored = json.loads(path.read_text())
        if not isinstance(stored, dict) or stored.get('schema_version') != MISSING_STATE_VERSION:
            raise ValueError('unsupported recovery-state schema')
        return {**base, **stored}
    except Exception as e:
        # The dispatch may already have happened before a torn/corrupt state was
        # observed. Fail safe against firing a second off-host workflow; the
        # notification remains retryable and reports the corrupt state.
        return {
            **base,
            'fallback_dispatch_attempted': True,
            'state_error': f'{type(e).__name__}: {e}',
        }


def write_missing_state(today, state):
    """Atomically persist recovery state before notification is attempted."""
    path = missing_state_path(today)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f'.{path.name}.{os.getpid()}.tmp')
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(path)


def alert_brief_missing(today, dry_run, issues=None):
    """09:05 HKT: landing artifacts are incomplete ⇒ page kcn + self-heal.

    Dispatch has to happen before 10:00 HKT — brief-fallback.yml refuses to generate a
    pre-open brief after HK open. That is why this pass runs at 09:05 and not later.
    We alert even when the dispatch succeeds: the fallback is a single-turn vendor call
    that can itself fail, so kcn should know the 08:00 swarm missed regardless."""
    issues = issues if issues is not None else inspect_brief_artifacts(today)
    if not issues:
        return 0
    flag = WS / 'memory' / '.tmp' / f'watchdog-brief-missing-{today}.done'
    if flag.exists():
        log({'tag': 'brief', 'action': 'skip', 'reason': 'brief-missing already handled today'})
        return 0

    state = load_missing_state(today)
    if state.get('notification_succeeded'):
        log({'tag': 'brief', 'action': 'skip',
             'reason': 'brief-missing notification already succeeded today',
             'recovery_state': state})
        return 0

    state['issues'] = list(issues)
    if not state.get('fallback_dispatch_attempted'):
        dispatched, out = dispatch_brief_fallback(dry_run)
        state.update({
            'fallback_dispatch_attempted': True,
            'fallback_dispatch_succeeded': bool(dispatched),
            'dispatch_attempted_at': datetime.now(HKT).isoformat(),
            'dispatch_out': out,
        })
        # This ordering is the core invariant: a Telegram timeout must never
        # erase the fact that the off-host fallback was already fired.
        if not dry_run:
            write_missing_state(today, state)
    else:
        dispatched = bool(state.get('fallback_dispatch_succeeded'))
        out = state.get('dispatch_out') or '(prior dispatch attempt; outcome unavailable)'

    labels = {
        'brief_missing': f'brief 缺失：memory/{today}-pre-open.md 不存在',
        'plan_missing': f'plan 缺失：memory/{today}-plan.json 不存在',
        'plan_invalid': f'plan 无效：memory/{today}-plan.json 无法解析或没有非空动作数组',
    }
    issue_text = '\n'.join(f'- {labels[x]}' for x in issues)
    alert = (
        f'🔴 盘前深度简报产物不完整 — {today}\n\n'
        f'09:05 检查结果：\n{issue_text}\n\n'
        + ('🔄 已 dispatch off-host 兜底 (brief-fallback.yml)，正在等待运行结果，稍后另发一条。\n'
           if dispatched else
           '⚠️ 自动 dispatch 兜底失败，需要手动：gh workflow run brief-fallback.yml\n'
           '（10:00 HKT 前有效，之后 workflow 会判定过期跳过）\n')
        + f'\n查因：openclaw cron runs --id $(openclaw cron list | grep 盘前深度简报) '
          f'/ sar -q 看 08:00 起的 blocked'
    )

    tg_ok, tg_out = False, ''
    for _ in range(NOTIFICATION_ATTEMPTS_PER_RUN):
        try:
            tg_ok, tg_out = send_telegram(KCN_TELEGRAM, alert, dry_run)
        except Exception as e:
            tg_ok, tg_out = False, f'{type(e).__name__}: {e}'[:300]
        state['notification_attempts'] = int(state.get('notification_attempts') or 0) + 1
        state['notification_succeeded'] = bool(tg_ok)
        state['notification_last_attempt_at'] = datetime.now(HKT).isoformat()
        state['notification_out'] = tg_out
        if not dry_run:
            write_missing_state(today, state)
        if tg_ok:
            break

    log({'tag': 'brief', 'action': 'alert-brief-missing', 'dry_run': dry_run,
         'issues': issues,
         'dispatched_fallback': dispatched, 'dispatch_out': out,
         'sent_ok': tg_ok, 'target': KCN_TELEGRAM, 'out': tg_out,
         'recovery_state': state})
    if tg_ok and not dry_run:
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text(datetime.now(HKT).isoformat())

    # The miss alert above is deliberately sent before the run finishes, so kcn learns
    # at 09:05 that 08:00 missed. Only now do we find out whether the recovery actually
    # worked — reporting that is the whole point (2026-08-11: dispatch accepted, run
    # failed 8min later, and the last thing kcn heard was a green check).
    outcome, outcome_detail = 'not-dispatched', ''
    if dispatched:
        outcome, outcome_detail = await_brief_fallback_outcome(
            state.get('dispatch_attempted_at') or datetime.now(HKT).isoformat(),
            dry_run)
        state['fallback_outcome'] = outcome
        state['fallback_outcome_detail'] = outcome_detail
        if not dry_run:
            write_missing_state(today, state)
        follow_up = _fallback_outcome_message(today, outcome, outcome_detail)
        try:
            follow_ok, follow_out = send_telegram(KCN_TELEGRAM, follow_up, dry_run)
        except Exception as e:
            follow_ok, follow_out = False, f'{type(e).__name__}: {e}'[:300]
        log({'tag': 'brief', 'action': 'fallback-outcome', 'dry_run': dry_run,
             'outcome': outcome, 'detail': outcome_detail,
             'sent_ok': follow_ok, 'target': KCN_TELEGRAM, 'out': follow_out})

    print(json.dumps({'tag': 'brief', 'reason': 'brief artifacts incomplete',
                      'issues': issues,
                      'dispatched_fallback': dispatched, 'alerted_telegram': tg_ok,
                      'fallback_outcome': outcome,
                      'dry_run': dry_run}, ensure_ascii=False))
    return 0


def _fallback_outcome_message(today, outcome, detail):
    """Telegram follow-up naming what the off-host fallback actually did.

    Only 'success' claims the brief exists, and it says so because the run concluded
    success — every other state is reported as unresolved with the manual next step."""
    if outcome == 'success':
        return (f'✅ off-host 兜底已完成 — {today}\n\n'
                f'{detail}\n\n'
                f'pre-open.md + plan.json 已由 workflow 生成并 push。')
    if outcome == 'failure':
        return (f'🔴 off-host 兜底失败 — {today}\n\n'
                f'{detail}\n\n'
                f'今天两条路径都没产出简报，没有自动补救了。\n'
                f'手动：gh run rerun <id> 或 gh workflow run brief-fallback.yml'
                f'（10:00 HKT 前有效）')
    return (f'⚠️ off-host 兜底结果未确认 — {today}\n\n'
            f'{detail}\n\n'
            f'注意：这不代表成功。请查 '
            f'gh run list --workflow=brief-fallback.yml')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--check-missing', action='store_true',
                    help='09:05 miss-detector mode (see module docstring)')
    args = ap.parse_args()

    today = datetime.now(HKT).strftime('%Y-%m-%d')
    tag = 'brief'

    if args.check_missing:
        issues = inspect_brief_artifacts(today)
        if issues:
            return alert_brief_missing(today, args.dry_run, issues)
        log({'tag': tag, 'action': 'ok',
             'reason': '09:05 brief and non-empty valid plan both present'})
        return 0

    # No brief on disk. There is no card to mirror either way — what differs is whether
    # we can yet call it a miss. At 08:30 we are inside the landing window (08:13-08:49
    # observed) so silence is correct; at 09:05 the window has closed, so it is a miss.
    if not (WS / 'memory' / f'{today}-pre-open.md').exists():
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
