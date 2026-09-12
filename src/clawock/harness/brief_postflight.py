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
from datetime import datetime
from pathlib import Path

from clawock.workspace import workspace_root
from clawock.safe_io import safe_write_json, safe_write_text
from clawock import sessions as trading_calendar
from clawock.context import brief as brief_context
from clawock.decision import ledger as decision_v2
from clawock.decision import packet as brief_decision_packet
from clawock.decision import risk as risk_discipline

WS = workspace_root()
_CHECKOUT = WS

from clawock.automation import workflow_outcomes  # noqa: E402
from clawock.automation import delivery_receipts  # noqa: E402

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
# The section names the rendered report must still contain. 2026-09-06 regrouped
# twenty flat sections into four parts (`brief_render.render_brief`), so the old
# names moved — and this table is a THIRD place that has to move with them, next
# to SKILL.md and the cron payload. It was the only thing that noticed: rendering
# the new layout against a real generation produced six "缺段标记" issues here
# while the markdown itself was perfectly valid.
#
# Aliases keep the old names accepted so a brief rendered before the change (or
# by a rolled-back harness) still validates rather than being called broken.
REQUIRED_MARKDOWN_SECTIONS = {
    'Header': ('Header', '盘前摘要', '盘前深度简报'),
    '分析师四格': ('分析师四格', 'Tier 1', '第一层'),
    '多空对辩': ('多空对辩', 'Tier 2', '第二层'),
    '风险官三票': ('风险官三票', 'Tier 3', '第三层'),
    '今日动作': ('今日动作', 'Judge', '裁决'),
    '信心与判定': ('信心与判定', 'Confidence', '信心'),
    '下一节点': ('下一节点', 'Next-Session', 'Next Session', '下一交易时段'),
    '同行扫描': ('同行扫描', 'Peer Rotation'),
}
HKD_USD_BUG_PATTERNS = [
    '合计 -4423', '合计 -4,423', '合计 -4423.0',
]

# Readability is measured separately from substantive validation. A modestly
# long brief remains a usable product; only extreme size becomes a warning.
BRIEF_READABILITY_TARGET_BYTES = 28_000
BRIEF_READABILITY_EXTREME_BYTES = 40_000


_LAYOUT_TAG = re.compile(r'</?(?:div|span|details|summary)\b[^>]*>')
_TABLE_RULE = re.compile(r'\|?[\s:|-]+\|?')


def reader_bytes(text):
    """Bytes of what a reader reads: the words, not the layout around them.

    The thresholds below are a reading-burden budget, but they used to be
    compared with the file size. On 2026-09-11 the report moved from prose
    tables to one card per subsection and one block per prose row
    (`brief_render.card` / `entries`): the same words, and 4–5KB more file per
    brief of `<div markdown="1">` wrappers, indentation and blank lines. Three
    of the five briefs from 09-07 to 09-11 would have jumped from `advisory` to
    `extreme` — a warning every morning about markup nobody sees.

    Counted here: front matter, layout tags, table rules and pipes, list and
    heading markers, `**`, and runs of whitespace all removed. Measured on those
    same five briefs, this count under the new layout gives the same status as
    the raw file size gave under the old one, on every day — so the 28KB/40KB
    lines keep the meaning they were calibrated with.
    """
    if text.startswith('---\n'):
        _, _, text = text[4:].partition('\n---\n')
    kept = []
    for line in _LAYOUT_TAG.sub('', text).splitlines():
        line = line.strip()
        if not line or _TABLE_RULE.fullmatch(line):
            continue
        line = re.sub(r'^(?:[-*]|\d+\.)\s+', '', line)
        line = re.sub(r'^#{1,6}\s+', '', line)
        line = line.replace('|', ' ').replace('**', '')
        kept.append(re.sub(r'\s+', ' ', line).strip())
    return len('\n'.join(kept).encode('utf-8'))


def assess_brief_readability(path):
    """Return structured size health without changing the authored brief.

    `bytes` is the reader-visible count that decides `status` (see
    `reader_bytes`) — it is what the dashboard shows beside the status and what
    the warning quotes. `file_bytes` is the raw size, kept for anyone tracking
    the artifact itself.
    """
    try:
        text = Path(path).read_text(encoding='utf-8')
        file_bytes = len(text.encode('utf-8'))
        nbytes = reader_bytes(text)
    except (OSError, UnicodeDecodeError):
        nbytes = file_bytes = None

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
        'file_bytes': file_bytes,
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
        f'{readability.get("bytes")} bytes 正文（≥40KB，版式标记不计；完整保留但下次生成须按分段预算收敛）'
    ]


