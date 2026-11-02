"""A missing intraday range must not hide a known session return.

Nasdaq's `/info` endpoint returns the last price and ``percentageChange`` but
no ``summaryData`` block, so ``pc``/``h``/``l`` are all absent. The old single
``quote_incomplete`` flag therefore made ``session_change_pct`` return ``None``
even when the prior close had been resolved correctly (from the provider's own
move or a dated stored close) and agreed with the canonical bar.

The flags now say which gap exists. The range gap keeps its strict consumers
(STALE_PRICE wording, day_high/day_low caveat); refresh coverage reads the
stale-print field separately, so a current price is not called unrefreshed
just because its range is local. The prior-close gap alone vetoes the return.
"""
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from clawock.harness._harness_common import quote_coverage
from clawock.market_data import us_quotes as quotes
from clawock.portfolio import integrity
from clawock.portfolio.math import (
    quote_price_is_current,
    quote_session_comparable,
    session_change_pct,
)
from clawock.publish.dashboard import trim_holding

ET = ZoneInfo("America/New_York")
HKT = ZoneInfo("Asia/Hong_Kong")


def _holding(**overrides):
    holding = {
        "ticker": "RKLX", "shares": 10, "cost_basis": 5.0,
        "current_price": 9.55, "prev_close": 9.8,
        "prev_close_date": "2026-10-30", "day_session_date": "2026-11-02",
        "day_high": 9.55, "day_low": 9.55, "day_open": 9.55,
        "today_change": -2.5, "today_change_pct": -2.551,
        "current_value": 95.5, "pnl_abs": -4.5, "pnl_percent": -9.0,
        "data_source": "Nasdaq API (etf) Nov 02, 2026 10:04 ET",
        "trades": [{"date": "2026-04-16", "action": "buy",
                    "shares": 10, "price": 5.0}],
    }
    holding.update(overrides)
    return holding


def _split(holding, *, prev_missing, range_missing):
    if prev_missing:
        holding["quote_incomplete_prev_close"] = True
    if range_missing:
        holding["quote_incomplete_range"] = True
    if prev_missing or range_missing:
        holding["quote_incomplete"] = True
    return holding


@pytest.mark.parametrize(
    ("prev_missing", "range_missing", "expected"),
    [
        (False, False, (9.55 / 9.8 - 1) * 100),
        (False, True, (9.55 / 9.8 - 1) * 100),
        (True, False, None),
        (True, True, None),
    ],
    ids=["both-known", "range-only-missing", "prev-only-missing", "both-missing"],
)
def test_only_the_prior_close_gap_vetoes_the_session_return(
        prev_missing, range_missing, expected):
    holding = _split(_holding(), prev_missing=prev_missing,
                     range_missing=range_missing)

    result = session_change_pct(holding)

    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected)
    assert quote_session_comparable(holding) is (expected is not None)
    # The price print is from this session in all four cases; a missing range
    # or a missing prior close does not turn a fresh print into an old one.
    assert quote_price_is_current(holding) is True


def test_an_earlier_session_print_is_not_a_session_return():
    holding = _split(_holding(), prev_missing=False, range_missing=True)
    holding["quote_stale_asof"] = "2026-10-30"

    assert session_change_pct(holding) is None
    assert quote_session_comparable(holding) is False
    assert quote_price_is_current(holding) is False


def test_a_pre_split_row_stays_conservative_until_it_is_refreshed():
    holding = _holding(quote_incomplete=True)

    assert session_change_pct(holding) is None
    assert quote_price_is_current(holding) is False


def test_dashboard_publishes_the_return_when_only_the_range_is_missing():
    row = trim_holding(
        _split(_holding(), prev_missing=False, range_missing=True), "USD")

    assert row["today_change_pct"] == pytest.approx(-2.55)
    assert row["today_change"] == -2.5


def test_dashboard_keeps_the_return_unknown_when_the_prior_close_is_missing():
    row = trim_holding(
        _split(_holding(), prev_missing=True, range_missing=True), "USD")

    assert row["today_change_pct"] is None


def _apply(q, holding=None, prev_closes=None):
    holding = holding or _holding(current_price=9.0)
    quotes._us_apply_quote(
        holding, q, prev_closes or {},
        now_et=datetime(2026, 11, 2, 10, 4, tzinfo=ET),
        today_et_date="2026-11-02", expected_prev_session="2026-10-30")
    return holding


def test_writer_separates_a_missing_range_from_a_missing_prior_close():
    # The Nasdaq /info shape: price and percentageChange, no summaryData. The
    # provider move rebuilds the correct prior close, so only the range is
    # missing.
    holding = _apply({
        "c": 9.55, "dp": -2.551, "h": None, "l": None, "o": None,
        "source": "Nasdaq API (etf)",
    })

    assert holding["prev_close"] == 9.8
    assert holding["prev_close_date"] == "2026-10-30"
    assert "quote_incomplete_prev_close" not in holding
    assert holding["quote_incomplete_range"] is True
    assert holding["quote_incomplete"] is True
    assert session_change_pct(holding) == pytest.approx(-2.551, abs=1e-3)


