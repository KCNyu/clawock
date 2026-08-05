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
  - --dry-run: normalize the authored plan in memory, validate, add missing Jekyll
    front matter, and write the publish-gate status; do not rewrite the authored
    plan, write the decision ledger, rebuild/commit the dashboard, push, deliver
    messages, or write the delivery marker
"""

import json
import re
import sys
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

# Location-independent root: runs under openclaw cron (local) AND on GH Action
# brief-fallback.yml (checkout dir). parents[2] = workspace root in both. See
# brief_preflight.py for the bug this avoids (hardcoded /root broke the runner).
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts' / 'data'))
from workspace import workspace_root  # noqa: E402

WS = workspace_root(Path(__file__).resolve().parents[2])

sys.path.insert(0, str(WS / 'scripts' / 'data'))
import trading_calendar  # noqa: E402
import decision_v2  # noqa: E402
import workflow_outcomes  # noqa: E402
import risk_discipline  # noqa: E402
import brief_context  # noqa: E402
import brief_decision_packet  # noqa: E402

# Required concepts and the section labels the brief model may legitimately emit.
# The canonical keys preserve the existing missing-section issue text.  The aliases
# come from the prompt that is sent verbatim to the model:
#   skills/daily-deep-brief/SKILL.md
#   - Header / Tier 1 / Tier 2 / Tier 3 / Confidence / Next-Session: lines 503-515
#   - the Chinese Tier/Judge/Confidence/next-session semantics: lines 94, 155-174,
#     296-306, and 480-495
#   - 同行扫描 / Peer Rotation: lines 332-358 and 509
# The Chinese labels are the direct localized renderings of those named concepts;
# 盘前深度简报 is also the prompt's own report name (lines 3 and 635).
REQUIRED_MARKDOWN_SECTIONS = {
    'Header': ('Header', '盘前摘要', '盘前深度简报'),
    'Tier 1': ('Tier 1', '第一层'),
    'Tier 2': ('Tier 2', '第二层'),
    'Tier 3': ('Tier 3', '第三层'),
    'Judge': ('Judge', '裁决'),
    'Confidence': ('Confidence', '信心'),
    'Next-Session': ('Next-Session', 'Next Session', '下一交易时段'),
    '同行扫描': ('同行扫描', 'Peer Rotation'),
}
HKD_USD_BUG_PATTERNS = [
    '合计 -4423', '合计 -4,423', '合计 -4423.0',
]

# Readability is measured separately from substantive validation. A modestly
# long brief remains a usable product; only extreme size becomes a warning.
BRIEF_READABILITY_TARGET_BYTES = 28_000
BRIEF_READABILITY_EXTREME_BYTES = 40_000


def assess_brief_readability(path):
    """Return structured size health without changing the authored brief."""
    try:
        nbytes = Path(path).stat().st_size
    except OSError:
        nbytes = None

    if nbytes is None:
        status = 'unavailable'
        over_by = None
    elif nbytes >= BRIEF_READABILITY_EXTREME_BYTES:
        status = 'extreme'
        over_by = max(0, nbytes - BRIEF_READABILITY_TARGET_BYTES)
    elif nbytes > BRIEF_READABILITY_TARGET_BYTES:
        status = 'advisory'
        over_by = nbytes - BRIEF_READABILITY_TARGET_BYTES
    else:
        status = 'within_budget'
        over_by = max(0, nbytes - BRIEF_READABILITY_TARGET_BYTES)

    return {
        'status': status,
        'bytes': nbytes,
        'target_bytes': BRIEF_READABILITY_TARGET_BYTES,
        'extreme_bytes': BRIEF_READABILITY_EXTREME_BYTES,
        'over_by_bytes': over_by,
    }


def readability_issues(readability):
    """Promote only an extreme overage into normal validation semantics."""
    if readability.get('status') != 'extreme':
        return []
    return [
        'pre-open.md 极端超长 '
        f'{readability.get("bytes")} bytes（≥40KB，完整保留但下次生成须按分段预算收敛）'
    ]


def _section_markers(text):
    """Return real section-marker lines, not incidental aliases in prose."""
    return [
        line.strip()
        for line in text.splitlines()
        if (re.match(r'^\s{0,3}#{1,6}\s+\S', line)
            or re.match(r'^\s{0,3}\*\*\S', line)
            or re.match(r'^\s{0,3}▎\s*\S', line))
    ]


def _marker_has_alias(marker, alias):
    """Match ASCII labels as words and CJK labels as literal phrases."""
    if alias.isascii():
        return re.search(
            rf'(?<![A-Za-z0-9]){re.escape(alias)}(?![A-Za-z0-9])',
            marker,
            re.IGNORECASE,
        ) is not None
    return alias in marker


def validate_generation_references(plan, context=None):
    """Require every plan generation reference to belong to this preflight run."""
    expected_generation = (context or {}).get('generation_id')
    if not expected_generation:
        return []
    cited = []

    def collect_generation_ids(value):
        if isinstance(value, dict):
            for key, nested in value.items():
                if key.endswith('generation_id'):
                    cited.append(nested)
                collect_generation_ids(nested)
        elif isinstance(value, list):
            for nested in value:
                collect_generation_ids(nested)

    collect_generation_ids(plan)
    issues = []
    if plan.get('context_generation_id') != expected_generation:
        issues.append(
            'plan.json context generation_id 缺失或跨代: '
            f'expected={expected_generation}, '
            f'got={plan.get("context_generation_id")}'
        )
    foreign = sorted({
        str(value) for value in cited if value != expected_generation
    })
    if foreign:
        issues.append(
            f'plan.json context generation_id 跨代引用: {foreign}'
        )
    return issues


_NORMALIZATION_OWNED_PLAN_ERRORS = (
    re.compile(
        r'^decision\[\d+\] missing '
        r'(decision_id|episode_id|plan_date|created_at)$'
    ),
    re.compile(r'^decision\[\d+\] schema_version must be 2$'),
)


def _normalization_owned_plan_error(issue):
    """Whether deterministic v2 normalization, rather than the model, owns it."""
    if issue in ('duplicate decision_id None', 'duplicate decision_id '):
        return True
    return any(pattern.fullmatch(issue)
               for pattern in _NORMALIZATION_OWNED_PLAN_ERRORS)


def _normalization_result(issues, normalized, return_plan):
    return (issues, normalized) if return_plan else issues


class _InMemoryPlanPath:
    """Path-compatible validation input backed by a normalized in-memory plan."""

    def __init__(self, path, plan):
        self._path = Path(path)
        self._body = json.dumps(plan, ensure_ascii=False, indent=2) + '\n'

    def exists(self):
        return self._path.exists()

    def read_text(self, *args, **kwargs):
        return self._body

    def __fspath__(self):
        return str(self._path)


def normalize_plan_json(path, ledger_path=None, *, write=True, return_plan=False):
    """Fill only machine-owned v2 fields before validation.

    ``normalize_authored_plan`` also canonicalizes legacy/default values.  Never
    run it over an authored semantic error: doing so could turn a bad action or
    condition into a valid default and let a retry pass without the model
    actually fixing its plan.  Raw v2 validation therefore runs first and only
    missing deterministic ids/linkage/timestamps are exempted.

    JSON parse/missing-file diagnostics remain owned by ``validate_plan_json``
    so callers do not receive duplicate issues. With ``write=False`` the
    normalized document stays in memory; ``return_plan=True`` exposes it to the
    validator while preserving the default issue-list return contract.
    """
    if not path.exists():
        return _normalization_result([], None, return_plan)
    try:
        authored = json.loads(path.read_text())
    except json.JSONDecodeError:
        return _normalization_result([], None, return_plan)

    if (authored.get('schema_version') != 2
            or not isinstance(authored.get('decisions'), list)):
        return _normalization_result([], authored, return_plan)

    authored_issues = decision_v2.validate_plan(authored, path)
    semantic_issues = [
        issue for issue in authored_issues
        if not _normalization_owned_plan_error(issue)
    ]
    if semantic_issues:
        issues = [f'plan.json authored: {issue}' for issue in semantic_issues]
        return _normalization_result(issues, authored, return_plan)

    try:
        normalized = decision_v2.normalize_authored_plan(
            authored,
            ledger_path or (WS / 'memory' / 'decisions.jsonl'),
        )
        if write and normalized != authored:
            path.write_text(
                json.dumps(normalized, ensure_ascii=False, indent=2) + '\n'
            )
    except Exception as exc:
        return _normalization_result(
            [f'plan.json 标准化失败: {exc}'], authored, return_plan
        )
    return _normalization_result([], normalized, return_plan)


def validate_plan_json(path, context=None, decision_packet=None):
    if not path.exists():
        return ['plan.json 缺失（critical）']
    try:
        plan = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        return [f'plan.json 解析失败: {e}']

    issues = [f'plan.json v2: {x}' for x in decision_v2.validate_plan(plan, path)]
    issues += validate_generation_references(plan, context)
    if decision_packet:
        issues += [
            f'plan.json harness: {item}'
            for item in brief_decision_packet.validate_plan_constraints(
                plan, decision_packet
            )
        ]
    decisions = plan.get('decisions', []) if isinstance(plan.get('decisions'), list) else []
    # Unpriceable calls score for direction but never reach the money chart.
    issues += [f'plan.json size: {x}' for x in decision_v2.missing_size_warnings(decisions)]
    issues += [
        f'plan.json calibration: {x}'
        for x in decision_v2.missing_regime_warnings(decisions)
    ]
    for i, d in enumerate(decisions):
        tag = f'plan.json decision[{i}] ({d.get("ticker", "?")}/{d.get("strategy_id", "?")})'
        # Active timing calls need a hard catalyst. Deterministic risk-rebalance is
        # the explicit exception: it is policy execution, not discretionary alpha.
        if (d.get('action') in decision_v2.ACTIVE_ACTIONS
                and d.get('strategy_id') != 'risk_rebalance'
                and d.get('driven_by') != 'catalyst'):
            issues.append(f'{tag}: catalyst-gate — 主动 {d.get("action")} 必须 driven_by=catalyst；'
                          'risk_rebalance 才允许 risk_rule/technical')

        # When the deterministic evidence graph is present, "catalyst" is no
        # longer a free-text escape hatch. An active discretionary call must cite
        # a current, primary/reliable, novel, price/volume-confirmed negative
        # event that the graph explicitly admitted.
        graph = (context or {}).get('news_evidence_graph') or {}
        if (graph and d.get('action') in decision_v2.ACTIVE_ACTIONS
                and d.get('strategy_id') != 'risk_rebalance'
                and d.get('driven_by') == 'catalyst'):
            event_id = d.get('evidence_event_id')
            actionable = {
                event.get('event_id'): event
                for event in graph.get('events') or []
                if event.get('actionable_escalation')
            }
            event = actionable.get(event_id)
            if not event:
                issues.append(
                    f'{tag}: news-evidence-gate — 主动 catalyst 动作必须填写 '
                    'evidence_event_id，且对应事件 actionable_escalation=true'
                )
            elif d.get('ticker') not in (
                    event.get('ticker'), event.get('reported_ticker')):
                issues.append(
                    f'{tag}: news-evidence-gate — {event_id} 属于 '
                    f'{event.get("reported_ticker") or event.get("ticker")}，'
                    f'不能驱动 {d.get("ticker")}'
                )

    # 仓位/杠杆硬闸闭环 (warn): context.risk_guardrail 的每条 breach / hard_stop
    # 必须在 plan 里有对应的减仓动作，否则 LLM 忽略了硬闸。见 SKILL「🚦 仓位/杠杆硬闸」。
    gr = (context or {}).get('risk_guardrail') or {}
    discipline = (context or {}).get('risk_discipline') or {}
    portfolio = (context or {}).get('portfolio') or {}
    issues += [
        f'风险增仓冻结: {issue}'
        for issue in risk_discipline.validate_exposure_increases(
            decisions, discipline, portfolio)
    ]
    if gr.get('breach_count'):
        TRIM = {'trim_on_rebound', 'cut'}
        def _leg(t): return 'HK' if str(t).isdigit() else 'US'
        trims = [d for d in decisions if d.get('action') in TRIM and d.get('strategy_id') == 'risk_rebalance']
        trim_tickers = {d.get('ticker') for d in trims}
        trim_legs = {_leg(d.get('ticker')) for d in trims}
        durable_overrides = {
            row.get('breach_id')
            for row in discipline.get('records') or []
            if risk_discipline.override_is_active(row)
        }
        for b in gr.get('breaches', []):
            tk, leg = b.get('ticker'), b.get('leg')
            if b.get('breach_id') in durable_overrides:
                continue
            if tk and tk not in trim_tickers:
                issues.append(f'仓位硬闸未处理: {b["type"]} {tk} ({b["detail"]}) — '
                              f'plan 里 {tk} 没有 trim/cut 动作（SKILL 要求每条 breach 出对应动作）')
            elif not tk and leg and leg not in trim_legs:
                issues.append(f'仓位硬闸未处理: {b["type"]}/{leg} ({b["detail"]}) — '
                              f'plan 里 {leg} leg 没有任何 trim/cut 动作')
        for s in gr.get('hard_stop_watch', []):
            if s.get('breach_id') in durable_overrides:
                continue
            cut_tickers = {
                d.get('ticker') for d in trims if d.get('action') == 'cut'
            }
            if s.get('ticker') not in cut_tickers:
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
    markers = _section_markers(text)
    for concept, aliases in REQUIRED_MARKDOWN_SECTIONS.items():
        if not any(_marker_has_alias(marker, alias)
                   for marker in markers for alias in aliases):
            issues.append(f'pre-open.md 缺段标记 "{concept}"')

    for bug in HKD_USD_BUG_PATTERNS:
        if bug in text:
            issues.append(f'pre-open.md 出现历史 bug 模式 "{bug}" (HKD+USD 直接相加)')

    if 'HHI' not in text and 'hhi' not in text:
        issues.append('pre-open.md 未提及 HHI（集中度风险段漏掉？）')

    if 'USDHKD' not in text and 'FX' not in text and '汇率' not in text:
        issues.append('pre-open.md 未提及 FX rate / 汇率')

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
        # Only enforce when macro is known-fresh. age None = unknown/stale (preflight
        # now omits stale sidecars, but if one reaches here, don't demand the section
        # off unprovable-fresh data — that would fail a correctly-omitted section).
        if (age is not None and age <= STALE_H) and m.get('vix') and '▎大盘速读' not in text:
            issues.append('pre-open.md 缺 ▎大盘速读 段（context.macro 有 fresh 数据 '
                          f'age={age}h 但 LLM 没写）')
    if context and context.get('sentiment'):
        s = context['sentiment']
        age = s.get('age_hours')
        tickers = s.get('tickers') or []
        if (age is not None and age <= STALE_H) and tickers and '▎社交舆情' not in text:
            issues.append(f'pre-open.md 缺 ▎社交舆情速读 段（context.sentiment '
                          f'{len(tickers)} 个 ticker 有信号 age={age}h 但 LLM 没写）')

    return issues


CRITICAL_KEYWORDS = [
    '缺失', '解析失败', '表格 #', 'generation_id',
    'plan.json harness', 'plan.json 标准化失败', 'decision packet 不可用',
]  # table mismatch and cross-generation output are critical


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
    """Upsert today's validated, normalized plan into the v2 decision ledger."""
    plan_path = WS / 'memory' / f'{today}-plan.json'

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
    # The four dashboard outputs are deliberately absent: #314 untracked them,
    # and `git add` on a gitignored path fails rather than skipping — it would
    # abort this entire commit, which carries portfolio.json, the decision
    # ledger and the whole preflight write set.
    add_ok, add_out = _git('add', 'memory/', 'portfolio.json',
                            'memory/decisions.jsonl', 'assets/data/risk.json',
                            'assets/data/lev_regime.json', 'assets/data/benchmark.json',
                            'assets/data/quant_signals.json',
                            'assets/data/quant_signals_history.jsonl',
                            'assets/data/quant_signal_review.json',
                            'assets/data/cross_sectional_factor.json',
                            'assets/data/cross_sectional_factor_history.jsonl',
                            'assets/data/peer_residual.json',
                            'assets/data/peer_residual_history.jsonl',
                            'assets/data/catalysts.json',
                            'assets/data/news_evidence_graph.json',
                            'assets/data/news_evidence_history.jsonl',
                            'assets/data/em_news.json',
                            'assets/data/guardrail_history.jsonl',
                            'assets/data/t0_setups.json',
                            'assets/data/t0_setups_history.jsonl',
                            'assets/data/t0_setup_review.json',
                            'assets/data/brief_projection.json',
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
                    help='normalize in memory and validate without rewriting plan.json, '
                         'ledger writes, dashboard rebuild/commit, push, message delivery, '
                         'or delivery-marker writes; still adds missing Jekyll front matter '
                         'and writes the publish-gate status')
    args = ap.parse_args()

    today = datetime.now().strftime('%Y-%m-%d')
    job_name = '盘前深度简报'
    slot = workflow_outcomes.slot_for_job(job_name)

    # Holiday/weekend gate: skip send/commit only when BOTH markets are closed
    # (mirrors brief_preflight; brief still ships if either market trades).
    if trading_calendar.closed_reason('hk') and trading_calendar.closed_reason('us'):
        workflow_outcomes.record_stage(
            job_name, 'preflight', 'skipped', slot=slot, dry_run=args.dry_run,
            reason='both markets closed',
        )
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

    readability = assess_brief_readability(md_path)
    issues = []
    manifest_path = ctx_path.with_suffix('') / 'manifest.json'
    decision_packet = None
    if context and context.get('generation_id'):
        issues += brief_context.validate_run_bundle(ctx_path, manifest_path)
        try:
            decision_packet = brief_decision_packet.read_packet(manifest_path)
        except Exception as exc:
            issues.append(f'decision packet 不可用: {exc}')
    issues += validate_markdown(md_path, context=context)
    issues += readability_issues(readability)
    normalization_issues, normalized_plan = normalize_plan_json(
        plan_path,
        write=not args.dry_run,
        return_plan=True,
    )
    issues += normalization_issues
    validation_path = (
        _InMemoryPlanPath(plan_path, normalized_plan)
        if args.dry_run and normalized_plan is not None
        else plan_path
    )
    issues += validate_plan_json(
        validation_path, context=context, decision_packet=decision_packet
    )

    status = categorize(issues)
    workflow_outcomes.record_stage(
        job_name,
        'preflight',
        'success' if context else 'failed',
        slot=slot,
        dry_run=args.dry_run,
        context_present=bool(context),
    )
    workflow_outcomes.record_stage(
        job_name,
        'llm',
        'success' if status == 'pass' else ('warning' if status == 'warn' else 'failed'),
        slot=slot,
        dry_run=args.dry_run,
        issue_count=len(issues),
        readability=readability,
    )
    # Emit the cross-process publish gate BEFORE anything else can raise, so the
    # off-host workflow's committer has an explicit verdict (and a crash leaves no
    # file → fail-closed).
    write_publish_gate(status, today)

    # Pages consumes a versioned projection, not the model's raw files.  Missing
    # or invalid prose is isolated: deterministic technical/risk rows still
    # publish with judgment_status=missing/invalid, and a projection exception
    # never blocks the report/plan commit.
    projection_path = WS / 'assets' / 'data' / 'brief_projection.json'
    judgment_path = WS / 'memory' / '.tmp' / f'brief-judgment-{today}.json'
    projection_status = 'skipped'
    projection_issues = []
    if status in ('pass', 'warn') and decision_packet and not args.dry_run:
        try:
            projection, projection_issues = (
                brief_decision_packet.write_pages_projection(
                    decision_packet, judgment_path, projection_path
                )
            )
            projection_status = projection.get('judgment_status') or 'written'
        except Exception as exc:
            projection_status = 'failed'
            projection_issues = [str(exc)]
            print(f'warn: brief Pages projection failed: {exc}', file=sys.stderr)

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
    tg_ok = None
    brief_marker = WS / 'memory' / '.tmp' / f'brief-sent-{today}.json'
    # Idempotency: brief marker is per-date, fires once/day. If it already shows a
    # delivery this run is an openclaw auto-retry of a turn that errored only in
    # post-turn summary-gen — the card already went out. Skip re-send. See
    # already_delivered (2026-07-11 retry-storm dup fix).
    if status in ('pass', 'warn') and already_delivered(brief_marker):
        print('idempotency: brief already delivered today — skip re-send', file=sys.stderr)
        wechat_sent = True
        try:
            tg_ok = json.loads(brief_marker.read_text()).get('tg_ok')
        except Exception:
            pass
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
        'projection_status': projection_status,
        'projection_issues': projection_issues,
        'readability': readability,
        'files_checked': {
            'pre_open_md':  str(md_path),
            'plan_json':    str(plan_path),
            'judgment_json': str(judgment_path),
            'pages_projection': str(projection_path),
        },
    }
    workflow_outcomes.record_stage(
        job_name,
        'postflight',
        'success' if status == 'pass' else ('warning' if status == 'warn' else 'failed'),
        slot=slot,
        dry_run=args.dry_run,
        issue_count=len(issues),
        commit_ok=commit_ok,
        readability=readability,
    )
    workflow_outcomes.record_stage(
        job_name,
        'primary_delivery',
        ('success' if (wechat_sent or tg_ok) else
         ('not_required' if status == 'fail' else 'failed')),
        slot=slot,
        dry_run=args.dry_run,
        channel='wechat_or_telegram',
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if status == 'pass' else (1 if status == 'warn' else 2)


if __name__ == '__main__':
    sys.exit(main())
