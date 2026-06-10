#!/usr/bin/env python3
"""
brief_postflight.py — validate LLM outputs + commit if pass.

Runs AFTER the agent writes memory/{date}-pre-open.md + memory/{date}-plan.json.

Validates:
  1. plan.json schema (required fields, valid enums, confidence 0-1)
  2. pre-open.md required sections (Header / Tier 1 / Tier 2 / Tier 3 / Judge / Confidence / Next-Session)
  3. Sanity: no HKD+USD direct-sum errors (historical bug)
  4. Sanity: concentration HHI was actually mentioned (preflight provided it)

Outputs JSON to stdout:
  {"status": "pass|warn|fail", "issues": [...], "wechat_prefix": "..."}

Side effects:
  - status=pass: git add memory/ portfolio.json + commit
  - status=warn: same as pass but commit msg flags validation warnings
  - status=fail: no commit (preserve commit history clean); print issues
"""

import json
import sys
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

# Location-independent root: runs under openclaw cron (local) AND on GH Action
# brief-fallback.yml (checkout dir). parents[2] = workspace root in both. See
# brief_preflight.py for the bug this avoids (hardcoded /root broke the runner).
WS = Path(__file__).resolve().parents[2]

VALID_BUCKETS = {
    'cut', 'trim_on_rebound', 'hold_and_watch', 't_only', 'add_only_on_trigger',
}
VALID_TRIGGER_TYPES = {
    'open', 'price_above', 'price_below', 'index_breakdown', 'event', 'manual',
}
# driven_by = which data source actually drove the call (vs trigger_type = the price
# mechanism). Lets calibration answer "does the news feed add edge per source".
# '' allowed (legacy/backfill); 'technical' is the default for chart/MA/RSI-driven calls.
VALID_DRIVERS = {
    '', 'technical', 'catalyst', 'sentiment', 'influencer', 'macro', 'peer',
}
REQUIRED_MARKDOWN_TOKENS = [
    'Header', 'Tier 1', 'Tier 2', 'Tier 3', 'Judge', 'Confidence', 'Next-Session',
    '同行扫描',  # NEW: peer rotation section
]
HKD_USD_BUG_PATTERNS = [
    '合计 -4423', '合计 -4,423', '合计 -4423.0',
]


