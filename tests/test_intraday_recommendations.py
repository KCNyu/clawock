"""Recommendations stay separate from research authority and require real inputs."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil

import pytest

from clawock.decision.intraday_recommendations import build, digest
from clawock.harness.intraday_recommendations import render, section
from clawock.harness.intraday_research import snapshot
from clawock.market_data.intraday_bars import fetch

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 19, 15, 16, tzinfo=timezone.utc)


@pytest.fixture
def inputs(tmp_path):
    (tmp_path / 'config').mkdir()
    for name in ('intraday-research-status.json', 'cost-model.json'):
        shutil.copy(ROOT / 'config' / name, tmp_path / 'config' / name)
    book = {'portfolios': {'us_stocks': {'cash_usd': 1000,
            'holdings': [{'ticker': 'SPY', 'shares': 10}]}}}
    (tmp_path / 'portfolio.json').write_text(json.dumps(book))
    evidence = snapshot(tmp_path, 'us', now=NOW)
    start = datetime(2026, 10, 19, 13, 35, tzinfo=timezone.utc)
    bars = []
    for i in range(21):
        close = 100 + (i % 2) * .1 if i < 20 else 103
        bars.append({'end': (start + timedelta(minutes=5*i)).isoformat(),
                     'open': close, 'close': close, 'high': close, 'low': close, 'volume': 10000})
    packet = {'provider': 'fixture', 'url': 'fixture:synthetic-not-live', 'bars': bars}
    return tmp_path, evidence, book, packet


def call(inputs, **kwargs):
    path, evidence, _, packet = inputs
    return build(path, 'us', evidence, {}, {}, now=NOW,
                 fetch=lambda *a: deepcopy(packet), **kwargs)


def test_conditional_advice_preserves_negative_evidence_and_is_traceable(inputs):
    ctx = call(inputs)
    row, = ctx['rows']
    assert ctx['execution_permission'] is False
    assert row['sell_limit'] == 103
    assert row['buyback_target'] == 100.05
    assert row['buyback_stop'] == 105.95
    assert row['shares'] == 1
    assert row['manifest_sha256'] == inputs[1]['manifest_sha256']
    assert row['data_sha256'] == inputs[1]['data_sha256']
    assert row['live_data_sha256'] == digest(ctx['live_input'])
    text = render(ctx)
    for phrase in ('-2.2329', '7.1304', '4.5453', 'not_started',
                   'no order book/queue', 'not historical invoice',
                   'Zero commission is conditional', 'manifest_sha256', 'data_sha256',
                   '先核对真实可卖股数', '重复卡不是追加单'):
        assert phrase in text
    assert inputs[1]['live_permission'] is False


@pytest.mark.parametrize('change, reason', [
    ('no_position', '真实账本未持有'), ('small_position', '真实底仓不足'),
    ('cash', '账本现金不足'), ('missing_hash', '研究指纹'),
    ('rights', '无可用'), ('blocked', '无可用'), ('synthetic', '无可用'),
    ('gap', '不完整'), ('stale', '过期'), ('flat', '未触及'),
    ('volume', '成交量'), ('nan', '不可用'), ('foreign_session', '不可用'),
])
def test_refusals_do_not_invent_orders(inputs, change, reason):
    path, evidence, book, packet = inputs
    if change == 'no_position':
        book['portfolios']['us_stocks']['holdings'] = []
    elif change == 'small_position':
        book['portfolios']['us_stocks']['holdings'][0]['shares'] = 9
    elif change == 'cash':
        book['portfolios']['us_stocks']['cash_usd'] = 0
    elif change == 'missing_hash':
        evidence['data_sha256'] = None
    elif change == 'rights':
        evidence['metrics_withheld_for_rights'] = True
    elif change == 'blocked':
        evidence['validation'] = 'blocked_data_rights'
    elif change == 'synthetic':
        evidence['recommendation_evidence_ok'] = False
    elif change == 'gap':
        del packet['bars'][5]
    elif change == 'stale':
        packet['bars'].pop()
    elif change == 'flat':
        for bar in packet['bars']:
            bar.update(open=100, close=100, high=100, low=100)
    elif change == 'volume':
        packet['bars'][-1]['volume'] = 0
    elif change == 'nan':
        packet['bars'][-1]['close'] = float('nan')
    elif change == 'foreign_session':
        packet['bars'][0]['end'] = '2026-10-16T13:35:00+00:00'
    (path / 'portfolio.json').write_text(json.dumps(book))
    result = call(inputs)
    assert not result['rows']
    assert reason in render(result)


def test_policy_and_open_plan_refuse_before_fetch(inputs):
    path, evidence, _, _ = inputs
    def forbidden(*a):
        pytest.fail('must not fetch')
    for policies, plan, reason in [({'SPY': {'forbid_reduce_advice': True}}, {}, '禁止减持'),
                                  ({}, {'open': [{'ticker': 'SPY'}]}, '已有未完成计划')]:
        result = build(path, 'us', evidence, policies, plan, now=NOW, fetch=forbidden)
        assert not result['rows'] and reason in render(result)


def test_closed_market_refuses_and_does_not_fetch(inputs, monkeypatch):
    path, evidence, _, _ = inputs
    monkeypatch.setattr('clawock.market_data.intraday_bars.fetch', lambda *a: pytest.fail('closed'))
    ctx, text = section(path, 'us', evidence, {}, {}, now=NOW.replace(hour=10))
    assert not ctx['rows'] and text == '' and '非美股常规交易时段' in render(ctx)


def test_tampered_manifest_does_not_become_recommendation_evidence(inputs):
    path, _, _, _ = inputs
    target = path / 'config/intraday-research-status.json'
    report = json.loads(target.read_text())
    report['manifest']['base_shares'] = 999
    target.write_text(json.dumps(report))
    assert snapshot(path, 'us', now=NOW)['recommendation_evidence_ok'] is False


def test_provider_uses_existing_key_raw_prices_bounded_request_and_no_retries(tmp_path, monkeypatch):
    monkeypatch.setattr('clawock.market_data.intraday_bars.load_api_keys', lambda p: {'POLYGON_API_KEY': 'fixture'})
    calls = []
    class Response:
        status_code = 403
    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response()
    monkeypatch.setattr('clawock.market_data.intraday_bars.requests.get', get)
    with pytest.raises(ValueError, match='403'):
        fetch(tmp_path, 'SPY', '2026-10-19')
    assert len(calls) == 1
    assert calls[0][1]['params']['adjusted'] == 'false'
    assert calls[0][1]['timeout'] == 6
    assert 'fixture' not in calls[0][0]


def test_future_forming_bar_cannot_change_signal(inputs):
    before = call(inputs)
    inputs[3]['bars'].append({**inputs[3]['bars'][-1], 'end': '2026-10-19T15:20:00+00:00', 'close': 999})
    after = call(inputs)
    assert before['rows'] == after['rows']


def test_preflight_and_fallback_keep_recommendation_block_and_adverse_facts(inputs, monkeypatch):
    from test_intraday_delta_gate import _wire_preflight
    from clawock.harness.intraday_postflight import assemble_message
    from clawock.harness.intraday_preflight import judgment_packet
    path, _, book, _ = inputs
    book['portfolios']['us_stocks']['holdings'] = []
    (path / 'portfolio.json').write_text(json.dumps(book))
    previous, run = _wire_preflight(monkeypatch, path)
    ctx = run(previous)
    assert 'intraday_recommendations' in judgment_packet(ctx)
    # No order -> nothing on the card; the refusal and the adverse evidence
    # stay in the context for audit (kcn 2026-10-19).
    assert '真实账本未持有 SPY' in render(ctx['intraday_recommendations'])
    for message in (assemble_message(ctx, ''), assemble_message(ctx, '▎我的看法\n等待条件。')):
        for hidden in ('▎策略研究', '▎今日可执行建议', '▎做T建议', '真实账本未持有 SPY',
                       inputs[1]['data_sha256'], 'manifest_sha256', 'OHLC execution'):
            assert hidden not in message


def test_early_close_and_expiration_boundaries_refuse(inputs):
    path, evidence, _, _ = inputs
    early = build(path, 'us', evidence, {}, {}, now=NOW.replace(month=11, day=27))
    assert not early['rows'] and '短交易场次' in render(early)
    near_close = build(path, 'us', evidence, {}, {}, now=NOW.replace(hour=19, minute=50))
    assert not near_close['rows'] and '临近收盘' in render(near_close)
    expired = build(path, 'us', evidence, {}, {}, now=NOW.replace(minute=20),
                    fetch=lambda *a: inputs[3])
    assert not expired['rows'] and '过期' in render(expired)


def test_incomplete_base_metrics_refuse_without_breaking_card(inputs):
    inputs[1]['metrics']['base']['net_increment'] = None
    ctx = call(inputs)
    assert not ctx['rows']
    assert '历史净结果缺失' in render(ctx) and '净增量 未知' in render(ctx)


def test_actionable_recommendation_cannot_be_silenced(inputs, monkeypatch):
    from test_intraday_delta_gate import _wire_preflight
    from clawock.harness import intraday_preflight as pre
    recommendation = call(inputs)
    assert recommendation['rows']
    previous, run = _wire_preflight(monkeypatch, inputs[0], healthy=True)
    monkeypatch.setattr('clawock.harness.intraday_recommendations.section',
                        lambda *a, **k: (recommendation, render(recommendation)))
    ctx = run(previous)
    assert ctx['delivery_mode'] == 'full_delta' and ctx['should_alert']
    assert pre.can_silence(ctx) is False
    assert '限价卖出' in ctx['raw_wechat_block']


def test_card_is_trading_language_and_audit_keeps_the_evidence(inputs):
    from clawock.harness.intraday_recommendations import render_card
    ctx = call(inputs)
    assert ctx['rows']
    card, audit = render_card(ctx), render(ctx)
    row = ctx['rows'][0]
    assert card.startswith('▎做T建议')
    assert f"{row['ticker']} 先卖后买回 {row['shares']} 股" in card
    for hidden in ('sha256', 'OHLC', 'prospective_status', 'Zero commission', '净增量'):
        assert hidden not in card
        assert hidden in audit
    refused = build(inputs[0], 'us', inputs[1], {}, {}, now=NOW.replace(hour=19, minute=50))
    assert render_card(refused) == ''
