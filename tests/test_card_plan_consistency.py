"""One answer per holding on every card: today's order, an owed exit, or neither.

2026-10-26 港股收盘日报, as delivered: 待你处理 listed 02208 / 03032 / 07226 /
03033 as 「止损线已破」 while the same card's prose said 「港股腿今天不加不减」 and
that morning's plan held all four (`hold_and_watch`). The STOP was the analyzer's
cost-basis line (浮亏 ≤ -20%), not an order; the one rule with teeth — 07226's
leveraged hard stop — had stood 74 days on the risk ledger with no execution,
acknowledgement or override, and the prose called it 「纪律不触发」. The 21:33
美股开盘快报 listed 「SPCH 止损线已破」, a holding whose strategy
(`infinite_ammo_dca`) silences cost-basis signals on every intraday card.

The blocks, plan rows and ledger record below are that day's, trimmed.
"""
from __future__ import annotations

from clawock.decision.plans import ORDER_BLOCK_HEADER
from clawock.harness import report

HK_CLOSE = f"""🇭🇰 港股盯盘 | 10/26 16:10 HKT
  恒指 23,212 ▲0.51%  恒科 3,858 ▼0.36%

📊 市值 HK$49,602 | 浮盈 -65,088 (-56.8%) | 今日 -2,190

| 代码  |    股 |   成本 |   现价 |   今日 |    浮% |     浮$ |
|:------|------:|-------:|-------:|-------:|-------:|--------:|
| 00100 |   140 | 508.47 | 174.10 |  -7.2% | -65.8% | -46,812 |
| 02208 |   400 | 14.084 |   6.94 |  -4.9% | -50.7% |  -2,858 |
| 03032 |   200 |  5.405 |  3.858 |  -0.3% | -28.6% |    -309 |
| 07226 |  7200 | 4.1175 |  2.224 |  -1.0% | -46.0% | -13,633 |
| 03033 |  1000 |   5.14 |  3.778 |  -0.5% | -26.5% |  -1,362 |
| 07709 |   100 |  20.04 |  18.90 |  +1.3% |  -5.7% |    -114 |

⚠️ 信号
  △ WATCH 00100 MINIMA | 今日-7.2% 浮-65.8%
  ✋ STOP? 02208 金风科技 | 今日-4.9% 浮-50.7%
  ✋ STOP? 03032 恒生科技ET | 今日-0.3% 浮-28.6%
  ✋ STOP? 07226 南方2倍做多 | 今日-1.0% 浮-46.0%
  ✋ STOP? 03033 南方恒生科技 | 今日-0.5% 浮-26.5%

📉 亏损持仓 6/6  |  2x杠杆敞口 36%

{ORDER_BLOCK_HEADER}
  ◆ 00100 反弹减仓 40股｜≥191.7"""

US_OPEN = f"""🇺🇸 美股盯盘 | 10/26 09:33 ET

📊 市值 $3,152 | 浮盈 $-1,285 (-29.0%) | 今日 $-14 | ✅ 已实现 +$2,376

| 代码  |    股 |   成本 |   现价 |   今日 |    浮% |     浮$ |
|:------|------:|-------:|-------:|-------:|-------:|--------:|
| CRCL  |     2 |  87.00 |  81.39 |  -5.3% |  -6.4% |     -11 |
| RKLX  |    10 |  49.69 |   9.65 |  +4.4% | -80.6% |    -400 |
| SPCX  |     1 | 147.50 | 147.34 |  -0.1% |  -0.1% |      -0 |
| SPCH  |   300 |  12.06 |   9.15 |  -0.3% | -24.1% |    -873 |

⚠️ 信号
  ▼ STOP-LOSS RKLX | 今日+4.4% 浮-80.6%
     · RSI 32.8 超卖区
     · 价格低于MA20 -31.9%
  ▼ STOP-LOSS SPCH | 今日-0.3% 浮-24.1%
     · 价格低于MA20 -12.5%
     · 跌破MA50

📉 亏损持仓 4/4  |  杠杆ETF敞口 90%

{ORDER_BLOCK_HEADER}
  ◆ RKLX 清仓 10股｜开盘｜风控纪律
  ◆ RKLB 触发加仓 1股｜开盘｜风控纪律"""