def validate_plan_json(path, context=None):
    if not path.exists():
        return ['plan.json 缺失（critical）']
    try:
        plan = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        return [f'plan.json 解析失败: {e}']

    issues = []
    for field in ('date', 'fx_rate_usdhkd', 'actions'):
        if field not in plan:
            issues.append(f'plan.json 缺顶层字段 "{field}"')

    actions = plan.get('actions', [])
    if not isinstance(actions, list) or not actions:
        issues.append('plan.json actions 空或非 list')
        return issues

    for i, a in enumerate(actions):
        tag = f'plan.json action[{i}] ({a.get("ticker", "?")})'
        if not a.get('ticker'):
            issues.append(f'{tag}: 缺 ticker')
        if a.get('bucket') not in VALID_BUCKETS:
            issues.append(f'{tag}: bucket "{a.get("bucket")}" 不合法')
        if a.get('trigger_type') not in VALID_TRIGGER_TYPES:
            issues.append(f'{tag}: trigger_type "{a.get("trigger_type")}" 不合法')
        if a.get('driven_by', '') not in VALID_DRIVERS:
            issues.append(f'{tag}: driven_by "{a.get("driven_by")}" 不合法 '
                          f'(允许 {sorted(VALID_DRIVERS - {""})})')
        # 消息面权重铁律 (warn): 软情绪 (sentiment/influencer) 不得单独驱动主动 call。
        # 硬催化才能翻 bucket;软情绪只能动 confidence。见 SKILL "消息面权重铁律"。
        if (a.get('driven_by') in ('sentiment', 'influencer')
                and a.get('bucket') in ('cut', 'trim_on_rebound', 'add_only_on_trigger')):
            issues.append(f'{tag}: 软情绪铁律 — driven_by={a.get("driven_by")} 不应单独驱动 '
                          f'{a.get("bucket")}(软情绪只能动 confidence,翻 bucket 需硬催化)')
        conf = a.get('confidence')
        if conf is not None and not (0.0 <= float(conf) <= 1.0):
            issues.append(f'{tag}: confidence {conf} 不在 [0, 1]')

    # 仓位/杠杆硬闸闭环 (warn): context.risk_guardrail 的每条 breach / hard_stop
    # 必须在 plan 里有对应的减仓动作，否则 LLM 忽略了硬闸。见 SKILL「🚦 仓位/杠杆硬闸」。
    gr = (context or {}).get('risk_guardrail') or {}
    if gr.get('breach_count'):
        TRIM = {'trim_on_rebound', 'cut'}
        def _leg(t): return 'HK' if str(t).isdigit() else 'US'
        trims = [a for a in actions if a.get('bucket') in TRIM]
        trim_tickers = {a.get('ticker') for a in trims}
        trim_legs = {_leg(a.get('ticker')) for a in trims}
        for b in gr.get('breaches', []):
            tk, leg = b.get('ticker'), b.get('leg')
            if tk and tk not in trim_tickers:
                issues.append(f'仓位硬闸未处理: {b["type"]} {tk} ({b["detail"]}) — '
                              f'plan 里 {tk} 没有 trim/cut 动作（SKILL 要求每条 breach 出对应动作）')
            elif not tk and leg and leg not in trim_legs:
                issues.append(f'仓位硬闸未处理: {b["type"]}/{leg} ({b["detail"]}) — '
                              f'plan 里 {leg} leg 没有任何 trim/cut 动作')
        for s in gr.get('hard_stop_watch', []):
            if s.get('ticker') not in {a.get('ticker') for a in actions if a.get('bucket') == 'cut'}:
                issues.append(f'杠杆硬止损未处理: {s["ticker"]} ({s["detail"]}) — plan 里没有对应 cut')
    return issues


def validate_markdown(path, context=None):
    if not path.exists():
        return ['pre-open.md 缺失（critical）']
    try:
        text = path.read_text()
    except Exception as e:
        return [f'pre-open.md 读取失败: {e}']

    issues = []
    for token in REQUIRED_MARKDOWN_TOKENS:
        if token not in text:
            issues.append(f'pre-open.md 缺段标记 "{token}"')

    for bug in HKD_USD_BUG_PATTERNS:
        if bug in text:
            issues.append(f'pre-open.md 出现历史 bug 模式 "{bug}" (HKD+USD 直接相加)')

    if 'HHI' not in text and 'hhi' not in text:
        issues.append('pre-open.md 未提及 HHI（集中度风险段漏掉？）')

    if 'USDHKD' not in text and 'FX' not in text and '汇率' not in text:
        issues.append('pre-open.md 未提及 FX rate / 汇率')

    # 体量卫生 (2026-05-31): WeChat 只发紧凑结论卡（Step 6），pre-open.md 仅作 dashboard
    # 全文，不再受 16KB 微信上限约束 → 不 fail。但过长 briefs 页难读，>24KB 给个 warn 提醒精简。
    nbytes = len(text.encode('utf-8'))
    if nbytes > 24000:
        issues.append(f'pre-open.md 偏长 {nbytes} bytes（dashboard 全文，建议精简到 ≤24KB 便于阅读）')

    # Markdown table column consistency — Pages renderer breaks if header/sep/data
    # rows diverge in pipe-segment count (same class of bug as the WeChat one
    # caught by intraday/report postflights).
    from _harness_common import check_md_table_column_consistency
    for issue in check_md_table_column_consistency(text):
        issues.append(f'pre-open.md {issue}')

    # NEW: peer-rotation enforcement — divergence_signal in context must be addressed
    if context and context.get('peer_scan'):
        divergence_tickers = [t for t, p in context['peer_scan'].items()
                              if p.get('divergence_signal')]
        unaddressed = [t for t in divergence_tickers if t not in text]
        if unaddressed:
            issues.append(f'pre-open.md 漏写 divergence 信号 ticker: {unaddressed} '
                          f'(preflight 标了 {len(divergence_tickers)} 个，markdown 漏 {len(unaddressed)} 个)')

    # NEW: 大盘速读 / 社交舆情速读 段落检查 (warn-only — 数据 fresh 但 LLM 漏写时提醒)
    # context.macro / context.sentiment 由 brief_preflight [13] 写入，stale > 36h 时
    # age_hours 字段已经标了，模板允许 LLM 写"⚠️ 数据 stale, 跳过"代替具体内容
    STALE_H = 36
    if context and context.get('macro'):
        m = context['macro']
        age = m.get('age_hours')
        # Only enforce when macro is reasonably fresh
        if (age is None or age <= STALE_H) and m.get('vix') and '▎大盘速读' not in text:
            issues.append('pre-open.md 缺 ▎大盘速读 段（context.macro 有 fresh 数据 '
                          f'age={age}h 但 LLM 没写）')
    if context and context.get('sentiment'):
        s = context['sentiment']
        age = s.get('age_hours')
        tickers = s.get('tickers') or []
        if (age is None or age <= STALE_H) and tickers and '▎社交舆情' not in text:
            issues.append(f'pre-open.md 缺 ▎社交舆情速读 段（context.sentiment '
                          f'{len(tickers)} 个 ticker 有信号 age={age}h 但 LLM 没写）')

    return issues


