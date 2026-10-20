"""The chat card on both markets, every slot (kcn 2026-10-20: 港美股的开盘盘中收盘都做).

The intraday check-in (`chat_card.render`) and the open/mid/pm/close reports
(`chat_card.render_report`) read the same analyzer text, and the two markets
write it differently: HK has an index strip, no `$` on its P&L, `2x杠杆敞口`
and `✋ STOP?` signals; US has `$`, 已实现, `杠杆ETF敞口` and `▼ STOP-LOSS` /
`△ WATCH`. The blocks below are trimmed from live analyzer output
(HK 2026-10-16 10:33 HKT, US 2026-10-19 14:03 ET).
"""
from __future__ import annotations

import pytest

from clawock.decision.plans import ORDER_BLOCK_HEADER
from clawock.harness import chat_card, intraday_preflight
from clawock.harness.report_preflight import TITLE_TEMPLATES

HK = """🇭🇰 港股盯盘 | 10/16 10:33 HKT
  恒指 24,321 ▲1.07%  恒科 4,130 ▲1.70%

📊 市值 HK$54,416 | 浮盈 -60,275 (-52.6%) | 今日 +1,691

| 代码  |    股 |   成本 |   现价 |   今日 |    浮% |     浮$ |
|:------|------:|-------:|-------:|-------:|-------:|--------:|
| 00100 |   140 | 508.47 | 186.40 |  +3.8% | -63.3% | -45,090 |
| 07226 |  7200 | 4.1175 |   2.57 |  +3.5% | -37.6% | -11,142 |
| 07709 |   100 |  20.04 |  19.87 |  -0.8% |  -0.8% |     -17 |

⚠️ 信号
  ✋ STOP? 00100 MINIMA | 今日+3.8% 浮-63.3%
  ✋ STOP? 07226 南方2倍做多 | 今日+3.5% 浮-37.6%
  △ WATCH 07709 2x SKHY | 今日-5.2% 浮-0.8%

📉 亏损持仓 3/3  |  2x杠杆敞口 38%"""

US = """🇺🇸 美股盯盘 | 10/19 14:03 ET

📊 市值 $3,210 | 浮盈 $-1,227 (-27.6%) | 今日 +$58 | ✅ 已实现 +$2,376

| 代码  |    股 |   成本 |   现价 |   今日 |    浮% |     浮$ |
|:------|------:|-------:|-------:|-------:|-------:|--------:|
| RKLX  |    10 |  49.69 |   9.06 |  +4.1% | -81.8% |    -406 |
| SPCX  |     1 | 147.50 | 147.45 |  +1.0% |  -0.0% |      -0 |

⚠️ 信号
  ▼ STOP-LOSS RKLX | 今日+4.1% 浮-81.8%
     · 浮亏 -81.8% 警惕止损
  △ WATCH SPCX | 今日+1.0% 浮-0.0%

📉 亏损持仓 2/2  |  杠杆ETF敞口 90%

📰 新闻
📰 SPCX (5条)
   · Top Midday Stories"""

TABLE_HEAD = '| 代码  |    股 |   成本 |   现价 |   今日 |    浮% |     浮$ |'
ORDERS = f'\n\n{ORDER_BLOCK_HEADER}\n  ◆ 07226 清仓 7200股 | 开盘 | 风控纪律'
PROSE = '▎要点\n1) 恒科反弹，07226 跟随。\n2) 纪律单照走。'


def _no_dangling_dot(lines):
    return all(not line.startswith('·') and not line.rstrip().endswith('·') and '·  ·' not in line
               and '· ·' not in line for line in lines)


def test_hk_intraday_card_keeps_hk_money_hkt_and_the_index_strip():
    lines = chat_card.render(analyzer=HK).splitlines()
    assert lines[:3] == ['**🇭🇰 港股盯盘 · 10/16 10:33 HKT**',
                         '**今日 +1,691** · 浮亏 -60,275（-52.6%）',
                         '市值 HK$54,416 · 亏损 3/3 · 2x杠杆敞口 38%']
    # HK P&L has no `$`; the card must not invent one (HK$ lives on 市值).
    assert '$-' not in lines[1] and '-$' not in lines[1]
    # The 恒指/恒科 strip is data: it stays, under the totals and above the table.
    strip = lines.index('恒指 24,321 ▲1.07%  恒科 4,130 ▲1.70%')
    assert 2 < strip < lines.index(TABLE_HEAD)
    assert _no_dangling_dot(lines[:3])


