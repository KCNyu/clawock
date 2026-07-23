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

Validates:
  1. ▎我的看法 段必须存在 + 段内容 ≥ 60 字（防敷衍 1 句话）
  2. 总长度 ≤ 2000 字 (warn), ≤ 2500 字 (fail) — 与 Mode 6 US 对齐
  3. 必须以 raw_wechat_block 开头 (verbatim)
  4. 若 preflight should_alert=true：报告必须提到至少一个异动票或 alert_reason
  5. 无敷衍 phrases

Note: Mode 7 does NOT commit portfolio.json. It rebuilds dashboard.json and commits
only semantic changes; every slot also updates the local heartbeat ledger, which
the existing single publisher exposes without introducing another git writer.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _harness_common import (  # noqa: E402
    categorize_issues,
    check_raw_tables_verbatim,
    dashboard_output_changes,
    git_cmd,
    push_with_rebase_retry,
    rebuild_dashboard,
    snapshot_date_for_now,
    validate_forbidden_phrases,
)
from _watchdog_common import resolve_wechat_target, send_wechat, cosend_telegram, already_delivered  # noqa: E402

# Workspace root, resolved from this file's location (location-independent;
# matches the old hardcoded /root path locally, robust if run elsewhere).
WS = Path(__file__).resolve().parents[2]
TMP = WS / 'memory' / '.tmp'

sys.path.insert(0, str(WS / 'scripts' / 'data'))
import trading_calendar  # noqa: E402
import cron_heartbeat  # noqa: E402

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
    hint = (f'Step 3 应先把报告写入 memory/.tmp/intraday-report-{market}.md，'
            f'再用 --text-file 调用 postflight；不要用 heredoc/<<< 喂 stdin')
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
    cron_heartbeat.record(market, 'postflight_failed', failure_stage='input')
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


def validate(text, ctx):
    issues = []

    raw = ctx.get('raw_wechat_block', '').strip()
    if raw:
        first_line = raw.splitlines()[0]
        if first_line not in text:
            issues.append(f'报告未包含原始数据块首行 "{first_line[:40]}..." (verbatim 失败)')
        issues.extend(check_raw_tables_verbatim(text, raw))

    if REQUIRED_SECTION not in text:
        issues.append(f'缺段标记 "{REQUIRED_SECTION}"')
    else:
        # 我的看法 段必须 ≥ 60 字（否则就是敷衍 1 句结案）
        section_body = text.split(REQUIRED_SECTION, 1)[1].strip()
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

    n = len(text)
    if n > 2500:
        issues.append(f'报告长度 {n} 字 > 2500 上限')
    elif n > 2000:
        issues.append(f'报告长度 {n} 字 > 2000 软上限 (warn)')

    if ctx.get('should_alert'):
        anomaly_tickers = [a['ticker'] for a in ctx.get('anomalies', [])]
        mentioned = [t for t in anomaly_tickers if t in text]
        if anomaly_tickers and not mentioned:
            issues.append(f'should_alert=true 但报告未提任何异动票 ({", ".join(anomaly_tickers)})')

    issues.extend(validate_forbidden_phrases(text, FORBIDDEN_PHRASES))

    return issues


