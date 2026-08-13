"""Entry rules re-run on the open bar — and never called a trigger (#515).

The three technical setups are evaluated once a day, at 08:00, on completed
bars. A reclaim of MA20 at 11:00 is therefore a fact the decision surface does
not see until the next morning: measured against real bars, 02208 produced 18
of these in 250 sessions and 03033 produced 11, and every one of them was a day
late.

This runs the identical rules against a bar that includes the live session, so
nothing here may loosen a threshold or add a rule — the evaluator's whole job is
to call `compute_signals` and label the answer honestly. The label is the point:
two of the three rules are statements about a close, and the bar has not closed,
so a row is a reason to look, never an entry that fired.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from clawock.decision import signals as S  # noqa: E402
from clawock_kcnyu.harness import intraday_preflight as P  # noqa: E402


def _flat(n, price):
    return [{'date': f'd{i}', 'open': price, 'close': price,
             'high': price, 'low': price} for i in range(n)]


def _breakout_series():
    """Trend on (close > MA200, MA50 > MA200), closing above the prior 20d high."""
    bars = _flat(260, 10.0)
    for i in range(260 - 60, 260):          # drift up so MA50 clears MA200
        bars[i] = {'date': f'u{i}', 'open': 12.0, 'close': 12.0, 'high': 12.0, 'low': 12.0}
    bars[-1] = {'date': 'today', 'open': 12.0, 'close': 13.5, 'high': 13.6, 'low': 11.9}
    return bars


def _universe(label='02208', region='HK'):
    return [{'label': label, 'code': f'hk{label}', 'region': region,
             'source_holdings': [label]}]


def test_the_evaluator_reports_what_compute_signals_reports(monkeypatch):
    """No second rule engine: the rows must be whatever the daily pipeline says."""
    bars = _breakout_series()
    expected = [s['setup_id'] for s in S.compute_signals(bars)['technical_setups']]
    assert expected, 'fixture must trigger at least one setup'

    out = S.provisional_setups(_universe(), fetch=lambda code, cnt: bars)

    assert [row['setup_id'] for row in out['rows']] == expected


def test_every_row_is_marked_unconfirmed(monkeypatch):
    """The bar is open. Nothing here may read as a completed signal."""
    out = S.provisional_setups(_universe(), fetch=lambda code, cnt: _breakout_series())

    assert out['confirmed_at_close'] is False
    assert all(row['confirmed_at_close'] is False for row in out['rows'])


def test_only_this_leg_is_evaluated():
    """A 港股 slot cannot act on a US breakout for another nine hours."""
    universe = _universe() + [{'label': 'RKLB', 'code': 'usRKLB.O', 'region': 'US',
                               'source_holdings': ['RKLX']}]

    out = S.provisional_setups(universe, region='HK',
                               fetch=lambda code, cnt: _breakout_series())

    assert {row['label'] for row in out['rows']} == {'02208'}


def test_a_dead_feed_is_reported_as_a_value_not_as_a_quiet_day():
    """No setups and no data look identical from the outside — they must not be."""
    def boom(code, cnt):
        raise TimeoutError('tencent unreachable')

    out = S.provisional_setups(_universe(), fetch=boom)

    assert out['rows'] == []
    assert out['errors'] and out['errors'][0]['label'] == '02208'
    assert 'TimeoutError' in out['errors'][0]['error']


def test_one_bad_symbol_does_not_blank_the_others():
    universe = _universe('02208') + _universe('03033')
    bars = _breakout_series()

    def half(code, cnt):
        if code == 'hk02208':
            raise ValueError('no canonical symbol')
        return bars

    out = S.provisional_setups(universe, fetch=half)

    assert [row['label'] for row in out['rows']] == ['03033']
    assert [err['label'] for err in out['errors']] == ['02208']


# ── the rendered block ───────────────────────────────────────────────────────

BLOCK = '🇭🇰 港股盯盘 | 08/13 15:33 HKT\n| 00100 | 120 | 553.08 |'


def test_a_slot_without_setups_leaves_the_block_byte_identical():
    """Postflight checks the report against this string, and most slots are quiet."""
    for setups in ({'rows': []}, {}, None, {'rows': [], 'errors': [{'label': 'x'}]}):
        assert P.append_setup_section(BLOCK, setups) == BLOCK, setups


def test_the_heading_says_it_has_not_closed():
    rows = {'rows': [{'label': '02208', 'label_zh': '20日突破确认',
                      'setup_id': 'confirmed_breakout',
                      'entry_price': 14.08, 'invalidation_price': 12.9}]}

    text = P.append_setup_section(BLOCK, rows)

    assert text.startswith(BLOCK)
    assert '未收盘' in text and '不是已触发' in text
    assert '02208' in text and '14.08' in text and '12.9' in text
    # "触发" alone would read as a completed signal in a skimmed push.
    assert '已触发' not in text.replace('不是已触发', '')


def test_the_section_is_bounded():
    rows = {'rows': [{'label': f't{i}', 'setup_id': 'confirmed_breakout',
                      'entry_price': i, 'invalidation_price': i - 1}
                     for i in range(P.MAX_SETUP_LINES + 3)]}

    text = P.append_setup_section(BLOCK, rows)

    assert text.count('◆') == P.MAX_SETUP_LINES
    assert '另有 3 条' in text


def test_the_collector_never_raises(monkeypatch):
    """A quote feed is not allowed to red the cron."""
    monkeypatch.setattr(P.quant_signals, 'provisional_setups',
                        lambda **kw: (_ for _ in ()).throw(RuntimeError('portfolio.json gone')))

    out = P.collect_provisional_setups('hk')

    assert out['rows'] == []
    assert 'RuntimeError' in out['errors'][0]['error']


# ── the two layers can disagree ──────────────────────────────────────────────

STOP_SIGNAL = [{'level': 'STOP', 'line': '✋ STOP? 02208 金风科技 | 今日-0.6% 浮-24.7%'}]


def _setup_row(label='02208', holdings=('02208',)):
    return {'rows': [{'label': label, 'holdings': list(holdings),
                      'label_zh': '20日突破确认', 'setup_id': 'confirmed_breakout',
                      'entry_price': 14.08, 'invalidation_price': 12.9}]}


def test_a_ticker_with_both_an_entry_and_a_risk_signal_is_marked():
    """An entry rule reads the series; the risk line reads the position.

    02208 can reclaim its 20-day high while sitting at -24% and flagged STOP?.
    Printing both without a word is a push that contradicts itself.
    """
    text = P.append_setup_section(BLOCK, _setup_row(), STOP_SIGNAL)

    assert '同票有风险信号(02208)' in text
    # Marked, not suppressed: the entry condition is still a fact.
    assert '20日突破确认' in text


def test_a_clean_ticker_carries_no_warning():
    text = P.append_setup_section(BLOCK, _setup_row('03033', ('03033',)), STOP_SIGNAL)

    assert '同票有风险信号' not in text


def test_a_proxy_row_is_matched_by_its_holdings_not_its_signal_symbol():
    """HSTECH is the signal symbol for 03032/03033 — the risk line names the holding."""
    signals = [{'level': 'STOP', 'line': '✋ STOP? 03033 恒科ETF | 浮-8.7%'}]

    text = P.append_setup_section(BLOCK, _setup_row('HSTECH', ('03032', '03033')), signals)

    assert '同票有风险信号(03033)' in text
    assert '03032' not in text.split('同票有风险信号')[1][:20]


def test_a_watch_signal_is_not_treated_as_a_contradiction():
    """WATCH is a -5% day, not a position-level stop; it does not veto an entry."""
    watch = [{'level': 'WATCH', 'line': '△ WATCH 02208 金风科技 | 今日-5.2%'}]

    assert '同票有风险信号' not in P.append_setup_section(BLOCK, _setup_row(), watch)


def test_missing_signal_detail_is_not_an_error():
    for signals in (None, [], [{'line': 'malformed'}], [{'level': None}]):
        text = P.append_setup_section(BLOCK, _setup_row(), signals)
        assert '20日突破确认' in text, signals
