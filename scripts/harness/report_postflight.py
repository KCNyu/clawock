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
  3. 总长度 ≤ 3000 字 (warn) / ≤ 3500 字 (fail) — HK + US 统一（2026-07-23 调升）
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

# Workspace root, resolved from this file's location (location-independent;
# matches the old hardcoded /root path locally, robust if run elsewhere).
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts' / 'data'))
from workspace import workspace_root  # noqa: E402

WS = workspace_root(Path(__file__).resolve().parents[2])
TMP = WS / 'memory' / '.tmp'

sys.path.insert(0, str(WS / 'scripts' / 'data'))
import trading_calendar  # noqa: E402
import workflow_outcomes  # noqa: E402

REQUIRED_SECTIONS = ['▎情绪面', '▎技术面', '▎操作建议']
FORBIDDEN_PHRASES = ['数据待获取', '等待数据', '数据缺失（占位）', 'TODO', 'TBD']

# A real report is always >500 字 (raw_wechat_block alone ≈600). Anything this
# short is a broken pipe, not a report — never deliver it. 2026-06-17: the cron
# LLM issued the file-write and `report_postflight ... <<< "$(cat report.txt)"`
# as PARALLEL tool calls in one turn; cat raced the write, read a missing file →
# empty stdin (n_chars=1). The validator (correctly) failed it, but deliver_wechat
# sends on ALL statuses incl. fail → kcn got a scary empty "🔴 Validation FAILED"
# banner before the model's serial retry delivered the real report. Guard the
# degenerate-input case BEFORE send/commit so a broken pipe never reaches WeChat.
MIN_REPORT_CHARS = 50

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


def _unusable_context(ctx, prose_only):
    """Reason string if the context can't back a report, else None.

    preflight writes blockless sentinels (status preflight_failed / market_closed)
    that carry none of the deterministic fields postflight assembles from. Anything
    but a 'ok' status with a nonempty raw block + title + commit_msg — plus a
    context_id in prose mode — is not a report context.
    """
    if ctx.get('status') != 'ok':
        return f'context status={ctx.get("status")!r}（preflight 未产出可用数据），跳过投递+commit'
    missing = [k for k in ('raw_wechat_block', 'title', 'commit_msg') if not (ctx.get(k) or '').strip()]
    if prose_only and not (ctx.get('context_id') or '').strip():
        missing.append('context_id')
    if missing:
        return f'context 缺字段 {missing}，跳过投递+commit'
    return None


def assemble_message(ctx, prose):
    """Build the delivered report from harness-owned data + model-owned prose.

    The 2026-07-24 incident happened because the deterministic data block made a
    round trip through the LLM: preflight put it in the context, the payload
    ordered the model to copy it verbatim, and validate() checked the copy. A
    model that read the wrong context therefore published wrong numbers, and the
    verbatim check could only notice *after* the send.

    Prepending it here removes the round trip: the numbers in the delivered
    message come from the context file at send time, so they cannot be stale,
    paraphrased, or table-mangled — no instruction and no validation rule needed.
    """
    parts = [ctx.get('title', '').strip(),
             (ctx.get('raw_wechat_block') or '').strip(),
             prose.strip()]
    return '\n\n'.join(p for p in parts if p)


def validate(body, ctx, prose_only=False, model_text=None):
    """Validate the delivered message.

    `body` is what gets sent. `model_text` is the part the MODEL wrote; in prose
    mode that is the prose alone, in legacy mode it is the whole report (== body).

    The content rules — sections, risk section, anomaly mention, forbidden phrases
    — MUST run against model_text, never body. In prose mode assemble_message has
    already prepended the raw data block, and that block itself contains the
    anomaly tickers and (potentially) section-looking tokens: checking body would
    let prose that mentions none of the movers pass because the table does. Only
    the length limit is a property of the assembled body. (2026-07-24 review.)
    """
    issues = []
    checked = body if model_text is None else model_text

    # 1. raw block 必须 verbatim 出现（legacy path only — see docstring）
    raw = ctx.get('raw_wechat_block', '').strip()
    if raw and not prose_only:
        first_line = raw.splitlines()[0]
        if first_line not in body:
            issues.append(f'报告未包含原始数据块首行 "{first_line[:40]}..." (verbatim 验证失败)')
        issues.extend(check_raw_tables_verbatim(body, raw))

    # 2. 必有三段标记（模型文本）
    for sec in REQUIRED_SECTIONS:
        if sec not in checked:
            issues.append(f'缺段标记 "{sec}"')

    # 3. 风险提示段（若 preflight 标了 needs；模型文本）
    if ctx.get('needs_risk_section') and '▎风险提示' not in checked:
        issues.append('preflight 标 needs_risk_section=true 但未见 "▎风险提示" 段')

    # 4. 长度 —— 按投递全文 (per-market)
    n_chars = len(body)
    limits = CHAR_LIMITS.get(ctx.get('market', 'hk'), CHAR_LIMITS['hk'])
    soft, hard = limits['soft'], limits['hard']
    if n_chars > hard:
        issues.append(f'报告长度 {n_chars} 字 > {hard} 上限')
    elif n_chars > soft:
        issues.append(f'报告长度 {n_chars} 字 > {soft} 软上限 (warn)')

    # 5. 异动票必须被提到（模型文本 —— 数据块里本就有票代码，不能拿它顶）
    anomalies = ctx.get('anomalies', [])
    if anomalies:
        mentioned = [a['ticker'] for a in anomalies if a['ticker'] in checked]
        if not mentioned:
            tickers = ', '.join(a['ticker'] for a in anomalies)
            issues.append(f'preflight 标了 {len(anomalies)} 个 ≥3% 异动票 ({tickers}) 但报告全部未提及')

    # 6. 敷衍 phrases（模型文本）
    issues.extend(validate_forbidden_phrases(checked, FORBIDDEN_PHRASES))

    # 7. 数字必须来自 context（模型文本）—— 一条聚合 warn，见 check_numeric_claims
    issues.extend(check_numeric_claims(checked, ctx))

    return issues


