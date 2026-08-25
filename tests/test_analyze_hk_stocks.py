"""Behavioral tests for pure helpers in ``analyze_hk_stocks``.

All quote inputs are synthetic Tencent wire-format responses.  These tests do
not call fetchers or patch a transport: the exercised surface is deterministic.
"""

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest


# analyze_hk_stocks imports requests at module load.  Keep collection healthy in
# deliberately minimal environments; it has no top-level numpy/pandas imports.
pytest.importorskip("requests")

ROOT = Path(__file__).resolve().parents[1]

from clawock.market_data import hk_analysis as hk  # noqa: E402


@pytest.fixture(autouse=True)
def _forbid_network(monkeypatch):
    """Fail immediately if a future edit makes these pure tests reach transport."""
    def unexpected_network(*args, **kwargs):
        pytest.fail("network access is forbidden in pure-function tests")

    monkeypatch.setattr(hk.SESSION, "get", unexpected_network)
    monkeypatch.setattr(hk, "em_get", unexpected_network)


def _gtimg_line(
    response_symbol: str,
    *,
    name: str,
    quote_symbol: str,
    current: str,
    prev_close: str,
    day_open: str,
    day_high: str,
    day_low: str,
) -> str:
    """Build a realistic qt.gtimg.cn line with the documented field layout."""
    fields = [""] * 40
    fields[0] = "100"
    fields[1] = name
    fields[2] = quote_symbol
    fields[3] = current
    fields[4] = prev_close
    fields[5] = day_open
    fields[30] = "20260717155930"
    fields[31] = "1.250"
    fields[32] = "0.41"
    fields[33] = day_high
    fields[34] = day_low
    return f'v_{response_symbol}="{"~".join(fields)}";'


def test_parse_gtimg_hk_quote_uses_definitional_price_and_day_range_fields():
    raw = _gtimg_line(
        "r_hk00700",
        name="腾讯控股",
        quote_symbol="00700",
        current="508.500",
        prev_close="501.000",
        day_open="503.500",
        day_high="512.000",
        day_low="499.500",
    )

    parsed = hk._parse_gtimg(raw)

    assert parsed == {
        "name": "腾讯控股",
        "c": 508.5,
        "pc": 501.0,
        "o": 503.5,
        "h": 512.0,
        "l": 499.5,
        "lot_size": None,
        "volume": None,
        "dp": 1.5,
    }


def test_parse_gtimg_carries_hk_board_lot_from_field_60():
    fields = [""] * 78
    fields[1] = "MINIMAX-W"
    fields[3] = "357.4"
    fields[4] = "328.0"
    fields[5] = "337.8"
    fields[33] = "364.6"
    fields[34] = "333.0"
    fields[60] = "20"

    parsed = hk._parse_gtimg('v_hk00100="' + "~".join(fields) + '";')

    assert parsed["lot_size"] == 20


@pytest.mark.parametrize(
    ("response_symbol", "quote_symbol", "name", "current", "expected_dp"),
    [
        ("usAAPL", "AAPL.OQ", "Apple", "215.750", 1.77),
        ("usSOXL.AM", "SOXL.AM", "Direxion半导体三倍做多", "42.125", -2.6),
    ],
)
def test_parse_gtimg_us_quote_suffix_does_not_shift_quote_fields(
    response_symbol, quote_symbol, name, current, expected_dp
):
    raw = _gtimg_line(
        response_symbol,
        name=name,
        quote_symbol=quote_symbol,
        current=current,
        prev_close="212.000" if quote_symbol == "AAPL.OQ" else "43.250",
        day_open="213.125" if quote_symbol == "AAPL.OQ" else "43.500",
        day_high="218.000" if quote_symbol == "AAPL.OQ" else "44.000",
        day_low="211.500" if quote_symbol == "AAPL.OQ" else "41.750",
    )

    parsed = hk._parse_gtimg(raw)

    assert parsed is not None
    assert parsed["name"] == name
    assert parsed["c"] == float(current)
    assert parsed["pc"] == (212.0 if quote_symbol == "AAPL.OQ" else 43.25)
    assert parsed["o"] == (213.125 if quote_symbol == "AAPL.OQ" else 43.5)
    assert parsed["h"] == (218.0 if quote_symbol == "AAPL.OQ" else 44.0)
    assert parsed["l"] == (211.5 if quote_symbol == "AAPL.OQ" else 41.75)
    assert parsed["dp"] == expected_dp


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "v_r_hk00700=;",
        'v_r_hk00700="100~腾讯控股~00700~508.5~501.0";',
        'v_r_hk00700="100~腾讯控股~00700~not-a-price~501.0~503.5";',
    ],
)
def test_parse_gtimg_rejects_empty_short_or_malformed_responses(raw):
    assert hk._parse_gtimg(raw) is None


