"""Intraday context layers: which layer every context field belongs to.

Three tables, each field in exactly one (`test_every_context_field_declares_its_layer`):
the core packet the model always reads, the reference layer it fetches by name,
and run control that stays in the on-disk context only. `judgment_packet` and
`tools.context_tools.IntradayReference` read them. It lives here so the tool
layer does not import the harness (docs/architecture/intraday-agent.md §3).
"""

REFERENCE_TOOL = 'intraday_reference'
REFERENCE_ENTRIES = {
    'signals_detail': '本档信号逐条（与 analyzer_block 的信号段同源；理由行以 analyzer_block 为准）',
    'source_signals_detail': '持仓策略过滤前的原始信号',
    'peer_scan': '持仓板块全景：每只持仓的同业今日/5日涨跌、背离信号',
    't0_setups': 'T+0 牌面质量评级（区间位置/追高检测，非买卖信号）',
    'early_trend_candidates': '早期趋势候选与各自 blockers',
    'opportunity_radar': '机会雷达 rows 与每只票的 20 日高 levels',
    'provisional_setups': '未收盘入场形态（若收在此位则成立）',
    'prior_semantic_state': '上次送达时的语义状态（对比基准）',
    'headline_feed': '分析器标题流（截断、无新旧闸，只作背景）',
    'information_full': '资讯全量：每只票的图谱事件/东财/美股摘要全文、情绪、宏观、7×24 原文、实时源（live）全部条目与请求记录',
}

# Run control: read by postflight, delivery and the dashboard from the context
# on disk, never by the judgment. `heartbeat.slot` reaches the model as
# `index.slot`.
CONTROL_ENTRIES = {
    'card_marks': '渠道高亮用的行标记（微信逐格加粗 / ⛔ 点名）',
    'heartbeat': '本档 job 与 slot，心跳与回执的身份',
}

# The core packet, by the question each field answers. A new context field has
# to be added to one of the three tables before it ships; until then
# `judgment_packet` keeps it in the core so nothing the model needs can go
# missing by omission.
CORE_FIELDS = {
    # 本档身份与发送模式
    'status': 'slot', 'market': 'slot', 'date': 'slot', 'time': 'slot',
    'generated_at': 'slot', 'context_id': 'slot',
    'delivery_mode': 'slot', 'always_full': 'slot',
    # 与上次送达相比变了什么
    'semantic_unchanged': 'change', 'semantic_state': 'change',
    'semantic_delta': 'change', 'anomalies': 'change', 'signal_count': 'change',
    'should_alert': 'change', 'alert_reasons': 'change',
    # 持仓与行情（三种视图各有用途：结构化逐票、分析器原样、卡面）
    'full_holdings': 'holdings', 'analyzer_block': 'holdings',
    'raw_wechat_block': 'holdings', 'quote_coverage': 'holdings',
    'leverage_legs': 'holdings',
    # 计划与持仓策略约束
    'plan_context': 'constraints', 'plan_triggers': 'constraints',
    'watch_levels': 'constraints', 'holding_policies': 'constraints',
    'strategy_checks': 'constraints', 'strategy_conflicts': 'constraints',
    'strategy_escalations': 'constraints', 'policy_evidence_errors': 'constraints',
    # 加仓侧与边缘候选
    'add_side_reads': 'add_side', 'soft_candidates': 'add_side',
    # 异动归因与资讯
    'information': 'evidence', 'mover_thesis': 'evidence', 'mover_news': 'evidence',
    'anomaly_search': 'evidence', 'active_information_candidates': 'evidence',
    'known_catalysts': 'evidence',
}


# What kind of statement each field makes (#2843). The layers above say where a
# field is read; this says how far it may be argued with.
#
#   observation — measured or recorded: a quote, a filing, a plan row, a clock.
#   policy      — the output of a rule that screens, scores or nominates:
#                 someone's registered opinion about the observations.
#   mixed       — observations carrying such labels inside them.
#   control     — run plumbing the judgment never reads.
#
# A policy or mixed field is evidence of what a registered rule concluded, not
# of what is true: the judgment may weigh it, depart from it and say why. It is
# never grounds for withholding the observation underneath. A field is listed
# once; `test_every_context_field_declares_its_semantics` holds the tables
# together.
POLICY_FIELDS = (
    'anomalies', 'signals_detail', 'source_signals_detail', 't0_setups',
    'early_trend_candidates', 'opportunity_radar', 'provisional_setups',
    'strategy_checks', 'strategy_escalations', 'add_side_reads', 'soft_candidates',
)
MIXED_FIELDS = (
    'analyzer_block', 'raw_wechat_block', 'semantic_state', 'semantic_delta',
    'prior_semantic_state', 'mover_thesis', 'mover_news', 'anomaly_search',
    'active_information_candidates',
)


def field_semantics(field):
    """`observation`, `policy`, `mixed` or `control` for a context field."""
    if field in CONTROL_ENTRIES:
        return 'control'
    if field in POLICY_FIELDS:
        return 'policy'
    if field in MIXED_FIELDS:
        return 'mixed'
    return 'observation'