CRITICAL_KEYWORDS = ['缺失', '解析失败', '表格 #']  # table column-mismatch is critical


def categorize(issues):
    return categorize_issues(issues, CRITICAL_KEYWORDS, warn_max=4)


sys.path.insert(0, str(Path(__file__).parent))
from _harness_common import (  # noqa: E402
    categorize_issues,
    git_cmd as _git,
    push_with_rebase_retry,
    rebuild_dashboard,
)
from _watchdog_common import (  # noqa: E402
    resolve_wechat_target, send_wechat, build_brief_card,
)


def _current_price_for(ticker):
    """Look up the freshest current_price for ticker in portfolio.json.
    Used as fallback `sim_entry_price` when LLM forgot to set
    `simulated_entry_price` on the plan action — without it the future
    outcome resolver can't compute cut/trim/add win/loss (see
    brief_preflight._resolve_pending_outcomes)."""
    try:
        pf = json.loads((WS / 'portfolio.json').read_text())
    except Exception:
        return ''
    for region in ('us_stocks', 'hk_stocks'):
        for h in pf['portfolios'].get(region, {}).get('holdings', []) or []:
            if h.get('ticker') == ticker:
                cp = h.get('current_price')
                return cp if cp not in (None, 0) else ''
    return ''


def log_calibration(today):
    """Append today's plan actions to memory/calibration.csv (outcome filled in by future preflight)."""
    import csv
    plan_path = WS / 'memory' / f'{today}-plan.json'
    if not plan_path.exists():
        return
    try:
        plan = json.loads(plan_path.read_text())
    except Exception:
        return
    actions = plan.get('actions', [])
    if not actions:
        return

    calib_path = WS / 'memory' / 'calibration.csv'
    new_file = not calib_path.exists()
    fieldnames = ['plan_date','ticker','bucket','trigger_type','driven_by','trigger_price',
                  'confidence','sim_entry_price','outcome','pnl_5d','pnl_30d',
                  'followed','followed_at','updated_at']
    rows = []
    if not new_file:
        try:
            with open(calib_path, encoding='utf-8') as f:
                rows = list(csv.DictReader(f))
        except Exception:
            rows = []

    # Skip if this plan_date already logged
    existing = {(r.get('plan_date'), r.get('ticker'), r.get('bucket')) for r in rows}
    appended = 0
    for a in actions:
        key = (today, a.get('ticker'), a.get('bucket'))
        if key in existing:
            continue
        # Fallback: pull current_price from portfolio.json when plan didn't carry one
        sim_entry = a.get('simulated_entry_price') or a.get('trigger_price') or _current_price_for(a.get('ticker'))
        rows.append({
            'plan_date':       today,
            'ticker':          a.get('ticker'),
            'bucket':          a.get('bucket', ''),
            'trigger_type':    a.get('trigger_type', ''),
            'driven_by':       a.get('driven_by', ''),  # which data source drove the call
            'trigger_price':   a.get('trigger_price', ''),
            'confidence':      a.get('confidence', ''),
            'sim_entry_price': sim_entry,
            'outcome':         'pending',  # filled by future preflight retrospective
            'pnl_5d':          '',
            'pnl_30d':         '',
            'followed':        'unknown',  # user marks via scripts/data/mark_followed.py
            'followed_at':     '',
            'updated_at':      datetime.now().isoformat(),
        })
        appended += 1

    # Retention: drop rows older than 365 days (rolling window)
    cutoff = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
    before = len(rows)
    rows = [r for r in rows if r.get('plan_date', '') >= cutoff]
    dropped = before - len(rows)

    if appended or dropped:
        import io
        from _harness_common import safe_write_text
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
        safe_write_text(str(calib_path), buf.getvalue())
        msg = f'  calibration.csv: +{appended} pending rows'
        if dropped:
            msg += f', -{dropped} old (>365d)'
        msg += f' ({len(rows)} total)'
        print(msg)


