"""The deterministic core of a market report: assemble, then judge.

Moved out of `scripts/harness/report_postflight.py` so it can run from the
installed package with no repository checkout. This is the part `clawock report`
executes directly — it does not shell out to the harness script, because a CLI
that re-invokes the same scripts would be a rename, not independence.

Pure functions over a context dict and the model's prose: no I/O, no git, no
delivery, no workspace paths. The postflight script re-exports them, so its own
twenty-odd regression tests keep exercising exactly this code.
"""
from __future__ import annotations

import re

from clawock import prose_claims
from clawock.harness.validation import (
    FORBIDDEN_PHRASES,
    PLAN_CONSISTENCY,
    REPORT_CHAR_LIMITS as CHAR_LIMITS,
    categorize_issues,
    check_identifier_leak,
    check_numeric_claims,
    with_compute_receipts,
    check_pipeline_self_reference,
    check_plan_consistency,
    has_section_marker,
    is_hard_char_limit,
    section_body,
    mentions_ticker,
    validate_forbidden_phrases,
)

REQUIRED_SECTIONS = ['▎情绪面', '▎技术面', '▎操作建议']
_SECTION_COVERAGE = {
    '▎情绪面': re.compile(
        r'消息|新闻|公告|停牌|异动|财报|板块|同业|同行|指数|市场|盘面|港股|美股|涨|跌|利率|成交|行情|未取到|《'),
    '▎技术面': re.compile(
        r'行情|报价|横盘|跳空|开盘|收盘|均线|涨|跌|破位|冲高|回落|回踩|反弹|高点|低点|'
        r'支撑|压力|量能|成交|走势|放量|缩量|波动|信号|趋势|整理|RSI|MA\d|突破|区间'),
    '▎操作建议': re.compile(
        r'计划|触发|持有|仓位|止损|卖|买|减仓|加仓|复核|订单|成交|观望|观察|等[^。！？\n]'),
    '▎风险提示': re.compile(r'风险|敞口|失效|止损|回撤|杠杆|集中|红线|触发|停牌|未取到'),
}
_EMPTY_OBSERVATION = re.compile(r'^[\s*。！?！？、]+|[\s*。！?！？、]+$')
_COVERAGE_ISSUE = '正文覆盖不足'
_ANOMALY_ISSUE = '异动归因漏写'
_NEWS_ISSUE = '逐票资讯漏引'

def _unusable_context(ctx):
    """Reason string if the context can't back a report, else None.

    preflight writes blockless sentinels (status preflight_failed / market_closed)
    that carry none of the deterministic fields postflight assembles from. Anything
    but a 'ok' status with a nonempty raw block + title + commit_msg + context_id
    is not a report context.
    """
    if ctx.get('status') != 'ok':
        return f'context status={ctx.get("status")!r}（preflight 未产出可用数据），跳过投递+commit'
    missing = [k for k in ('raw_wechat_block', 'title', 'commit_msg', 'context_id')
               if not (ctx.get(k) or '').strip()]
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
    # kcn 2026-10-19: the same sectioned card as the intraday check-in
    # (chat_card) — open orders and broken stops first, then the table,
    # signals, news one line per ticker, and the prose under bold labels.
    from clawock.harness.chat_card import render_report
    from clawock.decision.plans import plan_holds
    review = ctx.get('risk_followups')
    legacy_debts = 'notices' not in (review or {})
    return render_report(ctx.get('title', '').strip(),
                         (ctx.get('raw_wechat_block') or '').strip(), prose,
                         held=plan_holds(ctx.get('plan_context')),
                         debts=(ctx.get('risk_debts') or ()) if legacy_debts else (),
                         debts_error=ctx.get('risk_debts_error') if legacy_debts else None,
                         session_review=ctx.get('session_review'),
                         risk_followups=review)


def fallback_block(ctx):
    """Keep the analyzer first line used by receipts; include deterministic reviews."""
    from clawock.harness.chat_card import review_sections
    block = (ctx.get('raw_wechat_block') or '').strip()
    extra = review_sections(ctx.get('session_review'), ctx.get('risk_followups'))
    return block + ('\n' + '\n'.join(extra) if extra else '')