CRITICAL_KEYWORDS = ['缺段标记', '未包含原始数据块', '敷衍词', '表格行未 verbatim']


def _is_hard_char_limit(issue):
    """Hard char limit (e.g. '字 > 3500 上限') is critical; soft is not."""
    return '字 >' in issue and '上限' in issue and '软上限' not in issue


def categorize(issues):
    return categorize_issues(
        issues, CRITICAL_KEYWORDS, warn_max=3, extra_critical=_is_hard_char_limit,
    )


sys.path.insert(0, str(Path(__file__).parent))
from _harness_common import (  # noqa: E402
    REPORT_CHAR_LIMITS as CHAR_LIMITS,
    advisory_prefix,
    categorize_issues,
    check_numeric_claims,
    check_raw_tables_verbatim,
    dashboard_output_changes,
    git_cmd as _git,
    push_with_rebase_retry,
    rebuild_dashboard,
    snapshot_date_for_now,
    split_advisory,
    validate_forbidden_phrases,
)
from _watchdog_common import resolve_wechat_target, send_wechat, cosend_telegram, already_delivered  # noqa: E402


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
                   context_id=None):
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
            'market': market,
            'phase': phase,
            'out': (out or '')[-200:],
        }, ensure_ascii=False))
    except Exception as e:
        print(f'warn: report send marker write failed: {e}', file=sys.stderr)
    if not sent_ok:
        print(f'warn: WeChat send failed (watchdog will retry): {(out or "")[:200]}', file=sys.stderr)
    return sent_ok, out


def maybe_commit(status, commit_msg):
    rebuild_ok, _ = rebuild_dashboard()
    dashboard_paths = dashboard_output_changes()
    suffix = {
        'warn': ' (validation warnings)',
        'fail': ' (data only; prose rejected)',
    }.get(status, '')
    snap_date = snapshot_date_for_now()
    # logs/dashboard_build_status.json rides along: its only scheduled reader is
    # the GHA cron-health runner (fresh checkout), so it must reach origin.
    add_args = ['add', 'portfolio.json', *dashboard_paths,
                'logs/dashboard_build_status.json']
    if snap_date:
        add_args.append(f'memory/snapshots/{snap_date}.json')
    ok, _ = _git(*add_args)
    if not ok:
        return False, 'git add failed'
    commit_paths = add_args[1:]
    ok, out = _git('commit', '-m', f'{commit_msg}{suffix}', '--', *commit_paths)
    if not ok and 'nothing to commit' in out:
        return True, 'nothing to commit (idempotent)'
    if not ok:
        return False, out[-200:]

    # Push so Pages updates; rebase+retry handles races with GH Action commits
    push_ok, push_out = push_with_rebase_retry()
    if push_ok:
        if rebuild_ok:
            return True, 'committed + pushed'
        return True, 'committed + pushed (dashboard rebuild failed)'
    return True, f'committed (push failed: {push_out[-150:]})'


def classify_data_plane(commit_ok, commit_msg):
    """Return an explicit publication state independent of prose validation."""
    if not commit_ok:
        return 'failed'
    if 'push failed' in commit_msg:
        return 'committed_local'
    if 'rebuild failed' in commit_msg:
        return 'published_degraded'
    if 'nothing to commit' in commit_msg:
        return 'current'
    return 'published'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--market', choices=['hk', 'us'], required=True)
    parser.add_argument('--phase', choices=['open', 'mid', 'pm', 'close'], required=True)
    parser.add_argument('--text-file', help='briefing text file (default: stdin)')
    parser.add_argument('--context-id',
                        help='context_id echoed from preflight. Its presence selects '
                             'prose mode: the input is the analysis sections only and '
                             'this script prepends title + raw_wechat_block itself. '
                             'Omit for the legacy full-report input.')
    args = parser.parse_args()
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
    workflow_outcomes.record_stage(
        job_name,
        'llm',
        'success' if status == 'pass' else ('warning' if status == 'warn' else 'failed'),
        slot=slot,
        context_id=ctx.get('context_id'),
        issue_count=len(issues),
    )

    # The banner counts and lists ESCALATING issues only; advisory findings get
    # their own line below, so a truncated list can never drop them (#134).
    escalating, advisories = split_advisory(issues)
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
    if blocked and delivery_state == 'delivered' and _marker_state(report_marker) == 'failed':
        if claim_upgrade(args.market, args.phase, today):
            print(f'upgrade: {args.market}-{args.phase} superseding the fail-closed '
                  f'data block with the validated report', file=sys.stderr)
            blocked = False

    if blocked:
        print(f'idempotency: {args.market}-{args.phase} already delivered today — skip re-send',
              file=sys.stderr)
        wechat_sent = True
    else:
        wechat_sent, _ = deliver_wechat(args.market, args.phase, today, wechat_prefix, body,
                                        delivery_state=delivery_state,
                                        context_id=ctx.get('context_id'))

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
    )
    primary_delivery_ok = bool(wechat_sent)
    try:
        primary_delivery_ok = (
            primary_delivery_ok
            or json.loads(report_marker.read_text()).get('tg_ok') is True
        )
    except Exception:
        pass
    workflow_outcomes.record_stage(
        job_name,
        'primary_delivery',
        'success' if primary_delivery_ok else 'failed',
        slot=slot,
        channel='wechat_or_telegram',
        deterministic_fallback=(status == 'fail'),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if status == 'pass' else (1 if status == 'warn' else 2)


if __name__ == '__main__':
    sys.exit(main())