def test_writer_flags_the_pc_equals_c_fallback_as_no_prior_close():
    holding = _holding(current_price=9.0)
    holding.pop("prev_close")
    holding.pop("prev_close_date")
    holding = _apply({
        "c": 9.55, "dp": 0, "h": 9.95, "l": 9.55, "o": 9.55,
        "source": "Nasdaq API (etf)",
    }, holding=holding)

    # The resolver still writes a finite placeholder so the arithmetic holds,
    # and the flag says it is not a measurement.
    assert holding["prev_close"] == 9.55
    assert holding["quote_incomplete_prev_close"] is True
    assert "quote_incomplete_range" not in holding
    assert holding["quote_incomplete"] is True
    assert session_change_pct(holding) is None


def test_writer_clears_both_flags_on_a_complete_quote():
    holding = _apply({
        "c": 9.55, "pc": 9.8, "dp": -2.551, "h": 9.95, "l": 9.55, "o": 9.94,
        "source": "Finnhub",
    })

    assert "quote_incomplete_prev_close" not in holding
    assert "quote_incomplete_range" not in holding
    assert "quote_stale_asof" not in holding
    assert "quote_incomplete" not in holding
    assert session_change_pct(holding) == pytest.approx(-2.551, abs=1e-3)


def test_writer_keeps_an_old_print_in_its_own_bucket():
    holding = _apply({
        "c": 9.55, "pc": 9.8, "dp": -2.551, "h": 9.95, "l": 9.55,
        "source": "Nasdaq API (etf)", "stale_asof": "2026-10-30",
    })

    assert holding["quote_stale_asof"] == "2026-10-30"
    assert holding["quote_incomplete_range"] is True
    assert "quote_incomplete_prev_close" not in holding
    assert holding["quote_incomplete"] is True
    assert session_change_pct(holding) is None


def test_refresh_coverage_counts_a_current_print_even_when_the_range_is_local(tmp_path):
    now = datetime(2026, 11, 2, 23, 9, tzinfo=HKT)
    path = tmp_path / "portfolio.json"
    path.write_text(json.dumps({"portfolios": {"us_stocks": {"holdings": [
        _holding(ticker="CRCL", quote_incomplete=True,
                 quote_incomplete_range=True,
                 data_source="Nasdaq API (stocks) Nov 02, 2026 10:04 ET"),
        _holding(ticker="RKLX", quote_incomplete=True,
                 quote_incomplete_range=True, quote_stale_asof="2026-10-30",
                 data_source="Nasdaq API (etf) Nov 02, 2026 10:04 ET"),
    ]}}}))

    coverage = quote_coverage("us", path, now=now,
                              started_at=now - timedelta(minutes=5))

    # The range is local, but the price was fetched this run. The old print is
    # still named: refresh coverage is about the price, not the range.
    assert coverage == {"refreshed": 1, "active": 2, "unrefreshed": ["RKLX"]}


def _portfolio(holding):
    return {
        "last_updated": "2026/11/02 23:04 HKT",
        "portfolios": {"us_stocks": {
            "currency": "USD", "holdings": [holding],
            "total_cost": 50.0, "total_current_value": 95.5,
            "total_pnl": 45.5, "today_total_change": -2.5,
        }},
    }


def _stale_messages(tmp_path, holding):
    path = tmp_path / "portfolio.json"
    path.write_text(json.dumps(_portfolio(holding)))
    return [finding["msg"] for finding in integrity.check(path)["findings"]
            if finding["code"] == "STALE_PRICE"]


def test_the_gate_wording_names_the_range_gap_not_a_missing_prior_close(tmp_path):
    messages = _stale_messages(
        tmp_path, _split(_holding(), prev_missing=False, range_missing=True))

    assert len(messages) == 1
    assert "缺日内区间" in messages[0]
    assert "缺可信前收" not in messages[0]


def test_the_gate_wording_names_the_prior_close_gap_on_its_own(tmp_path):
    holding = _split(
        _holding(prev_close=9.55, current_price=9.55, prev_close_date="2026-10-30"),
        prev_missing=True, range_missing=False)
    messages = _stale_messages(tmp_path, holding)

    assert messages
    assert any("缺可信前收" in message for message in messages)
    assert not any("缺日内区间" in message for message in messages)
    # The old "provider froze at yesterday's close" sentence must not explain a
    # placeholder this resolver wrote itself.
    assert not any("四位小数完全相等" in message for message in messages)
