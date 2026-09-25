"""Intraday context layers: which fields are the reference layer.

One list, two readers: `harness.intraday_preflight.judgment_packet` keeps
everything else in the core packet, and `tools.context_tools.IntradayReference`
serves only these names. It lives here so the tool layer does not import the
harness (docs/architecture/intraday-agent.md §3).
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
    'information_full': '资讯全量：每只票的图谱事件/东财/美股摘要全文、情绪、宏观、7×24 原文',
}
