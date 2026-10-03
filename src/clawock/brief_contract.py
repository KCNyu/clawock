"""Markdown concepts required by the daily brief prompt and output gates."""

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
