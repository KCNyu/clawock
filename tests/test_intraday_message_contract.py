"""Intraday context, policy and message boundaries."""
import json
import ast
import re
from pathlib import Path

from clawock.harness import intraday_preflight as pre
from clawock.harness import intraday_postflight as post
from clawock.decision import intraday_policy as policy
from clawock.harness import validation as val


def test_mode7_named_context_fields_reach_model():
    """A new prompt field cannot be silently dropped by the model packet."""
    root = Path(__file__).resolve().parents[1]
    source = (root / 'src/clawock/harness/intraday_preflight.py').read_text()
    dicts = [node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Dict)]
    produced = max(({
        key.value for key in node.keys if isinstance(key, ast.Constant)
        and isinstance(key.value, str)
    } for node in dicts), key=len)
    produced.add('context_id')  # appended after the result dict is complete
    # What a slot loads: the thin payload and the one shared Mode 7 body (#2807).
    documents = [(root / 'config/cron-payloads/intraday.md').read_text(),
                 (root / 'skills/_shared/intraday-mode7.md').read_text()]
    tokens = set()
    for document in documents:
        tokens.update(re.findall(r'`([a-z][a-z0-9_]*(?:\.[a-z0-9_]+)*)`', document))
    named = {token.split('.', 1)[0] for token in tokens
             if '_' in token or token == 'anomalies'}
    non_fields = {'commit_ok', 'market_closed', 'full_delta', 'no_change',
                  'review_candidate',
                  'no_recent_filing', 'index_fund_no_issuer', 'suppressed_noise'}
    assert named - non_fields <= produced
    # Reachable: in the core packet, or listed in its index (reference layer).
    packet = pre.judgment_packet({key: None for key in produced})
    listed = {ref['name'] for ref in packet['index']['references']}
    assert named - non_fields <= set(packet) | listed


def test_delta_header_names_new_trigger_before_table():
    current = {'breaches': [{'ticker': '00100', 'kind': 'plan_trigger', 'level': 'gte'}]}
    block = pre.prepend_delta_lead(
        '🇭🇰 港股盯盘 | 10:33\n\n| 代码 | 现价 |',
        {'components': ['breaches', 'plans']}, current=current,
        previous={'breaches': []},
    )
    assert block.splitlines()[1] == '变化：信号/触发档位（新触发：00100）、未成交计划'
    assert block.index('变化：') < block.index('| 代码')


def test_full_card_discloses_unverified_quote_coverage():
    block = pre.prepend_coverage_warning(
        '🇺🇸 美股盯盘\n变化：本交易日首档\n\n| 代码 | 现价 |',
        {'unrefreshed': ['SPCH', 'SPCX']},
    )
    assert block.splitlines()[2] == '⛔ 数据降级：SPCH、SPCX 行情未证实（沿用上一笔）'
    assert '| 代码 |' in block


def test_an_unverified_gap_says_since_when_instead_of_repeating():
    """kcn 2026-09-25 preview: the same names in the same session carry the
    first slot's time; a changed set or a new session starts over."""
    prev = {'time': '22:33', 'semantic_state': {'session': 'us:2026-09-25'},
            'quote_coverage': {'unrefreshed': ['RKLX', 'CRCL', 'SPCH']}}
    now = {'unrefreshed': ['CRCL', 'RKLX', 'SPCH']}
    carried = pre.carry_quote_gap(now, prev, session='us:2026-09-25', slot_time='23:03')
    assert pre.coverage_warning(carried) == \
        '⛔ 数据降级：CRCL、RKLX、SPCH 行情未证实（沿用上一笔，自 22:33 起）'
    # Carried again: the start stays where it was.
    later = pre.carry_quote_gap(now, {**prev, 'time': '23:03', 'quote_coverage': carried},
                                session='us:2026-09-25', slot_time='23:33')
    assert later['unrefreshed_since'] == '22:33'
    for other in (pre.carry_quote_gap({'unrefreshed': ['CRCL']}, prev,
                                      session='us:2026-09-25', slot_time='23:03'),
                  pre.carry_quote_gap(now, prev, session='us:2026-09-26', slot_time='22:03')):
        assert '自' not in pre.coverage_warning(other)
    assert pre.carry_quote_gap({'unrefreshed': []}, prev, session='us:2026-09-25',
                               slot_time='23:03') == {'unrefreshed': []}
    # A holding's missing strategy evidence rides the same line as a pointer.
    assert pre.coverage_warning(carried, {'SPCH': ['行情未证实刷新']}).endswith(
        '（沿用上一笔，自 22:33 起） · SPCH 策略升级证据未取全')


def test_strategy_evidence_gaps_land_on_their_add_side_row():
    gaps = pre.evidence_gaps(
        ['SPCH: quote not freshly verified', 'SPCX: daily move unavailable'],
        [{'holding': 'SPCH', 'ticker': 'SPCH'}, {'holding': 'SPCH', 'ticker': 'SPCX'}])
    assert gaps == {'SPCH': ['行情未证实刷新', 'SPCX 今日涨跌缺失']}
    reads = {'rows': [{'ticker': 'RKLX', 'verdict': 'wait', 'why': '窗口内无一手公告'}]}
    lines = pre.append_add_side_section('x', reads, gaps).splitlines()
    assert lines[-1] == ('  · SPCH 观望：策略升级证据未取全（行情未证实刷新；SPCX 今日涨跌缺失）'
                         '→ 本档不给尺寸')
    # A holding with its own row keeps its verdict; the gap goes under it.
    on_row = pre.append_add_side_section(
        'x', reads, {'RKLX': ['行情未证实刷新']}).splitlines()
    assert on_row[-2].startswith('  · RKLX 等待：')
    assert on_row[-1] == '    ↳ 策略升级证据未取全（行情未证实刷新）'