def test_parse_gtimg_missing_previous_close_and_open_fall_back_to_current_only():
    raw = _gtimg_line(
        "r_hk00100",
        name="MINIMAX-W",
        quote_symbol="00100",
        current="297.400",
        prev_close="",
        day_open="",
        day_high="301.000",
        day_low="289.000",
    )

    parsed = hk._parse_gtimg(raw)

    assert parsed is not None
    assert parsed["c"] == 297.4
    assert parsed["pc"] == 297.4
    assert parsed["o"] == 297.4
    assert parsed["dp"] == 0.0
    assert parsed["h"] == 301.0
    assert parsed["l"] == 289.0


def test_parse_gtimg_valid_quote_without_day_range_does_not_fabricate_range():
    raw = 'v_r_hk00700="100~腾讯控股~00700~508.5~501.0~503.5";'

    parsed = hk._parse_gtimg(raw)

    assert parsed is not None
    assert parsed["h"] is None
    assert parsed["l"] is None


def test_parse_gtimg_carries_hk_volume_from_field_6():
    fields = [""] * 40
    fields[1] = "MINIMAX-W"
    fields[3] = "299.600"
    fields[4] = "312.200"
    fields[5] = "312.000"
    fields[6] = "12136215"
    fields[33] = "323.600"
    fields[34] = "290.400"

    parsed = hk._parse_gtimg('v_hk00100="' + "~".join(fields) + '";')

    assert parsed is not None
    assert parsed["volume"] == 12136215


def test_parse_gtimg_without_volume_field_does_not_fabricate_volume():
    # Field 6 absent/empty → volume must stay None so callers preserve the
    # prior verified value instead of inventing one.
    fields = [""] * 40
    fields[1] = "MINIMAX-W"
    fields[3] = "299.600"
    fields[4] = "312.200"

    parsed = hk._parse_gtimg('v_hk00100="' + "~".join(fields) + '";')

    assert parsed is not None
    assert parsed["volume"] is None


def test_update_hk_portfolio_stamps_prev_close_to_prior_session_and_writes_volume(
    tmp_path, monkeypatch
):
    port = {
        "portfolios": {
            "hk_stocks": {
                "holdings": [
                    {
                        "ticker": "00100",
                        "shares": 100.0,
                        "cost_basis": 300.0,
                        "current_price": 312.0,
                        "prev_close": 312.2,
                        "prev_close_date": "2026-08-25",
                        "day_session_date": "2026-08-25",
                        "day_open": 312.0,
                        "day_high": 323.6,
                        "day_low": 290.4,
                        "volume": 38060,
                        "lot_size": 500,
                    }
                ]
            }
        }
    }
    p = tmp_path / "portfolio.json"
    p.write_text(json.dumps(port))
    monkeypatch.setattr(hk, "PORTFOLIO_PATH", str(p))

    quote = {
        "name": "MINIMAX-W",
        "c": 299.6,
        "pc": 312.2,
        "o": 312.0,
        "h": 323.6,
        "l": 290.4,
        "lot_size": 500,
        "volume": 12136215,
        "dp": -4.04,
        "_src": "Tencent",
    }
    monkeypatch.setattr(hk, "fetch_hk_quotes", lambda codes: {"00100": quote})
    monkeypatch.setattr(hk, "fetch_indices", lambda: {})

    data = hk.update_hk_portfolio(dry_run=True)
    h = data["portfolios"]["hk_stocks"]["holdings"][0]

    # prev_close_date must be the PRIOR HK trading session, never today — this
    # is the fix that re-arms integrity's STALE_PRICE gate.
    assert h["prev_close_date"] != "2026-08-25"
    now_hkt = datetime.now(timezone(timedelta(hours=8)))
    expected = hk.trading_calendar.previous_trading_day("hk", now_hkt.date()).isoformat()
    assert h["prev_close_date"] == expected
    assert h["prev_close_date"] < h["day_session_date"]

    # Volume must be overwritten with the real traded volume from Tencent
    # parts[6], replacing the stale legacy 38060.
    assert h["volume"] == 12136215