def _section_markers(text):
    """Return real section markers, not incidental aliases in prose.

    A heading or `▎` line is a marker as a whole. A bold marker is only its bold
    text: since 2026-09-11 every prose row in the report is laid out as
    `  **理由**　<the reasoning>` (`brief_render.entries`), and counting that
    whole line let the reasoning itself satisfy a required section — the
    09-11 rationale for 07226 contains "Judge 段明确要求…", which is an alias
    for 今日动作. The label is the name; the sentence after it is prose.
    """
    markers = []
    for line in text.splitlines():
        if (re.match(r'^\s{0,3}#{1,6}\s+\S', line)
                or re.match(r'^\s{0,3}▎\s*\S', line)):
            markers.append(line.strip())
            continue
        bold = re.match(r'^\s{0,3}\*\*(\S.*?)\*\*', line)
        if bold:
            markers.append(bold.group(1).strip())
    return markers


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


def _citable_refs(context) -> set[str]:
    """Every debate citation this morning's context can actually back (#1141).

    One set, built once per plan, in the three namespaces
    `decision.ledger.DEBATE_EVIDENCE_NAMESPACES` declares. A namespace exists
    only where the context carries something stable to point at — an event id,
    a breach, a computed signal field — because a citation nobody can resolve
    reads as evidence without being any.
    """
    refs: set[str] = set()
    context = context or {}

    graph = context.get('news_evidence_graph') or {}
    for event in graph.get('events') or []:
        # The one the row advertises first, for the same reason as the
        # guardrail rows below: it is the string the model was handed.
        advertised = str((event or {}).get('evidence_id') or '').strip()
        if advertised:
            refs.add(advertised)
        event_id = str((event or {}).get('event_id') or '').strip()
        if event_id:
            refs.add(f'news:{event_id}')

    guardrail = context.get('risk_guardrail') or {}
    for key in risk_discipline.GUARDRAIL_ROW_KEYS:
        rows = guardrail.get(key) or []
        # A list whose rows all share one `type` has an unambiguous second
        # name: the key it is filed under. `hard_stop_watch` holds only
        # `leveraged_hard_stop` rows, so `risk:hard_stop_watch:RKLX` and
        # `risk:leveraged_hard_stop:RKLX` are the same row — and the context
        # hands the model BOTH names, the key wrapping the row and the type
        # inside it. On 2026-09-10 it took the outer one twice.
        #
        # Only for a homogeneous list, and that is computed, not listed:
        # `breaches` carries four different types, so `risk:breaches:07226`
        # would name a row without saying which, and a citation that vague is
        # the thing this resolver exists to refuse. Accepting the alias is not
        # a loosening — every alias still resolves to a row that is really
        # there, and the invented ones are dropped exactly as before.
        kinds = {str((row or {}).get('type') or '').strip() for row in rows}
        kinds.discard('')
        alias = key if len(kinds) == 1 else None
        for row in rows:
            # The one the row itself advertises. Reading the same field the
            # context hands the model is what makes "copy this" true — a
            # second spelling of the grammar here is a second thing to drift.
            advertised = str((row or {}).get('evidence_id') or '').strip()
            if advertised:
                refs.add(advertised)
            kind = str((row or {}).get('type') or '').strip()
            if not kind:
                continue
            names = [kind] + ([alias] if alias and alias != kind else [])
            for name in names:
                refs.add(f'risk:{name}')
            ticker = str((row or {}).get('ticker') or '').strip()
            if ticker:
                for name in names:
                    refs.add(f'risk:{name}:{ticker}')
            # A leg-level breach (`leveraged_exposure`, `beta`) carries no
            # ticker: the cap is on the book, not on a name. Without a scoped
            # form for those rows the only way to point at "the HK one" is to
            # borrow a ticker out of the row's prose, which resolves to
            # nothing — measured, 8 of 28 dropped refs did exactly that.
            leg = str((row or {}).get('leg') or '').strip()
            if leg:
                for name in names:
                    refs.add(f'risk:{name}:{leg}')

    rows = ((context.get('quant_signals') or {}).get('rows')) or {}
    if isinstance(rows, dict):
        for ticker, row in rows.items():
            if not isinstance(row, dict):
                continue
            for field, value in row.items():
                if value is not None:
                    refs.add(f'quant:{ticker}:{field}')
    return refs