def maybe_commit(status, today):
    if status == 'fail':
        return False, 'skipped (status=fail)'

    log_calibration(today)   # append today's plan to calibration log (idempotent)
    rebuild_dashboard()  # refresh dashboard.json before commit

    msg_suffix = ' (validation warnings)' if status == 'warn' else ''
    # risk.json / lev_regime.json / benchmark.json are rebuilt fresh by this
    # preflight every morning but were never committed — origin's copies went
    # stale, so GH-Action dashboard rebuilds (fresh checkout) regressed the 🚦
    # guardrail / 🧭 regime / benchmark curve to day-old values until the next
    # local push overwrote them again (found 2026-06-10; same class as the
    # 06-05 sidecar-strip bug). The daily brief commit is their natural ride.
    add_ok, add_out = _git('add', 'memory/', 'portfolio.json', 'assets/data/dashboard.json',
                            'memory/calibration.csv', 'assets/data/risk.json',
                            'assets/data/lev_regime.json', 'assets/data/benchmark.json',
                            'logs/dashboard_build_status.json')
    if not add_ok:
        return False, f'git add failed: {add_out[-200:]}'

    commit_ok, commit_out = _git('commit', '-m', f'memory: daily deep brief {today}{msg_suffix}')
    if not commit_ok and 'nothing to commit' in commit_out:
        return True, 'nothing to commit (idempotent)'
    if not commit_ok:
        return False, commit_out[-200:]

    # Push so Pages picks it up; rebase + retry handles races with GH Action commits
    push_ok, push_out = push_with_rebase_retry()
    if push_ok:
        return True, 'committed + pushed'
    return True, f'committed (push failed: {push_out[-150:]})'


