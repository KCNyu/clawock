"""An index row's day change is the day's change or it is unknown (#2347)."""
from clawock.harness import brief_render
from clawock.market_data import macro


def test_a_pre_open_repeat_of_the_last_close_has_no_day_change():
    row = macro._quote('^HSI', 24613.27, 24613.27, 0.0, 'tencent', '2026-10-02')
    assert row['price'] == 24613.27 and row['change_pct'] is None
    assert row['as_of'] == '2026-10-02'


def test_a_traded_session_keeps_the_vendor_change():
    row = macro._quote('^HSI', 23972.29, 24613.27, -2.6, 'tencent', '2026-10-02')
    assert (row['prev'], row['change_pct']) == (24613.27, -2.6)


def test_the_brief_never_prints_an_unknown_change_as_flat():
    section = brief_render.macro_section({'macro': {
        'hsi': {'price': 24613.27, 'change_pct': None, 'session': '2026-09-30'},
        'nasdaq': {'price': 26871.6, 'change_pct': 0.04},
    }}, {})
    assert 'HSI **' in section and '2026-09-30 收盘，当日涨跌未知' in section
    assert '0.00%' not in section
    assert '+0.04%' in section
