"""The bars the live factor row is computed on, and what the provider said about them.

The row shapes below are the ones Tencent's per-market endpoint returned on
2026-10-12, trimmed to a few sessions: TQQQ around its 2:1 split, 02208 with
the action slot on every row, CRCL with every slot empty, and a name answered
raw with no slot at all.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
import requests

from clawock.decision import signals
from clawock.market_data import tencent_daily
from clawock.plugin_host.kernel import Kernel
from clawock.strategies.plugins import daily_bars

SPLIT = {'qfqday': [
    ['2025-11-19', '53.26', '53.05', '54.20', '51.90', '90000000.00'],
    ['2025-11-20', '55.70', '51.63', '56.41', '51.19', '170000000.00',
     {'FHcontent': '', 'hgcgContent': '每1股拆分成2股', 'cqr': '2025-11-20'}],
    ['2025-11-21', '51.70', '52.90', '54.00', '50.10', '160000000.00']]}
SLOT_ON_EVERY_ROW = {'qfqday': [
    ['2026-06-17', '10.470', '10.570', '10.770', '10.370', '1.000', {}, '1.2', '100.0'],
    ['2026-06-18', '10.600', '10.500', '10.700', '10.400', '1.000',
     {'FHcontent': '末期息0.2人民币;相当于0.23005港元;', 'hgcgContent': ''}, '1.1', '90.0']]}
NO_ACTION = {'day': [
    ['2026-10-08', '80.00', '82.14', '83.00', '79.50', '1.00', {}, '5.1', '1.0', '0.00', '0.00'],
    ['2026-10-09', '82.14', '84.51', '87.60', '80.40', '1.00', {}, '5.1', '1.0', '0.00', '0.00']]}
NO_SLOT = {'day': [
    ['2026-10-08', '80.000', '82.140', '83.000', '79.500', '1.000'],
    ['2026-10-09', '82.140', '84.510', '87.600', '80.400', '1.000']]}
UNADJUSTED_ACTION = {'day': [
    ['2026-10-08', '80.00', '82.14', '83.00', '79.50', '1.00', {}, '5.1', '1.0', '0.00', '0.00'],
    ['2026-10-09', '41.00', '42.00', '43.00', '40.00', '1.00',
     {'FHcontent': '', 'hgcgContent': '每1股拆分成2股'}, '5.1', '1.0', '0.00', '0.00']]}


def _answers(monkeypatch, node, seen=None):
    def get(url, **kwargs):
        if seen is not None:
            seen.append(url)
        symbol = url.split('param=')[1].split(',')[0]
        return SimpleNamespace(json=lambda: {'data': {symbol: node}})
    monkeypatch.setattr(requests, 'get', get)


@pytest.mark.parametrize('node, basis, actions', [
    (SPLIT, 'adjusted', [{'date': '2025-11-20', 'dividend': '', 'split': '每1股拆分成2股'}]),
    (SLOT_ON_EVERY_ROW, 'adjusted', [
        {'date': '2026-06-18', 'dividend': '末期息0.2人民币;相当于0.23005港元;', 'split': ''}]),
    (NO_ACTION, 'no_action_on_record', []),
    (NO_SLOT, 'unconfirmed', []),
    (UNADJUSTED_ACTION, 'unconfirmed', [
        {'date': '2026-10-09', 'dividend': '', 'split': '每1股拆分成2股'}]),
    ({}, 'unconfirmed', []),
])
def test_the_basis_is_read_from_the_answer(monkeypatch, node, basis, actions):
    _answers(monkeypatch, node)
    bars, got, listed = tencent_daily.fetch_daily_with_basis('usX.N', 400)
    assert (got, listed) == (basis, actions)
    assert len(bars) == len(node.get('qfqday') or node.get('day') or [])
    assert tencent_daily.fetch_adjusted_daily_bars('usX.N', 400)[1] is (basis == 'adjusted')


def test_the_live_row_asks_the_per_market_adjusted_endpoint(monkeypatch):
    seen = []
    _answers(monkeypatch, SPLIT, seen)
    assert [bar['close'] for bar in signals.fetch_bars('usTQQQ.OQ', 400)] == [53.05, 51.63, 52.9]
    signals.fetch_bars('hk02208', 400)
    assert seen == [
        'https://web.ifzq.gtimg.cn/appstock/app/usfqkline/get?param=usTQQQ.OQ,day,,,400,qfq',
        'https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get?param=hk02208,day,,,400,qfq']


def test_a_name_with_no_action_on_record_is_served_as_sent_and_an_unconfirmed_one_is_named(
        monkeypatch, capsys):
    _answers(monkeypatch, NO_ACTION)
    assert [bar['close'] for bar in signals.fetch_bars('usCRCL.N')] == [82.14, 84.51]
    assert capsys.readouterr().err == ''
    _answers(monkeypatch, UNADJUSTED_ACTION)
    assert [bar['close'] for bar in signals.fetch_bars('usX.N')] == [82.14, 42.0]
    assert 'usX.N answered raw without an empty action record (1 action(s) on record)' in (
        capsys.readouterr().err)


def test_the_raw_row_is_the_rollback_and_makes_the_requests_it_always_made(monkeypatch):
    seen = []
    _answers(monkeypatch, NO_SLOT, seen)
    monkeypatch.setattr(daily_bars.trading_calendar, 'hkt_today',
                        lambda: SimpleNamespace(isoformat=lambda: '2026-10-12'))
    kernel = Kernel()
    kernel.plugin(daily_bars, {'adjustment': 'raw'})
    raw = kernel.get('daily_bars')
    assert raw.describe() == {'adjustment': 'raw'}
    assert len(raw.fetch('hk02208', 400)) == 2 and len(raw.fetch('usTQQQ.OQ', 400)) == 2
    assert seen == [
        'https://web.ifzq.gtimg.cn/appstock/app/kline/kline?param=hk02208,day,2024-01-01,2026-10-12,400',
        'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=usTQQQ.OQ,day,,,400,qfq']


def test_a_failed_request_is_an_empty_list_and_a_bad_row_is_refused(monkeypatch, capsys):
    def down(url, **kwargs):
        raise OSError('reset')
    monkeypatch.setattr(requests, 'get', down)
    assert signals.fetch_bars('usTQQQ.OQ') == []
    assert 'usTQQQ.OQ fetch failed: reset' in capsys.readouterr().err
    with pytest.raises(ValueError, match='adjustment must be one of'):
        Kernel().plugin(daily_bars, {'adjustment': 'hfq'})
