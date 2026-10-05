from clawock.publish.dashboard import compute_delta
from clawock.portfolio.guardrail import compute_breakeven_math


def test_delta_carries_the_actual_session_date():
    rows = [{'date': '2026-10-02', 'us_asof': '2026-10-01', 'hk_asof': '2026-10-02',
             'us_equity': 100, 'hk_equity': 100}]
    delta = compute_delta(rows)
    assert delta['us']['session_date'] == '2026-10-01'
    assert delta['hk']['session_date'] == '2026-10-02'


def test_swap_target_does_not_require_underlying_volatility():
    row = {'ticker': 'SPCH', 'shares': 10, 'cost_basis': 10,
           'current_price': 8, 'current_value': 80, 'pnl_percent': -20}
    result = compute_breakeven_math([], [row], {})['rows'][0]
    assert result['swap_1x'] == 'SPCX'
    assert result['underlying_need_if_1x_pct'] == 25
    assert 'underlying_vol_pct' not in result


def test_a_holding_row_carries_its_own_session_or_none():
    # The 场次 cell reads `h.day_session_date` first; the projection dropped it (#2587).
    from clawock.publish.dashboard import trim_holding
    row = {'ticker': 'CRCL', 'shares': 1, 'day_session_date': '2026-10-02'}
    assert trim_holding(row, 'USD')['day_session_date'] == '2026-10-02'
    assert trim_holding({'ticker': 'CRCL', 'shares': 1}, 'USD')['day_session_date'] is None
