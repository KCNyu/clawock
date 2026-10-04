"""The pre-open brief labels a day change with the session it belongs to (#2550).

The brief runs at 08:03 HKT, before either market trades, so every day change in
it is the previous close. #2531 said so on the sector table; the peer scan and the
holdings table print the same number (`peer_scan` copies `today_change_pct`) and
kept calling it 今日.
"""
from clawock.harness import brief_render


def test_the_same_number_carries_the_same_session_label_in_every_table():
    holding = {"ticker": "07226", "shares": 100, "cost_basis": 5.0, "current_price": 5.2,
               "today_change_pct": 0.15, "pnl_percent": 4.0, "pnl_abs": 20.0}
    context = {
        "portfolio": {"portfolios": {"hk_stocks": {"holdings": [holding]}}},
        "peer_scan": {"07226": {"self_pct_1d": 0.15, "theme": "tech", "listed_peers": []}},
    }

    holdings = brief_render.holdings_section(context)
    peers = brief_render.peer_section(context, {})

    assert "上一场收盘" in holdings
    assert "**07226** · 上一场收盘 +0.15%" in peers
    assert "今日" not in holdings + peers
