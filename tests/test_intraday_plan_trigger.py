"""A plan condition being met has to reach kcn, not just the JSON.

2026-09-07 HK: the 08:00 plan hung `00100 trim_on_rebound price_above 365`
(re-hung from 9/4, still unexecuted). 00100 traded to 393 in the morning — 7.7%
through the line — and every one of the eight intraday slots reported the same
generic 「跳空/异动」. It closed at 350.8 and the trim never happened.

Two things had to be true for that, and both are pinned here: the price has to
be in the context at all (test_plan_surface), and the slot has to say it out
loud and wake on it rather than leaving it to the model to notice a number.
"""
from clawock.decision import plans
from clawock.harness import _harness_common as harness_common
from clawock.harness import intraday_delta, intraday_preflight


HK_TABLE = """
| 代码 | 股数 | 成本 | 现价 | 今日 | 盈亏% | 盈亏 |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| 00100 | 120 | 553.08 | 384.60 | +6.4% | -30.5% | -20,218 |
| 02208 | 1000 | 14.08 | 9.10 | +0.2% | -35.4% | -4,980 |
| 07226 | 6200 | 4.35 | 3.12 | -0.6% | -28.3% | -7,626 |
"""

TRIGGERED = [{
    'decision_id': 'dec-554c', 'plan_date': '2026-09-07', 'ticker': '00100',
    'action': 'trim_on_rebound', 'condition': 'price_above',
    'condition_price': 365.0, 'last': 384.6, 'through_pct': 5.37,
    'shares': 20, 'execution_status': 'unknown',
    'open_since': '2026-09-04', 'restated_count': 2,
}]


def test_the_holdings_table_yields_every_row_not_only_the_movers():
    """A trigger can be met on a ticker that is flat on the day, so the ≥3%
    gate cannot be the only reader of this table."""
    rows = harness_common.parse_holdings_rows(HK_TABLE)

    assert {r['ticker']: r['price'] for r in rows} == {
        '00100': 384.60, '02208': 9.10, '07226': 3.12}
    # …and the anomaly view over the same parse is unchanged: only 00100 moved ≥3%.
    assert [a['ticker'] for a in harness_common.parse_holdings_anomalies(HK_TABLE)] == ['00100']


def test_a_dash_in_the_price_cell_is_absent_not_zero():
    """A missing quote must never read as 0 to a `price_below` gate."""
    rows = harness_common.parse_holdings_rows(
        '| 00100 | 120 | 553.08 | — | +0.0% | -30.5% | -20,218 |')

    assert rows[0]['price'] is None
    assert plans.triggered_conditions(
        {'open': [{'ticker': '00100', 'action': 'cut', 'condition': 'price_below',
                   'condition_price': 400.0}]},
        {r['ticker']: r['price'] for r in rows}) == []


def test_the_trigger_is_printed_in_the_block():
    """#515: a detector whose finding nothing prints has been silenced. The
    model may or may not notice a number in the context; a line in the block is
    in the message kcn reads."""
    block = intraday_preflight.append_plan_trigger_section('原始块', TRIGGERED)

    assert '原始块' in block
    assert '00100' in block and '≥365' in block and '384.6' in block
    assert '+5.37%' in block
    assert '未执行' in block
    assert '2026-09-04' in block          # how long it has been met-and-unfilled


def test_nothing_is_printed_when_nothing_is_triggered():
    assert intraday_preflight.append_plan_trigger_section('原始块', []) == '原始块'


def test_a_met_trigger_wakes_the_slot_on_its_own():
    """The condition can be met on a day the ticker moved 0.4% and tripped no
    signal — `decide_alert` would never have seen it."""
    should_alert, reasons = intraday_preflight.apply_plan_trigger_alert(
        False, [], TRIGGERED)

    assert should_alert is True
    assert any('00100' in r and '365' in r for r in reasons)


def test_an_untriggered_slot_is_left_exactly_as_it_was():
    assert intraday_preflight.apply_plan_trigger_alert(False, ['异动: X'], []) == (
        False, ['异动: X'])


def _state(**over):
    base = dict(signals_detail=[], anomalies=[], setups={'rows': []},
                plans={'open': []}, active_information={}, plan_triggers=None)
    base.update(over)
    return intraday_delta.semantic_state('hk', '2026-09-07', **base)


def test_a_newly_met_trigger_is_a_semantic_change():
    """Otherwise the delta gate calls the slot unchanged, sends a receipt, and
    forces should_alert False — silencing the one line that mattered."""
    quiet = _state()
    hit = _state(plan_triggers=TRIGGERED)

    assert intraday_delta.compare_semantic_states(hit, quiet)['changed']


def test_a_trigger_that_stays_met_is_one_delta_not_one_per_slot():
    """It collapses to a stable identity: the price wobbling above the line all
    afternoon is exactly the churn this gate exists to exclude."""
    first = _state(plan_triggers=TRIGGERED)
    later = _state(plan_triggers=[{**TRIGGERED[0], 'last': 391.2,
                                   'through_pct': 7.18}])

    assert not intraday_delta.compare_semantic_states(later, first)['changed']
