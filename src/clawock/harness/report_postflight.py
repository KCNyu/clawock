#!/usr/bin/env python3
"""
report_postflight.py — Mode 6 (briefing) harness postflight.

Assembles, validates and publishes the Mode 6 briefing.

Two input modes:
  prose  (--context-id ID --text-file PATH)  the model supplies ONLY the analysis
         sections; this script prepends ctx['title'] + ctx['raw_wechat_block'].
         ID must equal the context's `context_id` or the run is rejected.
  legacy (no --context-id)                   the model supplies the whole report
         including its own copy of the data block, which is then verbatim-checked.
         Kept so a master deploy that lands before the cron payloads are updated
         still delivers; remove once every payload passes --context-id.

Validates (on the assembled message):
  1. ▎情绪面 / ▎技术面 / ▎操作建议 三段标记齐全
  2. 若 preflight needs_risk_section=true, 必须有 ▎风险提示 段
  3. 总长度闸 clawock.harness.validation.REPORT_CHAR_LIMITS（防复读死循环，不是写作目标；#334）
  4. legacy only: 必须以 raw_wechat_block 开头（prose 模式由本脚本拼，无需校验）
  5. 如果 preflight 有 anomalies，报告必须提到至少一个 anomaly 票
  6. 没有"等待数据/数据待获取"等敷衍词

Delivery is fail-closed (2026-07-24): pass/warn send the full body; fail sends
the data block ALONE — never the rejected prose. Deterministic data publication
is independent of that narrative decision, so every usable context can refresh
the dashboard and commit. A closed market or a missing context sends/publishes
nothing. A slot whose only delivery was a fail-closed data block may be
superseded exactly once by a validated report (see claim_upgrade).

Outputs JSON to stdout:
  {"status": "pass|warn|fail", "mode": "prose|legacy", "issues": [...], ...}
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from clawock.workspace import workspace_root
from clawock import sessions as trading_calendar

WS = workspace_root(Path.cwd())
_CHECKOUT = WS
TMP = WS / 'memory' / '.tmp'

from clawock.automation import workflow_outcomes  # noqa: E402

# The deterministic report core moved into the installed package so `clawock
# report` can run it without a repository checkout. Re-exported here so this
# module's own regression suite keeps exercising exactly that code.
#
# Only what this module uses. The four names it merely re-exported
# (CRITICAL_KEYWORDS, FORBIDDEN_PHRASES, REQUIRED_SECTIONS, _is_hard_char_limit)
# retired with #267: nothing outside imported them through here, so they were an
# indirection with no consumer.
from clawock.harness.report import (  # noqa: E402
    MIN_REPORT_CHARS,
    _unusable_context,
    assemble_message,
    categorize,
    validate,
)

# Report slots are hours apart (open/mid/pm/close), so a prose file older than
# this is the previous slot's, not this one's. See read_prose_text.
PROSE_MAX_AGE_MIN = 30

def load_context(market, phase, date):
    path = TMP / f'report-context-{market}-{phase}-{date}.json'
    if not path.exists():
        return None, f'preflight context 不存在: {path.name}'
    try:
        return json.loads(path.read_text()), None
    except Exception as e:
        return None, f'preflight context 解析失败: {e}'




from clawock.harness.validation import (
    REPORT_CHAR_LIMITS as CHAR_LIMITS,
    advisory_prefix,
    categorize_issues,
    check_numeric_claims,
    check_raw_tables_verbatim,
    split_advisory,
    validate_forbidden_phrases,
)
from ._harness_common import (  # noqa: E402
    dashboard_publication_state,
    git_cmd as _git,
    push_with_rebase_retry,
    rebuild_dashboard,
    snapshot_date_for_now,
)
from ._watchdog_common import (  # noqa: E402
    resolve_wechat_target, send_wechat, cosend_telegram, already_delivered,
    claim_send, mark_send_started, release_claim, log,
)


def read_prose_text(market, phase, text_file):
    """Return (text, input_error). Plumbing failures never reach validate().

    The prose-mode move to --text-file buys us out of heredoc quoting (the report
    is full of emoji, `$` and `|` table pipes), but it opens the failure PR #22
    hit on intraday: the model forgets to rewrite the file and postflight happily
    republishes the previous slot's prose. `context_id` does NOT catch that — the
    model passes the CURRENT id on the command line while the file holds old text.
    So the file's own mtime is the gate. Report slots are hours apart, so 30
    minutes is generous and still far below the gap to the previous slot.
    """
    hint = (f'Step 2 应先把散文写入 memory/.tmp/report-prose-{market}-{phase}.md，'
            f'再用 --text-file 调用 postflight')
    if not text_file:
        text = sys.stdin.read()
        return (text, None) if text.strip() else ('', f'空输入 (stdin) — {hint}')

    path = Path(text_file)
    if not path.exists():
        return '', f'散文文件不存在: {path} — {hint}'
    age_min = (datetime.now().timestamp() - path.stat().st_mtime) / 60
    if age_min > PROSE_MAX_AGE_MIN:
        return '', (f'散文文件 {path.name} 已 {age_min:.0f} 分钟未更新 '
                    f'(> {PROSE_MAX_AGE_MIN} 分钟上限) — 疑似上一个 slot 的旧文本，'
                    f'拒绝投递；{hint}')
    text = path.read_text()
    if not text.strip():
        return '', f'空输入 (--text-file {path.name}) — {hint}'
    return text, None


def _marker_state(marker_path):
    """'delivered' | 'failed' | None. Markers written before this field existed
    are treated as full deliveries — the conservative read, since assuming
    'failed' would let an old marker unlock a re-send."""
    try:
        return json.loads(Path(marker_path).read_text()).get('delivery_state', 'delivered')
    except Exception:
        return None


def claim_upgrade(market, phase, date):
    """Atomically claim the one allowed failed→delivered re-send. True = it's ours.

    Fail-closed means a rejected report is delivered as the data block alone. If
    the model then fixes its prose, that corrected report MUST be able to reach
    kcn — otherwise fail-closed is strictly worse than 2026-07-24, where at least
    the numbers were eventually right on disk. But an unlimited re-send window
    reopens the 2026-06-03 duplicate-send class, and openclaw's auto-retry of a
    run can fire the same postflight several times.

    O_EXCL create is the whole lock: the first caller to create the claim file
    wins and sends, every later one loses and skips. One upgrade, no counting, no
    read-then-write race between concurrent retries.
    """
    claim = TMP / f'report-upgrade-{market}-{phase}-{date}.claim'
    try:
        fd = os.open(claim, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    except OSError as e:
        print(f'warn: upgrade claim failed ({e}) — not re-sending', file=sys.stderr)
        return False
    with os.fdopen(fd, 'w') as f:
        f.write(datetime.now().isoformat(timespec='seconds'))
    return True


def deliver_wechat(market, phase, date, wechat_prefix, text, delivery_state='delivered',
                   context_id=None, context_generated_at=None, claim_path=None):
    """Primary WeChat send for staged reports — fresh-token `openclaw message send`,
    decoupled from the cron's announce.

    WHY (2026-06-08): a staged report's cron `announce` fires at the END of a long
    agent turn (preflight+LLM+postflight+dashboard ≈ 130-300s) using a contextToken
    captured at turn START; Tencent expires it server-side after ~160s (#61174) →
    silent drop, run-record `delivered` still true. The 6-08 美股开盘报告 (133s turn)
    landed delivered=true but never reached kcn's WeChat. Mirroring the intraday fix:
    we send HERE in a short-lived fresh-token call (the path kcn confirmed lands),
    the staged crons run --no-deliver so this is the SOLE send (no double), and we
    record the real result to a marker so report_watchdog only re-sends on a
    CONFIRMED failure (never doubles a report that went out here).

    Returns (sent_ok, out). Writes marker report-sent-{market}-{phase}-{date}.json.

    The marker's `first_line` records the first line of the report body WE
    ACTUALLY SENT — not the block the context expected. report_watchdog compares
    it against the fresh context's `raw_wechat_block` first line to decide whether
    Telegram already has *this* report; recording the expected line made that
    comparison tautological, so a body built from a stale context still looked
    delivered (2026-07-24 美股收盘报告: WeChat got 07/22 numbers and no backstop
    ever fired). Deriving it from `text` makes the mismatch detectable.
    """
    message = (wechat_prefix + text).strip()
    body_lines = text.strip().splitlines()
    sent_first = body_lines[0].strip() if body_lines else ''
    # Flip the claim to "in flight" BEFORE the send, so a process killed between
    # here and the marker write (the 2026-08-13 duplicate, #508) is readable as
    # "may already have reached WeChat" by whoever claims next.
    if claim_path is not None:
        mark_send_started(claim_path)
    try:
        channel, to, account = resolve_wechat_target(market)
        sent_ok, out = send_wechat(channel, to, account, message, dry_run=False)
    except Exception as e:
        sent_ok, out = False, str(e)[:300]
    # Always co-send to Telegram — WeChat can't confirm real delivery (cold drop
    # returns sent_ok=true), so we don't gate on it. See cosend_telegram docstring.
    # Record the Telegram result too: it's the cold-proof channel and the ONLY
    # backstop report_watchdog now uses (it no longer re-sends WeChat), so the
    # watchdog needs to know whether THIS report already reached Telegram.
    tg_ok, _tg_out = cosend_telegram(message, f'{market}-{phase}')
    marker = TMP / f'report-sent-{market}-{phase}-{date}.json'
    try:
        marker.write_text(json.dumps({
            'ts': int(datetime.now().timestamp() * 1000),
            'sent_ok': bool(sent_ok),
            'tg_ok': bool(tg_ok),
            'first_line': sent_first,
            'delivery_state': delivery_state,
            # Exact slot identity for report_watchdog. In prose mode the sent body
            # starts with the title, so first_line no longer matches the context's
            # block and a string compare would mirror a duplicate to Telegram.
            'context_id': context_id,
            # When the id alone can't decide, this dates the DATA we sent, not the
            # send. `context_id` is strictly per-preflight-invocation, so an
            # openclaw auto-retry (which re-runs preflight but is blocked from
            # re-sending by the idempotency lock above) leaves the marker pointing
            # at a generation the context file no longer holds — an id compare then
            # reads a healthy delivery as "never delivered" (2026-08-03 hk-open +
            # hk-pm, both double-sent a deterministic fallback). The watchdog needs
            # to tell that two-minute regeneration apart from the genuinely stale
            # body of 2026-07-24, and only the source context's own timestamp can.
            'context_generated_at': context_generated_at,
            'market': market,
            'phase': phase,
            'out': (out or '')[-200:],
        }, ensure_ascii=False))
    except Exception as e:
        print(f'warn: report send marker write failed: {e}', file=sys.stderr)
    # This send ran to completion, so the marker now owns the idempotency question
    # and the claim has nothing left to arbitrate. Releasing it keeps "a claim
    # exists" meaning "a sender died holding it".
    if claim_path is not None:
        release_claim(claim_path)
    if not sent_ok:
        print(f'warn: WeChat send failed (watchdog will retry): {(out or "")[:200]}', file=sys.stderr)
    return sent_ok, out


def maybe_commit(status, commit_msg):
    rebuild_ok, _ = rebuild_dashboard()
    publication_state = dashboard_publication_state(WS)
    suffix = {
        'warn': ' (validation warnings)',
        'fail': ' (data only; prose rejected)',
    }.get(status, '')
    snap_date = snapshot_date_for_now()
    # logs/dashboard_build_status.json rides along: its only scheduled reader is
    # the GHA cron-health runner (fresh checkout), so it must reach origin.
    # The four dashboard outputs are NOT staged: #314 took them out of the
    # repository, and `git add` on a gitignored path FAILS rather than skipping
    # — which would abort this commit and take portfolio.json and the snapshot
    # down with it. The rebuild above still refreshes them in the worktree; the
    # scheduled publisher puts them on the data branch within 20 minutes.
    add_args = ['add', 'portfolio.json',
                'logs/dashboard_build_status.json']
    if snap_date:
        add_args.append(f'memory/snapshots/{snap_date}.json')
    ok, _ = _git(*add_args)
    if not ok:
        return False, 'git add failed'
    commit_paths = add_args[1:]
    ok, out = _git('commit', '-m', f'{commit_msg}{suffix}', '--', *commit_paths)
    if not ok and 'nothing to commit' in out:
        return True, f'nothing to commit (idempotent; dashboard={publication_state})'
    if not ok:
        return False, out[-200:]

    # Push so Pages updates; rebase+retry handles races with GH Action commits
    push_ok, push_out = push_with_rebase_retry()
    if push_ok:
        if rebuild_ok:
            return True, 'committed + pushed'
        return True, f'committed + pushed (dashboard={publication_state})'
    return True, (f'committed (push failed: {push_out[-150:]}; '
                  f'dashboard={publication_state})')


def classify_data_plane(commit_ok, commit_msg):
    """Return an explicit publication state independent of prose validation."""
    if not commit_ok:
        return 'failed'
    if 'dashboard=publish_failed' in commit_msg:
        return 'publish_failed'
    if 'dashboard=rebuild_failed' in commit_msg:
        return 'rebuild_failed'
    if 'dashboard=unavailable' in commit_msg:
        return 'unavailable'
    if 'push failed' in commit_msg:
        return 'committed_local'
    if 'nothing to commit' in commit_msg:
        return 'current'
    return 'published'


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--market', choices=['hk', 'us'], required=True)
    parser.add_argument('--phase', choices=['open', 'mid', 'pm', 'close'], required=True)
    parser.add_argument('--text-file', help='briefing text file (default: stdin)')
    parser.add_argument('--context-id',
                        help='context_id echoed from preflight. Its presence selects '
                             'prose mode: the input is the analysis sections only and '
                             'this script prepends title + raw_wechat_block itself. '
                             'Omit for the legacy full-report input.')
    args = parser.parse_args(argv)
    job_name = workflow_outcomes.job_for(args.market, args.phase)
    slot = workflow_outcomes.slot_for_job(job_name)

    # Holiday/weekend gate: never send/commit on a closed market — even if the
    # model produced a report off stale data. Mirrors the preflight gate.
    session = trading_calendar.phase_session(args.market, args.phase)
    closed = trading_calendar.closed_reason(args.market, session=session)
    if closed:
        workflow_outcomes.record_stage(
            job_name, 'preflight', 'skipped', slot=slot, reason=closed
        )
        market_cn = '港股' if args.market == 'hk' else '美股'
        result = {'status': 'market_closed', 'market': args.market, 'phase': args.phase,
                  'reason': closed, 'wechat_sent': False, 'commit_ok': False,
                  'wechat_prefix': '', 'issues': [f'{market_cn}{closed}，跳过投递+commit']}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    text, in_err = read_prose_text(args.market, args.phase, args.text_file)
    if in_err:
        workflow_outcomes.record_stage(
            job_name, 'llm', 'failed', slot=slot, reason=in_err
        )
        workflow_outcomes.record_stage(
            job_name, 'postflight', 'failed', slot=slot, reason='input_error'
        )
        # Classified apart from `fail`: this is a broken caller, not a bad report.
        # Nothing is sent — a stale or missing file must never be republished —
        # and the non-zero exit keeps the run record honest (a false green here is
        # worse than a false red: it would hide a silently skipped report).
        print(f'error: {in_err}', file=sys.stderr)
        result = {
            'status': 'input_error', 'market': args.market, 'phase': args.phase,
            'issues': [in_err], 'wechat_prefix': '', 'wechat_sent': False,
            'commit_ok': False, 'commit_msg': 'skipped (input error)', 'n_chars': 0,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    today = datetime.now().strftime('%Y-%m-%d')
    ctx, ctx_err = load_context(args.market, args.phase, today)
    prose_only = args.context_id is not None

    # A missing OR unusable context both mean "preflight did not produce data to
    # assemble". preflight writes a blockless sentinel on a fetch failure
    # (status=preflight_failed / market_closed) with no raw_wechat_block, title,
    # commit_msg or context_id; assembling against it would send a banner-only
    # message and then crash on ctx['commit_msg']. Reject before any send/commit,
    # non-zero, so the run record shows preflight is the breakage. (2026-07-24 review.)
    ctx_bad = ctx_err or _unusable_context(ctx, prose_only)
    if ctx_bad:
        workflow_outcomes.record_stage(
            job_name, 'preflight', 'failed', slot=slot, reason=ctx_bad
        )
        workflow_outcomes.record_stage(
            job_name, 'postflight', 'failed', slot=slot, reason='unusable_context'
        )
        result = {
            'status': 'preflight_error',
            'market': args.market, 'phase': args.phase, 'date': today,
            'issues': [ctx_bad],
            'wechat_prefix': '', 'wechat_sent': False,
            'commit_ok': False, 'commit_msg': 'skipped (no usable preflight context)',
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    # Degenerate/empty input = broken pipe. Legacy input is a whole report so the
    # 50-字 floor is a real broken-pipe signal there; prose is a few sections and
    # a terse-but-valid one can sit under 50 chars, so read_prose_text's own
    # empty/missing/stale gate already covers the prose plumbing failure. Apply
    # the char floor to legacy input only. (2026-07-24 review.)
    if not prose_only and len(text.strip()) < MIN_REPORT_CHARS:
        workflow_outcomes.record_stage(
            job_name, 'llm', 'failed', slot=slot, reason='degenerate_input'
        )
        workflow_outcomes.record_stage(
            job_name, 'postflight', 'failed', slot=slot, reason='degenerate_input'
        )
        result = {
            'status': 'fail',
            'market': args.market,
            'phase': args.phase,
            'date': today,
            'issues': [f'report text 仅 {len(text.strip())} 字 (< {MIN_REPORT_CHARS}) '
                       f'— 疑似空管道（写文件与读取竞态），跳过投递+commit'],
            'wechat_prefix': '',
            'wechat_sent': False,
            'commit_ok': False,
            'commit_msg': 'skipped (degenerate empty report text)',
            'n_chars': len(text),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    # ── Generation gate (prose mode only) ────────────────────────────────────
    # The model echoes the context_id it wrote against. A mismatch means the
    # context on disk was replaced after the prose was written — exactly what
    # happened on 2026-07-24, where the agent ran preflight a second time
    # mid-turn. Assembling fresh numbers under stale prose would produce an
    # internally contradictory report that LOOKS clean, which is worse than the
    # loud banner we got, so refuse to assemble and fall back to data-only.
    stale_generation = prose_only and args.context_id != ctx.get('context_id')

    # Keep the model's own text for the content rules; assemble the delivered body
    # separately. Validating the assembled body would let the prepended data block
    # satisfy the anomaly/section rules on the model's behalf. (2026-07-24 review.)
    model_text = text if prose_only else None
    if prose_only and not stale_generation:
        text = assemble_message(ctx, text)

    issues = ([f'context_id 不匹配: 模型基于 {args.context_id}，当前 context 是 '
               f'{ctx.get("context_id")} — 散文与数据不同代，拒绝拼装']
              if stale_generation
              else validate(text, ctx, prose_only=prose_only, model_text=model_text))
    status = categorize(issues) if not stale_generation else 'fail'

    # The banner counts and lists ESCALATING issues only; advisory findings get
    # their own line below, so a truncated list can never drop them (#134).
    # The split happens before the stage record because the ledger needs the same
    # distinction: an advisory-only slot delivers a clean report and must not be
    # filed as a degraded product (#764).
    escalating, advisories = split_advisory(issues)
    workflow_outcomes.record_stage(
        job_name,
        'llm',
        'success' if status == 'pass' else ('warning' if status == 'warn' else 'failed'),
        slot=slot,
        context_id=ctx.get('context_id'),
        issue_count=len(issues),
        escalating_count=len(escalating),
        advisory_count=len(advisories),
    )
    if status == 'pass' or not escalating:
        banner = ''
    elif status == 'warn':
        banner = (f'⚠️ Validation warnings ({len(escalating)}): '
                  + '; '.join(escalating[:3])
                  + ('; ...' if len(escalating) > 3 else '')
                  + '\n\n')
    else:
        banner = (f'🔴 Validation FAILED ({len(escalating)} issues), 仅发布数据块、未 commit:\n'
                  + '\n'.join('- ' + i for i in escalating[:5])
                  + ('\n- ...' if len(escalating) > 5 else '')
                  + '\n\n')
    wechat_prefix = banner + advisory_prefix(advisories)

    # ── Fail-closed body selection ───────────────────────────────────────────
    # A rejected report used to be delivered in full behind its banner, which is
    # how 07/22 numbers reached kcn on 2026-07-24. But silence is also wrong: a
    # market day with no message is indistinguishable from a dead cron. So a
    # failure delivers the harness-owned data block ALONE — every number in it is
    # trustworthy by construction — and drops the prose that failed validation.
    # This is the same shape report_watchdog already uses as its deterministic
    # fallback. pass/warn deliver the full body.
    if status == 'fail':
        body = assemble_message(ctx, '')
    else:
        body = text

    # ── Primary WeChat send (fresh token, decoupled from the cron announce) ───
    # Idempotency: this phase's marker is per market+phase+date and fires once/day,
    # so if it already shows a delivery this is an openclaw auto-retry of a run that
    # errored only in post-turn summary-gen — the report already went out. Skip the
    # re-send (watchdog still backstops a genuine miss). See already_delivered.
    report_marker = TMP / f'report-sent-{args.market}-{args.phase}-{today}.json'
    delivery_state = 'failed' if status == 'fail' else 'delivered'
    blocked = already_delivered(report_marker)

    # One exception to the idempotency lock: the slot's only delivery so far was a
    # fail-closed data block, and this run has a report that actually validates.
    # claim_upgrade() makes it exactly one. Everything else — a second failure, a
    # retry of an already-good send — stays blocked.
    upgrading = False
    if blocked and delivery_state == 'delivered' and _marker_state(report_marker) == 'failed':
        if claim_upgrade(args.market, args.phase, today):
            print(f'upgrade: {args.market}-{args.phase} superseding the fail-closed '
                  f'data block with the validated report', file=sys.stderr)
            blocked = False
            upgrading = True

    send_claim = 'not-required'
    # True when claim_send refused this process the send right: it then holds no
    # delivery evidence and must not file a primary_delivery verdict over the
    # concurrent holder's (#1006).
    claim_declined = False
    if blocked:
        print(f'idempotency: {args.market}-{args.phase} already delivered today — skip re-send',
              file=sys.stderr)
        wechat_sent = True
    elif upgrading:
        # The upgrade is the one re-send this slot is allowed, and `claim_upgrade`
        # is already an O_EXCL one-shot — so it needs no send claim on top. Asking
        # for one would in fact deny it: the fail-closed send that ran first left
        # its own claim behind, and the upgrade would read that as a sender still
        # in flight and skip the corrected report (caught by
        # test_a_failed_slot_can_be_superseded_once_then_locks).
        send_claim = 'upgrade'
        wechat_sent, _ = deliver_wechat(args.market, args.phase, today, wechat_prefix, body,
                                        delivery_state=delivery_state,
                                        context_id=ctx.get('context_id'),
                                        context_generated_at=ctx.get('generated_at'))
    else:
        # The marker only proves a send that FINISHED. A concurrent postflight
        # that is still mid-send leaves no marker at all, so the claim is what
        # keeps the second one quiet (#508).
        claim_path = TMP / f'report-send-{args.market}-{args.phase}-{today}.claim'
        won, send_claim = claim_send(claim_path)
        if not won:
            print(f'concurrency: {args.market}-{args.phase} send is already claimed '
                  f'({send_claim}) — not sending a second copy; the watchdog owns this '
                  f'slot if the first one did not land', file=sys.stderr)
            log({'tag': f'{args.market}-{args.phase}', 'action': 'send-claim-declined',
                 'reason': send_claim})
            wechat_sent = False
            claim_declined = True
        else:
            wechat_sent, _ = deliver_wechat(args.market, args.phase, today, wechat_prefix, body,
                                            delivery_state=delivery_state,
                                            context_id=ctx.get('context_id'),
                                            context_generated_at=ctx.get('generated_at'),
                                            claim_path=claim_path)

    # Record delivery here, not at the end of main(). Everything below — commit,
    # dashboard, data-plane publish — can take minutes, and on 2026-08-19 a 60s
    # `exec` timeout SIGTERM'd this process in exactly that gap, leaving a
    # delivered report filed as `pending` forever (#765). The send is already
    # proven at this point; nothing after it can make it less true.
    # Record the two channels separately. `channel='wechat_or_telegram'` folded
    # them into one label, which is exactly the fact needed to answer "how many
    # slots did WeChat drop this week" — a question that currently has no answer
    # because the receipts are pruned within days (#771). WeChat's `ret=-2
    # prepare failed` is a known, upstream-wontfix, periodic failure that kcn has
    # decided not to chase; that is a reason to make it countable, not invisible.
    # A declined claim process records nothing: the concurrent holder owns this
    # verdict, and a late false `failed` would stand forever because receipt
    # reconciliation only fills unknown stages (#1006).
    if not claim_declined:
        wechat_ok = bool(wechat_sent)
        telegram_ok = False
        try:
            telegram_ok = json.loads(report_marker.read_text()).get('tg_ok') is True
        except Exception:
            pass
        primary_delivery_ok = wechat_ok or telegram_ok
        workflow_outcomes.record_stage(
            job_name,
            'primary_delivery',
            'success' if primary_delivery_ok else 'failed',
            slot=slot,
            channel=workflow_outcomes.delivery_channel(wechat_ok, telegram_ok),
            wechat_ok=wechat_ok,
            telegram_ok=telegram_ok,
            deterministic_fallback=(status == 'fail'),
        )

    commit_ok, commit_msg = maybe_commit(status, ctx['commit_msg'])
    data_plane_status = classify_data_plane(commit_ok, commit_msg)

    result = {
        'status':        status,
        'market':        args.market,
        'phase':         args.phase,
        'date':          today,
        'mode':          'prose' if prose_only else 'legacy',
        'issues':        issues,
        'wechat_prefix': wechat_prefix,
        'wechat_sent':   wechat_sent,
        # So a re-run that correctly declined to double-send says so in its own
        # output instead of looking like a send failure to whoever reads Step 4.
        'send_claim':    send_claim,
        'delivered':     'data-block only (prose rejected)' if status == 'fail' else 'full report',
        'commit_ok':     commit_ok,
        'commit_msg':    commit_msg,
        'data_plane_status': data_plane_status,
        'narrative_status': {
            'pass': 'success', 'warn': 'warning', 'fail': 'failed',
        }[status],
        'n_chars':       len(body),
    }
    # Even a rejected prose report can have a successful postflight: the harness
    # deliberately delivers its deterministic data block. Preserve that degraded
    # product instead of collapsing it into the LLM's failure.
    workflow_outcomes.record_stage(
        job_name,
        'postflight',
        'success'
        if status == 'pass' and data_plane_status in {'published', 'current'}
        else 'warning',
        slot=slot,
        delivered=result['delivered'],
        data_plane_status=data_plane_status,
        issue_count=len(issues),
        escalating_count=len(escalating),
        advisory_count=len(advisories),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if data_plane_status not in {'published', 'current'}:
        return 2
    return 0 if status == 'pass' else (1 if status == 'warn' else 2)


if __name__ == '__main__':
    sys.exit(main())