def test_us_intraday_card_keeps_dollars_et_and_has_no_strip():
    lines = chat_card.render(analyzer=US).splitlines()
    assert lines[:3] == ['**🇺🇸 美股盯盘 · 10/19 14:03 ET**',
                         '**今日 +$58** · 浮亏 -$1,227（-27.6%）',
                         '市值 $3,210 · 已实现 +$2,376 · 亏损 2/2 · 杠杆 90%']
    assert lines[3] == ''
    assert not any('恒指' in line for line in lines)


@pytest.mark.parametrize('name, underlying', [('07226', 'HSTECH'), ('07709', 'SKHY')])
def test_mover_row_keeps_missing_underlying_move_explicit(name, underlying):
    legs = intraday_preflight.leverage_legs(
        'hk', [{'ticker': name, 'pct_1d': 3.5}],
        {'rows': {name: {'leveraged': f'2x {underlying}'}}}, '', {},
        bars=lambda *_a: [], session_date='2026-10-20')
    assert legs[0]['underlying_pct'] is None
    assert legs[0]['expected_pct'] is None and legs[0]['gap_pp'] is None
    rows = chat_card.mover_rows(
        [(name, 3.5)], legs, {name: {'status': 'no_recent_disclosure'}})
    assert rows == [f'- **{name} +3.5%** · {underlying} 今日涨跌本档未取到 · 无公告']
    assert rows[0] in chat_card.render(analyzer=HK, changes=rows).splitlines()


@pytest.mark.parametrize('gap, suffix', [(None, ''), (0.3, ''), (1.5, '（偏离 +1.5pp）')])
def test_mover_row_with_underlying_move_and_optional_gap(gap, suffix):
    legs = [{'ticker': '07226', 'underlying': 'HSTECH', 'underlying_pct': 1.23,
             'decimals': 2, 'gap_pp': gap}]
    assert chat_card.mover_rows([('07226', 3.5)], legs, {}) == [
        f'- **07226 +3.5%** · HSTECH +1.23%{suffix}']


@pytest.mark.parametrize('book, risk, expected', [
    ('📊 市值 HK$54,416 | 浮盈 -60,275 (-52.6%) | 今日 +1,691', '',
     ['**今日 +1,691** · 浮亏 -60,275（-52.6%）', '市值 HK$54,416']),
    ('📊 市值 HK$54,416 | 浮盈 1,200 (2.1%)', '📉 亏损持仓 0/3',
     ['浮盈 +1,200（2.1%）', '市值 HK$54,416 · 亏损 0/3']),
    ('📊 浮盈 $-1,227 (-27.6%)', '', ['浮亏 -$1,227（-27.6%）']),
    ('', '📉 亏损持仓 3/3  |  2x杠杆敞口 38%', ['亏损 3/3 · 2x杠杆敞口 38%']),
    ('', '', []),
])
def test_summary_lines_hold_their_shape_when_fields_are_missing(book, risk, expected):
    lines = chat_card.summary_lines(book, risk)
    assert lines == expected
    assert all(lines) and _no_dangling_dot(lines)