def categorize(issues):
    def is_hard_char_limit(issue):
        return '字 >' in issue and '上限' in issue and '软上限' not in issue

    return categorize_issues(
        issues, CRITICAL_KEYWORDS, warn_max=2, extra_critical=is_hard_char_limit,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--market', choices=['hk', 'us'], required=True)
    parser.add_argument('--text-file',
                        help='report text file (canonical path; stdin only for manual runs)')
    args = parser.parse_args()

    # Holiday/weekend gate: no send/publish on a closed market.
    closed = trading_calendar.closed_reason(args.market)
    if closed:
        market_cn = '港股' if args.market == 'hk' else '美股'
        result = {'status': 'market_closed', 'market': args.market, 'reason': closed,
                  'wechat_sent': False, 'wechat_prefix': '',
                  'issues': [f'{market_cn}{closed}，跳过投递+publish']}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    text, in_err = read_report_text(args.market, args.text_file)
    if in_err:
        return input_error(args.market, in_err)

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

    issues = validate(text, ctx)
    status = categorize(issues)

    # Step 2.5 sidecar liveness (warn-only, stderr — NOT in the WeChat report):
    # the dashboard status banner went dark 06-04→06-10 when a payload rewrite
    # dropped Step 2.5 and nothing noticed for 6 days. A missing narrative
    # sidecar must never block/clutter the report (kcn: no per-cron alerts),
    # but it should leave a visible trace in the cron run log + result JSON.
    insights_path = TMP / f'intraday-insights-{datetime.now().strftime("%Y-%m-%d")}.json'
    insights_written = insights_path.exists()
    if not insights_written:
        print(f'warn: {insights_path.name} 未写 — dashboard status_banner 将过期隐藏 '
              f'(SKILL Mode 7 Step 2.5 / cron payload Step 2.5)', file=sys.stderr)

    if status == 'pass':
        wechat_prefix = ''
    elif status == 'warn':
        wechat_prefix = (f'⚠️ Validation warnings ({len(issues)}): '
                         + '; '.join(issues[:2])
                         + '\n\n')
    else:
        wechat_prefix = (f'🔴 Validation FAILED ({len(issues)} issues):\n'
                         + '\n'.join('- ' + i for i in issues[:4])
                         + '\n\n')

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
    if status in ('pass', 'warn') and already_delivered(marker, within_ms=20 * 60 * 1000):
        print('idempotency: intraday already delivered this slot — skip re-send', file=sys.stderr)
        try:
            prior = json.loads(marker.read_text())
            wechat_sent = prior.get('sent_ok')
            tg_ok = prior.get('tg_ok')
        except Exception:
            pass
    elif status in ('pass', 'warn'):
        block_first = (ctx.get('raw_wechat_block', '') or '').strip().splitlines()
        block_first = block_first[0] if block_first else ''
        message = (wechat_prefix + text).strip()
        try:
            channel, to, account = resolve_wechat_target(args.market)
            wechat_sent, send_out = send_wechat(channel, to, account, message, dry_run=False)
        except Exception as e:
            wechat_sent, send_out = False, str(e)[:300]
        # Always co-send to Telegram (cold-proof) — WeChat can't confirm real delivery.
        # Record the Telegram result: it's the sole backstop intraday_watchdog now
        # uses (no more WeChat resend), so it needs to know if TG already got this.
        tg_ok, _tg_out = cosend_telegram(message, f'intraday-{args.market}')
        try:
            marker.write_text(json.dumps({
                'ts': int(datetime.now().timestamp() * 1000),
                'sent_ok': bool(wechat_sent),
                'tg_ok': bool(tg_ok),
                'first_line': block_first,
                'market': args.market,
                'out': (send_out or '')[-200:],
            }, ensure_ascii=False))
        except Exception as e:
            print(f'warn: marker write failed: {e}', file=sys.stderr)
        if not wechat_sent:
            print(f'warn: WeChat send failed (watchdog will retry): {send_out[:200]}', file=sys.stderr)

    dashboard_published = False
    if status in ('pass', 'warn'):
        try:
            ok, _ = rebuild_dashboard()
            if ok:
                paths = [*dashboard_output_changes(), 'logs/dashboard_build_status.json']
                snap = snapshot_date_for_now()
                if snap:
                    paths.append(f'memory/snapshots/{snap}.json')
                git_cmd('add', '--', *paths)
                # git diff --cached --quiet returns 0 when there is NO diff
                clean, _ = git_cmd('diff', '--cached', '--quiet', '--', *paths)
                if not clean:
                    msg = f"dashboard: intraday refresh ({args.market} {datetime.now().strftime('%H:%M HKT')})"
                    c_ok, _ = git_cmd('commit', '-m', msg, '--', *paths)
                    if c_ok:
                        push_ok, _ = push_with_rebase_retry()
                        dashboard_published = push_ok
        except Exception as e:
            print(f'warn: dashboard auto-publish failed: {e}', file=sys.stderr)

    result = {
        'status':        status,
        'market':        args.market,
        'time':          datetime.now().strftime('%H:%M'),
        'issues':        issues,
        'wechat_prefix': wechat_prefix,
        'n_chars':       len(text),
        'wechat_sent':   wechat_sent,
        'telegram_sent': tg_ok,
        'dashboard_published': dashboard_published,
        'insights_sidecar': insights_written,
    }
    heartbeat = ctx.get('heartbeat') or {}
    cron_heartbeat.record(
        args.market,
        'completed' if status in ('pass', 'warn') else 'postflight_failed',
        job_name=heartbeat.get('job'), slot=heartbeat.get('slot'),
        postflight_status=status, wechat_sent=wechat_sent,
        telegram_sent=tg_ok, dashboard_published=dashboard_published,
        insights_sidecar=insights_written, issue_count=len(issues),
    )
    result['heartbeat'] = {
        'job': heartbeat.get('job'), 'slot': heartbeat.get('slot'),
        'state': 'completed' if status in ('pass', 'warn') else 'postflight_failed',
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if status == 'pass' else (1 if status == 'warn' else 2)


if __name__ == '__main__':
    sys.exit(main())
