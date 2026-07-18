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
  - status=pass: rebuild dashboard, commit scoped report artifacts, deliver WeChat + Telegram
  - status=warn: same as pass but commit msg flags validation warnings
  - status=fail: no commit or delivery (preserve commit history clean); print issues
  - --dry-run: validate, add missing Jekyll front matter, and write the publish-gate status;
    do not write the decision ledger, rebuild/commit the dashboard, push, deliver messages,
    or write the delivery marker
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

sys.path.insert(0, str(WS / 'scripts' / 'data'))
import trading_calendar  # noqa: E402
import decision_v2  # noqa: E402

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

    issues = [f'plan.json v2: {x}' for x in decision_v2.validate_plan(plan, path)]
    decisions = plan.get('decisions', []) if isinstance(plan.get('decisions'), list) else []
    # Unpriceable calls score for direction but never reach the money chart.
    issues += [f'plan.json size: {x}' for x in decision_v2.missing_size_warnings(decisions)]
    for i, d in enumerate(decisions):
        tag = f'plan.json decision[{i}] ({d.get("ticker", "?")}/{d.get("strategy_id", "?")})'
        # Active timing calls need a hard catalyst. Deterministic risk-rebalance is
        # the explicit exception: it is policy execution, not discretionary alpha.
        if (d.get('action') in decision_v2.ACTIVE_ACTIONS
                and d.get('strategy_id') != 'risk_rebalance'
                and d.get('driven_by') != 'catalyst'):
            issues.append(f'{tag}: catalyst-gate — 主动 {d.get("action")} 必须 driven_by=catalyst；'
                          'risk_rebalance 才允许 risk_rule/technical')

    # 仓位/杠杆硬闸闭环 (warn): context.risk_guardrail 的每条 breach / hard_stop
    # 必须在 plan 里有对应的减仓动作，否则 LLM 忽略了硬闸。见 SKILL「🚦 仓位/杠杆硬闸」。
    gr = (context or {}).get('risk_guardrail') or {}
    if gr.get('breach_count'):
        TRIM = {'trim_on_rebound', 'cut'}
        def _leg(t): return 'HK' if str(t).isdigit() else 'US'
        trims = [d for d in decisions if d.get('action') in TRIM and d.get('strategy_id') == 'risk_rebalance']
        trim_tickers = {d.get('ticker') for d in trims}
        trim_legs = {_leg(d.get('ticker')) for d in trims}
        overridden = {d.get('ticker') for d in decisions
                      if (d.get('override') or {}).get('status') == 'active'}
        for b in gr.get('breaches', []):
            tk, leg = b.get('ticker'), b.get('leg')
            if tk and tk not in trim_tickers and tk not in overridden:
                issues.append(f'仓位硬闸未处理: {b["type"]} {tk} ({b["detail"]}) — '
                              f'plan 里 {tk} 没有 trim/cut 动作（SKILL 要求每条 breach 出对应动作）')
            elif not tk and leg and leg not in trim_legs:
                issues.append(f'仓位硬闸未处理: {b["type"]}/{leg} ({b["detail"]}) — '
                              f'plan 里 {leg} leg 没有任何 trim/cut 动作')
        for s in gr.get('hard_stop_watch', []):
            if s.get('ticker') not in {d.get('ticker') for d in trims if d.get('action') == 'cut'} \
                    and s.get('ticker') not in overridden:
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

    # 体量卫生 (2026-05-31): WeChat 只发紧凑结论卡（Step 4-D），pre-open.md 仅作 dashboard
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
    dashboard_output_changes,
    git_cmd as _git,
    push_with_rebase_retry,
    rebuild_dashboard,
)
from _watchdog_common import (  # noqa: E402
    resolve_wechat_target, send_wechat, build_brief_card, cosend_telegram, already_delivered,
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


def log_decisions(today):
    """Normalize and upsert today's plan into the v2 decision ledger."""
    plan_path = WS / 'memory' / f'{today}-plan.json'

    # V2 authoring keeps semantic fields human/LLM-readable; deterministic ids,
    # episode linkage and evaluation defaults are filled here before validation.
    if plan_path.exists():
        try:
            authored = json.loads(plan_path.read_text())
            if authored.get('schema_version') == 2 and isinstance(authored.get('decisions'), list):
                authored = decision_v2.normalize_authored_plan(authored)
                plan_path.write_text(json.dumps(authored, ensure_ascii=False, indent=2) + '\n')
        except Exception as e:
            print(f'warn: v2 plan normalization failed: {e}', file=sys.stderr)
    if not plan_path.exists():
        return
    try:
        plan = json.loads(plan_path.read_text())
    except Exception:
        return
    if plan.get('schema_version') != 2 or not plan.get('decisions'):
        return
    for d in plan['decisions']:
        if d.get('simulated_entry_price') is None:
            d['simulated_entry_price'] = _current_price_for(d.get('ticker'))
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + '\n')
    inserted, updated = decision_v2.upsert_plan_decisions(plan)
    ledger = decision_v2.load_decisions()
    settled = decision_v2.settle_decisions(ledger)
    decision_v2.write_decisions(ledger)
    print(f'  decisions.jsonl: +{inserted}, updated {updated}, settled {settled} ({len(ledger)} total)')