def test_change_line_names_the_soft_candidate_and_what_changed():
    """#2804, 2026-10-09 HK 11:33: 「变化：边缘候选」 for 00100 crossing from the
    2.5-3 band into 1.5-2.5 — a real new identity the card did not explain."""
    seen = [{'ticker': '00100', 'kind': 'soft_move', 'band': '2.5-3'},
            {'ticker': 'HSTECH', 'kind': 'near_20d_high'}]
    previous = {'session': 'hk:2026-10-09', 'soft_candidates_seen': seen}
    delta = {'components': ['soft_candidates_seen']}
    moved = {'ticker': '00100', 'kind': 'soft_move', 'band': '1.5-2.5'}

    def lead(new, rows, prev=previous, components=delta):
        return pre.delta_lead(components, previous=prev, soft_candidates=rows, current={
            'soft_candidates_seen': [*prev['soft_candidates_seen'], *new]})

    # Same ticker, another band: said as that, with this slot's move.
    assert lead([moved], [{**moved, 'pct_1d': -2.0}]) == \
        '变化：00100 进入另一观察区间（日内 -2.0%，此前报过 2.5-3% 档）'
    # A ticker not watched before today is a first entry, not a band change.
    first = {'ticker': '02208', 'kind': 'soft_move', 'band': '1.5-2.5'}
    assert lead([first], [{**first, 'pct_1d': 1.6}]) == '变化：02208 首次进入观察区间（日内 +1.6%）'
    # Several at once are each named; the other kinds say what they are.
    high = {'ticker': 'RKLB', 'kind': 'near_20d_high'}
    many = lead([moved, first, high], [{**moved, 'pct_1d': -2.0}, {**first, 'pct_1d': 1.6},
                                       {**high, 'pct_from_high': -1.2}])
    assert many.count('；') == 2 and '00100 进入另一观察区间' in many
    assert '02208 首次进入观察区间' in many and 'RKLB 首次进入距20日高 3% 内（-1.2%）' in many
    # Crossing back into a band already delivered today adds no identity: the
    # seen set is unchanged, so the slot says nothing is new.
    assert pre.delta_lead({'components': []}, current=previous, previous=previous,
                          soft_candidates=[{**seen[0], 'pct_1d': -2.6}]) == \
        '变化：无（与上次送达相比，本档没有新条件）'
    # Alongside a hard trigger, the trigger keeps its own label and names.
    both = pre.delta_lead(
        {'components': ['breaches', 'soft_candidates_seen']}, soft_candidates=[],
        current={'breaches': [{'ticker': '07226', 'kind': 'move', 'level': 'high'}],
                 'soft_candidates_seen': [*seen, moved]},
        previous={**previous, 'breaches_seen': []})
    assert both == '变化：信号/触发档位（新触发：07226）、00100 进入另一观察区间（此前报过 2.5-3% 档）'
    # A new session's first comparison does not list the whole candidate set.
    opening = lead([moved], [], components={'components': ['session', 'soft_candidates_seen']})
    assert opening == '变化：本交易日首档、边缘候选'


def test_information_gap_line_keeps_the_fact_and_drops_the_exception_name():
    """#2805: 「同花顺7×24（URLError）」 put an exception class on kcn's card.
    The gap stays a ⛔ line; a count or a reason in card words stays with it."""
    assert pre.information_gap_line(['同花顺7×24（URLError）']) == \
        '⛔ 资讯缺口：同花顺7×24 未取到（不是无消息）'
    assert pre.information_gap_line(
        ['东财7×24（empty_or_failed）', 'sentiment_snapshot（unreadable: JSONDecodeError）',
         'Yahoo RSS（2/5 URLError、超时）', 'Google News（超出请求预算）']) == (
        '⛔ 资讯缺口：东财7×24、sentiment_snapshot、Yahoo RSS（2/5 超时）、'
        'Google News（超出请求预算） 未取到（不是无消息）')
    assert pre.information_gap_line([]) is None


def test_generic_headline_feed_is_not_repeated_in_intraday_card():
    block = ('🇺🇸 美股盯盘\n| CRCL | 1 |\n📰 新闻\n'
             '📰 CRCL (5条)\n   · old clipped headline\n\n'
             '🎯 机会雷达\n  ◆ RKLB')
    rendered = pre.strip_generic_news(block)
    assert 'old clipped headline' not in rendered
    assert '| CRCL |' in rendered and '🎯 机会雷达' in rendered
    # The card loses the feed; the model's context keeps it.
    assert pre.generic_news_feed(block) == ['📰 CRCL (5条)', '· old clipped headline']


ANALYZER = """🇭🇰 港股盯盘 | 09/25 11:33 HKT
  恒指 24,329 ▼1.74%  恒科 4,264 ▼2.24%

📊 市值 HK$63,746 | 浮盈 -46,347 (-42.1%) | 今日 -1,923

| 代码  |    股 |   成本 |   现价 |   今日 |    浮% |     浮$ |
|:------|------:|-------:|-------:|-------:|-------:|--------:|
| 00100 |   140 | 508.47 | 272.80 |  -2.2% | -46.4% | -32,994 |
| 07226 |  6200 |   4.36 |   2.75 |  -4.7% | -36.9% |  -9,977 |
| 03032 |   200 |   5.41 |   4.26 |  -2.3% | -21.1% |    -228 |

⚠️ 信号
  ✋ STOP? 00100 MINIMA | 今日-2.2% 浮-46.4%
  ✋ STOP? 07226 南方2倍做多 | 今日-4.7% 浮-36.9%
     · 浮亏 -36.9% 警惕止损

📉 亏损持仓 3/3  |  2x杠杆敞口 27%"""
TABLE = [line for line in ANALYZER.splitlines() if line.startswith('|')]


def _card(fresh=('07226',), stale=('03032',), p0=True, status_lines=(),
          seen=(('STOP', '00100'),)):
    block = pre.mark_card_changes(ANALYZER, fresh_tickers=set(fresh),
                                  unrefreshed=list(stale),
                                  seen_signals=set(seen), status_lines=status_lines)
    return pre.compose_card(
        block, p0_lines=['P0：07226 单日 -16.0%，07226 策略是否继续？'] if p0 else [],
        lead='变化：信号/触发档位（新触发：07226）',
        degraded=[pre.coverage_warning({'unrefreshed': list(stale)}), None])


def test_card_layout_contract():
    """kcn 2026-09-25 「还是有点乱」: the layout is a contract, not a habit.
    Order, the untouched table, one pointer for only the kinds used, and one
    symbol per meaning are enforced here rather than left to each edit."""
    msg = post.assemble_message({'raw_wechat_block': _card()}, '▎我的看法\n先看 07226。')
    lines = msg.splitlines()
    # 1. The analyzer's table is byte-identical and contiguous.
    start = lines.index(TABLE[0])
    assert lines[start:start + len(TABLE)] == TABLE
    def at(prefix):
        return next(i for i, line in enumerate(lines) if line.startswith(prefix))
    # 2. Block order: title, P0, 变化, ⛔, strip/book, table, pointer, new
    #    signals, standing state, then the judgment below the whole data block.
    order = [0, at('P0：'), at('变化：'), at('⛔'), at('  恒指'),
             at('📊'), start, at('↑ '), at('⚠️ 信号'), at('▎持续状态'),
             at('今日已报、仍在：'), at('亏损持仓'), at('▎我的看法')]
    assert order == sorted(order) and lines[0].startswith('🇭🇰 港股盯盘')
    # 3. One pointer, after a blank line, naming only the kinds present.
    # An unverified row is named once, in ⛔ — not again next to the table.
    pointers = [line for line in lines if line.startswith('↑ ')]
    assert pointers == ['↑ 新异动/触发 07226']
    assert lines[at('↑ ') - 1] == ''
    assert [line for line in lines if '03032' in line and not line.startswith('|')] == [
        '⛔ 数据降级：03032 行情未证实（沿用上一笔）']
    assert not any(line.startswith('↑ ') for line in _card(fresh=(), stale=()).splitlines())
    assert not any(line.startswith('↑ ') for line in _card(fresh=()).splitlines())
    # 4. ⛔ is only data health; ⚠️ only heads the analyzer's signal block.
    assert all(line.startswith('⛔') for line in lines if '数据降级' in line)
    assert [line for line in lines if line.startswith('⚠️')] == ['⚠️ 信号']
    # 5. Repeated signals fold into the standing-state block; a new one stays
    #    whole with its reason. The analyzer's risk line moves there, icon off.
    assert lines[at('▎持续状态') + 1:at('▎持续状态') + 3] == [
        '今日已报、仍在：STOP? 00100', '亏损持仓 3/3｜2x杠杆敞口 27%']
    assert 'STOP? 00100 MINIMA' not in msg and '警惕止损' in msg
    assert not any(line.startswith('📉') for line in lines)
    # 6. #2805 layout A: with every signal already delivered the ⚠️ header goes
    #    too, the level is said once, and no blank line is left doubled.
    told = _card(fresh=(), stale=(), p0=False,
                 seen=(('STOP', '00100'), ('STOP', '07226'))).splitlines()
    assert not any(line.startswith('⚠️') for line in told) and '警惕止损' not in told
    assert told[told.index(TABLE[-1]) + 1:] == [
        '', '▎持续状态', '今日已报、仍在：STOP? 00100、07226', '亏损持仓 3/3｜2x杠杆敞口 27%']
    # kcn 2026-09-25 「表格位置怎么倒置了？」: the judgment never precedes the
    # table, with or without P0/⛔ lines.
    quiet = post.assemble_message({'raw_wechat_block': _card(stale=(), p0=False)}, '▎我的看法\nx')
    q = quiet.splitlines()
    assert q[1].startswith('变化：') and q.index('▎我的看法') > q.index(TABLE[-1])
    assert q[-2:] == ['▎我的看法', 'x']


