"""Intraday context, policy and message boundaries."""
import json
import ast
import re
from pathlib import Path

from clawock.harness import intraday_preflight as pre
from clawock.harness import intraday_postflight as post
from clawock.decision import intraday_policy as policy


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
    assert block.splitlines()[2] == '⚠️ 行情未证实完整刷新：SPCH、SPCX'
    assert '| 代码 |' in block


def test_generic_headline_feed_is_not_repeated_in_intraday_card():
    block = ('🇺🇸 美股盯盘\n| CRCL | 1 |\n📰 新闻\n'
             '📰 CRCL (5条)\n   · old clipped headline\n\n'
             '🎯 机会雷达\n  ◆ RKLB')
    rendered = pre.strip_generic_news(block)
    assert 'old clipped headline' not in rendered
    assert '| CRCL |' in rendered and '🎯 机会雷达' in rendered


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


def test_instance_strategy_has_only_the_two_current_p0_lines():
    root = Path(__file__).resolve().parents[1]
    configured = json.loads((root / 'config/intraday-strategy-policies.json').read_text())
    rules = configured['infinite_ammo_dca']['escalations']
    assert [(row['ticker'], row['window'], row['below_pct']) for row in rules] == [
        ('SPCH', 'session', -15), ('SPCX', 'five_sessions', -25)]
    assert '$3000' not in json.dumps(configured)


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
