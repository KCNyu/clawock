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


def test_unchanged_slot_is_visible_but_does_not_repeat_the_full_table():
    receipt = P.render_unchanged_receipt(
        "us", "🇺🇸 美股盯盘 | 08/13 13:30 ET\n| CRCL | 2 | 87 | 71 |",
        {"priced": 5, "active": 5},
        {"collection": {"cache_hit": False, "fetched_at": "2026-08-13T17:30:00+00:00"},
         "degraded_issuers": [], "partially_degraded_issuers": ["RKLB"]},
    )

    assert receipt.startswith("🇺🇸 美股盯盘 | 08/13 13:30 ET")
    assert "本轮无新的加仓/减仓条件" in receipt
    assert "5/5 行情已刷新" in receipt
    assert "一级信息刚检查" in receipt
    assert "RKLB" in receipt
    assert "| CRCL |" not in receipt


def test_receipt_quote_coverage_does_not_call_a_missing_row_priced(tmp_path):
    portfolio = tmp_path / 'portfolio.json'
    portfolio.write_text('{"portfolios":{"us_stocks":{"holdings":['
                         '{"ticker":"CRCL","shares":2},'
                         '{"ticker":"RKLB","shares":1}]}}}')

    coverage = P.quote_coverage(
        '| 代码 | 股 | 成本 | 现价 | 今日 | 浮% | 浮$ |\n'
        '| CRCL | 2 | 87 | 71 | +1% | -2% | -3 |',
        'us', portfolio,
    )

    assert coverage == {'priced': 1, 'active': 2}


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

STOP_SIGNAL = [{'level': 'STOP', 'ticker': '02208',
                'line': '✋ STOP? 02208 金风科技 | 今日-0.6% 浮-24.7%'}]


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
    signals = [{'level': 'STOP', 'ticker': '03033', 'line': '✋ STOP? 03033 恒科ETF | 浮-8.7%'}]

    text = P.append_setup_section(BLOCK, _setup_row('HSTECH', ('03032', '03033')), signals)

    assert '同票有风险信号(03033)' in text
    assert '03032' not in text.split('同票有风险信号')[1][:20]


def test_a_watch_signal_is_not_treated_as_a_contradiction():
    """WATCH is a -5% day, not a position-level stop; it does not veto an entry."""
    watch = [{'level': 'WATCH', 'ticker': '02208', 'line': '△ WATCH 02208 金风科技 | 今日-5.2%'}]

    assert '同票有风险信号' not in P.append_setup_section(BLOCK, _setup_row(), watch)


def test_missing_signal_detail_is_not_an_error():
    for signals in (None, [], [{'line': 'malformed'}], [{'level': None}]):
        text = P.append_setup_section(BLOCK, _setup_row(), signals)
        assert '20日突破确认' in text, signals


ANALYZE_BLOCK = """⚠️ 信号
  ✋ STOP? SPCX 商业航天 | 今日-9.0% 浮-20.2%
  ⚠️ ALERT 02208 金风科技 | 今日-8.4% 浮-24.7%
  △ WATCH 03033 恒科ETF | 今日-5.1%
📉 亏损持仓 5/5"""


def test_the_ticker_comes_from_the_parser_not_from_matching_display_text():
    """`SPC` is a substring of the flagged `SPCX` and is not the ticker."""
    _, detail = P.parse_signals(ANALYZE_BLOCK)

    assert '同票有风险信号' not in P.append_setup_section(
        BLOCK, _setup_row('SPC', ('SPC',)), detail)
    assert '同票有风险信号(SPCX)' in P.append_setup_section(
        BLOCK, _setup_row('SPCX', ('SPCX',)), detail)


def test_the_most_severe_line_reaches_the_contradiction_check():
    """⚠️ ALERT (a -8% day) outranks STOP and was in none of the counts.

    A name crashing 8% while deeply underwater could therefore have shown an
    entry row with no risk annotation at all — the one case where the two
    layers disagreeing matters most.
    """
    counts, detail = P.parse_signals(ANALYZE_BLOCK)

    assert counts['alert'] == 1
    assert [d['ticker'] for d in detail] == ['SPCX', '02208', '03033']
    text = P.append_setup_section(BLOCK, _setup_row('02208', ('02208',)), detail)
    assert '同票有风险信号(02208)' in text