def test_judgment_packet_preserves_every_decision_field():
    ctx = {
        'status': 'ok', 'context_id': 'abc', 'market': 'hk',
        'plan_context': {'open': [{'ticker': '00100', 'shares': 0},
                                  {'ticker': '02208', 'shares': 0}]},
        'peer_scan': {'00100': {'theme': 'AI'}, '02208': {'theme': 'wind'}},
        'semantic_state': {'breaches': []}, 't0_setups': {'rows': ['rating']},
        'watch_levels': {'index': 'HSI'}, 'source_signals_detail': [],
        'active_information_candidates': {'error': 'source unavailable'},
    }
    # Layered, never trimmed (contract §3): every field is either in the core
    # packet or listed in its index — together they are the whole context.
    packet = pre.judgment_packet(ctx)
    listed = {ref['name'] for ref in packet['index']['references']}
    core = {key for key in packet if key != 'index'}
    assert core | listed == set(ctx) and not core & listed
    assert {key: packet[key] for key in core} == {key: ctx[key] for key in core}
    # #1839 lost zero-share plans: they are core, whole.
    assert len(packet['plan_context']['open']) == 2
    assert 'peer_scan' in listed and 'peer_scan' not in packet


def test_soft_sweep_surfaces_a_name_below_the_hard_anomaly_gate():
    block = '🇭🇰 港股盯盘\n| EDGE | 10 | 8 | 9.00 | +2.1% | +12% | +10 |'
    holdings, candidates = pre.decision_sweep(
        block, {'active': 1, 'refreshed': 1, 'unrefreshed': []},
        {'open': [{'ticker': 'EDGE', 'condition_price': 9.5,
                   'decision_id': 'plan-1'}]},
        {'levels': {'EDGE': {'pct_from_high': -2.4}},
         'rows': [{'label': 'EDGE', 'zscore20': 1.7}]},
        {'rows': {'EDGE': {'grade_label': 'watch', 'range_pos': 88}}})
    assert holdings[0]['quote_fresh'] is True
    assert holdings[0]['plan_distances'][0]['pct_to_trigger'] == 5.56
    assert {'soft_move', 'near_20d_high', 'zscore_watch', 't0_quality'} == {
        row['kind'] for row in candidates}


def test_strategy_policy_suppresses_copy_without_discarding_source_signal():
    configured = {'AAA': {'suppress_cost_basis_signals': True}}
    counts = {'alert': 0, 'watch': 0, 'stop': 1, 'trim': 0}
    source = [{'ticker': 'AAA', 'level': 'STOP', 'line': 'STOP AAA'}]
    effective, rows = policy.actionable_signals(counts, source, configured)
    assert source[0]['ticker'] == 'AAA' and effective['stop'] == 0 and rows == []
    block = ('🇺🇸 美股盯盘\n⚠️ 信号\n  ▼ STOP-LOSS AAA | 浮-20%\n'
             '     · 浮亏触发\n\n📉 亏损持仓 1/1')
    rendered = policy.strip_suppressed_signal_lines(block, configured)
    assert 'STOP-LOSS AAA' not in rendered and '亏损持仓' in rendered


def test_the_signal_header_survives_a_section_led_by_trim_or_alert():
    # The guard knew ▼ △ ✋ ▲ only: a TRIM (▽) or HK ALERT (⚠️) first line lost
    # the header, and mark_card_changes stopped folding the section (#2219).
    for first in ('  ▽ TRIM RKLX | 今日-6.9% 浮-65.4%', '  ⚠️ ALERT 00100 | 今日-9.1%'):
        block = f'⚠️ 信号\n{first}\n\n📉 亏损持仓 1/1'
        assert policy.strip_suppressed_signal_lines(block, {}).startswith('⚠️ 信号\n')
    # A section stripped empty still loses its header.
    emptied = policy.strip_suppressed_signal_lines(
        '⚠️ 信号\n  ▼ STOP-LOSS AAA | 浮-20%\n\n📉 亏损持仓 1/1',
        {'AAA': {'suppress_cost_basis_signals': True}})
    assert '⚠️ 信号' not in emptied


def test_strategy_escalations_need_fresh_daily_and_weekly_evidence():
    policies = {'AAA': {'escalations': [
        {'ticker': 'AAA', 'window': 'session', 'below_pct': -15},
        {'ticker': 'BASE', 'window': 'five_sessions', 'below_pct': -25},
    ]}}
    bars = [{'date': day, 'close': 100} for day in
            ('2026-09-17', '2026-09-18', '2026-09-21', '2026-09-22', '2026-09-23')]
    checks = []
    rows = policy.escalations(policies, [{'ticker': 'AAA', 'move_pct': -15.1}],
        {'active': 2, 'refreshed': 2, 'unrefreshed': []}, {'BASE': 74},
        [{'label': 'BASE', 'code': 'usBASE'}], lambda *_: bars, '2026-09-24',
        checks=checks)
    assert [(r['ticker'], r['move_pct']) for r in rows] == [('AAA', -15.1), ('BASE', -26.0)]
    assert [row['status'] for row in checks] == ['triggered', 'triggered']
    missing_checks = []
    assert policy.escalations(policies, [], {'active': 2, 'refreshed': 1,
        'unrefreshed': ['BASE']}, {'BASE': 74}, [], lambda *_: bars,
        '2026-09-24', checks=missing_checks) == []
    assert missing_checks[1]['status'] == 'unavailable'