def _ensure_jekyll_front_matter(md_path, date):
    """Prepend Jekyll front matter so Pages can render the brief in-site (not via github.com blob)."""
    if not md_path.exists():
        return
    try:
        content = md_path.read_text()
    except Exception:
        return
    # Already has valid front matter?
    if content.startswith('---\n') and 'layout:' in content.split('---', 2)[1][:200]:
        return
    # Strip stale empty `---\n\n` if present
    if content.startswith('---\n\n') and 'layout:' not in content[:200]:
        content = content[5:].lstrip()
    fm = f'---\nlayout: default\ntitle: 盘前深度简报 · {date}\n---\n\n'
    md_path.write_text(fm + content)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true',
                    help='validate + commit as usual, but do NOT actually send WeChat '
                         '(message send runs with --dry-run). For testing / GH fallback.')
    args = ap.parse_args()

    today = datetime.now().strftime('%Y-%m-%d')
    md_path   = WS / 'memory' / f'{today}-pre-open.md'
    plan_path = WS / 'memory' / f'{today}-plan.json'

    # Ensure Jekyll can render this brief as a Pages page (not just GitHub blob jump)
    _ensure_jekyll_front_matter(md_path, today)

    # Load preflight context (for cross-validation)
    ctx_path = WS / 'memory' / '.tmp' / f'brief-context-{today}.json'
    context = None
    if ctx_path.exists():
        try:
            context = json.loads(ctx_path.read_text())
        except Exception:
            pass

    issues = []
    issues += validate_markdown(md_path, context=context)
    issues += validate_plan_json(plan_path, context=context)

    status = categorize(issues)

    if status == 'pass':
        wechat_prefix = ''
    elif status == 'warn':
        wechat_prefix = (f'⚠️ Validation warnings ({len(issues)}): '
                         + '; '.join(issues[:3])
                         + ('; ...' if len(issues) > 3 else '')
                         + '\n\n')
    else:
        wechat_prefix = (f'🔴 Validation FAILED ({len(issues)} issues), brief 仍发布但未 commit:\n'
                         + '\n'.join('- ' + i for i in issues[:5])
                         + ('\n- ...' if len(issues) > 5 else '')
                         + '\n\n')

    commit_ok, commit_msg = maybe_commit(status, today)

    # ── WeChat delivery (decoupled from the cron's announce) ──────────────────
    # The cron now runs delivery=none. The announce used to fire at the END of a
    # long agent turn with a token captured at turn START → expired mid-turn
    # (#61174) → silent drop while delivered=true (see memory:
    # openclaw-wechat-longturn-token-expiry; brief turns run 173–975s, ALWAYS
    # >160s). We instead send HERE in a short-lived `openclaw message send` that
    # grabs a FRESH token — the SOLE send, so no double, no long-turn drop. Mirrors
    # intraday_postflight. The real result goes to a marker so brief_watchdog only
    # re-sends on a CONFIRMED miss. Card = LLM's brief-card-{date}.txt, else a
    # deterministic compact card from plan.json (build_brief_card).
    wechat_sent = None
    if status in ('pass', 'warn'):
        card = build_brief_card(today)
        message = (wechat_prefix + card).strip()
        first_line = card.strip().splitlines()[0] if card.strip() else ''
        try:
            channel, to, account = resolve_wechat_target()
            wechat_sent, send_out = send_wechat(channel, to, account, message, dry_run=args.dry_run)
        except Exception as e:
            wechat_sent, send_out = False, str(e)[:300]
        marker = WS / 'memory' / '.tmp' / f'brief-sent-{today}.json'
        try:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(json.dumps({
                'ts': int(datetime.now().timestamp() * 1000),
                'sent_ok': bool(wechat_sent),
                'first_line': first_line,
                'out': (send_out or '')[-200:],
            }, ensure_ascii=False))
        except Exception as e:
            print(f'warn: brief-sent marker write failed: {e}', file=sys.stderr)
        if not wechat_sent:
            print(f'warn: WeChat send failed (watchdog will retry): {str(send_out)[:200]}',
                  file=sys.stderr)

    result = {
        'status':        status,
        'date':          today,
        'issues':        issues,
        'wechat_prefix': wechat_prefix,
        'wechat_sent':   wechat_sent,
        'commit_ok':     commit_ok,
        'commit_msg':    commit_msg,
        'files_checked': {
            'pre_open_md':  str(md_path),
            'plan_json':    str(plan_path),
        },
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if status == 'pass' else (1 if status == 'warn' else 2)


if __name__ == '__main__':
    sys.exit(main())
