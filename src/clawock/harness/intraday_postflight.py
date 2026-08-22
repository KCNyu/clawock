#!/usr/bin/env python3
"""
intraday_postflight.py — Mode 7 (intraday) harness postflight.

Validates the LLM-generated intraday check-in.

Usage: `--text-file PATH` (canonical — write the report to a file first, then call
this). Stdin is still accepted for manual runs, but the cron/SKILL path must use
--text-file: heredoc/`<<<` plumbing has repeatedly failed (2026-07-23 10:00 HK:
the model called postflight with no stdin at all, the empty read produced four
misleading content issues, and the run was flagged error even though the retry
delivered fine).

Empty or stale input is reported as `status: input_error` — a plumbing failure,
distinct from `fail` (the report itself is bad). It still exits non-zero: this is
the delivery gate, and a false green is worse than a false red.

Two input modes, selected by `--context-id`:
  prose (canonical, with --context-id): the model writes ONLY the ▎我的看法 prose;
      assemble_message() prepends the harness-owned data block at send time.
  legacy (no --context-id): the model's text IS the whole message and the data
      block is checked for a byte-exact copy. Kept so a cron payload that has not
      been migrated yet still delivers.

Validates:
  1. ▎我的看法 段必须存在 + 段内容 ≥ 60 字（防敷衍 1 句话）
  2. 总长度闸与 Mode 6 共用 clawock.harness.validation.REPORT_CHAR_LIMITS（防复读死循环，不是写作目标）
  3. legacy 模式：必须以 raw_wechat_block 开头且表格逐字符复制
     prose 模式：数据块由 harness 拼装，无往返可校验
  4. 若 preflight should_alert=true：报告必须提到至少一个异动票或 alert_reason
  5. 无敷衍 phrases

Note: Mode 7 does NOT commit portfolio.json. For every usable preflight context,
including a slot whose prose is rejected, it rebuilds dashboard.json and commits
only semantic changes. Every slot also updates the local heartbeat ledger, which
the existing single publisher exposes without introducing another git writer.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from clawock.harness.validation import (
    ADVISORY_MARK,
    REPORT_CHAR_LIMITS,
    advisory_prefix,
    categorize_issues,
    check_numeric_claims,
    check_raw_tables_verbatim,
    split_advisory,
    validate_forbidden_phrases,
)
from ._harness_common import (  # noqa: E402
    dashboard_publication_state,
    git_cmd,
    push_with_rebase_retry,
    rebuild_dashboard,
    snapshot_date_for_now,
)
from ._watchdog_common import (  # noqa: E402
    resolve_wechat_target, send_wechat, cosend_telegram, already_delivered,
    claim_send, mark_send_started, release_claim, log,
)

from clawock.workspace import workspace_root
from clawock import sessions as trading_calendar
from clawock.safe_io import safe_write_json

WS = workspace_root(Path.cwd())
_CHECKOUT = WS
TMP = WS / 'memory' / '.tmp'

from clawock.automation import cron_heartbeat  # noqa: E402
from clawock.harness import intraday_delta  # noqa: E402

# A report file older than this is assumed to be a previous slot's leftover. Kept
# below the 30min slot cadence (and aligned with the already_delivered window) so a
# forgotten write is refused instead of silently re-publishing a stale report.
REPORT_MAX_AGE_MIN = 20

REQUIRED_SECTION = '▎我的看法'
FORBIDDEN_PHRASES = ['数据待获取', '等待数据', 'TODO', 'TBD']
CRITICAL_KEYWORDS = ['缺段标记', '未包含原始数据块', '敷衍词', '表格行未 verbatim']


def load_context(market):
    path = TMP / f'intraday-context-{market}-latest.json'
    if not path.exists():
        return None, f'preflight latest context 不存在: {path.name}'
    try:
        return json.loads(path.read_text()), None
    except Exception as e:
        return None, f'context 解析失败: {e}'


def read_report_text(market, text_file):
    """Return (text, input_error). Plumbing failures never reach validate()."""
    hint = (f'Step 3 应先把 ▎我的看法 散文写入 memory/.tmp/intraday-prose-{market}.md，'
            f'再用 --text-file + --context-id 调用 postflight；'
            f'不要用 heredoc/here-string 重定向喂 stdin')
    if text_file:
        path = Path(text_file)
        if not path.exists():
            return '', f'报告文件不存在: {path} — {hint}'
        age_min = (datetime.now().timestamp() - path.stat().st_mtime) / 60
        if age_min > REPORT_MAX_AGE_MIN:
            return '', (f'报告文件 {path.name} 已 {age_min:.0f} 分钟未更新 '
                        f'(> {REPORT_MAX_AGE_MIN} 分钟上限) — 疑似上一个 slot 的旧报告，'
                        f'拒绝投递；{hint}')
        text = path.read_text()
    else:
        text = sys.stdin.read()

    if not text.strip():
        src = f'--text-file {text_file}' if text_file else 'stdin'
        return '', f'空输入 ({src}) — postflight 没收到任何报告文本；{hint}'
    return text, None


def input_error(market, err):
    """Exit path for empty/stale/missing input: loud, single-cause, still non-zero."""
    # Attribute the failure to the slot the preflight context was built for, not to
    # whatever slot the wall clock happens to be in now. A run that starts at 10:00
    # and hits empty input at 10:31 would otherwise stamp a phantom 10:30 failure,
    # and the retry that succeeds would mark 10:00 completed — leaving a slot in the
    # health ledger that never actually failed. Context is best-effort here: an
    # input error must still be recorded when the context is missing too.
    ctx, _ = load_context(market)
    hb = (ctx or {}).get('heartbeat') or {}
    cron_heartbeat.record(market, 'postflight_failed', failure_stage='input',
                          job_name=hb.get('job'), slot=hb.get('slot'))
    print(f'error: {err}', file=sys.stderr)
    result = {
        'status':        'input_error',
        'market':        market,
        'time':          datetime.now().strftime('%H:%M'),
        'issues':        [err],
        'wechat_prefix': '',
        'n_chars':       0,
        'wechat_sent':   None,
        'telegram_sent': None,
        'dashboard_published': False,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2


def normalize_intraday_insights(path, generated_at=None):
    """Replace model metadata with the current harness generation timestamp.

    The model owns narrative only. Malformed/missing sidecars are dashboard
    degradation, never a reason to suppress the deterministic market report.
    """
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text())
        if not isinstance(payload, dict):
            raise ValueError('top-level JSON must be an object')
        canonical = {
            'generated_at': generated_at or datetime.now(timezone.utc).isoformat(
                timespec='seconds').replace('+00:00', 'Z'),
            'status_banner': payload.get('status_banner'),
            'movers': payload.get('movers'),
        }
        safe_write_json(str(path), canonical)
        return True
    except Exception as exc:
        print(f'warn: {path.name} 解析/规范化失败 — dashboard status_banner 将忽略: '
              f'{exc}', file=sys.stderr)
        return False


def assemble_message(ctx, prose):
    """Build the delivered check-in from harness-owned data + model-owned prose.

    Mode 7 used to make the deterministic data block round-trip through the LLM:
    preflight put it in the context, the payload ordered the model to retype it
    character for character, and validate() diffed the copy. Mode 6 dropped that
    on 2026-07-24; Mode 7 was left behind and kept paying for it — on 2026-07-28
    00:30 the model padded RKLX's 浮$ cell with one extra space, the strict
    substring check raised a CRITICAL, and the whole ▎我的看法 段 was dropped in
    favour of the bare data block. The table was correct; only its whitespace
    was not.

    Prepending here removes the round trip: the numbers in the delivered message
    come from the context file at send time, so they cannot be paraphrased or
    table-mangled — no copy instruction and no verbatim rule needed. Mode 7 has
    no separate `title`; raw_wechat_block already opens with the titled first
    line, so the block alone is the prefix.
    """
    parts = [(ctx.get('raw_wechat_block') or '').strip(), (prose or '').strip()]
    return '\n\n'.join(p for p in parts if p)


def validate(text, ctx, prose_only=False, model_text=None):
    """Validate the delivered check-in.

    `text` is what gets sent. `model_text` is the part the MODEL wrote; in prose
    mode that is the prose alone, in legacy mode it is the whole report.

    The content rules — 我的看法 段, anomaly mention, forbidden phrases, numeric
    claims — MUST run against model_text, never the assembled body. The prepended
    block itself contains the anomaly tickers and section-looking tokens, so
    checking the body would let prose that names none of the movers pass because
    the table does. Only the length limit is a property of the assembled body.
    (Same split as report_postflight.validate — see its docstring.)
    """
    issues = []
    checked = text if model_text is None else model_text

    raw = ctx.get('raw_wechat_block', '').strip()
    if raw and not prose_only:
        first_line = raw.splitlines()[0]
        if first_line not in text:
            issues.append(f'报告未包含原始数据块首行 "{first_line[:40]}..." (verbatim 失败)')
        issues.extend(check_raw_tables_verbatim(text, raw))

    if REQUIRED_SECTION not in checked:
        issues.append(f'缺段标记 "{REQUIRED_SECTION}"')
    else:
        # 我的看法 段必须 ≥ 60 字（否则就是敷衍 1 句结案）
        section_body = checked.split(REQUIRED_SECTION, 1)[1].strip()
        # cut to next section (▎XXX) or end
        next_marker = section_body.find('\n▎')
        if next_marker > 0:
            section_body = section_body[:next_marker]
        section_body = section_body.strip()
        if len(section_body) < 60:
            issues.append(
                f'"{REQUIRED_SECTION}" 段仅 {len(section_body)} 字，太敷衍 '
                f'(< 60 软下限)；需引用具体票 + 一行判断'
            )

    # Length is a property of what actually gets pushed to WeChat, so it — and
    # only it — measures the assembled body. The thresholds are Mode 6's, shared
    # rather than copied: this file used to carry its own 3000/3500 literals,
    # so the two modes could drift apart with nothing to notice.
    n = len(text)
    soft, hard = REPORT_CHAR_LIMITS['soft'], REPORT_CHAR_LIMITS['hard']
    if n > hard:
        issues.append(f'报告长度 {n} 字 > {hard} 上限')
    elif n > soft:
        issues.append(f'报告长度 {n} 字 > {soft} 软上限 (warn)')

    if ctx.get('should_alert'):
        anomaly_tickers = [a['ticker'] for a in ctx.get('anomalies', [])]
        mentioned = [t for t in anomaly_tickers if t in checked]
        if anomaly_tickers and not mentioned:
            issues.append(f'should_alert=true 但报告未提任何异动票 ({", ".join(anomaly_tickers)})')

    # 加仓侧的读数 (#755)。它的三条输入(异动/机会雷达/早期趋势)以前全都算好了却从没
    # 进过正文,所以模板加了要求之后必须配一条闸——否则就是又一个「写了没人写」。
    # advisory:它只能提醒漏写,不许把一份已经可发的报告变成不发
    # (feedback-detect-but-never-silence)。
    add_rows = (ctx.get('add_side_reads') or {}).get('rows') or []
    if add_rows and not any(row.get('ticker') in checked for row in add_rows):
        verdicts = '/'.join(f"{row['ticker']} {row['verdict']}" for row in add_rows[:3])
        issues.append(
            f'加仓侧读数非空但报告一个都没写 ({verdicts}) {ADVISORY_MARK}')

    issues.extend(validate_forbidden_phrases(checked, FORBIDDEN_PHRASES))

    # 数字必须来自 context —— 一条聚合 warn，见 check_numeric_claims
    issues.extend(check_numeric_claims(checked, ctx))

    return issues


def categorize(issues):
    def is_hard_char_limit(issue):
        return '字 >' in issue and '上限' in issue and '软上限' not in issue

    return categorize_issues(
        issues, CRITICAL_KEYWORDS, warn_max=2, extra_critical=is_hard_char_limit,
    )


def delivery_marker_payload(ctx, *, ts, sent_ok, tg_ok, first_line, market, out,
                            delivery_state='delivered'):
    """Build the watchdog marker with the preflight slot as its identity.

    `delivery_state` distinguishes a full report from the fail-closed data block
    (#135): both are real deliveries — the watchdog must not re-send either —
    but only one of them carried the model's prose.

    `context_id` and `context_generated_at` name the preflight invocation this
    body was built from. Without them the only link back to the delivered report
    was its first line, which carries the generation minute — so when openclaw
    auto-retried a run that had already delivered, the retry's preflight rewrote
    the context, the first lines disagreed, and the watchdog mirrored a report kcn
    already had (#458, 2026-08-10 HK 10:30 and 11:30). Mode 6's marker has carried
    both fields since 2026-08-03; Mode 7's context always had them and threw them
    away here.
    """
    heartbeat = ctx.get('heartbeat') or {}
    return {
        'ts': ts,
        'sent_ok': bool(sent_ok),
        'tg_ok': bool(tg_ok),
        'first_line': first_line,
        'market': market,
        'job': heartbeat.get('job'),
        'slot': heartbeat.get('slot'),
        'context_id': ctx.get('context_id'),
        'context_generated_at': ctx.get('generated_at'),
        'delivery_state': delivery_state,
        'out': (out or '')[-200:],
    }


def publish_data_plane(market):
    """Publish deterministic dashboard outputs, independent of prose quality."""
    try:
        ok, _ = rebuild_dashboard()
        publication_state = dashboard_publication_state(WS)
        # No dashboard outputs here: #314 untracked them, and `git add` on a
        # gitignored path fails rather than skipping, which would abort the
        # snapshot commit too.
        paths = ['logs/dashboard_build_status.json']
        snap = snapshot_date_for_now()
        if snap:
            paths.append(f'memory/snapshots/{snap}.json')
        added, _ = git_cmd('add', '--', *paths)
        if not added:
            return 'git_add_failed', False
        # git diff --cached --quiet returns 0 when there is NO diff
        clean, _ = git_cmd('diff', '--cached', '--quiet', '--', *paths)
        if clean:
            return ('current', False) if ok else (publication_state, False)
        msg = (
            f"dashboard: intraday refresh "
            f"({market} {datetime.now().strftime('%H:%M HKT')})"
        )
        committed, _ = git_cmd('commit', '-m', msg, '--', *paths)
        if not committed:
            return 'commit_failed', False
        pushed, _ = push_with_rebase_retry()
        if not pushed:
            return 'committed_local', False
        # The status file must reach master even when the data-plane push failed;
        # otherwise the off-host health check keeps reading the previous green
        # record. Report the actual public outcome after that diagnostic commit.
        return ('published', True) if ok else (publication_state, False)
    except Exception as exc:
        print(f'warn: dashboard auto-publish failed: {exc}', file=sys.stderr)
        return 'publish_failed', False


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--market', choices=['hk', 'us'], required=True)
    parser.add_argument('--text-file',
                        help='report text file (canonical path; stdin only for manual runs)')
    parser.add_argument('--context-id',
                        help='the context_id printed by intraday_preflight. Passing it '
                             'selects prose mode: the file holds ONLY the ▎我的看法 prose '
                             'and the harness prepends the data block. Omit for legacy '
                             'whole-report input.')
    args = parser.parse_args(argv)

    # Holiday/weekend gate: no send/publish on a closed market.
    closed = trading_calendar.closed_reason(args.market)
    if closed:
        market_cn = '港股' if args.market == 'hk' else '美股'
        result = {'status': 'market_closed', 'market': args.market, 'reason': closed,
                  'wechat_sent': False, 'wechat_prefix': '',
                  'issues': [f'{market_cn}{closed}，跳过投递+publish']}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    ctx, err = load_context(args.market)
    if ctx is None:
        cron_heartbeat.record(
            args.market, 'postflight_failed', failure_stage='context_load',
        )
        result = {
            'status': 'fail',
            'issues': [err],
            'wechat_prefix': f'🔴 postflight 异常: {err}\n\n',
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    receipt_only = ctx.get('delivery_mode') == 'unchanged_receipt'
    if receipt_only:
        # No model prose exists on this path.  Requiring a dummy text file would
        # turn the cheapest healthy slot back into tool churn and stale-file risk.
        text, in_err = (ctx.get('raw_wechat_block') or '').strip(), None
    else:
        text, in_err = read_report_text(args.market, args.text_file)
    if in_err:
        return input_error(args.market, in_err)

    prose_only = args.context_id is not None

    # ── Generation gate (prose mode only) ────────────────────────────────────
    # The model echoes the context_id it wrote against. A mismatch means the
    # context on disk was replaced after the prose was written — the agent ran
    # preflight a second time mid-turn. Assembling fresh numbers under stale
    # prose would produce an internally contradictory check-in that LOOKS clean,
    # so refuse to assemble and fall through to the data-block-only path.
    stale_generation = (
        prose_only and not receipt_only
        and args.context_id != ctx.get('context_id')
    )

    # Keep the model's own text for the content rules; assemble the delivered
    # body separately, so the prepended block never satisfies a rule on the
    # model's behalf.
    model_text = text if prose_only else None
    if receipt_only and not stale_generation:
        text = (ctx.get('raw_wechat_block') or '').strip()
    elif prose_only and not stale_generation:
        text = assemble_message(ctx, text)

    issues = ([f'context_id 不匹配: 模型基于 {args.context_id}，当前 context 是 '
               f'{ctx.get("context_id")} — 散文与数据不同代，拒绝拼装']
              if stale_generation
              else ([] if receipt_only else validate(
                  text, ctx, prose_only=prose_only, model_text=model_text)))
    status = 'fail' if stale_generation else categorize(issues)

    # Step 2.5 sidecar liveness (warn-only, stderr — NOT in the WeChat report):
    # the dashboard status banner went dark 06-04→06-10 when a payload rewrite
    # dropped Step 2.5 and nothing noticed for 6 days. A missing narrative
    # sidecar must never block/clutter the report (kcn: no per-cron alerts),
    # but it should leave a visible trace in the cron run log + result JSON.
    sidecar_date = ctx.get('date')
    try:
        datetime.strptime(str(sidecar_date), '%Y-%m-%d')
    except (TypeError, ValueError):
        sidecar_date = datetime.now().strftime('%Y-%m-%d')
    insights_path = TMP / f'intraday-insights-{sidecar_date}.json'
    # A receipt has no new model judgement.  Re-normalizing yesterday's file
    # would stamp old prose with the current UTC time and make it look fresh.
    insights_written = False if receipt_only else normalize_intraday_insights(insights_path)
    if not insights_written and not receipt_only:
        print(f'warn: {insights_path.name} 缺失或不可用 — dashboard status_banner 将过期隐藏 '
              f'(SKILL Mode 7 Step 2.5 / cron payload Step 2.5)', file=sys.stderr)

    # The banner counts and lists ESCALATING issues only; advisory findings get
    # their own line below, so a truncated list can never drop them (#134).
    escalating, advisories = split_advisory(issues)
    if status == 'pass' or not escalating:
        banner = ''
    elif status == 'warn':
        banner = (f'⚠️ Validation warnings ({len(escalating)}): '
                  + '; '.join(escalating[:2])
                  + '\n\n')
    else:
        banner = (f'🔴 Validation FAILED ({len(escalating)} issues), 仅发布数据块:\n'
                  + '\n'.join('- ' + i for i in escalating[:4])
                  + '\n\n')
    wechat_prefix = banner + advisory_prefix(advisories)

    # ── WeChat delivery (decoupled from the cron's announce) ──────────────────
    # The cron's announce fires at the END of a long agent turn using a token
    # captured at turn START → expires mid-turn (#61174) → silent drop. We instead
    # send here, in a short-lived `openclaw message send` that grabs a FRESH token
    # (the path kcn confirmed lands when announce didn't). The 3 intraday crons run
    # --no-deliver so this is the SOLE send → no double, no long-turn drop. We
    # record the real send result to a marker so intraday_watchdog only re-sends on
    # a CONFIRMED failure (never doubles a report that went out here).
    wechat_sent = None
    tg_ok = None
    marker = TMP / f'intraday-sent-{args.market}.json'
    # Idempotency: if openclaw auto-retried this run (post-turn summary-gen failure),
    # the report already went out on the prior attempt — skip the re-send. Intraday's
    # marker is per-market, so use a 20min window (< the 30min slot cadence, > the
    # few-min retry gap) to tell a retry from the next legit slot. See already_delivered.
    delivered_this_run = False
    if already_delivered(marker, within_ms=20 * 60 * 1000):
        print('idempotency: intraday already delivered this slot — skip re-send', file=sys.stderr)
        try:
            prior = json.loads(marker.read_text())
            wechat_sent = prior.get('sent_ok')
            tg_ok = prior.get('tg_ok')
        except Exception:
            pass
    else:
        # Fail-closed, not silent (#135). A rejected report used to send nothing
        # at all, leaving a market slot indistinguishable from a dead cron until
        # the watchdog mirrored a block to Telegram 10-40 minutes later. Deliver
        # the harness-owned data block instead — every number in it is
        # trustworthy by construction — and drop the prose that failed. Same
        # shape as report_postflight's fail-closed body selection.
        raw_block = (ctx.get('raw_wechat_block', '') or '').strip()
        block_first = raw_block.splitlines()
        block_first = block_first[0] if block_first else ''
        body = raw_block if status == 'fail' else text
        if status == 'fail' and not raw_block:
            # Nothing trustworthy to deliver: the banner alone is the scary empty
            # send this harness already fixed once (2026-06-17). Leave it to the
            # watchdog rather than push a message with no content.
            print('warn: validation failed and the context carries no data block — '
                  'nothing sent, watchdog owns this slot', file=sys.stderr)
        else:
            message = (wechat_prefix + body).strip()
            # Same race as #508 on the report path: the marker is written only
            # after both sends return, so a second postflight started inside
            # that window sees "not delivered" and doubles the slot. The claim
            # is taken before the send. Its staleness window matches the
            # already_delivered one — intraday's claim is per-market, so it must
            # expire before the next 30min slot needs it.
            claim_path = TMP / f'intraday-send-{args.market}.claim'
            won, claim_reason = claim_send(claim_path, stale_after_ms=20 * 60 * 1000)
            if not won:
                print(f'concurrency: intraday {args.market} send is already claimed '
                      f'({claim_reason}) — not sending a second copy; the watchdog owns '
                      f'this slot if the first one did not land', file=sys.stderr)
                log({'tag': f'intraday-{args.market}', 'action': 'send-claim-declined',
                     'reason': claim_reason})
                wechat_sent, send_out = False, f'send-claim-declined: {claim_reason}'
            else:
                mark_send_started(claim_path)
                try:
                    channel, to, account = resolve_wechat_target(args.market)
                    wechat_sent, send_out = send_wechat(channel, to, account, message,
                                                        dry_run=False)
                except Exception as e:
                    wechat_sent, send_out = False, str(e)[:300]
                # Always co-send to Telegram (cold-proof) — WeChat can't confirm real
                # delivery. Record the Telegram result: it's the sole backstop
                # intraday_watchdog now uses (no more WeChat resend), so it needs to
                # know if TG already got this.
                tg_ok, _tg_out = cosend_telegram(message, f'intraday-{args.market}')
                delivered_this_run = bool(wechat_sent or tg_ok)
                # Only the process that actually sent may write the marker. A
                # declined claim writing one would tell intraday_watchdog this
                # slot was handled while nothing went out (#508).
                try:
                    marker.write_text(json.dumps(delivery_marker_payload(
                        ctx,
                        ts=int(datetime.now().timestamp() * 1000),
                        sent_ok=wechat_sent,
                        tg_ok=tg_ok,
                        first_line=block_first,
                        market=args.market,
                        out=send_out,
                        delivery_state='failed' if status == 'fail' else 'delivered',
                    ), ensure_ascii=False))
                except Exception as e:
                    print(f'warn: marker write failed: {e}', file=sys.stderr)
                # Completed send: the marker owns idempotency from here, and a
                # claim left behind would refuse the NEXT slot (whose marker
                # correctly does not block it when this one failed to send).
                release_claim(claim_path)
                if not wechat_sent:
                    print(f'warn: WeChat send failed (watchdog will retry): {send_out[:200]}',
                          file=sys.stderr)

    # A failed generation delivers the deterministic block so the slot remains
    # visible, but it has not delivered the intended semantic report.  Keep the
    # old cursor so the next slot retries the full delta instead of collapsing
    # it into an unchanged receipt.
    if delivered_this_run and status != 'fail':
        try:
            intraday_delta.persist_delivered_state(WS, ctx)
        except OSError as exc:
            print(f'warn: intraday delivered-state write failed: {exc}', file=sys.stderr)

    raw_block = (ctx.get('raw_wechat_block', '') or '').strip()
    data_plane_ready = ctx.get('status') == 'ok' and bool(raw_block)
    if data_plane_ready:
        data_plane_status, dashboard_published = publish_data_plane(args.market)
    else:
        data_plane_status, dashboard_published = 'unavailable', False

    result = {
        'status':        status,
        'market':        args.market,
        'mode':          ('unchanged_receipt' if receipt_only else
                          ('prose' if prose_only else 'legacy')),
        'time':          datetime.now().strftime('%H:%M'),
        'issues':        issues,
        'wechat_prefix': wechat_prefix,
        'n_chars':       len(text),
        'n_chars_model': len(model_text) if model_text is not None else len(text),
        'wechat_sent':   wechat_sent,
        'telegram_sent': tg_ok,
        'dashboard_published': dashboard_published,
        'data_plane_status': data_plane_status,
        'narrative_status': {
            'pass': 'success', 'warn': 'warning', 'fail': 'failed',
        }[status],
        'insights_sidecar': insights_written,
    }
    heartbeat = ctx.get('heartbeat') or {}
    publication_ok = data_plane_status in {'published', 'current'}
    if data_plane_ready and publication_ok:
        heartbeat_state = 'completed'
    elif data_plane_ready:
        heartbeat_state = 'publish_failed'
    else:
        heartbeat_state = 'postflight_failed'
    cron_heartbeat.record(
        args.market,
        heartbeat_state,
        job_name=heartbeat.get('job'), slot=heartbeat.get('slot'),
        postflight_status=status, wechat_sent=wechat_sent,
        telegram_sent=tg_ok, dashboard_published=dashboard_published,
        data_plane_status=data_plane_status,
        insights_sidecar=insights_written, issue_count=len(issues),
        # The ledger needs the same escalating/advisory split the banner uses:
        # an advisory-only slot delivered a clean report (#764).
        escalating_count=len(escalating), advisory_count=len(advisories),
    )
    result['heartbeat'] = {
        'job': heartbeat.get('job'), 'slot': heartbeat.get('slot'),
        'state': heartbeat_state,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not publication_ok:
        return 2
    return 0 if status == 'pass' else (1 if status == 'warn' else 2)


if __name__ == '__main__':
    sys.exit(main())