def test_instance_strategy_has_only_the_two_current_p0_lines(tmp_path):
    """SPCH's contract (-15% day, SPCX -25% over five sessions; the $3000 line
    was revoked 08-13) comes out of a ticker-free strategy bound per holding."""
    root = Path(__file__).resolve().parents[1]
    configured = (root / 'config/intraday-strategy-policies.json').read_text()
    assert '$3000' not in configured
    assert not re.search(r'"ticker"', configured)
    (tmp_path / 'config').mkdir()
    (tmp_path / 'config/intraday-strategy-policies.json').write_text(configured)
    (tmp_path / 'portfolio.json').write_text(json.dumps({'portfolios': {'us_stocks': {
        'holdings': [{'ticker': 'SPCH', 'shares': 300, 'strategy': 'infinite_ammo_dca'},
                     {'ticker': 'RKLX', 'shares': 10, 'strategy': 'infinite_ammo_dca'},
                     {'ticker': 'CRCL', 'shares': 2}]}}}))
    loaded = policy.load(tmp_path, 'us')
    rules = {holding: [(row['ticker'], row['window'], row['below_pct'])
                       for row in loaded[holding]['escalations']] for holding in loaded}
    assert rules == {
        'SPCH': [('SPCH', 'session', -15), ('SPCX', 'five_sessions', -25)],
        # Another holding choosing the strategy gets its own underlying, not SPCX.
        'RKLX': [('RKLX', 'session', -15), ('RKLB', 'five_sessions', -25)],
    }


def test_an_unresolvable_underlying_is_unavailable_evidence_not_a_silent_skip():
    policies = {'AAA': {'escalations': [
        {'subject': 'underlying', 'ticker': None, 'window': 'five_sessions',
         'below_pct': -25}]}}
    errors, checks = [], []
    assert policy.escalations(policies, [], {'active': 1, 'refreshed': 1,
        'unrefreshed': []}, {}, [], lambda *_: [], '2026-09-24',
        errors=errors, checks=checks) == []
    assert checks[0]['status'] == 'unavailable'
    assert errors == ['AAA: underlying not in instrument registry']


def test_configured_no_reduce_advice_fails_closed():
    ctx = {'market': 'us', 'should_alert': False,
           'holding_policies': {'AAA': {'forbid_reduce_advice': True}},
           'raw_wechat_block': '🇺🇸 美股盯盘'}
    prose = '▎我的看法\n建议 AAA 现在砍仓 300 股。' + '今日继续观察其他票的变化。' * 4
    issues = post.validate(post.assemble_message(ctx, prose), ctx, prose)
    assert post.categorize(issues) == 'fail'
    assert any('AAA 策略冲突' in issue for issue in issues)
    factual = '▎我的看法\nAAA 旧计划仍挂 cut，但与当前策略冲突，不重复减仓建议。' + '其他票照常检查。' * 5
    assert not any('策略冲突' in issue for issue in post.validate(
        post.assemble_message(ctx, factual), ctx, factual))
    mixed = '▎我的看法\nAAA 旧计划仍挂 cut，但建议现在减仓。' + '其他票照常检查。' * 5
    assert any('AAA 策略冲突' in issue for issue in post.validate(
        post.assemble_message(ctx, mixed), ctx, mixed))


def test_unavailable_strategy_source_cannot_be_called_clear():
    ctx = {'market': 'us', 'should_alert': False,
           'raw_wechat_block': '🇺🇸 美股盯盘',
           'strategy_checks': [{'ticker': 'BASE', 'window': 'five_sessions',
                                'status': 'unavailable'}]}
    prose = '▎我的看法\nBASE 五交易日跌幅未触发 P0，本档先继续观察。' + '其余票按原计划等待。' * 5
    issues = post.validate(post.assemble_message(ctx, prose), ctx, prose)
    assert any('策略证据不足' in issue for issue in issues)
    assert post.categorize(issues) == 'fail'


def test_policy_gates_see_a_code_glued_to_chinese():
    """#1852: `\b` never fires between a code and CJK, so ordinary prose
    without spaces walked past both strategy gates."""
    ctx = {'market': 'hk', 'should_alert': False, 'raw_wechat_block': '🇭🇰 港股盯盘',
           'holding_policies': {'00100': {'forbid_reduce_advice': True},
                                'SPCH': {'forbid_reduce_advice': True}}}
    for glued in ('建议00100立即减仓', '建议SPCH立即减仓', 'SPCH现在cut掉'):
        prose = f'▎我的看法\n{glued}，风险已经扩大。' + '其他票照常检查。' * 5
        issues = post.validate(post.assemble_message(ctx, prose), ctx, prose)
        assert any('策略冲突' in issue for issue in issues), glued
    ctx = {'market': 'hk', 'should_alert': False, 'raw_wechat_block': '🇭🇰 港股盯盘',
           'strategy_checks': [{'ticker': '00100', 'window': 'session',
                                'status': 'unavailable'}]}
    prose = '▎我的看法\n00100单日涨跌未触发升级线，先观察。' + '其余票按原计划等待。' * 5
    issues = post.validate(post.assemble_message(ctx, prose), ctx, prose)
    assert any('策略证据不足' in issue for issue in issues)


def test_detailed_judgment_kept_for_filing_plan_and_add_side():
    # A primary filing, an outstanding risk_rule plan, and three add-side
    # dispositions routinely need more than the old 320/600 character limits.
    ctx = {'market': 'hk', 'should_alert': False,
           'raw_wechat_block': '🇭🇰 港股盯盘'}
    prose = '▎我的看法\n' + ('一级披露核验；纪律单仍挂；加仓侧 candidate/wait/reject 不授权。' * 18)
    issues = post.validate(post.assemble_message(ctx, prose), ctx, prose)
    assert any('判断段长度' in issue and '软上限' in issue for issue in issues)
    assert post.categorize(issues) != 'fail'


def test_bad_sidecar_does_not_get_fresh_timestamp(tmp_path):
    path = tmp_path / 'insights.json'
    path.write_text(json.dumps({'status_banner': ['invalid'], 'movers': {}}))
    assert post.normalize_intraday_insights(path) is False
    assert 'generated_at' not in json.loads(path.read_text())


def test_a_number_from_a_folded_signal_reason_still_has_its_source():
    """09-25 00:33 replay: folding RKLX's repeated STOP also removed its
    '价格高于MA20 +25.7%' reason from the card, and a correct +25.7% in the
    judgment was flagged as unsourced. The model reads `analyzer_block`."""
    analyzer = ('🇺🇸 美股盯盘\n\n⚠️ 信号\n  ▼ STOP-LOSS RKLX | 今日+10.9% 浮-60.8%\n'
                '     · 价格高于MA20 +25.7%\n\n📉 亏损持仓 2/4')
    card = pre.mark_card_changes(analyzer, fresh_tickers=set(), unrefreshed=[],
                                 seen_signals={('STOP', 'RKLX')})
    assert '+25.7%' not in card
    ctx = {'market': 'us', 'should_alert': False, 'raw_wechat_block': card,
           'analyzer_block': analyzer}
    prose = '▎我的看法\nRKLX 站上 MA20 +25.7%，反弹非反转，不追。' + '其余票按原计划等待。' * 4
    issues = post.validate(post.assemble_message(ctx, prose), ctx, prose)
    assert not any('+25.7%' in issue for issue in issues), issues