def prune_debate_citations(plan, context):
    """Drop debate citations the context cannot resolve. Returns what was cut.

    Dropped rather than rejected, on purpose. `validate_plan` is a publish
    gate: a plan that fails it does not degrade to a thinner brief, it degrades
    to no brief, and an invented reference in an annotation is not worth that
    trade. But dropping in silence would leave the debate looking better
    sourced than it is, so every cut is returned for the caller to file as a
    degradation — the same detect-but-never-silence shape the rest of this
    harness uses.
    """
    dropped: list[str] = []
    if not context:
        return plan, dropped
    citable = _citable_refs(context)
    if not citable:
        return plan, dropped
    for decision in plan.get('decisions') or []:
        debate = (decision or {}).get('debate')
        if not isinstance(debate, dict):
            continue
        cited = debate.get('evidence_ids')
        if not isinstance(cited, list) or not cited:
            continue
        kept = [ref for ref in cited if ref in citable]
        for ref in cited:
            if ref not in citable:
                dropped.append(f"{decision.get('decision_id') or '?'}:{ref}")
        if kept:
            debate['evidence_ids'] = kept
        else:
            debate.pop('evidence_ids', None)
    return plan, dropped


def normalize_plan_json(path, ledger_path=None, *, decision_packet=None,
                        write=True, return_plan=False, context=None):
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
        if decision_packet:
            normalized = brief_decision_packet.bind_plan_provenance(
                normalized, decision_packet
            )
        normalized, dropped_citations = prune_debate_citations(normalized, context)
        if dropped_citations:
            workflow_outcomes.note_degradation(
                None, 'debate_citation_unresolved',
                f"{len(dropped_citations)} debate evidence ref(s) matched "
                f"nothing in this generation's context: "
                + ', '.join(dropped_citations[:5]))
        if write and normalized != authored:
            # Atomic write: this process is SIGTERM-prone (60s exec timeout,
            # #508/#765) and a torn plan.json would fail every downstream
            # consumer the same day.
            safe_write_json(str(path), normalized)
    except Exception as exc:
        return _normalization_result(
            [f'plan.json 标准化失败: {exc}'], authored, return_plan
        )
    return _normalization_result([], normalized, return_plan)


def validate_plan_json(path, context=None, decision_packet=None, *,
                       normalized=True):
    """Validate the plan on disk.

    ``normalized=False`` says normalization was skipped because the authored
    plan already had semantic errors. The file then still lacks every field
    normalization fills, and listing those — six per decision, 48 of 62 issues
    on 2026-09-11 — tells the model to write ids itself. It did, on eleven
    briefs, and the ledger kept them (see `decision_v2._harness_owned_ids`).
    The model is shown only what it owns; the semantic issues that stopped
    normalization are already reported by `normalize_plan_json`.
    """
    if not path.exists():
        return ['plan.json 缺失（critical）']
    try:
        plan = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        return [f'plan.json 解析失败: {e}']

    issues = [
        f'plan.json v2: {x}' for x in decision_v2.validate_plan(plan, path)
        if normalized or not _normalization_owned_plan_error(x)
    ]
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
        # Active timing calls need either a hard catalyst or a harness-approved
        # technical tactical-entry setup. The packet validator above owns the
        # exact setup/trigger/size/lot match; free-text technical calls still fail.
        technical_entry = (
            d.get('strategy_id') == 'tactical_entry'
            and d.get('driven_by') == 'technical'
            and d.get('action') in {'add_only_on_trigger', 'add_on_breakout'}
            and decision_packet is not None
        )
        if (d.get('action') in decision_v2.ACTIVE_ACTIONS
                and d.get('strategy_id') != 'risk_rebalance'
                and d.get('driven_by') != 'catalyst'
                and not technical_entry):
            issues.append(f'{tag}: catalyst-gate — 主动 {d.get("action")} 必须 driven_by=catalyst；'
                          '只有 packet 批准的 tactical_entry 技术 setup 或 '
                          'risk_rebalance 可例外')

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
            # A breach the book keeps declining may stand today — holding it is the
            # plan writer's call, not an omission (risk.py `_adaptive`).
            if b.get('breach_id') in durable_overrides or risk_discipline.may_stand(b):
                continue
            if tk and tk not in trim_tickers:
                issues.append(f'仓位硬闸未处理: {b["type"]} {tk} ({b["detail"]}) — '
                              f'plan 里 {tk} 没有 trim/cut 动作（SKILL 要求每条 breach 出对应动作）')
            elif not tk and leg and leg not in trim_legs:
                targets = set((b.get('required_reduction') or {}).get('target_tickers') or [])
                if leg == 'BOOK' and targets & trim_tickers:
                    continue
                issues.append(f'仓位硬闸未处理: {b["type"]}/{leg} ({b["detail"]}) — '
                              f'plan 里没有任何目标 ticker 的 trim/cut 动作')
        for s in gr.get('hard_stop_watch', []):
            if s.get('breach_id') in durable_overrides or risk_discipline.may_stand(s):
                continue
            cut_tickers = {
                d.get('ticker') for d in trims if d.get('action') == 'cut'
            }
            if s.get('ticker') not in cut_tickers:
                issues.append(f'杠杆硬止损未处理: {s["ticker"]} ({s["detail"]}) — plan 里没有对应 cut')
    return issues