# ── the failure that actually happens in production ──────────────────────────

def test_an_empty_bar_list_is_reported_not_raised():
    """`fetch_bars` returns [] on a failed request — it does not raise.

    The first version only tested an exception, which is the shape production
    never produces: `compute_signals` answers None below 30 bars, and an
    unguarded `.get` escaped the loop and took every row already collected with
    it — the exact opposite of the per-symbol isolation claimed above.
    """
    out = S.provisional_setups(_universe(), fetch=lambda code, cnt: [])

    assert out['rows'] == []
    assert out['errors'] == [{'label': '02208', 'error': 'no_bars'}]


def test_too_few_bars_is_reported_with_the_count():
    short = _flat(29, 10.0)

    out = S.provisional_setups(_universe(), fetch=lambda code, cnt: short)

    assert out['errors'] == [{'label': '02208', 'error': 'insufficient_bars(29)'}]


def test_an_empty_feed_for_one_symbol_keeps_the_rows_already_collected():
    universe = _universe('02208') + _universe('03033')
    bars = _breakout_series()

    out = S.provisional_setups(
        universe, fetch=lambda code, cnt: [] if code == 'hk03033' else bars)

    assert [row['label'] for row in out['rows']] == ['02208']
    assert [err['label'] for err in out['errors']] == ['03033']


def test_every_row_repeats_the_caveat_so_the_heading_is_not_load_bearing():
    """Nothing validates the heading.

    Postflight's verbatim check covers the block's first line and its markdown
    tables; the setup section is neither. In legacy mode a report that dropped
    the heading and kept `20日突破确认 | 入场 …` would pass every gate, and a
    provisional condition would ship as an entry that fired.
    """
    text = P.append_setup_section(BLOCK, _setup_row(), None)

    body = [line for line in text.splitlines() if '◆' in line]
    assert body and all('未收盘' in line for line in body)


def test_the_level_comes_from_the_marker_not_from_anywhere_on_the_line():
    """A holding called WATCH must not turn a TRIM row into a WATCH row.

    Nothing held today is named after a level word, which is exactly why this
    would fail quietly the first time one is.
    """
    counts, detail = P.parse_signals(
        '⚠️ 信号\n  ▽ TRIM WATCH 某基金 | 浮+52%\n  ✋STOP? ALERT 某票 | 浮-21%\n📉 末尾')

    assert [d['level'] for d in detail] == ['TRIM', 'STOP']
    assert [d['ticker'] for d in detail] == ['WATCH', 'ALERT']
    assert counts['trim'] == 1 and counts['stop'] == 1
    assert counts['watch'] == 0 and counts['alert'] == 0


def test_a_level_word_further_along_the_line_is_not_a_signal():
    """The level lives in the marker, so only the marker may be read.

    A line inside the 信号 block that carries no marker but happens to contain a
    level word — a company name, a note — would otherwise be counted as a
    signal, and the token after it published as that signal's ticker.
    """
    counts, detail = P.parse_signals(
        '⚠️ 信号\n  持仓说明 WATCHDOG 覆盖 5/5\n  某段自由文本\n📉 末尾')

    assert detail == [] and sum(counts.values()) == 0


def _counts(**kw):
    return {level.lower(): kw.get(level.lower(), 0) for level in P.SIGNAL_LEVELS}


def test_a_lone_alert_wakes_the_slot_and_says_so():
    """ALERT outranks STOP in the renderer; it may not be the quiet severity."""
    should_alert, reasons = P.decide_alert(_counts(alert=1), [])

    assert should_alert is True
    assert any('ALERT 信号 ×1' == r for r in reasons)


def test_a_lone_trim_or_watch_does_not_wake_the_slot():
    for counts in (_counts(trim=1), _counts(watch=1)):
        should_alert, reasons = P.decide_alert(counts, [])
        assert should_alert is False, counts
        assert reasons == [], counts


def test_two_mild_signals_still_wake_it_and_the_tally_names_every_level():
    should_alert, reasons = P.decide_alert(_counts(watch=1, trim=1), [])

    assert should_alert is True
    assert '多重信号 (A0 W1 S0 T1)' in reasons