def test_an_unchanged_slot_may_say_so_in_one_line_but_not_invent_a_move():
    """always_full (kcn 2026-09-25): an unchanged slot still gets a judgment.
    A short honest line passes the 60-char floor; a short line that does not
    say 'no change' still warns, and a claimed new move is flagged."""
    ctx = {'market': 'hk', 'should_alert': False, 'semantic_unchanged': True,
           'raw_wechat_block': '🇭🇰 港股盯盘'}
    honest = '▎我的看法\n本档无实质变化，继续观察 07226，下一触发 3.0。'
    issues = post.validate(post.assemble_message(ctx, honest), ctx, honest)
    assert not any('太敷衍' in i or '新异动' in i for i in issues), issues
    natural = '▎我的看法\n本档没有实质性变化，继续观察 07226。'
    issues = post.validate(post.assemble_message(ctx, natural), ctx, natural)
    assert not any('太敷衍' in i for i in issues), issues
    vague = '▎我的看法\n继续观察 07226，下一触发 3.0。'
    assert any('太敷衍' in i for i in post.validate(
        post.assemble_message(ctx, vague), ctx, vague))
    invented = '▎我的看法\n本档无实质变化，但 07226 出现新异动，下一触发 3.0。'
    flagged = [i for i in post.validate(post.assemble_message(ctx, invented), ctx, invented)
               if '新异动' in i]
    assert flagged and flagged[0].endswith('(advisory)')
    changed = {**ctx, 'semantic_unchanged': False}
    assert any('太敷衍' in i for i in post.validate(
        post.assemble_message(changed, honest), changed, honest))


def test_stale_headline_time_in_next_sentence_is_accepted(monkeypatch):
    monkeypatch.setattr(post.intraday_information, 'stale_titles',
                        lambda _information, _full=None: ['某公司发布重大公告'])
    ctx = {'information': {}}
    assert post.check_stale_citation('某公司发布重大公告。截至10:00，内容是业绩预增。', ctx) == []
    assert post.check_stale_citation('某公司发布重大公告。业绩预增。', ctx)


def test_a_context_field_name_in_the_judgment_is_flagged_on_top():
    """Regression: 2026-09-25 HK 14:33 delivered 「本档无实质变化（semantic_unchanged）」
    with status pass — the pipeline-term word list did not know the key. The
    rule is the identifier shape, and it escalates (a banner), not a footnote."""
    ctx = {'market': 'hk', 'should_alert': False, 'semantic_unchanged': True,
           'raw_wechat_block': '🇭🇰 港股盯盘'}
    leaked = ('▎我的看法\n本档无实质变化（semantic_unchanged），无新硬催化。'
              '07226 现价 2.80 距 3.0 未触发；下一触发：恒科 4,300 / 07226 3.0。')
    issues = post.validate(post.assemble_message(ctx, leaked), ctx, leaked)
    flagged = [i for i in issues if '字段名' in i]
    assert flagged and 'semantic_unchanged' in flagged[0]
    assert not val.is_advisory(flagged[0])
    assert post.categorize(issues) == 'warn'
    # 2026-09-24 US: a key=value pair is the same leak.
    kv = '▎我的看法\nCRCL verdict=wait，技术未接近突破。' + '其余票按原计划等待。' * 4
    assert any('verdict' in i for i in post.validate(post.assemble_message(ctx, kv), ctx, kv)
               if '字段名' in i)
    clean = leaked.replace('（semantic_unchanged）', '')
    assert not any('字段名' in i for i in post.validate(
        post.assemble_message(ctx, clean), ctx, clean))
    # Tickers, indicators and codes are not identifiers.
    assert val.check_identifier_leak('07226 跌破 MA20，RSI 28，T+0 追高，SPCX/SPCH 同跌，z=2.22') == []


def _reads(n):
    verdicts = ['reject', 'wait', 'candidate', 'wait', 'wait', 'reject']
    return {'rows': [{'ticker': f'T{i}', 'verdict': verdicts[i],
                      'why': '纪律动作未了结:反弹减仓 5 股(风控规则)' + '很长' * 30 * (i == 1),
                      'needs': '站上 73.57(现距高 0.84%)'} for i in range(n)]}


def test_add_side_line_copies_every_verdict_and_sits_before_the_judgment():
    """Card block 10b: non-empty `add_side_reads.rows` ⇒ the card carries the
    add-side line, row for row (ticker and three-state copied, never
    rewritten), with the caveat, a fixed cap and clipped why/needs."""
    reads = _reads(6)
    block = pre.append_add_side_section(_card(), reads)
    msg = post.assemble_message({'raw_wechat_block': block}, '▎我的看法\n先看 07226。')
    lines = msg.splitlines()
    head = lines.index(pre.ADD_SIDE_HEADER)
    assert '三态都不是下单授权' in lines[head]
    assert (lines.index(TABLE[-1]) < lines.index('▎持续状态')
            < next(i for i, x in enumerate(lines) if x.startswith('亏损持仓'))
            < head < lines.index('▎我的看法'))
    shown = lines[head + 1:head + 1 + pre.MAX_ADD_SIDE_ROWS]
    inverse = {word: verdict for verdict, word in pre.ADD_SIDE_WORDS.items()}
    for line, row in zip(shown, reads['rows']):
        ticker, rest = line.strip().removeprefix('· ').split(' ', 1)
        assert ticker == row['ticker']
        assert inverse[rest.split('：', 1)[0]] == row['verdict']
    assert lines[head + 1 + pre.MAX_ADD_SIDE_ROWS] == '  …另有 2 条'
    assert all(len(line.split('：', 1)[1].split(' → ')[0]) <= pre.ADD_SIDE_WHY_CHARS
               for line in shown)
    # Empty rows: no block, byte-identical card.
    assert pre.append_add_side_section(_card(), {'rows': []}) == _card()
    # kcn 2026-10-09 「千万不要影响到我们的加仓侧」: layout A (#2805) leaves
    # this block alone — its own header with the icon and the caveat, the
    # indented rows with why → needs, after ▎持续状态 and last in the data.
    assert pre.ADD_SIDE_HEADER == '🛰️ 加仓侧（三态都不是下单授权）'
    one = {'rows': [{'ticker': '07226', 'verdict': 'wait',
                     'why': '窗口内无一手公告、技术面未接近突破',
                     'needs': '等一手催化或技术面进入突破区'}]}
    tail = pre.append_add_side_section(_card(), one).splitlines()[-3:]
    assert tail == ['', '🛰️ 加仓侧（三态都不是下单授权）',
                    '  · 07226 等待：窗口内无一手公告、技术面未接近突破 → 等一手催化或技术面进入突破区']
    # ⚠️ stays the signal header alone.
    assert [line for line in lines if line.startswith('⚠️')] == ['⚠️ 信号']