def load_preflight_context(ctx_path):
    """Return (context, blocking_issue) for today's preflight bundle.

    Fail closed: with a missing or unparseable context every context-dependent
    gate in main() would silently no-op while the ledger still recorded
    ``success`` — so both cases surface as a critical issue ('解析失败' /
    '缺失' are in CRITICAL_KEYWORDS) instead of a quiet None.
    """
    if not ctx_path.exists():
        return None, 'brief context 缺失（preflight 未产出 memory/.tmp bundle）'
    try:
        return json.loads(ctx_path.read_text()), None
    except Exception as exc:
        return None, f'brief context 解析失败: {exc}'


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
        if (age is not None and age <= STALE_H) and m.get('vix') and '大盘速读' not in text:
            issues.append('pre-open.md 缺 ▎大盘速读 段（context.macro 有 fresh 数据 '
                          f'age={age}h 但 LLM 没写）')
    if context and context.get('sentiment'):
        s = context['sentiment']
        age = s.get('age_hours')
        tickers = s.get('tickers') or []
        if (age is not None and age <= STALE_H) and tickers and '社交舆情' not in text:
            issues.append(f'pre-open.md 缺「社交舆情」段（context.sentiment '
                          f'{len(tickers)} 个 ticker 有信号 age={age}h 但 LLM 没写）')

    return issues


CRITICAL_KEYWORDS = [
    '缺失', '解析失败', '表格 #', 'generation_id',
    'plan.json harness', 'plan.json 标准化失败', 'decision packet 不可用',
]  # table mismatch and cross-generation output are critical


def categorize(issues):
    return categorize_issues(issues, CRITICAL_KEYWORDS, warn_max=4)


from clawock.harness.validation import (
    categorize_issues,
    check_md_table_column_consistency,
    postflight_exit_code,
    product_status,
    split_advisory,
)
from ._harness_common import (  # noqa: E402
    dashboard_publication_state,
    git_cmd as _git,
    push_with_rebase_retry,
    rebuild_dashboard,
)
from ._watchdog_common import (  # noqa: E402
    BRIEF_URL_TMPL,
    resolve_wechat_target, send_wechat, build_brief_card, cosend_telegram, already_delivered,
    claim_send, mark_send_started, release_claim, log, send_per_policy,
)
from clawock.harness import brief_render  # noqa: E402


def log_decisions(today):
    """Upsert today's validated, normalized plan into the v2 decision ledger.

    `simulated_entry_price` is never backfilled here (#1003): it used to be
    filled from portfolio.json `current_price`, whose docstring justified the
    write with `brief_preflight._resolve_pending_outcomes` — a function the v2
    refactor (a563b3c0) deleted. The live resolver, decision_v2.settle_decisions,
    derives every entry/fill from canonical memory/bars and never reads this
    field; the only consumers left render it as the public dashboard's
    plannedPrice when execution_price is absent. Backfilling it meant publishing
    a fetch-vintage quote (bars.py: previous close 7/15, intraday 5/15 on 00100)
    as a price nobody ever planned. What the LLM authored stays; nothing is
    invented."""
    plan_path = WS / 'memory' / f'{today}-plan.json'

    if not plan_path.exists():
        return
    try:
        plan = json.loads(plan_path.read_text())
    except Exception:
        return
    if plan.get('schema_version') != 2 or not plan.get('decisions'):
        return
    # One load, mutate in memory, write once only if something changed (#916):
    # the old sequence was upsert(load+write) then load+settle+write — two full
    # rewrites per brief even on the common no-new-decisions day.
    ledger = decision_v2.load_decisions()
    before = json.dumps(ledger, ensure_ascii=False, sort_keys=True)
    inserted, updated = decision_v2.upsert_plan_decisions(
        plan, ledger=ledger, write=False)
    settled = decision_v2.settle_decisions(ledger)
    after = json.dumps(ledger, ensure_ascii=False, sort_keys=True)
    if after != before:
        decision_v2.write_decisions(ledger)
    print(f'  decisions.jsonl: +{inserted}, updated {updated}, settled {settled} ({len(ledger)} total)')


