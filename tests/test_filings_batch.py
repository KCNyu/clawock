"""#918：filings 批量是「一个进程顺序跑」，不是并行。

SEC 限速器是模块内的 `_last_call`，N 个 spawn 就是 N 份限速器 —— 这正是当初
「不能简单并行」的原因，所以批量入口必须在同一个进程里把 ticker 走完。
"""
import json

from clawock.market_data import filings


def test_latest_quarterly_fact_prefers_single_quarter_over_ytd():
    facts = {'facts': {'us-gaap': {'Revenues': {'units': {'USD': [
        {'start': '2026-01-01', 'end': '2026-06-30', 'val': 1_395_448_000,
         'fp': 'Q2', 'form': '10-Q', 'filed': '2026-08-05'},
        {'start': '2026-04-01', 'end': '2026-06-30', 'val': 701_315_000,
         'fp': 'Q2', 'form': '10-Q', 'filed': '2026-08-05'},
    ]}}}}}
    rows = filings._latest_value(facts, 'Revenues')
    assert rows[0]['value'] == 701_315_000
    assert rows[0]['start'] == '2026-04-01'


def test_multiple_tickers_share_one_process_and_one_throttle(monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(filings, 'get_key_financials',
                        lambda ticker: seen.append(ticker) or {'Revenues': {ticker: 1}})

    filings.main(['MSFT', 'AAPL', '--financials', '--json'])

    payload = json.loads(capsys.readouterr().out)
    assert seen == ['MSFT', 'AAPL'], 'batch must run in order, in one process'
    assert set(payload['batch']) == {'MSFT', 'AAPL'}
    assert payload['batch']['AAPL']['key_financials'] == {'Revenues': {'AAPL': 1}}


def test_one_ticker_keeps_the_single_shape(monkeypatch, capsys):
    """单只的输出形状一个字不动 —— 否则每个调用方都要按只数切换解析。"""
    monkeypatch.setattr(filings, 'get_key_financials', lambda ticker: {'Revenues': {}})

    filings.main(['MSFT', '--financials', '--json'])

    payload = json.loads(capsys.readouterr().out)
    assert payload['ticker'] == 'MSFT'
    assert 'batch' not in payload


def test_a_form_type_list_is_not_mistaken_for_a_ticker(monkeypatch, capsys):
    """`--filings 8-K,10-Q` 的表单清单也是位置参数，不能被当成第二只票。"""
    monkeypatch.setattr(filings, 'get_filings',
                        lambda ticker, form_types=None, limit=20: [
                            {'form': form_types[0] if form_types else 'ANY'}])

    filings.main(['MSFT', '--filings', '8-K,10-Q', '--json'])

    payload = json.loads(capsys.readouterr().out)
    assert payload['ticker'] == 'MSFT'
    assert 'batch' not in payload
    assert payload['filings'] == [{'form': '8-K'}]