TRIGGER_CTX = {'market': 'hk', 'should_alert': False, 'semantic_unchanged': True,
               'raw_wechat_block': '🇭🇰 港股盯盘\n\n| 07226 |  6200 |   4.36 |   2.80 |',
               'watch_levels': {'hstech_breakdown': 4300, '07226_trim_trigger': 3.0}}


def _trigger_issues(prose, ctx=TRIGGER_CTX):
    return [i for i in post.validate(post.assemble_message(ctx, prose), ctx, prose)
            if '下一触发' in i]


def test_next_trigger_is_its_own_checked_block_above_the_judgment():
    """Card block 11. 2026-09-25 14:33 ended its paragraph with
    「下一触发：恒科 4,300 / 07226 3.0 / 02208 8.84」 — unchecked, and kcn had to
    find it. Now: its own line, lifted above ▎我的看法, every item naming a
    subject and quoting a level the context holds."""
    prose = ('▎我的看法\n本档无实质变化，恒科贴近破位线，07226 杠杆放大。\n'
             '下一触发：恒科 跌破 4,300；07226 站上 3.0（减仓线）')
    assert _trigger_issues(prose) == []
    lines = post.assemble_message(TRIGGER_CTX, prose).splitlines()
    trigger = lines.index('下一触发：恒科 跌破 4,300；07226 站上 3.0（减仓线）')
    assert trigger < lines.index('▎我的看法') and lines[trigger - 1] == ''
    assert lines[-1] == '本档无实质变化，恒科贴近破位线，07226 杠杆放大。'
    # The real 14:33 shape: inline at the end of a paragraph.
    inline = '▎我的看法\n本档无实质变化。下一触发：恒科 4,300 / 07226 3.0'
    assert any('没有单独成行' in i for i in _trigger_issues(inline))
    assert any('缺「下一触发」行' in i for i in _trigger_issues('▎我的看法\n本档无实质变化。'))
    # A level the context does not hold, or an item with no subject, is named.
    made_up = '▎我的看法\n本档无实质变化。\n下一触发：07226 站上 3.2；等反弹 4,300'
    flagged = _trigger_issues(made_up)
    assert len(flagged) == 1 and '3.2' in flagged[0] and '无标的' in flagged[0]
    assert not val.is_advisory(flagged[0])
    # The 60-char floor is measured on the judgment, not the trigger line.
    ctx = {**TRIGGER_CTX, 'semantic_unchanged': False}
    short = '▎我的看法\n07226 跟随恒科。\n下一触发：恒科 跌破 4,300；07226 站上 3.0（减仓线）'
    assert any('太敷衍' in i for i in post.validate(post.assemble_message(ctx, short), ctx, short))


def test_a_second_next_trigger_line_is_checked_and_never_reaches_the_card_raw():
    """#2077: only the first 下一触发 line used to be lifted and checked; a
    second one stayed in the judgment and went out with a level the context
    does not hold while the gate said pass."""
    prose = ('▎我的看法\n本档无实质变化，恒科贴近破位线，07226 杠杆放大。\n'
             '下一触发：恒科 跌破 4,300\n'
             '下一触发：07226 站上 9.99 立即清仓')
    flagged = _trigger_issues(prose)
    assert len(flagged) == 1 and '9.99' in flagged[0]
    lines = post.assemble_message(TRIGGER_CTX, prose).splitlines()
    assert [line for line in lines if line.startswith('下一触发')] == [
        '下一触发：恒科 跌破 4,300；07226 站上 9.99 立即清仓']
    assert lines[-1] == '本档无实质变化，恒科贴近破位线，07226 杠杆放大。'
    # Two checkable lines merge into one line and stay clean.
    good = prose.replace('9.99 立即清仓', '3.0（减仓线）')
    assert _trigger_issues(good) == []


def test_every_reference_the_core_packet_names_resolves_to_the_same_content(tmp_path):
    """Contract §3 invariants: an entry moved out of the core packet is listed
    in its index and fetched by name, pinned to the same context_id, with the
    content on disk (the authority); a ticker slice is a subset; the analyzer's
    output is never a reference."""
    from clawock.tools import build_registry
    from clawock.tools.context_tools import slice_reference

    ctx = {
        'status': 'ok', 'market': 'hk', 'context_id': 'c0ffee000001',
        'analyzer_block': '🇭🇰 港股盯盘', 'plan_context': {'open': []},
        'signals_detail': [{'ticker': '07226', 'level': 'STOP'}, {'ticker': '00100', 'level': 'WATCH'}],
        'source_signals_detail': [], 'headline_feed': ['10:05 恒科走弱', '11:20 07226 放量'],
        'peer_scan': {'00100': {'theme': 'AI'}, '07226': {'theme': '2x HSTECH'}},
        't0_setups': {'rows': {'00100': {'grade_label': '中性'}}},
        'early_trend_candidates': {'rows': []}, 'provisional_setups': {'rows': []},
        'opportunity_radar': {'rows': [{'label': 'HSTECH', 'holdings': ['07226']}], 'levels': {}},
        'prior_semantic_state': {'session': 'hk:2026-09-25', 'breaches_seen': []},
        'information_full': {'tickers': {'07226': [{'title': '恒科走弱'}]}},
    }
    tmp = tmp_path / 'memory' / '.tmp'
    tmp.mkdir(parents=True)
    (tmp / 'intraday-context-hk-latest.json').write_text(json.dumps(ctx, ensure_ascii=False))
    registry = build_registry(tmp_path)
    packet = pre.judgment_packet(ctx)
    assert 'analyzer_block' in packet and 'analyzer_block' not in pre.REFERENCE_ENTRIES
    refs = packet['index']['references']
    assert {ref['name'] for ref in refs} == set(pre.REFERENCE_ENTRIES)
    for ref in refs:
        assert f"--arg entry={ref['name']}" in ref['fetch'] and 'c0ffee000001' in ref['fetch']
        got = registry.call(pre.REFERENCE_TOOL, market='hk', context_id='c0ffee000001',
                            entry=ref['name'])
        assert json.loads(got) == ctx[ref['name']], ref['name']
    one = json.loads(registry.call(pre.REFERENCE_TOOL, market='hk', context_id='c0ffee000001',
                                   entry='signals_detail', ticker='07226'))
    assert one == [{'ticker': '07226', 'level': 'STOP'}]
    assert slice_reference(ctx['peer_scan'], ticker='07226') == {'07226': {'theme': '2x HSTECH'}}
    assert slice_reference(ctx['opportunity_radar'], ticker='07226')['rows'] == ctx['opportunity_radar']['rows']
    assert slice_reference(ctx['headline_feed'], since='11:00',
                           as_of='2026-09-30T11:33:00+08:00') == ['11:20 07226 放量']
    # Another generation's id, or a name that is not a reference, is refused.
    import pytest
    from clawock.tools.base import ToolError
    with pytest.raises(ToolError):
        registry.call(pre.REFERENCE_TOOL, market='hk', context_id='stale0000000', entry='peer_scan')
    with pytest.raises(ToolError):
        registry.call(pre.REFERENCE_TOOL, market='hk', context_id='c0ffee000001',
                      entry='analyzer_block')