def _row(ticker, action, shares=None, condition='open', price=None, driven_by='technical'):
    return {'decision_id': f'dec-{ticker}', 'plan_date': '2026-10-26', 'ticker': ticker,
            'action': action, 'condition': condition, 'condition_price': price,
            'shares': shares, 'driven_by': driven_by, 'execution_status': 'unknown'}


# memory/2026-10-26-plan.json, the HK and US legs as plans.open_decisions_context read them.
HK_PLAN = {'plan_date': '2026-10-26', 'open': [
    _row('00100', 'trim_on_rebound', 40, 'price_above', 191.7),
    _row('07226', 'hold_and_watch', driven_by='risk_rule'),
    _row('03033', 'hold_and_watch'), _row('02208', 'hold_and_watch'),
    _row('07709', 'hold_and_watch'), _row('03032', 'hold_and_watch')]}
US_PLAN = {'plan_date': '2026-10-26', 'open': [
    _row('RKLX', 'cut', 10, driven_by='risk_rule'),
    _row('RKLB', 'add_only_on_trigger', 1.0, driven_by='risk_rule'),
    _row('SPCH', 'hold_and_watch', driven_by='risk_rule'),
    _row('CRCL', 'hold_and_watch'), _row('SPCX', 'hold_and_watch')]}
SPCH_POLICY = {'SPCH': {'strategy': 'infinite_ammo_dca', 'suppress_cost_basis_signals': True,
                        'forbid_reduce_advice': True}}


def _ledger_record(**over):
    """memory/risk_breaches.json `risk-4ab7eff27f15` on 2026-10-26, governance fields."""
    row = {
        'breach_id': 'risk-4ab7eff27f15', 'type': 'hard_stop', 'leg': 'HK', 'ticker': '07226',
        'status': 'open', 'severity': 'critical', 'age_days': 74,
        'required_reduction': {'kind': 'full_leveraged_position', 'minimum_shares': 7200,
                               'target_tickers': ['07226'], 'swap_to': '03033'},
        'acknowledgement': {'status': 'unacknowledged', 'acknowledged_at': None, 'note': ''},
        'override': {'status': 'none', 'reason': '', 'created_at': None, 'expires_at': None},
        'execution': {'status': 'pending', 'confirmed_at': None, 'evidence': []},
    }
    row.update(over)
    return row


def _section(lines, header):
    if header not in lines:
        return []
    start = lines.index(header) + 1
    end = lines.index('', start) if '' in lines[start:] else len(lines)
    return lines[start:end]


def _card(block, plan, **ctx):
    return report.assemble_message(
        {'title': '🔔 港股收盘日报｜2026-10-26', 'raw_wechat_block': block,
         'plan_context': plan, **ctx}, '').splitlines()


def test_a_name_todays_plan_holds_is_not_a_todo_on_the_report_card():
    """The 2026-10-26 close card with that day's plan: the order is the only
    to-do. Red before this change (four 「止损线已破」 rows), green after."""
    lines = _card(HK_CLOSE, HK_PLAN)
    assert _section(lines, '**待你处理**') == ['- **00100** 反弹减仓 40股 · ≥191.7']
    assert not any('止损线已破' in line for line in lines)
    # The cost-basis signal is not erased: it stays a signal, with the stance.
    signals = _section(lines, '**信号**')
    for name in ('02208', '03032', '07226', '03033'):
        assert sum(f'**{name}** STOP?' in row and '计划持有' in row for row in signals) == 1, name


def test_an_order_and_an_unplanned_stop_are_still_todos():
    """Not "the plan always holds": a cut is today's order, and a stop on a
    name the plan never ruled on (here 02208 dropped from the plan) still asks."""
    hk = _section(_card(HK_CLOSE, {**HK_PLAN, 'open': [
        row for row in HK_PLAN['open'] if row['ticker'] != '02208']}), '**待你处理**')
    assert '- **02208** 止损线已破 · 金风科技 | 今日-4.9% 浮-50.7%' in hk
    us = _section(_card(US_OPEN, US_PLAN), '**待你处理**')
    assert us[:2] == ['- **RKLX** 清仓 10股 · 开盘单 · 风控纪律',
                      '- **RKLB** 触发加仓 1股 · 开盘单 · 风控纪律']
    # No plan at all (or a plan that did not read) holds nothing.
    assert sum('止损线已破' in row for row in _section(_card(HK_CLOSE, {}), '**待你处理**')) == 4
    assert sum('止损线已破' in row for row in _section(
        _card(HK_CLOSE, {'error': 'JSONDecodeError'}), '**待你处理**')) == 4
    assert sum('止损线已破' in row for row in _section(
        _card(HK_CLOSE, {**HK_PLAN, 'truncated': 2}), '**待你处理**')) == 4


