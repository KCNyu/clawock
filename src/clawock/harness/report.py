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

from clawock.harness.validation import (
    ADVISORY_MARK,
    REPORT_CHAR_LIMITS as CHAR_LIMITS,
    categorize_issues,
    check_md_table_column_consistency,
    check_numeric_claims,
    validate_forbidden_phrases,
)

REQUIRED_SECTIONS = ['▎情绪面', '▎技术面', '▎操作建议']
FORBIDDEN_PHRASES = ['数据待获取', '等待数据', '数据缺失（占位）', 'TODO', 'TBD']

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
    parts = [ctx.get('title', '').strip(),
             (ctx.get('raw_wechat_block') or '').strip(),
             prose.strip()]
    return '\n\n'.join(p for p in parts if p)


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
    for sec in REQUIRED_SECTIONS:
        if sec not in checked:
            issues.append(f'缺段标记 "{sec}"')

    # 2. 风险提示段（若 preflight 标了 needs；模型文本）
    if ctx.get('needs_risk_section') and '▎风险提示' not in checked:
        issues.append('preflight 标 needs_risk_section=true 但未见 "▎风险提示" 段')

    # 3. 长度 —— 按投递全文 (per-market)
    n_chars = len(body)
    soft, hard = CHAR_LIMITS['soft'], CHAR_LIMITS['hard']
    if n_chars > hard:
        issues.append(f'报告长度 {n_chars} 字 > {hard} 上限')
    elif n_chars > soft:
        issues.append(f'报告长度 {n_chars} 字 > {soft} 软上限 (warn)')

    # 4. 异动票必须被提到（模型文本 —— 数据块里本就有票代码，不能拿它顶）
    anomalies = ctx.get('anomalies', [])
    if anomalies:
        mentioned = [a['ticker'] for a in anomalies if a['ticker'] in checked]
        if not mentioned:
            tickers = ', '.join(a['ticker'] for a in anomalies)
            issues.append(f'preflight 标了 {len(anomalies)} 个 ≥3% 异动票 ({tickers}) 但报告全部未提及')

    # 5. 敷衍 phrases（模型文本）
    issues.extend(validate_forbidden_phrases(checked, FORBIDDEN_PHRASES))

    # 6. 数字必须来自 context（模型文本）—— 一条聚合 warn，见 check_numeric_claims
    issues.extend(check_numeric_claims(checked, ctx))

    return issues


CRITICAL_KEYWORDS = ['缺段标记', '敷衍词']


def _is_hard_char_limit(issue):
    """Hard char limit (e.g. '字 > 3500 上限') is critical; soft is not."""
    return '字 >' in issue and '上限' in issue and '软上限' not in issue


def categorize(issues):
    return categorize_issues(
        issues, CRITICAL_KEYWORDS, warn_max=3, extra_critical=_is_hard_char_limit,
    )