def test_information_full_ticker_slice_keeps_live_rows_and_macro():
    from clawock.tools.context_tools import slice_reference

    full = {
        'tickers': {'00100': [{'title': 'morning'}], '02208': []},
        'live': {'tickers': {'00100': [{'title': 'live'}], '02208': []},
                 'flashes': []},
        'macro': {'rates': 'unchanged'},
    }
    selected = slice_reference(full, ticker='00100')
    assert selected['tickers'] == {'00100': [{'title': 'morning'}]}
    assert selected['live']['tickers'] == {'00100': [{'title': 'live'}]}
    assert selected['macro'] == {'rates': 'unchanged'}


def test_information_full_since_slice_filters_the_per_ticker_rows():
    # `--arg since=` returned `tickers` ({ticker: [row, …]}) whole (#2218).
    from clawock.tools.context_tools import slice_reference

    full = {
        'tickers': {'00100': [{'title': 'old', 'published_at': '2026-09-26T13:09:00+08:00'},
                              {'title': 'new', 'published_at': '2026-09-30T14:10:00+08:00'}]},
        'em_market_724': [{'title': 'flash', 'date': '2026-09-30 09:40'}],
        'macro': {'rates': 'unchanged'},
    }
    selected = slice_reference(full, since='14:00', as_of='2026-09-30T15:33:00+08:00')
    assert selected['tickers'] == {'00100': [full['tickers']['00100'][1]]}
    assert selected['em_market_724'] == []
    assert selected['macro'] == {'rates': 'unchanged'}
    # No arguments still returns every family as it was.
    assert slice_reference(full) == full


def test_a_stale_title_only_in_the_reference_layer_is_held_to_the_label_rule():
    # The gate read the summary's three rows a ticker; the model is told the
    # rest are in information_full and quoted them unlabelled (#2217).
    title = '港股大模型板塊走低，MINIMAX-W(00100.HK)跌超10%'
    ctx = {'information': {'tickers': {'00100': []}},
           'information_full': {'tickers': {'00100': [
               {'title': title, 'cite': f'《{title}》（news_evidence_graph，截至 09-26 21:09，开盘前旧闻）'}]}}}
    assert post.check_stale_citation(f'{title}，情绪偏弱。', ctx)
    assert post.check_stale_citation(f'{title}（截至 09-26 21:09，开盘前旧闻），情绪偏弱。', ctx) == []


def test_a_clipped_add_side_line_never_cuts_a_number():
    """「…RKLB 回踩守住 73.5…」 for 73.57 reads as another price."""
    text = '先把纪律动作走完,再谈加仓(之后:RKLB 回踩守住 73.57(现高于前高 0.84%))'
    for limit in range(20, len(text)):
        clipped = pre._clip(text, limit)
        assert len(clipped) <= limit
        head = clipped.rstrip('…')
        # whatever number survives is a whole number from the source
        for number in re.findall(r'\d+(?:\.\d+)?', head):
            assert re.search(rf'(?<![\d.]){re.escape(number)}(?![\d.])', text), (limit, clipped)


def test_an_unchanged_sec_mirror_list_is_one_sentence():
    active = {'candidates': [], 'partially_degraded_issuers': ['RKLB']}
    state = {'session': 'us:2026-09-25'}
    prior = {'session': 'us:2026-09-25', 'primary_source_health': {'partial': ['RKLB']}}
    assert pre.partial_unchanged(active, state, prior)
    folded = pre.append_active_information_section('x', active, partial_unchanged=True)
    assert folded.splitlines()[-1] == \
        '  · RKLB：无新披露（SEC 直连降级已由镜像兜住；名单未变，不再逐档印）'
    assert not pre.partial_unchanged(active, state, {**prior, 'session': 'us:2026-09-24'})
    assert not pre.partial_unchanged(
        active, state, {**prior, 'primary_source_health': {'partial': ['CRCL']}})
    assert not pre.partial_unchanged({'partially_degraded_issuers': []}, state, prior)


def test_a_leveraged_leg_sits_next_to_its_underlying_with_the_gap():
    """kcn 2026-09-25 preview: the T+0 map (`t0_setups.rows.<t>.leveraged`),
    the underlying's move from the table, the index strip or this slot's bars,
    and the gap in pp — written so the validator's derived-figure rule accepts
    it, and stated as missing when no reading exists."""
    holdings = [{'ticker': '07226', 'pct_1d': -2.8}, {'ticker': '00100', 'pct_1d': -1.6}]
    t0 = {'rows': {'07226': {'leveraged': '2x HSTECH'}, '00100': {'leveraged': None},
                   'RKLX': {'leveraged': '2x RKLB'}}}
    hk = pre.leverage_legs('hk', holdings, t0, '  恒指 24,477 ▼1.15%  恒科 4,304 ▼1.31%',
                           {}, bars=lambda *_a: [], session_date='2026-09-25')
    assert [(r['ticker'], r['underlying_pct'], r['source'], r['gap_pp']) for r in hk] == [
        ('07226', -1.31, 'index_strip', -0.18)]
    text = '07226：恒科 -1.31% → 2x 应 -2.62%，实测 -2.8%，差 -0.18pp'
    assert pre.leverage_lines(hk) == [text]
    # In the standing-state block, the table itself untouched.
    line = _card(status_lines=pre.leverage_lines(hk)).splitlines()
    start = line.index(TABLE[0])
    assert line[start:start + len(TABLE)] == TABLE
    assert line.index('▎持续状态') < line.index(text)
    # The whole row is one sentence to the validator: a ； before 实测 would
    # leave the gap with one operand and a judgment repeating it flagged.
    at = text.index('-0.18pp')
    assert val._derived_in_sentence(text, at, 'pp', '-0.18')
    assert not val._derived_in_sentence(
        text.replace('%，实测', '%；实测'), at, 'pp', '-0.18')

    us = [{'ticker': 'RKLX', 'pct_1d': -1.4}, {'ticker': 'SPCX', 'pct_1d': -1.0},
          {'ticker': 'SPCH', 'pct_1d': -2.3}]
    t0['rows']['SPCH'] = {'leveraged': '2x SPCX'}
    bars = [{'date': '2026-09-24', 'close': 73.61}, {'date': '2026-09-25', 'close': 73.95}]
    legs = pre.leverage_legs('us', us, t0, '', {}, bars=lambda code, _n: bars,
                             session_date='2026-09-25', codes={'RKLB': 'usRKLB.OQ'})
    assert [(r['ticker'], r['underlying_pct'], r['source'], r['gap_pp']) for r in legs] == [
        ('RKLX', 0.46, 'slot_daily_bar', -2.32), ('SPCH', -1.0, 'holdings_table', -0.3)]
    # No bar dated this session: the reading is missing and nothing is computed.
    stale = pre.leverage_legs('us', us, t0, '', {'levels': {'RKLB': {
        'close': 73.13, 'pct_from_high': -3.09}}}, bars=lambda code, _n: bars,
        session_date='2026-09-28', codes={'RKLB': 'usRKLB.OQ'})
    assert stale[0]['gap_pp'] is None and stale[0]['missing']
    shown = pre.leverage_lines(stale, ['SPCH'])
    assert shown == [
        'RKLX：2x RKLB 今日涨跌本档未取到，不算差值（现价 73.13，距前高 -3.1%）',
        'SPCH：SPCX -1.0% → 2x 应 -2.0%，实测 -2.3%，差 -0.30pp',
        '  ↳ 行情未证实：SPCH（见上方 ⛔ 行，差值仅作参考）']
    assert val._derived_in_sentence(shown[1], shown[1].index('-0.30pp'), 'pp', '-0.30')
    assert pre.leverage_lines([]) == []


