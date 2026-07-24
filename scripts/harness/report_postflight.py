#!/usr/bin/env python3
"""
report_postflight.py — Mode 6 (briefing) harness postflight.

Validates the LLM-generated WeChat briefing AFTER it's been written.

Usage: read the briefing text from stdin (preferred for cron),
       or pass --text-file PATH.

Validates:
  1. ▎情绪面 / ▎技术面 / ▎操作建议 三段标记齐全
  2. 若 preflight needs_risk_section=true, 必须有 ▎风险提示 段
  3. 总长度 ≤ 3000 字 (warn) / ≤ 3500 字 (fail) — HK + US 统一（2026-07-23 调升）
  4. 必须以 raw_wechat_block 开头（脚本数据块 verbatim，禁止编造）
  5. 如果 preflight 有 anomalies，报告必须提到至少一个 anomaly 票
  6. 没有"等待数据/数据待获取"等敷衍词

Side effects:
  - status=pass/warn: refresh snapshot/dashboard, commit the scoped generated
    state, push through safe_push.sh, then send WeChat + Telegram mirror
  - status=fail: no commit, return non-zero

Outputs JSON to stdout:
  {"status": "pass|warn|fail", "issues": [...], "wechat_prefix": "..."}
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Workspace root, resolved from this file's location (location-independent;
# matches the old hardcoded /root path locally, robust if run elsewhere).
WS = Path(__file__).resolve().parents[2]
TMP = WS / 'memory' / '.tmp'

sys.path.insert(0, str(WS / 'scripts' / 'data'))
import trading_calendar  # noqa: E402

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

# Char limits — HK + US 统一 3000/3500（2026-07-23 起，各档在 2000/2500 基础上 +1000；
# 更早一版 1200 太紧、2000 仍让正常长度的报告频繁 warn）
CHAR_LIMITS = {
    'hk': {'soft': 3000, 'hard': 3500},
    'us': {'soft': 3000, 'hard': 3500},
}


def load_context(market, phase, date):
    path = TMP / f'report-context-{market}-{phase}-{date}.json'
    if not path.exists():
        return None, f'preflight context 不存在: {path.name}'
    try:
        return json.loads(path.read_text()), None
    except Exception as e:
        return None, f'preflight context 解析失败: {e}'


def validate(text, ctx):
    issues = []

    # 1. raw block 必须 verbatim 出现
    raw = ctx.get('raw_wechat_block', '').strip()
    if raw:
        first_line = raw.splitlines()[0]
        if first_line not in text:
            issues.append(f'报告未包含原始数据块首行 "{first_line[:40]}..." (verbatim 验证失败)')
        issues.extend(check_raw_tables_verbatim(text, raw))

    # 2. 必有三段标记
    for sec in REQUIRED_SECTIONS:
        if sec not in text:
            issues.append(f'缺段标记 "{sec}"')

    # 3. 风险提示段（若 preflight 标了 needs）
    if ctx.get('needs_risk_section') and '▎风险提示' not in text:
        issues.append('preflight 标 needs_risk_section=true 但未见 "▎风险提示" 段')

    # 4. 长度 (per-market)
    n_chars = len(text)
    limits = CHAR_LIMITS.get(ctx.get('market', 'hk'), CHAR_LIMITS['hk'])
    soft, hard = limits['soft'], limits['hard']
    if n_chars > hard:
        issues.append(f'报告长度 {n_chars} 字 > {hard} 上限')
    elif n_chars > soft:
        issues.append(f'报告长度 {n_chars} 字 > {soft} 软上限 (warn)')

    # 5. 异动票必须被提到
    anomalies = ctx.get('anomalies', [])
    if anomalies:
        mentioned = [a['ticker'] for a in anomalies if a['ticker'] in text]
        if not mentioned:
            tickers = ', '.join(a['ticker'] for a in anomalies)
            issues.append(f'preflight 标了 {len(anomalies)} 个 ≥3% 异动票 ({tickers}) 但报告全部未提及')

    # 6. 敷衍 phrases
    issues.extend(validate_forbidden_phrases(text, FORBIDDEN_PHRASES))

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
    categorize_issues,
    check_raw_tables_verbatim,
    dashboard_output_changes,
    git_cmd as _git,
    push_with_rebase_retry,
    rebuild_dashboard,
    snapshot_date_for_now,
    validate_forbidden_phrases,
)
from _watchdog_common import resolve_wechat_target, send_wechat, cosend_telegram, already_delivered  # noqa: E402


def deliver_wechat(market, phase, date, wechat_prefix, text):
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
    if status == 'fail':
        return False, 'skipped (status=fail)'
    rebuild_dashboard()
    dashboard_paths = dashboard_output_changes()
    suffix = ' (validation warnings)' if status == 'warn' else ''
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
    ok, out = _git('commit', '-m', f'{commit_msg}{suffix}')
    if not ok and 'nothing to commit' in out:
        return True, 'nothing to commit (idempotent)'
    if not ok:
        return False, out[-200:]

    # Push so Pages updates; rebase+retry handles races with GH Action commits
    push_ok, push_out = push_with_rebase_retry()
    if push_ok:
        return True, 'committed + pushed'
    return True, f'committed (push failed: {push_out[-150:]})'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--market', choices=['hk', 'us'], required=True)
    parser.add_argument('--phase', choices=['open', 'mid', 'pm', 'close'], required=True)
    parser.add_argument('--text-file', help='briefing text file (default: stdin)')
    args = parser.parse_args()

    # Holiday/weekend gate: never send/commit on a closed market — even if the
    # model produced a report off stale data. Mirrors the preflight gate.
    session = trading_calendar.phase_session(args.market, args.phase)
    closed = trading_calendar.closed_reason(args.market, session=session)
    if closed:
        market_cn = '港股' if args.market == 'hk' else '美股'
        result = {'status': 'market_closed', 'market': args.market, 'phase': args.phase,
                  'reason': closed, 'wechat_sent': False, 'commit_ok': False,
                  'wechat_prefix': '', 'issues': [f'{market_cn}{closed}，跳过投递+commit']}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.text_file:
        text = Path(args.text_file).read_text()
    else:
        text = sys.stdin.read()

    today = datetime.now().strftime('%Y-%m-%d')
    ctx, ctx_err = load_context(args.market, args.phase, today)

    if ctx is None:
        result = {
            'status': 'fail',
            'issues': [ctx_err],
            'wechat_prefix': f'🔴 postflight 异常: {ctx_err}\n\n',
            'commit_ok': False,
            'commit_msg': 'skipped (no preflight context)',
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    # Degenerate/empty stdin = broken pipe (see MIN_REPORT_CHARS note). Bail out
    # BEFORE deliver_wechat so kcn never gets an empty-bodied FAILED banner; exit
    # non-zero so the run record shows the breakage. The model's retry (serial
    # `< file`) or report_watchdog's raw-block fallback delivers the real report.
    if len(text.strip()) < MIN_REPORT_CHARS:
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

    issues = validate(text, ctx)
    status = categorize(issues)

    if status == 'pass':
        wechat_prefix = ''
    elif status == 'warn':
        wechat_prefix = (f'⚠️ Validation warnings ({len(issues)}): '
                         + '; '.join(issues[:3])
                         + ('; ...' if len(issues) > 3 else '')
                         + '\n\n')
    else:
        wechat_prefix = (f'🔴 Validation FAILED ({len(issues)} issues), 报告仍发布但未 commit:\n'
                         + '\n'.join('- ' + i for i in issues[:5])
                         + ('\n- ...' if len(issues) > 5 else '')
                         + '\n\n')

    # ── Primary WeChat send (fresh token, decoupled from the cron announce) ───
    # Send on ALL statuses incl. fail — a fail report is still published to kcn
    # with its banner (matches the old announce behavior); only the commit is
    # gated on not-fail. The staged crons run --no-deliver so this is the sole
    # send. See deliver_wechat() docstring for the #61174 long-turn-drop rationale.
    # Idempotency: this phase's marker is per market+phase+date and fires once/day,
    # so if it already shows a delivery this is an openclaw auto-retry of a run that
    # errored only in post-turn summary-gen — the report already went out. Skip the
    # re-send (watchdog still backstops a genuine miss). See already_delivered.
    report_marker = TMP / f'report-sent-{args.market}-{args.phase}-{today}.json'
    if already_delivered(report_marker):
        print(f'idempotency: {args.market}-{args.phase} already delivered today — skip re-send',
              file=sys.stderr)
        wechat_sent = True
    else:
        wechat_sent, _ = deliver_wechat(args.market, args.phase, today, wechat_prefix, text)

    commit_ok, commit_msg = maybe_commit(status, ctx['commit_msg'])

    result = {
        'status':        status,
        'market':        args.market,
        'phase':         args.phase,
        'date':          today,
        'issues':        issues,
        'wechat_prefix': wechat_prefix,
        'wechat_sent':   wechat_sent,
        'commit_ok':     commit_ok,
        'commit_msg':    commit_msg,
        'n_chars':       len(text),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if status == 'pass' else (1 if status == 'warn' else 2)


if __name__ == '__main__':
    sys.exit(main())
