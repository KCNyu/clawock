#!/usr/bin/env python3
"""
intraday_postflight.py — Mode 7 (intraday) harness postflight.

Validates the LLM-generated intraday check-in.

Usage: pipe brief text via stdin, or --text-file PATH.

Validates:
  1. ▎我的看法 段必须存在 + 段内容 ≥ 60 字（防敷衍 1 句话）
  2. 总长度 ≤ 2000 字 (warn), ≤ 2500 字 (fail) — 与 Mode 6 US 对齐
  3. 必须以 raw_wechat_block 开头 (verbatim)
  4. 若 preflight should_alert=true：报告必须提到至少一个异动票或 alert_reason
  5. 无敷衍 phrases

Note: Mode 7 does NOT commit portfolio.json (cron runs */30 too noisy to commit
each refresh). But it DOES rebuild + commit dashboard.json so the public Pages
front-end shows the latest 30-min prices instead of stale brief/report snapshots.
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
    git_cmd,
    push_with_rebase_retry,
    rebuild_dashboard,
    snapshot_date_for_now,
    validate_forbidden_phrases,
)
from _watchdog_common import resolve_wechat_target, send_wechat, cosend_telegram  # noqa: E402

# Workspace root, resolved from this file's location (location-independent;
# matches the old hardcoded /root path locally, robust if run elsewhere).
WS = Path(__file__).resolve().parents[2]
TMP = WS / 'memory' / '.tmp'

sys.path.insert(0, str(WS / 'scripts' / 'data'))
import trading_calendar  # noqa: E402

REQUIRED_SECTION = '▎我的看法'
FORBIDDEN_PHRASES = ['数据待获取', '等待数据', 'TODO', 'TBD']
CRITICAL_KEYWORDS = ['缺段标记', '未包含原始数据块', '> 1000', '敷衍词', '表格行未 verbatim']


def load_context(market):
    path = TMP / f'intraday-context-{market}-latest.json'
    if not path.exists():
        return None, f'preflight latest context 不存在: {path.name}'
    try:
        return json.loads(path.read_text()), None
    except Exception as e:
        return None, f'context 解析失败: {e}'


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
    return categorize_issues(issues, CRITICAL_KEYWORDS, warn_max=2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--market', choices=['hk', 'us'], required=True)
    parser.add_argument('--text-file', help='briefing text file (default: stdin)')
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

    text = Path(args.text_file).read_text() if args.text_file else sys.stdin.read()

    ctx, err = load_context(args.market)
    if ctx is None:
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
    if status in ('pass', 'warn'):
        block_first = (ctx.get('raw_wechat_block', '') or '').strip().splitlines()
        block_first = block_first[0] if block_first else ''
        message = (wechat_prefix + text).strip()
        try:
            channel, to, account = resolve_wechat_target(args.market)
            wechat_sent, send_out = send_wechat(channel, to, account, message, dry_run=False)
        except Exception as e:
            wechat_sent, send_out = False, str(e)[:300]
        # Always co-send to Telegram (cold-proof) — WeChat can't confirm real delivery.
        cosend_telegram(message, f'intraday-{args.market}')
        marker = TMP / f'intraday-sent-{args.market}.json'
        try:
            marker.write_text(json.dumps({
                'ts': int(datetime.now().timestamp() * 1000),
                'sent_ok': bool(wechat_sent),
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
                paths = ['assets/data/dashboard.json', 'logs/dashboard_build_status.json']
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
        'dashboard_published': dashboard_published,
        'insights_sidecar': insights_written,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if status == 'pass' else (1 if status == 'warn' else 2)


if __name__ == '__main__':
    sys.exit(main())
