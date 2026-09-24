"""Message lane and SPCH policy from a full preflight context to rendered copy."""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from clawock.harness import intraday_preflight as pre
from clawock.harness import intraday_postflight as post


def test_delta_header_names_new_trigger_before_table():
    current = {'breaches': [{'ticker': '00100', 'kind': 'plan_trigger', 'level': 'gte'}]}
    block = pre.prepend_delta_lead(
        '🇭🇰 港股盯盘 | 10:33\n\n| 代码 | 现价 |',
        {'components': ['breaches', 'plans']}, current=current,
        previous={'breaches': []},
    )
    assert block.splitlines()[1] == '变化：信号/触发档位、未成交计划（新触发：00100）'
    assert block.index('变化：') < block.index('| 代码')


def test_generic_headline_feed_is_not_repeated_in_intraday_card():
    block = ('🇺🇸 美股盯盘\n| CRCL | 1 |\n📰 新闻\n'
             '📰 CRCL (5条)\n   · old clipped headline\n\n'
             '🎯 机会雷达\n  ◆ RKLB')
    rendered = pre.strip_generic_news(block)
    assert 'old clipped headline' not in rendered
    assert '| CRCL |' in rendered and '🎯 机会雷达' in rendered


def test_compact_packet_keeps_gate_and_relevant_decisions_only():
    ctx = {
        'status': 'ok', 'context_id': 'abc', 'market': 'hk',
        'anomalies': [{'ticker': '00100'}], 'signals_detail': [],
        'plan_triggers': [], 'peer_scan': {'00100': {'theme': 'AI'}, '02208': {'theme': 'wind'}},
        'plan_context': {'open': [{'ticker': '00100', 'shares': 0},
                                  {'ticker': '07226', 'shares': 1000},
                                  {'ticker': '02208', 'shares': 0}]},
        'raw_wechat_block': 'fresh table', 'semantic_state': {'large': 'audit only'},
    }
    packet = pre.judgment_packet(ctx)
    assert packet['context_id'] == 'abc'
    assert packet['raw_wechat_block'] == 'fresh table'
    assert 'semantic_state' not in packet
    assert list(packet['peer_scan']) == ['00100']
    assert [row['ticker'] for row in packet['plan_context']['open']] == ['00100', '07226']


def test_spch_generic_stop_does_not_become_intraday_action():
    counts = {'alert': 0, 'watch': 0, 'stop': 1, 'trim': 0}
    detail = [{'ticker': 'SPCH', 'level': 'STOP', 'line': 'STOP SPCH'}]
    effective, rows = pre.actionable_signals('us', counts, detail)
    assert effective['stop'] == 0 and rows == []
    assert pre.decide_alert(effective, [])[0] is False
    block = ('🇺🇸 美股盯盘\n⚠️ 信号\n  ▼ STOP-LOSS SPCH | 浮-20%\n'
             '     · 浮亏触发\n\n📉 亏损持仓 1/1')
    rendered = pre.apply_spch_intraday_contract(block, {})
    assert 'STOP-LOSS SPCH' not in rendered
    assert '⚠️ 信号' not in rendered
    assert '亏损持仓' in rendered


def test_spch_p0_uses_fresh_daily_and_verified_weekly_price(monkeypatch):
    monkeypatch.setattr(pre.quant_signals, 'universe_details',
                        lambda: [{'label': 'SPCX', 'code': 'usSPCX.OQ'}])
    bars = [{'date': day, 'close': 100} for day in
            ('2026-09-17', '2026-09-18', '2026-09-21', '2026-09-22', '2026-09-23')]
    monkeypatch.setattr(pre, '_fetch_bars_cached', lambda *_args: bars)
    now = datetime(2026, 9, 24, 22, 3, tzinfo=ZoneInfo('Asia/Hong_Kong'))
    block = '| SPCX | 1 | 100 | 74 | -26% | -26% | -26 |'
    evidence = pre.spch_p0_evidence(
        block, [{'ticker': 'SPCH', 'move_pct': -15.1}],
        {'active': 2, 'refreshed': 2, 'unrefreshed': []}, now=now)
    assert evidence == {'spch_daily_pct': -15.1, 'spcx_weekly_pct': -26.0}
    assert 'P0：SPCX 单周 -26.0%' in pre.apply_spch_intraday_contract('🇺🇸 美股盯盘', evidence)
    assert pre.spch_p0_evidence(
        block, [], {'active': 2, 'refreshed': 1, 'unrefreshed': ['SPCX']},
        now=now)['spcx_weekly_pct'] is None


def test_spch_cut_in_model_prose_fails_closed():
    ctx = {'market': 'us', 'should_alert': False, 'raw_wechat_block': '🇺🇸 美股盯盘'}
    prose = '▎我的看法\nSPCH 300 股 open cut 今早没砍下来仍挂着。' + '今日继续观察其他票的变化。' * 4
    issues = post.validate(post.assemble_message(ctx, prose), ctx, prose)
    assert post.categorize(issues) == 'fail'
    assert any('SPCH 策略冲突' in issue for issue in issues)


def test_bad_sidecar_does_not_get_fresh_timestamp(tmp_path):
    path = tmp_path / 'insights.json'
    path.write_text(json.dumps({'status_banner': '重复' * 30, 'movers': {}}))
    assert post.normalize_intraday_insights(path) is False
    assert 'generated_at' not in json.loads(path.read_text())