@pytest.mark.parametrize('phase', ['open', 'mid', 'pm', 'close'])
def test_hk_reports_put_orders_and_stops_first_and_keep_the_strip(phase):
    title = TITLE_TEMPLATES[('hk', phase)].format(date='2026-10-16')
    card = chat_card.render_report(title, HK + ORDERS, PROSE)
    lines = card.splitlines()
    # WeChat shows `## ` literally and unbolded; the title is a bold line.
    assert lines[0] == '**' + title.replace('2026-10-16', '10/16').replace('｜', ' · ') + '**'
    assert lines[1:3] == ['**今日 +1,691** · 浮亏 -60,275（-52.6%）',
                          '市值 HK$54,416 · 亏损 3/3 · 2x杠杆敞口 38%']
    assert '恒指 24,321 ▲1.07%  恒科 4,130 ▲1.70%' in lines
    # `✋ STOP?` is a stop: it goes under 待你处理 with its ticker; a stop
    # whose ticker already has an order is that order, not a second row.
    assert chat_card.ACTION in lines and '****' not in card
    action = lines[lines.index(chat_card.ACTION) + 1:lines.index('', lines.index(chat_card.ACTION))]
    assert action == ['- **07226** 清仓 7200股 · 开盘单 · 风控纪律',
                      '- **00100** 止损线已破 · MINIMA | 今日+3.8% 浮-63.3%']
    assert '- **07709** WATCH · 2x SKHY | 今日-5.2% 浮-0.8%' in lines
    # Order: action, table, signals, then the prose under bold labels.
    assert (lines.index(chat_card.ACTION) < lines.index(TABLE_HEAD)
            < lines.index(chat_card.SIGNALS) < lines.index('**要点**'))
    assert lines[-2:] == ['1. 恒科反弹，07226 跟随。', '2. 纪律单照走。']
    assert not any(line.startswith(('▎', '📊', '📉', '⚠️', '✋')) for line in lines)


@pytest.mark.parametrize('phase', ['open', 'close'])
def test_us_reports_read_their_signal_glyphs_too(phase):
    title = TITLE_TEMPLATES[('us', phase)].format(date='2026-10-19')
    lines = chat_card.render_report(title, US, PROSE).splitlines()
    assert lines[0].startswith('**') and lines[0].endswith('**') and '10/19' in lines[0] and '｜' not in lines[0]
    assert '- **RKLX** 止损线已破 · 今日+4.1% 浮-81.8% · 浮亏 -81.8% 警惕止损' in lines
    assert '- **SPCX** WATCH · 今日+1.0% 浮-0.0%' in lines
    assert '- **SPCX** · 5 条 · Top Midday Stories' in lines
    assert '****' not in '\n'.join(lines)


def test_report_prose_bolds_only_the_paragraph_labels():
    """kcn 2026-10-20 「太多加粗了」: a ▎ line is a small bold label; the
    paragraph after it — inline after `｜` (US) or on the next lines (HK) — is plain."""
    prose = ('▎情绪面｜同业齐涨，反弹不代表扭转。\n加密端偏弱。\n'
             '▎技术面\nRSI 超卖。\n▎操作建议：纪律单照走。')
    lines = chat_card.render_report('🌙 美股收盘日报｜2026-10-19', US, prose).splitlines()
    body = lines[lines.index('**情绪面**'):]
    assert body == ['**情绪面**', '同业齐涨，反弹不代表扭转。', '加密端偏弱。', '',
                    '**技术面**', 'RSI 超卖。', '', '**操作建议**', '纪律单照走。']


def test_report_news_keeps_each_sentiment_mark_on_its_own_ticker():
    """`📰✅`/`📰⚠️` are the analyzer's sentiment marks; a marked line is a
    ticker of its own, not a stray line whose headlines join the ticker above."""
    block = US + ('\n   · SpaceX midday\n📰⚠️ SPCH (2条)\n   · SPCH leverage decay\n'
                  '📰✅ RKLX (1条)\n   · RKLX bounce')
    parts = chat_card.parse_report_block(block)
    assert [(item['ticker'], item['mark'], item['titles']) for item in parts['news']] == [
        ('SPCX', '', ['Top Midday Stories', 'SpaceX midday']),
        ('SPCH', '⚠️', ['SPCH leverage decay']),
        ('RKLX', '✅', ['RKLX bounce'])]
    assert not any('📰' in line for line in parts['other'])
    lines = chat_card.render_report('🌙 美股收盘日报｜2026-10-19', block, PROSE).splitlines()
    assert '- **SPCH** ⚠️ · 2 条 · SPCH leverage decay' in lines
