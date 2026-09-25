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
    documents = [(root / 'config/cron-payloads/intraday.md').read_text()]
    for market in ('hk', 'us'):
        skill = (root / f'skills/{market}-stock-analysis/SKILL.md').read_text()
        documents.append(skill.split('### Mode 7', 1)[1].split('### Mode 6', 1)[0])
    tokens = set()
    for document in documents:
        tokens.update(re.findall(r'`([a-z][a-z0-9_]*(?:\.[a-z0-9_]+)*)`', document))
    named = {token.split('.', 1)[0] for token in tokens
             if '_' in token or token == 'anomalies'}
    non_fields = {'commit_ok', 'market_closed', 'full_delta', 'no_change',
                  'review_candidate',
                  'no_recent_filing', 'index_fund_no_issuer', 'suppressed_noise'}
    assert named - non_fields <= produced
    assert named - non_fields <= set(pre.judgment_packet({key: None for key in produced}))


def test_delta_header_names_new_trigger_before_table():
    current = {'breaches': [{'ticker': '00100', 'kind': 'plan_trigger', 'level': 'gte'}]}
    block = pre.prepend_delta_lead(
        '🇭🇰 港股盯盘 | 10:33\n\n| 代码 | 现价 |',
        {'components': ['breaches', 'plans']}, current=current,
        previous={'breaches': []},
    )
    assert block.splitlines()[1] == '变化：信号/触发档位、未成交计划（新触发：00100）'
    assert block.index('变化：') < block.index('| 代码')


def test_full_card_discloses_unverified_quote_coverage():
    block = pre.prepend_coverage_warning(
        '🇺🇸 美股盯盘\n变化：本交易日首档\n\n| 代码 | 现价 |',
        {'unrefreshed': ['SPCH', 'SPCX']},
    )
    assert block.splitlines()[2] == '⛔ 数据降级：行情未证实完整刷新：SPCH、SPCX（沿用上一笔）'
    assert '| 代码 |' in block


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


def _card(fresh=('07226',), stale=('03032',), p0=True):
    block = pre.mark_card_changes(ANALYZER, fresh_tickers=set(fresh),
                                  unrefreshed=list(stale),
                                  seen_signals={('STOP', '00100')})
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
    # 2. Block order: title, P0, 变化, ⛔, strip/book, table, pointer, signals,
    #    risk line, then the judgment below the whole data block.
    order = [0, at('P0：'), at('变化：'), at('⛔'), at('  恒指'),
             at('📊'), start, at('↑ '), at('⚠️ 信号'), at('📉'), at('▎我的看法')]
    assert order == sorted(order) and lines[0].startswith('🇭🇰 港股盯盘')
    # 3. One pointer, after a blank line, naming only the kinds present.
    pointers = [line for line in lines if line.startswith('↑ ')]
    assert pointers == ['↑ 新异动/触发 07226　行情未证实 03032']
    assert lines[at('↑ ') - 1] == ''
    only_new = _card(stale=()).splitlines()
    assert [line for line in only_new if line.startswith('↑ ')] == ['↑ 新异动/触发 07226']
    assert not any(line.startswith('↑ ') for line in _card(fresh=(), stale=()).splitlines())
    # 4. ⛔ is only data health; ⚠️ only heads the analyzer's signal block.
    assert all(line.startswith('⛔') for line in lines if '数据降级' in line)
    assert [line for line in lines if line.startswith('⚠️')] == ['⚠️ 信号']
    # 5. Repeated signals fold; a new one stays whole with its reason.
    assert '  · 今日已报、仍在：STOP? 00100' in lines
    assert 'STOP? 00100 MINIMA' not in msg and '警惕止损' in msg
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
    assert pre.judgment_packet(ctx) == ctx
    assert len(pre.judgment_packet(ctx)['plan_context']['open']) == 2
    assert len(pre.judgment_packet(ctx)['peer_scan']) == 2


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
    path.write_text(json.dumps({'status_banner': '重复' * 30, 'movers': {}}))
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
    assert val.check_identifier_leak('07226 跌破 MA20，RSI 28，T+0 追高，SPCX/SPCH 同跌') == []