def write_publish_gate(status, today, *, reason=None):
    """Machine-readable publish gate the off-host fallback workflow reads before it
    commits. The fallback runs on a fresh GH-Action checkout where a broad
    `git add … && commit && push` is its own committer and cannot see maybe_commit's
    `status == 'fail'` refusal — so a failing brief was published anyway. This file
    carries the same verdict across the process boundary. Fail-closed by contract:
    the workflow must treat a MISSING file (postflight crashed before here) as
    do-not-publish, so only an explicit publish_ok=true releases a commit."""
    gate = {'today': today, 'status': status, 'publish_ok': status != 'fail',
            'written_at': datetime.now().isoformat()}
    if reason:
        gate['reason'] = reason
    p = WS / 'logs' / 'brief_postflight_status.json'
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(gate, ensure_ascii=False) + '\n')
    return gate


def record_risk_stances(today, workspace=None):
    """File what today's plan did with each breach allowed to stand (reissue/stand).

    The harness writes it, from the validated plan — the model never touches the
    breach ledger (#1433 is what a model-written ledger field looks like). A failure
    here must not cost the day's commit: the rails then count from the last filed
    reissue, which errs toward raising the breach again sooner, not later.
    """
    ws = Path(workspace) if workspace else WS
    try:
        plan = json.loads((ws / 'memory' / f'{today}-plan.json').read_text(encoding='utf-8'))
        return risk_discipline.record_stances(
            ws / 'memory' / 'risk_breaches.json', today, plan.get('decisions') or [])
    except Exception as exc:  # noqa: BLE001 — see docstring
        print(f'warn: risk stance filing failed: {type(exc).__name__}: {exc}', file=sys.stderr)
        return []


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
    record_risk_stances(today)
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
    # The evidence artifact joined 2026-08-06 (#345) as the next instance of
    # exactly the failure above: preflight rebuilds it every morning via
    # build_evidence.py and nothing ever staged it, so the published copy sat on
    # numbers from 08-02 (claiming "留痕 38 天" against artifacts saying 42) while
    # live carried a permanently dirty file for other pushes to trip over. It
    # lived at `site/evidence.md`, outside every directory-scoped `git add` above
    # — the same gap MEMORY.md/DREAMS.md needed commit_dreaming.sh for.
    #
    # It moved to `assets/data/evidence.json` on 2026-09-12 when the standalone
    # page was retired. The path changed; the reason this line exists did not, and
    # a reader who finds this comment should not have to rediscover it.
    add_ok, add_out = _git('add', 'memory/', 'portfolio.json',
                            'memory/decisions.jsonl', 'assets/data/risk.json',
                            'assets/data/lev_regime.json', 'assets/data/benchmark.json',
                            'assets/data/quant_signals.json',
                            'assets/data/quant_signals_history.jsonl',
                            'assets/data/quant_signal_review.json',
                            'assets/data/cross_sectional_factor.json',
                            'assets/data/cross_sectional_factor_history.jsonl',
                            'assets/data/bar_signal_history.jsonl',
                            'assets/data/decision_map.json',
                            'assets/data/peer_residual.json',
                            'assets/data/peer_residual_history.jsonl',
                            'assets/data/catalysts.json',
                            'assets/data/news_evidence_graph.json',
                            'assets/data/news_evidence_history.jsonl',
                            # 滚动窗口的冷段（#951）。目录里有 .gitkeep，所以
                            # 归档还没生成的日子这条 pathspec 也匹配得到 ——
                            # 匹配不到 git add 会失败，而失败会带走整次提交。
                            'assets/data/archive/',
                            'assets/data/em_news.json',
                            'assets/data/guardrail_history.jsonl',
                            'assets/data/t0_setups.json',
                            'assets/data/t0_setups_history.jsonl',
                            'assets/data/t0_setup_review.json',
                            'assets/data/brief_projection.json',
                            'logs/dashboard_build_status.json',
                            'assets/data/evidence.json')
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
    return False, f'committed (push failed: {push_out[-150:]})'