def write_publish_gate(status, today):
    """Machine-readable publish gate the off-host fallback workflow reads before it
    commits. The fallback runs on a fresh GH-Action checkout where a broad
    `git add … && commit && push` is its own committer and cannot see maybe_commit's
    `status == 'fail'` refusal — so a failing brief was published anyway. This file
    carries the same verdict across the process boundary. Fail-closed by contract:
    the workflow must treat a MISSING file (postflight crashed before here) as
    do-not-publish, so only an explicit publish_ok=true releases a commit."""
    gate = {'today': today, 'status': status, 'publish_ok': status != 'fail',
            'written_at': datetime.now().isoformat()}
    p = WS / 'logs' / 'brief_postflight_status.json'
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(gate, ensure_ascii=False) + '\n')
    return gate


def maybe_commit(status, today, dry_run=False):
    if status == 'fail':
        return False, 'skipped (status=fail)'
    # --dry-run used to reach ONLY send_wechat/cosend_telegram, so `postflight --dry-run`
    # still ran log_decisions + rebuilt the dashboard + committed + PUSHED — i.e. it
    # published for real while reporting itself as a dry run (2026-07-16: a --dry-run
    # meant as a validation check pushed the day's brief to origin). A dry run must not
    # write to the ledger or to origin.
    if dry_run:
        return False, 'skipped (dry-run)'

    log_decisions(today)   # upsert today's v2 plan (idempotent)
    rebuild_dashboard()
    dashboard_paths = dashboard_output_changes()

    msg_suffix = ' (validation warnings)' if status == 'warn' else ''
    # risk.json / lev_regime.json / benchmark.json are rebuilt fresh by this
    # preflight every morning but were never committed — origin's copies went
    # stale, so GH-Action dashboard rebuilds (fresh checkout) regressed the 🚦
    # guardrail / 🧭 regime / benchmark curve to day-old values until the next
    # local push overwrote them again (found 2026-06-10; same class as the
    # 06-05 sidecar-strip bug). The daily brief commit is their natural ride.
    # The rest of preflight's write set, added 2026-07-16 for the same reason and
    # found the same way: each is built fresh every morning and was never committed,
    # so origin only moved when an unrelated commit happened to sweep it up
    # (t0_setups/em_news last rode in on a docs commit, 940aaa9). Between those
    # accidents the public dashboard served stale Chinese news and a T0 history with
    # holes, and guardrail_history — which README leans on for the "风控纪律" claim —
    # silently lost samples on every fresh checkout. macro/sentiment/influencer/
    # us_news_digest are deliberately NOT here: GH Actions own those, preflight only
    # reads them, and committing them from this side would fight the workflow.
    add_ok, add_out = _git('add', 'memory/', 'portfolio.json', *dashboard_paths,
                            'memory/decisions.jsonl', 'assets/data/risk.json',
                            'assets/data/lev_regime.json', 'assets/data/benchmark.json',
                            'assets/data/quant_signals.json',
                            'assets/data/quant_signals_history.jsonl',
                            'assets/data/quant_signal_review.json',
                            'assets/data/catalysts.json',
                            'assets/data/em_news.json',
                            'assets/data/guardrail_history.jsonl',
                            'assets/data/t0_setups.json',
                            'assets/data/t0_setups_history.jsonl',
                            'assets/data/t0_setup_review.json',
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
    # Per-page meta description → unique, keyword-rich (the `default` layout emits it
    # as <meta name=description>). Without this every brief falls back to the site-wide
    # description = duplicate meta across all pages = near-zero long-tail SEO. The date
    # makes each one unique; the keywords target the topics people actually search.
    desc = (f'clawock 盘前深度简报 {date}：港股 + 美股真实持仓的多空辩论、量化因子、'
            f'风控硬闸与 AI 自评战绩（诚实公开，承认主动操作跑输躺平）。')
    fm = (f'---\nlayout: default\ntitle: 盘前深度简报 · {date}\n'
          f'description: "{desc}"\n---\n\n')
    md_path.write_text(fm + content)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true',
                    help='validate without ledger writes, dashboard rebuild/commit, push, '
                         'message delivery, or delivery-marker writes; still adds missing '
                         'Jekyll front matter and writes the publish-gate status')
    args = ap.parse_args()

    today = datetime.now().strftime('%Y-%m-%d')

    # Holiday/weekend gate: skip send/commit only when BOTH markets are closed
    # (mirrors brief_preflight; brief still ships if either market trades).
    if trading_calendar.closed_reason('hk') and trading_calendar.closed_reason('us'):
        result = {'status': 'market_closed', 'date': today, 'wechat_sent': False,
                  'issues': ['港股+美股均休市，跳过简报投递+commit']}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

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
    # Emit the cross-process publish gate BEFORE anything else can raise, so the
    # off-host workflow's committer has an explicit verdict (and a crash leaves no
    # file → fail-closed).
    write_publish_gate(status, today)

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

    commit_ok, commit_msg = maybe_commit(status, today, dry_run=args.dry_run)

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
    brief_marker = WS / 'memory' / '.tmp' / f'brief-sent-{today}.json'
    # Idempotency: brief marker is per-date, fires once/day. If it already shows a
    # delivery this run is an openclaw auto-retry of a turn that errored only in
    # post-turn summary-gen — the card already went out. Skip re-send. See
    # already_delivered (2026-07-11 retry-storm dup fix).
    if status in ('pass', 'warn') and already_delivered(brief_marker):
        print('idempotency: brief already delivered today — skip re-send', file=sys.stderr)
        wechat_sent = True
    elif status in ('pass', 'warn'):
        card = build_brief_card(today)
        message = (wechat_prefix + card).strip()
        first_line = card.strip().splitlines()[0] if card.strip() else ''
        try:
            channel, to, account = resolve_wechat_target()
            wechat_sent, send_out = send_wechat(channel, to, account, message, dry_run=args.dry_run)
        except Exception as e:
            wechat_sent, send_out = False, str(e)[:300]
        # Always co-send to Telegram (cold-proof) — WeChat can't confirm real delivery.
        # Record the Telegram result: it's the sole backstop brief_watchdog now uses
        # (no more WeChat resend), so it needs to know if TG already got this card.
        tg_ok, _tg_out = cosend_telegram(message, 'brief', dry_run=args.dry_run)
        # NEVER write the marker on a dry run (2026-07-16). send_wechat/cosend_telegram
        # return ok=True for a dry run (the CLI exits 0 without sending), so this used to
        # record sent_ok/tg_ok=true for a delivery that never happened. brief_watchdog
        # treats a fresh marker with tg_ok as its SOLE proof the card landed, so one
        # dry run silently disabled that day's backstop — exactly the "card never
        # arrived and nothing noticed" hole the watchdog exists to close. Hit for real:
        # a --dry-run postflight at 10:14 today wrote a marker claiming delivery while
        # kcn got nothing.
        if args.dry_run:
            print('dry-run: skipping brief-sent marker write', file=sys.stderr)
        else:
            try:
                brief_marker.parent.mkdir(parents=True, exist_ok=True)
                brief_marker.write_text(json.dumps({
                    'ts': int(datetime.now().timestamp() * 1000),
                    'sent_ok': bool(wechat_sent),
                    'tg_ok': bool(tg_ok),
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