def validate(body, ctx, model_text):
    """Validate the delivered message.

    `body` is what gets sent; `model_text` is the part the MODEL wrote — the prose
    alone. The content rules — sections, risk section, anomaly mention, forbidden
    phrases — MUST run against model_text, never body: assemble_message has already
    prepended the raw data block, and that block itself contains the anomaly tickers
    and (potentially) section-looking tokens, so checking body would let prose that
    mentions none of the movers pass because the table does. Only the length limit
    is a property of the assembled body. (2026-07-24 review.)
    """
    issues = []
    checked = model_text

    # 1. 必有三段标记（模型文本）
    # 标记须自成一行开头，句中点名不算（#2049）
    for sec in REQUIRED_SECTIONS:
        if not has_section_marker(checked, sec):
            issues.append(f'缺段标记 "{sec}"')

    # 2. 风险提示段（若 preflight 标了 needs；模型文本）
    if ctx.get('needs_risk_section') and not has_section_marker(checked, '▎风险提示'):
        issues.append('preflight 标 needs_risk_section=true 但未见 "▎风险提示" 段')

    # 3. 长度 —— 按投递全文 (per-market)
    n_chars = len(body)
    soft, hard = CHAR_LIMITS['soft'], CHAR_LIMITS['hard']
    if n_chars > hard:
        issues.append(f'报告长度 {n_chars} 字 > {hard} 上限')
    elif n_chars > soft:
        issues.append(f'报告长度 {n_chars} 字 > {soft} 软上限 (warn)')

    # The generated data block already names movers. Each belongs in the
    # sentiment narrative, where the reader can see what explains the move.
    sentiment = section_body(checked, '▎情绪面')
    missing = [row['ticker'] for row in (ctx.get('anomalies') or [])
               if not mentions_ticker(sentiment, row['ticker'])]
    if missing:
        issues.append(f'{_ANOMALY_ISSUE}（情绪面）：{"、".join(missing)}')

    if prose_claims.enabled(ctx):
        sections = [*REQUIRED_SECTIONS, '▎风险提示'] if ctx.get('needs_risk_section') else REQUIRED_SECTIONS
        for section in sections:
            prose = _EMPTY_OBSERVATION.sub('', section_body(checked, section))
            anchors = _SECTION_COVERAGE[section]
            if has_section_marker(checked, section) and (
                    not anchors.search(prose) or anchors.fullmatch(prose)):
                issues.append(f'{_COVERAGE_ISSUE}：{section}')
        for extra in ('▎异动归因', '▎证据'):
            if has_section_marker(checked, extra):
                issues.append(f'{_COVERAGE_ISSUE}：把 {extra} 写入对应段落')

    # 5. 敷衍 phrases（模型文本）
    issues.extend(validate_forbidden_phrases(checked, FORBIDDEN_PHRASES))

    # 6. Reconcile explicit numeric fields. Legacy prose also gets a provenance advisory.
    issues.extend(check_numeric_claims(checked, ctx))

    # 7. 管线术语（模型文本）—— advisory，见 check_pipeline_self_reference
    issues.extend(check_pipeline_self_reference(checked))

    # 8. 字段名/枚举值（模型文本）—— escalating，与盘中（#1870）和简报同一把闸。
    # 词表点不到每个 key：2026-09-29 港股开盘/午盘/收盘三份报告都把
    # `hold_and_watch` 原样发进了微信，postflight 印 pass（#2146）。
    issues.extend(check_identifier_leak(checked, label='散文'))

    # 9. 正文与今日计划、风控账本、持仓策略说反话（模型文本）—— escalating，
    # 一条聚合，见 check_plan_consistency（2026-10-26 港股收盘 / 美股开盘）。
    issues.extend(check_plan_consistency(checked, ctx))

    return issues


def live_news_references(ctx):
    """Exact report pointers for current per-holding news, preferring filings."""
    references = {}
    for ticker, rows in ((ctx.get('live_information') or {}).get('summary') or {}).items():
        # Same-day filings with incomplete clock precision have stale=None.
        # Retain them without treating them as intraday news.
        current = [i for i, row in enumerate(rows) if row.get('cite')
                   and (row.get('stale') is False
                        or (row.get('stale') is None and row.get('filed_date')))]
        primary = [i for i in current if rows[i].get('grade') == 'primary']
        if current:
            escaped = ticker.replace('~', '~0').replace('/', '~1')
            references[ticker] = [f'/ctx/live_information/summary/{escaped}/{i}'
                                  for i in (primary or current)]
    return references


def _live_news_coverage(draft, ctx):
    sentiment = section_body(draft, '▎情绪面')
    refs = {match[1] for match in prose_claims.TOKEN.finditer(sentiment)}
    missing = [ticker for ticker, paths in live_news_references(ctx).items()
               if not any(path + suffix in refs for path in paths for suffix in ('|cite', '/cite'))]
    return [f'{_NEWS_ISSUE}（情绪面）：{"、".join(missing)}'] if missing else []


def prepare_report(ctx, draft, workspace, *, validator=validate):
    """Resolve authored references before assembling and checking the reader text."""
    ctx = with_compute_receipts(ctx, workspace)
    issues = []
    if prose_claims.enabled(ctx):
        renderer = prose_claims.ClaimRenderer(ctx, receipts=ctx.get('compute_receipts', ()))
        news_findings = _live_news_coverage(draft, ctx)
        draft = renderer.render(draft, '报告')
        issues = [*renderer.issues, *renderer.advisories, *news_findings]
    body = assemble_message(ctx, draft)
    return body, [*issues, *validator(body, ctx, draft)]


CRITICAL_KEYWORDS = [
    '缺段标记', '敷衍词', 'needs_risk_section=true', prose_claims.ISSUE,
    PLAN_CONSISTENCY, '仓位支配度不符', _COVERAGE_ISSUE, _ANOMALY_ISSUE, _NEWS_ISSUE,
]


def categorize(issues):
    return categorize_issues(
        issues, CRITICAL_KEYWORDS, warn_max=3, extra_critical=is_hard_char_limit,
    )