def classify_commit_outcome(commit_ok, commit_msg):
    """The data-plane state maybe_commit's outcome settles on its own.

    `None` means it settles nothing — the commit landed, so the dashboard build
    status file is the authority on whether the public data plane is current.

    maybe_commit returns False for three different things, and #1457 printed all
    three as `failed`: a push that did not reach origin (a real failure), but also
    a dry run and a brief that was rejected before any commit was attempted —
    neither of which touched the data plane. A `--dry-run` is the run you make
    specifically to check the wiring, and it was reporting
    `data_plane_status: failed` next to `commit_msg: skipped (dry-run)`: the same
    run, two contradictory claims. `committed_local` is the vocabulary
    report_postflight.classify_data_plane and intraday_postflight.publish_data_plane
    already use for a commit that exists locally but lost its push.
    """
    if commit_msg.startswith('skipped'):
        return 'skipped'
    if 'push failed' in commit_msg:
        return 'committed_local'
    if not commit_ok:
        return 'failed'
    return None


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
    # Atomic write — the GHA fallback publishes this file straight to Pages; a
    # torn write here would ship half a brief.
    safe_write_text(str(md_path), fm + content)


def _judgment_gap_issues(judgment_path, decision_packet):
    """What the reader will be missing, said before the brief ships.

    Split deliberately: an absent judgment leaves the rendered report's Tier
    2/3, sector, macro and calibration sections empty, while an invalid one
    still renders (the renderer reads what is there) but is dropped from the
    Pages projection. Those are different losses and the operator should not
    have to guess which one happened.
    """
    try:
        overlay = json.loads(Path(judgment_path).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return ['judgment 缺失：报告的辩论段（Tier 2/3、板块、大盘、校准）会是空的']
    except (OSError, ValueError) as exc:
        return [f'judgment 无法解析（{exc}）：报告的辩论段会是空的']
    if decision_packet is None:
        return []
    overlay_issues = brief_decision_packet.validate_judgment_overlay(
        decision_packet, overlay)
    if not overlay_issues:
        return []
    shown = '；'.join(overlay_issues[:2])
    more = f'（共 {len(overlay_issues)} 条）' if len(overlay_issues) > 2 else ''
    return [f'judgment 未通过校验{more}：{shown} —— 报告按原文渲染，'
            'Pages projection 会丢掉整个判断层']


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true',
                    help='normalize in memory and validate without rewriting plan.json, '
                         'ledger writes, dashboard rebuild/commit, push, message delivery, '
                         'or delivery-marker writes; still adds missing Jekyll front matter '
                         'and writes the publish-gate status')
    args = ap.parse_args(argv)

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

    # Load preflight context (for cross-validation). Fail closed: a missing or
    # unparseable context would silently skip every context-dependent hard gate
    # below (generation pin, position/leverage回查, peer divergence,
    # macro/sentiment) while the ledger still recorded success.
    ctx_path = WS / 'memory' / '.tmp' / f'brief-context-{today}.json'
    context, context_issue = load_preflight_context(ctx_path)

    issues = []
    if context_issue:
        issues.append(context_issue)
    manifest_path = ctx_path.with_suffix('') / 'manifest.json'
    decision_packet = None
    if context and context.get('generation_id'):
        issues += brief_context.validate_run_bundle(ctx_path, manifest_path)
        try:
            decision_packet = brief_decision_packet.read_packet(manifest_path)
        except Exception as exc:
            issues.append(f'decision packet 不可用: {exc}')
    normalization_issues, normalized_plan = normalize_plan_json(
        plan_path,
        decision_packet=decision_packet,
        write=not args.dry_run,
        return_plan=True,
        context=context,
    )
    issues += normalization_issues

    # A judgment that is absent or does not validate now costs published
    # content, not just a Pages sidecar field: since #1232 the report's debate
    # sections are rendered from it. `projection_issues` records the same fact
    # further down, but only in the result JSON — nothing reads that in time to
    # notice the brief went out with empty sections.
    issues += _judgment_gap_issues(
        WS / 'memory' / '.tmp' / f'brief-judgment-{today}.json', decision_packet)

    # The report is rendered here, from the judgment and the normalized plan —
    # the model no longer writes markdown at all (see clawock.harness.
    # brief_render for why). Rendering after normalization is deliberate: the
    # published tables then show the same decisions the ledger records.
    # A renderer that cannot run must not take the brief down with it, so the
    # failure is an issue and whatever markdown exists still ships.
    try:
        render_issues, _ = brief_render.render_from_workspace(
            WS, today, plan=normalized_plan,
            page_url=BRIEF_URL_TMPL.format(date=today),
            write=not args.dry_run)
        # Unreadable inputs are reported, not escalated here: the consequence —
        # no report, or yesterday's — is what `validate_markdown` below is for,
        # and counting it twice can push a warn to a fail on the strength of one
        # underlying fact.
        for issue in render_issues:
            print(f'warn: {issue}', file=sys.stderr)
        # One of them is counted rather than only printed. The sector sweep is
        # written by the model, and it stopped after 2026-08-27: eight sessions
        # with no `sector-scan-*.json`, the report's 板块全景 quietly degrading
        # to the read alone, and the only trace anywhere a grey 「12天前 · 待
        # brief 刷新」 on one dashboard card. A cron log nobody reads twice
        # cannot answer "since when, and how often" (#1146).
        if brief_render.SECTOR_SCAN_MISSING in render_issues:
            workflow_outcomes.note_degradation(
                None, 'sector_scan_missing', brief_render.SECTOR_SCAN_MISSING)
    except Exception as exc:
        issues.append(f'简报渲染失败（保留现有 pre-open.md）: {exc}')
        print(f'warn: brief render failed: {exc}', file=sys.stderr)

    # Jekyll needs front matter to serve this as a page rather than a blob view.
    # The renderer emits it, so this now covers the day the renderer could not
    # run and an earlier file is what ships.
    _ensure_jekyll_front_matter(md_path, today)

    readability = assess_brief_readability(md_path)
    issues += validate_markdown(md_path, context=context)
    issues += readability_issues(readability)
    validation_path = (
        _InMemoryPlanPath(plan_path, normalized_plan)
        if args.dry_run and normalized_plan is not None
        else plan_path
    )
    issues += validate_plan_json(
        validation_path, context=context, decision_packet=decision_packet,
        normalized=not normalization_issues,
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
    # Same escalating/advisory split the report/intraday banners use: an
    # advisory-only slot delivers a clean product and must not be filed as a
    # degraded one (#764).
    escalating, advisories = split_advisory(issues)
    # What shipped, not what the checker noticed — the same correction #768 made
    # to final_product, applied to the stage and the commit subject (#1076).
    product = product_status(status, escalating)
    workflow_outcomes.record_stage(
        job_name,
        'llm',
        'success' if product == 'pass' else ('warning' if product == 'warn' else 'failed'),
        slot=slot,
        dry_run=args.dry_run,
        issue_count=len(issues),
        escalating_count=len(escalating),
        advisory_count=len(advisories),
        readability=readability,
    )
    # Emit a CLOSED cross-process gate before anything else can raise.  A valid
    # brief is not yet a publishable generation: the deterministic Pages
    # projection below is part of that generation too.  Releasing pass/warn here
    # let a projection exception preserve yesterday's sidecar while the fallback
    # workflow committed everything else and reported green (#520).
    write_publish_gate('fail', today, reason='pending_pages_projection')

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

    projection_ready = (
        args.dry_run
        or status == 'fail'
        or projection_status in {'valid', 'missing', 'invalid'}
    )
    publication_status = product if projection_ready else 'fail'
    # This is the only release of the off-host committer.  Judgment validity is
    # deliberately not required: missing/invalid prose still writes a complete
    # deterministic projection.  A writer exception or absent decision packet is
    # different — no current generation was produced.
    write_publish_gate(
        publication_status,
        today,
        reason=None if projection_ready else 'pages_projection_failed',
    )

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
    send_out = None
    # Set when claim_send refuses this process the send right: it then holds no
    # delivery evidence and must not file a primary_delivery verdict over the
    # concurrent holder's (#1006).
    claim_declined = False
    brief_marker = delivery_receipts.receipt_path(WS / 'memory' / '.tmp', 'brief', date=today)
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
        card = build_brief_card(today, decision_packet=decision_packet)
        message = (wechat_prefix + card).strip()
        first_line = card.strip().splitlines()[0] if card.strip() else ''
        # Take the send right before sending, not after (#508). The marker below
        # is written only once both channels have returned, so two postflights
        # racing on the same day would both read "not delivered yet" and both
        # send the card. A dry run sends nothing, so it takes no claim.
        claim_path = delivery_receipts.claim_path(brief_marker.parent, 'brief', date=today)
        if args.dry_run:
            claim_won, claim_reason = True, 'dry-run'
        else:
            claim_won, claim_reason = claim_send(claim_path)
        if not claim_won:
            print(f'concurrency: brief send is already claimed ({claim_reason}) — not '
                  f'sending a second card; the watchdog owns today if the first one '
                  f'did not land', file=sys.stderr)
            log({'tag': 'brief', 'action': 'send-claim-declined', 'reason': claim_reason})
            wechat_sent, send_out = False, f'send-claim-declined: {claim_reason}'
            claim_declined = True
        else:
            if not args.dry_run:
                mark_send_started(claim_path)
            # WeChat, then Telegram (cold-proof — WeChat can't confirm real delivery), per
            # the delivery policy. The Telegram result is recorded: it's the sole backstop
            # brief_watchdog uses (no WeChat resend), so it needs to know if TG got this card.
            wechat_sent, send_out, tg_ok = send_per_policy(
                'brief', message, tag='brief', dry_run=args.dry_run,
                wechat=send_wechat, telegram=cosend_telegram, resolve=resolve_wechat_target)
            # NEVER write the marker on a dry run (2026-07-16). send_wechat/cosend_telegram
            # return ok=True for a dry run (the CLI exits 0 without sending), so this used to
            # record sent_ok/tg_ok=true for a delivery that never happened. brief_watchdog
            # treats a fresh marker with tg_ok as its SOLE proof the card landed, so one
            # dry run silently disabled that day's backstop — exactly the "card never
            # arrived and nothing noticed" hole the watchdog exists to close. Hit for real:
            # a --dry-run postflight at 10:14 today wrote a marker claiming delivery while
            # kcn got nothing. A declined claim is the same shape: it sent nothing, so it
            # must not leave a marker either.
            if args.dry_run:
                print('dry-run: skipping brief-sent marker write', file=sys.stderr)
            else:
                try:
                    brief_marker.parent.mkdir(parents=True, exist_ok=True)
                    safe_write_text(str(brief_marker), json.dumps(
                        delivery_receipts.build_receipt(
                            ts=int(datetime.now().timestamp() * 1000),
                            sent_ok=wechat_sent, tg_ok=tg_ok, out=send_out,
                            first_line=first_line),
                        ensure_ascii=False))
                except Exception as e:
                    print(f'warn: brief-sent marker write failed: {e}', file=sys.stderr)
            # Completed send: the marker owns idempotency from here. A dry run
            # took no claim, so there is nothing to release.
            if not args.dry_run:
                release_claim(claim_path)
            if not wechat_sent:
                print(f'warn: WeChat send failed (watchdog will retry): {str(send_out)[:200]}',
                      file=sys.stderr)

    # ── Commit AFTER delivery (report/intraday order, #765) ───────────────────
    # maybe_commit runs log_decisions + rebuild_dashboard + git push — seconds of
    # local work the reader never sees. Delivering first means the card lands a
    # full dashboard-rebuild earlier and brief_watchdog's 08:30 pass finds the
    # sent-marker already written instead of racing a still-running postflight
    # (the TG double-card window). The card itself is order-independent: it reads
    # the LLM's brief-card file, or plan fields (book/decisions) that
    # log_decisions never rewrites.
    commit_ok, commit_msg = maybe_commit(
        publication_status, today, dry_run=args.dry_run
    )
    settled = classify_commit_outcome(commit_ok, commit_msg)
    if settled is not None:
        data_plane_status = settled
    elif (status in ('pass', 'warn') and projection_ready
            and not args.dry_run):
        data_plane_status = dashboard_publication_state(WS)
    else:
        data_plane_status = 'skipped'

    result = {
        'status':        status,
        'date':          today,
        'issues':        issues,
        'wechat_prefix': wechat_prefix,
        'wechat_sent':   wechat_sent,
        'commit_ok':     commit_ok,
        'commit_msg':    commit_msg,
        'data_plane_status': data_plane_status,
        'projection_status': projection_status,
        'projection_issues': projection_issues,
        'publication_ready': projection_ready,
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
        ('success'
         if (product == 'pass' and projection_ready
             and data_plane_status in {'published', 'skipped'})
         else ('warning'
               if (product == 'warn' and projection_ready
                   and data_plane_status in {'published', 'skipped'})
               else 'failed')),
        slot=slot,
        dry_run=args.dry_run,
        issue_count=len(issues),
        escalating_count=len(escalating),
        advisory_count=len(advisories),
        commit_ok=commit_ok,
        readability=readability,
    )
    # A declined claim process never sent, so it must not file the primary
    # verdict — the concurrent holder owns it, and a false `failed` written
    # after the holder's `success` would stand (reconciliation only fills
    # unknown stages) even though kcn got the card (#1006).
    if not claim_declined:
        workflow_outcomes.record_primary_delivery(
            job_name,
            slot=slot,
            dry_run=args.dry_run,
            wechat_ok=wechat_sent,
            telegram_ok=tg_ok,
            failed_status='not_required' if status == 'fail' else 'failed',
            wechat_detail=send_out,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if (not args.dry_run and status in ('pass', 'warn')
            and (not projection_ready or data_plane_status != 'published')):
        return 2
    return postflight_exit_code(product)


if __name__ == '__main__':
    sys.exit(main())