def test_the_judgment_marker_named_inside_a_sentence_is_missing_and_revisable():
    """#2049: 「这一档我不写 ▎我的看法 段：…」 passed as the section, and the
    60-char floor counted the rest of the prose as its body."""
    ctx = {**TRIGGER_CTX, 'semantic_unchanged': False}
    prose = ('07226 跟随恒科走弱，这一档我不写 ▎我的看法 段：恒科贴近破位线，杠杆腿波动放大，'
             '等收盘再看是否需要调整，其余持仓维持原判断不动，00100 与 02208 本档没有新的异动，'
             '仍按晨间计划执行。\n'
             '下一触发：恒科 跌破 4,300；07226 站上 3.0（减仓线）')
    issues = post.validate(post.assemble_message(ctx, prose), ctx, prose)
    assert f'缺段标记 "{post.REQUIRED_SECTION}"' in issues
    assert post.categorize(issues) == 'fail'
    assert any(key in f'缺段标记 "{post.REQUIRED_SECTION}"' for key in post.REVISABLE)
    # Own-line marker, body measured from after it: unchanged behaviour.
    good = '▎我的看法\n' + prose.split('段：', 1)[1]
    assert not any('缺段标记' in i or '太敷衍' in i
                   for i in post.validate(post.assemble_message(ctx, good), ctx, good))


def test_a_stale_live_title_beyond_the_summary_cap_is_held_to_the_label_rule():
    from clawock.evidence.intraday_information import stale_titles
    title = '根據首次公開發售後股份激勵計劃授出獎勵（公告及通告 - [股份計劃]）'
    fresh = [{'title': f'盘中新消息第{i}条', 'stale': False, 'cite': '盘中实时'}
             for i in range(4)]
    old = {'title': title, 'stale': True,
           'cite': f'《{title}》（HKEXnews披露易，09-29 20:43 HKT 发布，开盘前旧闻）'}
    ctx = {'information': {'live': {'00100': fresh}},
           'information_full': {'live': {'tickers': {'00100': [*fresh, old]}}}}
    assert title in stale_titles(ctx['information'], ctx['information_full'])
    assert post.check_stale_citation(f'《{title}》是本档催化。', ctx)
    assert post.check_stale_citation(f'{old["cite"]}，作为背景。', ctx) == []


def _reference_window(tmp_path, *, market, as_of, rows, since, ticker=None):
    from clawock.tools import build_registry
    ctx = {'context_id': 'window000001', 'market': market,
           'generated_at': as_of, 'date': as_of[:10], 'time': as_of[11:16],
           'information_full': {'tickers': {'00100': rows, '02208': rows},
                                'live': {'tickers': {'00100': rows, '02208': rows},
                                         'flashes': rows},
                                'macro': {'rates': 'unchanged'}}}
    tmp = tmp_path / 'memory' / '.tmp'
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / f'intraday-context-{market}-latest.json').write_text(json.dumps(ctx))
    return json.loads(build_registry(tmp_path).call(
        'intraday_reference', market=market, context_id=ctx['context_id'],
        entry='information_full', since=since, **({'ticker': ticker} if ticker else {})))


def test_reference_since_uses_hkt_dates_and_combines_the_ticker_filter(tmp_path):
    rows = [
        {'title': 'boundary', 'published_at': '2026-09-30T01:30:00Z'},
        {'title': 'fresh UTC', 'published_at': '2026-09-30T01:32:26+00:00'},
        {'title': 'fresh ET', 'published_at': '2026-09-29T21:35:00-04:00'},
        {'title': 'old date, later clock', 'published_at': '2026-09-29T13:17:42+00:00'},
        {'title': 'today pre-open', 'published_at': '2026-09-29T23:47:00+00:00'},
        {'title': 'date only', 'published_at': '2026-09-30'},
        {'title': 'unknown', 'published_at': 'not a timestamp'},
        {'title': 'no time'},
        {'title': 'malformed offset', 'published_at': '2026-09-30T10:35:00+bad'},
        {'title': 'invalid date', 'published_at': '2026-13-30T10:35:00+08:00'},
    ]
    for ticker in (None, '00100'):
        got = _reference_window(tmp_path, market='hk', as_of='2026-09-30T11:03:00+08:00',
                                rows=rows, since='09:30', ticker=ticker)
        expected = {t: rows[:3] for t in (['00100'] if ticker else ['00100', '02208'])}
        assert got['tickers'] == expected
        assert got['live']['tickers'] == expected
        assert got['macro'] == {'rates': 'unchanged'}
        if ticker is None:
            assert got['live']['flashes'] == rows[:3]


def test_reference_since_wraps_the_us_slot_across_midnight(tmp_path):
    rows = [
        {'title': 'start', 'published_at': '2026-09-30T14:00:00+00:00'},
        {'title': 'after midnight', 'published_at': '2026-09-30T16:10:00+00:00'},
        {'title': 'before start', 'published_at': '2026-09-30T13:59:59+00:00'},
        {'title': 'prior session', 'published_at': '2026-09-29T23:30:00+08:00'},
    ]
    got = _reference_window(tmp_path, market='us', as_of='2026-10-01T02:33:00+08:00',
                            rows=rows, since='22:00')
    assert got['live']['tickers']['00100'] == rows[:2]


def test_a_since_window_requires_a_valid_clock_and_slot_timestamp():
    import pytest
    from clawock.tools.context_tools import slice_reference
    from clawock.tools.base import ToolError
    for since, as_of in [('29:00', '2026-09-30T11:03:00+08:00'), ('09:30', None)]:
        with pytest.raises(ToolError):
            slice_reference([], since=since, as_of=as_of)


def test_clock_only_headlines_also_wrap_with_the_overnight_slot():
    from clawock.tools.context_tools import slice_reference
    lines = ['21:59 old', '22:00 boundary', '23:30 last night', '00:10 this morning']
    assert slice_reference(lines, since='22:00', as_of='2026-10-01T02:33:00+08:00') == lines[1:]