def test_the_owed_hard_stop_stays_on_the_card_until_an_exit_is_recorded():
    from clawock.decision import risk
    debts = risk.open_debts([_ledger_record()], leg='HK')
    lines = _card(HK_CLOSE, HK_PLAN, risk_debts=debts)
    owed = _section(lines, '**欠着的账**')
    assert owed[0] == '- **07226** 硬止损 · 74 天未结 · 今日计划持有'
    assert 'clawock risk ack' in owed[-1] and 'clawock risk override' in owed[-1]
    assert lines.index('**待你处理**') < lines.index('**欠着的账**') < lines.index(
        next(line for line in lines if line.startswith('| 代码')))
    # Each of the three exits closes it; a resolved breach or another leg is not owed.
    closed = [
        _ledger_record(acknowledgement={'status': 'acknowledged', 'note': '看见了，继续拿'}),
        _ledger_record(status='overridden', override={'status': 'active', 'reason': 'x',
                                                      'expires_at': '2099-01-01T00:00:00+00:00'}),
        _ledger_record(execution={'status': 'confirmed', 'evidence': []}),
        _ledger_record(status='resolved'),
    ]
    for record in closed:
        assert risk.open_debts([record], leg='HK') == []
    assert risk.open_debts([_ledger_record()], leg='US') == []
    # A sized order on the name is its exit, said as such.
    with_order = _section(_card(US_OPEN, US_PLAN, risk_debts=risk.open_debts([_ledger_record(
        breach_id='risk-0a0af7ae3b3a', leg='US', ticker='RKLX', age_days=103,
        required_reduction={'target_tickers': ['RKLX']})], leg='US')), '**欠着的账**')
    assert with_order[0] == '- **RKLX** 硬止损 · 103 天未结 · 出口：上面 RKLX 的单'
    # An unreadable ledger is said, not skipped.
    assert _section(_card(HK_CLOSE, HK_PLAN, risk_debts=None, risk_debts_error='ValueError: x'),
                    '**欠着的账**') == ['- 风控账本未读到（ValueError: x），欠账未列']


def test_the_intraday_card_files_the_same_stop_the_same_way():
    from clawock.decision import risk
    from clawock.harness import chat_card, intraday_preflight as pre
    detail = [{'level': 'STOP', 'ticker': t, 'line': f'✋ STOP? {t} x | 今日-1.0% 浮-30.0%'}
              for t in ('02208', '03032', '07226', '03033')]
    parts = pre.card_inputs(
        signals_detail=detail, holding_policies={},
        seen_signals={('STOP', '03032'), ('STOP', '07226'), ('STOP', '03033')},
        p0_lines=[], plan_ctx=HK_PLAN, plan_triggers=[], movers=[], leverage=[],
        mover_news={}, soft_changes=[], first_slot=False, active_information='',
        setups={}, early='', radar='', add_side_reads={}, health=[],
        debts=risk.open_debts([_ledger_record()], leg='HK'))
    assert parts['action'] == ['- **00100** 反弹减仓 40股 · ≥191.7']
    # A newly seen stop on a held name is this slot's news, marked; seen ones are not repeated.
    assert [row for row in parts['changes'] if 'STOP' in row] == [
        '- STOP? 02208 x：今日-1.0% 浮-30.0%（计划持有）']
    assert parts['debts'][0] == '- **07226** 硬止损 · 74 天未结 · 今日计划持有'
    card = chat_card.render(analyzer=HK_CLOSE, **parts).splitlines()
    assert card.index(chat_card.ACTION) < card.index(chat_card.DEBTS) < card.index(chat_card.CHANGES)