def test_update_hk_portfolio_preserves_volume_when_quote_lacks_volume(
    tmp_path, monkeypatch
):
    port = {
        "portfolios": {
            "hk_stocks": {
                "holdings": [
                    {
                        "ticker": "00100",
                        "shares": 100.0,
                        "cost_basis": 300.0,
                        "current_price": 312.0,
                        "prev_close": 312.2,
                        "day_open": 312.0,
                        "day_high": 323.6,
                        "day_low": 290.4,
                        "volume": 38060,
                        "lot_size": 500,
                    }
                ]
            }
        }
    }
    p = tmp_path / "portfolio.json"
    p.write_text(json.dumps(port))
    monkeypatch.setattr(hk, "PORTFOLIO_PATH", str(p))

    # Fallback source that does not expose volume.
    quote = {
        "name": "MINIMAX-W",
        "c": 299.6,
        "pc": 312.2,
        "o": 312.0,
        "h": 323.6,
        "l": 290.4,
        "lot_size": 500,
        "dp": -4.04,
        "_src": "Eastmoney",
    }
    monkeypatch.setattr(hk, "fetch_hk_quotes", lambda codes: {"00100": quote})
    monkeypatch.setattr(hk, "fetch_indices", lambda: {})

    data = hk.update_hk_portfolio(dry_run=True)
    h = data["portfolios"]["hk_stocks"]["holdings"][0]

    # Without a volume on the quote, the prior verified value must be kept.
    assert h["volume"] == 38060


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("00700", ["0700.HK", "HK:700", "00700.HK"]),
        ("00100", ["0100.HK", "HK:100", "00100.HK"]),
        ("07226", ["7226.HK", "HK:7226", "07226.HK"]),
    ],
)
def test_finnhub_symbols_normalize_hk_codes_without_losing_fallback_form(code, expected):
    assert hk._finnhub_syms(code) == expected


@pytest.mark.parametrize(
    ("current", "prev_close", "expected"),
    [(105.0, 100.0, 5.0), (95.0, 100.0, -5.0), (10.005, 10.0, 0.05), (8.0, 0.0, 0.0)],
)
def test_pct_is_previous_close_return_rounded_to_two_decimals(
    current, prev_close, expected
):
    assert hk._pct(current, prev_close) == expected


@pytest.mark.parametrize(
    ("articles", "expected"),
    [
        ([{"headline": "Profit surge after upgrade", "summary": "strong gain"}], "positive"),
        ([{"headline": "盈利增长", "summary": "机构上调后买入"}], "positive"),
        ([{"headline": "Loss risk after downgrade", "summary": "shares drop"}], "negative"),
        ([{"headline": "Profit warning", "summary": "loss risk"}], "neutral"),
        ([], "neutral"),
    ],
)
def test_news_sentiment_uses_documented_two_hit_margin(articles, expected):
    assert hk.news_sentiment(articles) == expected


@pytest.mark.parametrize(
    ("holding", "expected"),
    [
        ({"today_change_pct": -8.0, "pnl_percent": 80.0}, "⚠️ ALERT"),
        ({"today_change_pct": -5.0, "pnl_percent": 80.0}, "△ WATCH"),
        ({"today_change_pct": 0.0, "pnl_percent": 50.0}, "▽ TRIM"),
        ({"today_change_pct": 1.0, "pnl_percent": -20.0}, "✋ STOP?"),
        ({"today_change_pct": 1.0, "pnl_percent": -10.0}, "─ HOLD"),
        ({"today_change_pct": 5.0, "pnl_percent": 0.0}, "▲ HOLD+"),
        ({}, "─ HOLD"),
    ],
)
def test_signal_thresholds_and_priority_are_definitional(holding, expected):
    assert hk.signal(holding) == expected