def test_the_report_reads_holding_strategies_the_way_the_intraday_slot_does():
    """SPCH's strategy silences its cost-basis signals and forbids a reduce
    order on the intraday card; the report preflight now applies both."""
    from clawock.decision import intraday_policy
    from clawock.decision.plans import append_order_block
    block = intraday_policy.strip_suppressed_signal_lines(US_OPEN, SPCH_POLICY)
    assert '▼ STOP-LOSS SPCH' not in block and '▼ STOP-LOSS RKLX' in block
    assert '跌破MA50' not in block and 'RSI 32.8' in block
    lines = _card(block, US_PLAN)
    assert not any('SPCH' in line and 'STOP' in line for line in lines)
    plan = {**US_PLAN, 'open': [*US_PLAN['open'], _row('SPCH', 'cut', 300, driven_by='risk_rule')]}
    kept = intraday_policy.without_conflicting_orders(SPCH_POLICY, plan)
    assert 'SPCH 清仓' not in append_order_block('x', kept)
    assert [row['ticker'] for row in intraday_policy.plan_conflicts(SPCH_POLICY, plan)] == ['SPCH']


# The sentences as delivered on 2026-10-26.
HK_PROSE = ('▎操作建议\n- 07226 那条是纪律不是择时：收盘 2.224 仍在破位线之上，纪律不触发，'
            '维持不动，我不给它加「等回踩」这类条件。\n我的判断：港股腿今天不加不减，全部等信号。')
US_PROSE = '▎技术面\nSPCH 是今天结构真坏掉的一只：跌破 MA50，又在 MA20 下方 12.5%，硬止损信号挂着。'


def _issues(prose, plan, **ctx):
    from clawock.harness.validation import check_plan_consistency
    return check_plan_consistency(prose, {'plan_context': plan, **ctx})


def test_the_prose_is_held_to_the_plan_the_ledger_and_the_strategy():
    from clawock.decision import risk
    debts = risk.open_debts([_ledger_record()], leg='HK')
    assert _issues(HK_PROSE, HK_PLAN, risk_debts=debts) == [
        '与计划/账本不一致：07226 账本里硬止损已破 74 天未结，正文却说纪律/止损未触发或写成一条没破的价位']
    assert _issues(US_PROSE, US_PLAN, holding_policies=SPCH_POLICY) == [
        '与计划/账本不一致：SPCH 持仓策略不设硬止损，正文却按硬止损在说']
    # A held name told to cut is flagged; the plan's own re-evaluation line is not.
    assert _issues('03032 建议现在清仓。', HK_PLAN) == [
        '与计划/账本不一致：03032 今日计划持有，正文却给了砍仓/减仓/止损指令']
    # The same denial as a price still ahead (that morning's three reports).
    for said in ('07226 现价 2.228 对硬止损 2.156，空间只剩三个点。',
                 '07226 现价 2.198，离纪律线 2.156 只剩一点。',
                 '盯 07226 的收盘，收盘若压在 2.156 之下，才是纪律触发的时刻。'):
        assert _issues(said, HK_PLAN, risk_debts=debts), said
    for fine in ('07226 收盘失守 2.156 再执行止损换仓。', '港股腿今天不加不减，全部等信号。',
                 '07226 的硬止损还欠着出口，今天不重复砍单。', 'SPCH 豁免硬止损，继续按定投走。',
                 '00100 反弹到 191.7 就执行减仓。', '07226 的硬止损 -18% 早已破线。',
                 '07226 收盘失守 2.156 是计划写的重评线。'):
        assert _issues(fine, HK_PLAN, risk_debts=debts, holding_policies=SPCH_POLICY) == [], fine


def test_a_consistency_finding_warns_on_the_report_and_is_revised_once_intraday():
    from clawock.decision import risk
    from clawock.harness import intraday_postflight as post
    ctx = {'title': 't', 'raw_wechat_block': HK_CLOSE, 'plan_context': HK_PLAN,
           'risk_debts': risk.open_debts([_ledger_record()], leg='HK')}
    prose = ('▎情绪面\n恒科偏弱。\n▎技术面\n07226 跟随指数。\n' + HK_PROSE)
    issues = report.validate(report.assemble_message(ctx, prose), ctx, prose)
    assert report.categorize([i for i in issues if '不一致' in i]) == 'warn'
    judgment = '▎我的看法\n07226 收盘仍在破位线上方，纪律不触发，维持不动。' + '其余票按计划等待。' * 6
    found = [i for i in post.validate(post.assemble_message(ctx, judgment), ctx, judgment)
             if '不一致' in i]
    assert found and all(any(key in i for key in post.REVISABLE) for i in found)
    assert post.categorize(found) == 'warn'
