"""Regression net for the 2026-07-27 US quote incident.

What actually shipped: PLTU sat on the dashboard at 0.00% on a +6.3% day and
SKHY at -0.31% on a -6.2% day, and not one gate said a word. Five independent
defects had to line up, so each gets a test:

  1. Nasdaq `/info` carries no summaryData, but get_nasdaq_quote defaulted
     pc/o/h/l to the last price -> every quote looked complete and flat.
  2. Nasdaq is provider #1 and therefore always won, so Eastmoney/Finnhub
     (which do return a real range) were never consulted.
  3. Polygon's per-ticker prev-close loop burned through a 5 req/min free tier
     and silently dropped everything past the fifth ticker.
  4. A reconstructed prior close was stamped with *today's* date, which also
     tripped preflight_integrity's `opened_this_session` exemption and switched
     off TODAY_LEG for exactly the affected rows.
  5. Nothing anywhere compared current_price against the prior close, so a last
     price frozen at yesterday's close passed every check by being perfectly
     self-consistent.

Run: `python3 -m pytest tests/test_us_quote_staleness.py -q`
"""
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from zoneinfo import ZoneInfo

import pytest

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(WS, "scripts", "data"))

from clawock.market_data import us_quotes as F  # noqa: E402
from clawock.portfolio import integrity as pi  # noqa: E402
from clawock import trading_calendar as tc  # noqa: E402


# ── 1. the parser must not invent fields the payload does not have ───────────
class _FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


# The real shape of api.nasdaq.com/api/quote/SPCX/info on 2026-07-27: rich
# primaryData, and no summaryData key at all.
NASDAQ_INFO_NO_SUMMARY = {
    "data": {
        "symbol": "PLTU",
        "companyName": "Direxion Daily PLTR Bull 2X Shares",
        "primaryData": {
            "lastSalePrice": "$28.82",
            "netChange": "+1.47",
            "percentageChange": "+5.37%",
            "deltaIndicator": "up",
            "lastTradeTimestamp": "Jul 27, 2026 9:30 AM ET",
            "isRealTime": True,
        },
        "assetClass": "ETF",
    }
}


class TestNasdaqParserDoesNotFabricate:
    def test_absent_summary_fields_stay_none(self, monkeypatch):
        monkeypatch.setattr(F.SESSION, "get",
                            lambda *a, **k: _FakeResp(NASDAQ_INFO_NO_SUMMARY))
        q = F.get_nasdaq_quote("PLTU")
        assert q is not None
        assert q["c"] == 28.82
        # The whole bug in one assertion: these used to silently become 28.82.
        assert q["pc"] is None
        assert q["o"] is None
        assert q["h"] is None
        assert q["l"] is None

    def test_netchange_and_pct_are_kept(self, monkeypatch):
        monkeypatch.setattr(F.SESSION, "get",
                            lambda *a, **k: _FakeResp(NASDAQ_INFO_NO_SUMMARY))
        q = F.get_nasdaq_quote("PLTU")
        # netChange is the only exact way back to the prior close from /info.
        assert q["nc"] == 1.47
        assert q["dp"] == 5.37
        assert round(q["c"] - q["nc"], 4) == 27.35   # the true prior close

    def test_negative_netchange_parses(self, monkeypatch):
        payload = json.loads(json.dumps(NASDAQ_INFO_NO_SUMMARY))
        payload["data"]["primaryData"].update(
            {"lastSalePrice": "$110.42", "netChange": "-5.50",
             "percentageChange": "-4.78%"})
        monkeypatch.setattr(F.SESSION, "get", lambda *a, **k: _FakeResp(payload))
        q = F.get_nasdaq_quote("SPCX")
        assert q["nc"] == -5.50 and q["dp"] == -4.78

    def test_real_summary_payload_still_parses(self, monkeypatch):
        payload = json.loads(json.dumps(NASDAQ_INFO_NO_SUMMARY))
        payload["data"]["summaryData"] = {
            "PreviousClose": {"value": "$27.35"},
            "OpenPrice": {"value": "$28.00"},
            "TodayHighLow": {"value": "$27.90 - $29.10"},
            "ShareVolume": {"value": "2,703,700"},
        }
        monkeypatch.setattr(F.SESSION, "get", lambda *a, **k: _FakeResp(payload))
        q = F.get_nasdaq_quote("PLTU")
        assert (q["pc"], q["o"], q["l"], q["h"]) == (27.35, 28.00, 27.90, 29.10)
        assert q["volume"] == 2703700


class TestLastTradeTimestamp:
    """The provider states the age of its own print — read it.

    2026-07-27 11:12 ET, live: SPCH was serving a Jul 22 10:22 ET trade, PLTU
    and CRCL a Jul 23 one. Four and five sessions stale, said out loud in the
    payload, and nothing in the pipeline looked. `current_price == prev_close`
    only catches the subset where the frozen print happens to equal the prior
    close — SPCH's did not, so that heuristic alone would have missed it.
    """

    @pytest.mark.parametrize("raw,expected", [
        ("Jul 27, 2026 9:34 AM ET", "2026-07-27"),
        ("Jul 22, 2026 10:22 AM ET", "2026-07-22"),
        ("Jul 23, 2026", "2026-07-23"),
        ("Jan 05, 2026 4:00 PM ET", "2026-01-05"),
        (None, None),
        ("", None),
        ("garbage", None),
    ])
    def test_timestamp_parsing(self, raw, expected):
        assert F._parse_nasdaq_ts(raw) == expected

    def test_quote_from_an_earlier_session_is_not_fresh(self):
        assert not F._quote_is_fresh({"asof_date": "2026-07-23"}, "2026-07-27")

    def test_todays_quote_is_fresh(self):
        assert F._quote_is_fresh({"asof_date": "2026-07-27"}, "2026-07-27")

    def test_missing_timestamp_is_treated_as_fresh(self):
        # Providers that publish no timestamp must not be penalised.
        assert F._quote_is_fresh({"c": 1.0}, "2026-07-27")

    def test_asof_date_is_captured_from_the_payload(self, monkeypatch):
        payload = json.loads(json.dumps(NASDAQ_INFO_NO_SUMMARY))
        payload["data"]["primaryData"]["lastTradeTimestamp"] = "Jul 23, 2026"
        monkeypatch.setattr(F.SESSION, "get", lambda *a, **k: _FakeResp(payload))
        assert F.get_nasdaq_quote("PLTU")["asof_date"] == "2026-07-23"


class TestQuoteCompleteness:
    def test_missing_range_is_incomplete(self):
        assert not F._quote_is_complete({"c": 1.0, "pc": 1.0, "h": None, "l": None})

    def test_missing_prev_close_is_incomplete(self):
        assert not F._quote_is_complete({"c": 1.0, "pc": None, "h": 2.0, "l": 0.5})

    def test_full_quote_is_complete(self):
        assert F._quote_is_complete({"c": 1.0, "pc": 0.9, "h": 1.1, "l": 0.8})

    def test_none_is_incomplete(self):
        assert not F._quote_is_complete(None)


# ── 2. an incomplete quote must not win the provider race ────────────────────
class TestProviderRace:
    def _silence(self, monkeypatch):
        for name in ("get_eastmoney_batch",):
            monkeypatch.setattr(F, name, lambda *a, **k: {})
        for name in ("get_finnhub_quote", "get_yahoo_v8_quote",
                     "get_yfinance_quote", "get_alpha_vantage_quote",
                     "get_polygon_quote"):
            monkeypatch.setattr(F, name, lambda *a, **k: None)

    def test_richer_provider_overrides_rangeless_nasdaq(self, monkeypatch):
        self._silence(monkeypatch)
        monkeypatch.setattr(F, "get_nasdaq_quote",
                            lambda t: {"c": 28.82, "pc": None, "h": None, "l": None,
                                       "o": None, "dp": 5.37, "source": "Nasdaq API (etf)"})
        monkeypatch.setattr(F, "get_finnhub_quote",
                            lambda t, k: {"c": 29.07, "pc": 27.35, "h": 29.81,
                                          "l": 28.41, "o": 28.515, "dp": 6.2888,
                                          "source": "Finnhub"})
        out = F.fetch_us_quotes(["PLTU"], {"FINNHUB_API_KEY": "x"})
        assert out["PLTU"]["source"] == "Finnhub"
        assert out["PLTU"]["l"] == 28.41
        assert not out["PLTU"].get("incomplete")

    def test_incomplete_quote_used_as_last_resort_and_flagged(self, monkeypatch):
        self._silence(monkeypatch)
        monkeypatch.setattr(F, "get_nasdaq_quote",
                            lambda t: {"c": 28.82, "pc": None, "h": None, "l": None,
                                       "o": None, "dp": 5.37, "source": "Nasdaq API (etf)"})
        out = F.fetch_us_quotes(["PLTU"], {})
        # Better than nothing, but it must say so rather than look healthy.
        assert out["PLTU"]["c"] == 28.82
        assert out["PLTU"]["incomplete"] is True

    def test_days_old_print_loses_to_a_current_one(self, monkeypatch):
        # The exact SPCH shape: Nasdaq's price is precise but five sessions old,
        # Finnhub's is this session. Recency wins.
        self._silence(monkeypatch)
        monkeypatch.setattr(F, "get_nasdaq_quote",
                            lambda t: {"c": 7.595, "pc": None, "h": None, "l": None,
                                       "o": None, "dp": 0.0, "asof_date": "2026-07-22",
                                       "source": "Nasdaq API (etf)"})
        monkeypatch.setattr(F, "get_finnhub_quote",
                            lambda t, k: {"c": 6.15, "pc": 6.65, "h": 6.65, "l": 5.9,
                                          "o": 6.5, "dp": -7.52, "source": "Finnhub"})
        out = F.fetch_us_quotes(["SPCH"], {"FINNHUB_API_KEY": "x"})
        assert out["SPCH"]["c"] == 6.15
        assert out["SPCH"]["source"] == "Finnhub"

    def test_days_old_print_also_loses_to_an_incomplete_current_one(self, monkeypatch):
        # A rangeless price from this session still beats an exact price from
        # four sessions ago, so the stale one must rank below `partial`.
        self._silence(monkeypatch)
        monkeypatch.setattr(F, "get_nasdaq_quote",
                            lambda t: {"c": 27.35, "pc": None, "h": None, "l": None,
                                       "o": None, "dp": 0.0, "asof_date": "2026-07-23",
                                       "source": "Nasdaq API (etf)"})
        monkeypatch.setattr(F, "get_yahoo_v8_quote",
                            lambda t: {"c": 29.52, "pc": None, "h": None, "l": None,
                                       "o": None, "dp": 7.93, "source": "Yahoo v8"})
        out = F.fetch_us_quotes(["PLTU"], {})
        assert out["PLTU"]["c"] == 29.52
        assert out["PLTU"]["incomplete"] is True

    def test_stale_print_is_last_resort_and_labelled(self, monkeypatch):
        # Nothing else answered at all -> use it, but say how old it is rather
        # than let it look like a live quote.
        self._silence(monkeypatch)
        monkeypatch.setattr(F, "get_nasdaq_quote",
                            lambda t: {"c": 7.595, "pc": None, "h": None, "l": None,
                                       "o": None, "dp": 0.0, "asof_date": "2026-07-22",
                                       "source": "Nasdaq API (etf)"})
        out = F.fetch_us_quotes(["SPCH"], {})
        assert out["SPCH"]["c"] == 7.595
        assert out["SPCH"]["stale_asof"] == "2026-07-22"
        assert out["SPCH"]["incomplete"] is True

    def test_complete_nasdaq_quote_short_circuits(self, monkeypatch):
        self._silence(monkeypatch)
        called = []
        monkeypatch.setattr(F, "get_nasdaq_quote",
                            lambda t: {"c": 28.82, "pc": 27.35, "h": 29.0, "l": 28.0,
                                       "o": 28.5, "dp": 5.37, "source": "Nasdaq API (etf)"})

        def _spy(t, k):
            called.append(t)
            return None
        monkeypatch.setattr(F, "get_finnhub_quote", _spy)
        out = F.fetch_us_quotes(["PLTU"], {"FINNHUB_API_KEY": "x"})
        assert out["PLTU"]["source"].startswith("Nasdaq")
        assert called == []          # no wasted downstream calls


# ── 3. one grouped request instead of a rate-limited per-ticker loop ─────────
class TestPolygonGrouped:
    @pytest.fixture(autouse=True)
    def isolated_cache(self, monkeypatch, tmp_path):
        monkeypatch.setattr(F, "POLYGON_PREV_CACHE_DIR", tmp_path)

    def _grouped(self, monkeypatch, by_date, status=200):
        seen = []

        def _get(url, **kw):
            date = url.rstrip("/").split("/")[-1]
            seen.append(date)
            if status != 200:
                return _FakeResp({"status": "ERROR", "error": "rate limit"}, status)
            return _FakeResp({"results": by_date.get(date, []), "status": "OK"})
        monkeypatch.setattr(F.SESSION, "get", _get)
        return seen

    def test_all_tickers_from_a_single_request(self, monkeypatch):
        seen = self._grouped(monkeypatch, {"2026-07-24": [
            {"T": "SPCX", "c": 115.07}, {"T": "PLTU", "c": 27.35},
            {"T": "MSFU", "c": 22.9}, {"T": "SKHY", "c": 154.57},
            {"T": "RKLX", "c": 16.32}, {"T": "CRCL", "c": 62.36},
            {"T": "NOISE", "c": 1.0},
        ]})
        out, limited, valid = F.get_prev_closes_polygon_grouped(
            ["SPCX", "PLTU", "MSFU", "SKHY", "RKLX", "CRCL"], "key", "2026-07-27")
        # Positions 6 and 7 (MSFU/SKHY) are exactly what the old 5/min loop lost.
        assert set(out) == {"SPCX", "PLTU", "MSFU", "SKHY", "RKLX", "CRCL"}
        assert out["MSFU"] == (22.9, "2026-07-24")
        assert out["SKHY"] == (154.57, "2026-07-24")
        assert len(seen) == 1                      # one call, not one per ticker
        assert limited is False
        assert valid is True

    def test_weekend_is_skipped_without_spending_a_request(self, monkeypatch):
        seen = self._grouped(monkeypatch, {"2026-07-24": [{"T": "SPCX", "c": 115.07}]})
        out, _, _ = F.get_prev_closes_polygon_grouped(["SPCX"], "key", "2026-07-27")
        assert out["SPCX"] == (115.07, "2026-07-24")
        assert "2026-07-25" not in seen and "2026-07-26" not in seen

    def test_empty_expected_session_is_not_replaced_by_an_older_bar(self, monkeypatch):
        seen = self._grouped(monkeypatch, {
            "2026-07-23": [{"T": "SPCX", "c": 120.0}],
            "2026-07-24": [],
        })
        out, _, valid = F.get_prev_closes_polygon_grouped(
            ["SPCX"], "key", "2026-07-27")
        assert out == {} and valid is False
        assert seen == ["2026-07-24"]

    def test_rate_limit_aborts_instead_of_burning_the_rest_of_the_quota(
            self, monkeypatch, tmp_path):
        # A 429 means "no budget left", not "this date has no data". Walking
        # further back would spend the remaining requests on certain failures
        # and starve the per-ticker fallback too.
        seen = self._grouped(monkeypatch, {}, status=429)
        out, limited, valid = F.get_prev_closes_polygon_grouped(
            ["SPCX"], "key", "2026-07-27")
        assert out == {} and limited is True and valid is False
        assert seen == ["2026-07-24"]              # exactly one attempt
        assert not (tmp_path / "2026-07-24.json").exists()

    def test_http_error_never_poison_the_cache(
            self, monkeypatch, tmp_path):
        seen = self._grouped(monkeypatch, {}, status=503)
        out, limited, valid = F.get_prev_closes_polygon_grouped(
            ["SPCX"], "key", "2026-07-27")

        assert out == {} and limited is False and valid is False
        assert seen == ["2026-07-24"]
        assert not (tmp_path / "2026-07-24.json").exists()

    def test_no_key_makes_no_request(self, monkeypatch):
        seen = self._grouped(monkeypatch, {})
        assert F.get_prev_closes_polygon_grouped(
            ["SPCX"], "", "2026-07-27") == ({}, False, False)
        assert seen == []

    def test_sequential_callers_download_once_and_emit_cache_metadata(
            self, monkeypatch, capsys):
        seen = self._grouped(
            monkeypatch, {"2026-07-24": [{"T": "SPCX", "c": 115.07}]})

        first = F.get_prev_closes_polygon_grouped(
            ["SPCX"], "key", "2026-07-27")
        second = F.get_prev_closes_polygon_grouped(
            ["SPCX"], "key", "2026-07-27")

        assert first[0] == second[0] == {"SPCX": (115.07, "2026-07-24")}
        assert seen == ["2026-07-24"]
        diagnostics = capsys.readouterr().out
        assert "cache_hit=false session=2026-07-24 source=Polygon grouped" in diagnostics
        assert "cache_hit=true session=2026-07-24 source=Polygon grouped" in diagnostics

    def test_concurrent_callers_cannot_stampede_polygon(self, monkeypatch):
        seen = self._grouped(
            monkeypatch, {"2026-07-24": [{"T": "SPCX", "c": 115.07}]})
        start = threading.Barrier(2)

        def fetch():
            start.wait()
            return F.get_prev_closes_polygon_grouped(
                ["SPCX"], "key", "2026-07-27")

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: fetch(), range(2)))

        assert [result[0] for result in results] == [
            {"SPCX": (115.07, "2026-07-24")},
            {"SPCX": (115.07, "2026-07-24")},
        ]
        assert seen == ["2026-07-24"]

    def test_session_rollover_downloads_exactly_one_new_snapshot(
            self, monkeypatch):
        seen = self._grouped(monkeypatch, {
            "2026-07-24": [{"T": "SPCX", "c": 115.07}],
            "2026-07-27": [{"T": "SPCX", "c": 116.50}],
        })
        F.get_prev_closes_polygon_grouped(["SPCX"], "key", "2026-07-27")
        monday, _, _ = F.get_prev_closes_polygon_grouped(
            ["SPCX"], "key", "2026-07-28")
        again, _, _ = F.get_prev_closes_polygon_grouped(
            ["SPCX"], "key", "2026-07-28")

        assert monday == again == {"SPCX": (116.50, "2026-07-27")}
        assert seen == ["2026-07-24", "2026-07-27"]

    def test_corrupt_cache_is_ignored_and_atomically_replaced(
            self, monkeypatch, tmp_path):
        (tmp_path / "2026-07-24.json").write_text("{partial")
        seen = self._grouped(
            monkeypatch, {"2026-07-24": [{"T": "SPCX", "c": 115.07}]})

        out, _, valid = F.get_prev_closes_polygon_grouped(
            ["SPCX"], "key", "2026-07-27")

        assert valid is True and out["SPCX"] == (115.07, "2026-07-24")
        assert seen == ["2026-07-24"]
        repaired = json.loads((tmp_path / "2026-07-24.json").read_text())
        assert repaired["session_date"] == "2026-07-24"

    def test_valid_snapshot_can_prove_a_symbol_is_genuinely_absent(
            self, monkeypatch):
        self._grouped(
            monkeypatch, {"2026-07-24": [{"T": "NOISE", "c": 1.0}]})

        out, limited, valid = F.get_prev_closes_polygon_grouped(
            ["SPCX"], "key", "2026-07-27")

        assert out == {} and limited is False and valid is True


def test_quote_and_prior_sessions_are_calendar_aware_before_tuesday_open():
    at = F.datetime(2026, 7, 28, 0, 15, tzinfo=ZoneInfo("America/New_York"))
    quote_session = F._us_quote_session_date(at)

    assert quote_session == "2026-07-27"
    assert F._prev_trading_day(quote_session) == "2026-07-24"


def test_tuesday_after_monday_holiday_resolves_real_sessions():
    before_open = F.datetime(
        2026, 9, 8, 0, 15, tzinfo=ZoneInfo("America/New_York"))
    after_open = F.datetime(
        2026, 9, 8, 10, 0, tzinfo=ZoneInfo("America/New_York"))

    assert F._us_quote_session_date(before_open) == "2026-09-04"
    assert F._prev_trading_day("2026-09-04") == "2026-09-03"
    assert F._us_quote_session_date(after_open) == "2026-09-08"
    assert F._prev_trading_day("2026-09-08") == "2026-09-04"


# ── 4 + 5. end-to-end: the PLTU shape through update_us_portfolio ────────────
def _portfolio(tmp_path, holding):
    p = tmp_path / "portfolio.json"
    p.write_text(json.dumps({
        "last_updated": "2026/07/27 10:00 HKT",
        "portfolios": {"us_stocks": {"currency": "USD", "holdings": [holding]}},
    }), encoding="utf-8")
    return str(p)


@pytest.fixture
def no_indices(monkeypatch):
    monkeypatch.setattr(F, "fetch_us_indices", lambda: {})


class TestStaleLastGuard:
    BASE = {"ticker": "PLTU", "shares": 14, "cost_basis": 40.9571,
            "trades": [{"date": "2026-04-16", "action": "buy", "shares": 14,
                        "price": 40.9571}]}

    def _run(self, monkeypatch, tmp_path, quote, prev_closes):
        monkeypatch.setattr(F, "fetch_us_quotes", lambda t, k: {"PLTU": quote})
        monkeypatch.setattr(F, "get_prev_closes_polygon_grouped",
                            lambda t, k, d, **kw: (prev_closes, False, True))
        monkeypatch.setattr(F, "get_prev_close_polygon", lambda t, k: None)
        monkeypatch.setattr(F, "load_api_keys", lambda: {"POLYGON_API_KEY": "key"})
        monkeypatch.setattr(F, "_us_quote_session_date", lambda at=None: "2026-07-27")
        path = _portfolio(tmp_path, dict(self.BASE))
        data = F.update_us_portfolio(portfolio_path=path, dry_run=True)
        return data["portfolios"]["us_stocks"]["holdings"][0]

    def test_frozen_last_is_rebuilt_from_netchange(self, monkeypatch, tmp_path,
                                                   no_indices):
        # Exactly 2026-07-27: Nasdaq served Friday's close as the last price
        # while its own netChange still described a +5.37% day.
        h = self._run(monkeypatch, tmp_path,
                      {"c": 27.35, "pc": None, "h": None, "l": None, "o": None,
                       "dp": 5.37, "nc": 1.47, "source": "Nasdaq API (etf)"},
                      {"PLTU": (27.35, _fresh_prev_bar_date())})
        assert h["current_price"] == 28.82          # was 27.35 -> "flat today"
        assert h["today_change_pct"] > 5.0          # was 0.0
        assert h["today_change"] != 0
        assert h["stale_price_repair"]["reported"] == 27.35
        assert h["stale_price_repair"]["basis"] == "netChange"

    def test_falls_back_to_percentage_change_without_netchange(
            self, monkeypatch, tmp_path, no_indices):
        h = self._run(monkeypatch, tmp_path,
                      {"c": 27.35, "pc": None, "h": None, "l": None, "o": None,
                       "dp": 5.37, "source": "Nasdaq API (etf)"},
                      {"PLTU": (27.35, _fresh_prev_bar_date())})
        assert h["current_price"] == pytest.approx(28.8187, abs=1e-3)
        assert h["stale_price_repair"]["basis"] == "percentageChange"

    def test_genuinely_flat_day_is_left_alone(self, monkeypatch, tmp_path,
                                              no_indices):
        # c == pc with the provider ALSO reporting ~0% is a real flat day, not a
        # stale print. Repairing it would invent movement that never happened.
        h = self._run(monkeypatch, tmp_path,
                      {"c": 27.35, "pc": 27.35, "h": 27.40, "l": 27.30,
                       "o": 27.35, "dp": 0.0, "source": "Finnhub"},
                      {"PLTU": (27.35, _fresh_prev_bar_date())})
        assert h["current_price"] == 27.35
        assert "stale_price_repair" not in h

    def test_healthy_quote_is_untouched(self, monkeypatch, tmp_path, no_indices):
        h = self._run(monkeypatch, tmp_path,
                      {"c": 29.25, "pc": 27.35, "h": 29.81, "l": 28.41,
                       "o": 28.515, "dp": 6.95, "source": "Finnhub"},
                      {"PLTU": (27.35, _fresh_prev_bar_date())})
        assert h["current_price"] == 29.25
        assert "stale_price_repair" not in h

    def test_reconstructed_prev_close_is_never_stamped_today(
            self, monkeypatch, tmp_path, no_indices):
        # No Polygon bar -> prev_close gets rebuilt from dp. It describes the
        # PRIOR session, so it must not carry today's date: that impossible
        # state is what disabled TODAY_LEG for MSFU/SKHY.
        h = self._run(monkeypatch, tmp_path,
                      {"c": 23.85, "pc": 22.9, "h": 24.28, "l": 23.64,
                       "o": 23.65, "dp": 4.15, "source": "Finnhub"},
                      {})
        assert h["prev_close"] == 22.9
        assert h["prev_close_date"] < h["day_session_date"]


# ── 2026-08-06 (#332): the guard above, pointed at a daily-bar provider ──────
# The 07-27 net above assumed the provider's %change and our prev_close share a
# baseline. Alpha Vantage's GLOBAL_QUOTE is a daily endpoint: mid-session it can
# serve YESTERDAY's whole bar, whose %change is measured against the close
# before it. Composing the two rebuilt PLTU to $70.7585 — a price that never
# traded — and every derived field agreed with it afterwards.
AV_PRIOR_SESSION_BAR = {   # verbatim, 2026-08-05 12:01 ET, PLTU
    "Global Quote": {
        "01. symbol": "PLTU", "02. open": "36.9800", "03. high": "45.7100",
        "04. low": "36.2650", "05. price": "44.8200", "06. volume": "12549412",
        "07. latest trading day": "2026-08-04",
        "08. previous close": "28.3900", "09. change": "16.4300",
        "10. change percent": "57.8725%",
    }
}


class TestDailyBarProviderIsNotComposed:
    def test_alpha_vantage_reports_the_session_its_bar_belongs_to(self, monkeypatch):
        monkeypatch.setattr(F.SESSION, "get",
                            lambda *a, **k: _FakeResp(AV_PRIOR_SESSION_BAR))
        q = F.get_alpha_vantage_quote("PLTU", "key")
        # Without this the quote carries no date, and _quote_is_fresh's "no
        # timestamp means current" contract lets an overnight bar win a ticker.
        assert q["asof_date"] == "2026-08-04"
        assert not F._quote_is_fresh(q, "2026-08-05")

    def test_prior_session_bar_is_never_rebuilt_into_a_price(
            self, monkeypatch, tmp_path, no_indices):
        # c == our prev_close and the provider shouts +57.87%, which is the
        # guard's exact trigger — but that 57.87% is measured against 28.39,
        # not against the 44.82 we hold. Refusing leaves today reading flat,
        # which preflight's STALE_PRICE gate reports; inventing $70.7585 was
        # silent and moved the whole US day-change from -265 to +7.
        h = TestStaleLastGuard()._run(
            monkeypatch, tmp_path,
            {"c": 44.82, "pc": 28.39, "h": 45.71, "l": 36.265, "o": 36.98,
             "dp": 57.8725, "asof_date": "2026-08-04",
             "source": "Alpha Vantage"},
            {"PLTU": (44.82, _fresh_prev_bar_date())})
        assert h["current_price"] == 44.82
        assert "stale_price_repair" not in h

    def test_known_old_print_keeps_its_price_but_not_its_range(
            self, monkeypatch, tmp_path, no_indices):
        # Step 8's last resort: every provider failed and we knowingly use an
        # earlier session's print. Its last price is still the best number we
        # have; its high/low belong to that session and must not seed today's
        # range (PLTU carried day_low 36.265 into a 42.61-46.76 day).
        h = TestStaleLastGuard()._run(
            monkeypatch, tmp_path,
            {"c": 27.35, "pc": None, "h": 29.9, "l": 26.1, "o": 26.4,
             "dp": 5.37, "nc": 1.47, "stale_asof": "2026-07-23",
             "incomplete": True, "source": "Nasdaq API (etf)"},
            {"PLTU": (27.35, _fresh_prev_bar_date())})
        assert h["current_price"] == 27.35        # not rebuilt to 28.82
        assert "stale_price_repair" not in h
        assert h["day_low"] != 26.1 and h["day_high"] != 29.9


# ── 2026-08-06 (#336): the same disease, one provider further down ──────────
# Polygon's `/prev` endpoint returns the PRIOR SESSION's daily bar. Step 7 was
# the only branch calling `_done` instead of `_offer`, so that bar skipped both
# the freshness and the completeness gate and was recorded as a healthy, flat,
# current quote — yesterday's close as today's price, yesterday's range as
# today's range.
POLYGON_PREV_BAR = {   # verbatim, PLTU, requested 2026-08-05 15:1x ET
    "ticker": "PLTU", "queryCount": 1, "resultsCount": 1, "adjusted": True,
    "results": [{"T": "PLTU", "v": 12746526.0, "vw": 41.7637, "o": 36.98,
                 "c": 44.82, "h": 45.71, "l": 36.265,
                 "t": 1785873600000, "n": 165741}],
    "status": "OK", "count": 1,
}


class TestPolygonPrevCloseStatesItsAge:
    def test_the_bar_reports_its_own_session_and_no_invented_prior_close(
            self, monkeypatch):
        monkeypatch.setattr(F.SESSION, "get",
                            lambda *a, **k: _FakeResp(POLYGON_PREV_BAR))
        q = F.get_polygon_quote("PLTU", "key")
        assert q["asof_date"] == "2026-08-04"
        assert not F._quote_is_fresh(q, "2026-08-05")
        # `vw` is the prior session's VWAP; it was never a prior close.
        assert q["pc"] is None
        assert q["c"] == 44.82

    def test_a_live_quote_beats_it_instead_of_being_skipped(self, monkeypatch):
        # Every other provider fails, but Finnhub answers: the prior-session bar
        # must not win, and previously it could not even be compared because
        # step 7 bypassed the race entirely.
        monkeypatch.setattr(F, "get_eastmoney_batch", lambda *a, **k: {})
        for name in ("get_nasdaq_quote", "get_yahoo_v8_quote",
                     "get_yfinance_quote", "get_alpha_vantage_quote"):
            monkeypatch.setattr(F, name, lambda *a, **k: None)
        monkeypatch.setattr(F, "get_finnhub_quote",
                            lambda t, k: {"c": 43.04, "pc": 44.82, "h": 46.76,
                                          "l": 42.61, "o": 43.78, "dp": -3.9714,
                                          "source": "Finnhub"})
        monkeypatch.setattr(F, "get_polygon_quote",
                            lambda t, k: {"c": 44.82, "pc": None, "h": 45.71,
                                          "l": 36.265, "o": 36.98, "dp": 0.0,
                                          "asof_date": "2026-08-04",
                                          "source": "Polygon (prev close)"})
        out = F.fetch_us_quotes(["PLTU"], {"FINNHUB_API_KEY": "x",
                                           "POLYGON_API_KEY": "k"})
        assert out["PLTU"]["source"] == "Finnhub"
        assert out["PLTU"]["c"] == 43.04

    def test_as_the_only_survivor_it_is_used_but_labelled(self, monkeypatch):
        monkeypatch.setattr(F, "get_eastmoney_batch", lambda *a, **k: {})
        for name in ("get_nasdaq_quote", "get_finnhub_quote",
                     "get_yahoo_v8_quote", "get_yfinance_quote",
                     "get_alpha_vantage_quote"):
            monkeypatch.setattr(F, name, lambda *a, **k: None)
        monkeypatch.setattr(F, "get_polygon_quote",
                            lambda t, k: {"c": 44.82, "pc": None, "h": 45.71,
                                          "l": 36.265, "o": 36.98, "dp": 0.0,
                                          "asof_date": "2026-08-04",
                                          "source": "Polygon (prev close)"})
        out = F.fetch_us_quotes(["PLTU"], {"POLYGON_API_KEY": "k"})
        # A price is still better than none — but it must say what it is, which
        # is what keeps yesterday's 36.265 out of today's range (#332's
        # accumulator rule keys off exactly this flag).
        assert out["PLTU"]["c"] == 44.82
        assert out["PLTU"]["stale_asof"] == "2026-08-04"
        assert out["PLTU"]["incomplete"] is True


# ── the gate that should have caught it ──────────────────────────────────────
def _mini_portfolio(holding):
    return {
        "portfolios": {
            "us_stocks": {
                "currency": "USD", "holdings": [holding],
                "total_cost": round(holding["shares"] * holding["cost_basis"], 2),
                "total_current_value": holding["current_value"],
                "total_pnl": round(holding["current_value"]
                                   - holding["shares"] * holding["cost_basis"], 2),
                "today_total_change": holding["today_change"],
            }
        }
    }


def _session_dates():
    """The two session dates STALE_PRICE needs, resolved at run time.

    The fixture used to hardcode the incident's own 2026-07-27/24 pair. That
    made the row genuinely stale one day later: STALENESS compares data_source
    against `_last_session()`, so from 2026-07-28 the arithmetic-gates test
    started failing on every branch for a reason that has nothing to do with the
    branch. A fixture that asserts a wall-clock-relative property has to compute
    it — see clawock-no-live-numbers-in-static-copy.
    """
    today = date.fromisoformat(pi._last_session("us"))
    prev = today - timedelta(days=1)
    while not tc.is_trading_day("us", prev):
        prev -= timedelta(days=1)
    return today, prev


_SESSION, _PREV_SESSION = _session_dates()


def _fresh_prev_bar_date():
    """The real prior session for the deterministic Monday quote fixture."""
    return "2026-07-24"


PLTU_STALE = {
    "ticker": "PLTU", "shares": 14, "cost_basis": 40.9571,
    "current_price": 27.35, "current_value": 382.9,
    "pnl_abs": round((27.35 - 40.9571) * 14, 2),
    "pnl_percent": -33.2229,
    "prev_close": 27.35, "prev_close_date": _PREV_SESSION.isoformat(),
    "day_session_date": _SESSION.isoformat(),
    "day_high": 28.82, "day_low": 27.35, "day_open": 28.82,
    "today_change": 0.0, "today_change_pct": 0.0,
    "data_source": f"Nasdaq API (etf) {_SESSION:%b %-d, %Y} 10:33 ET",
    "trades": [{"date": "2026-04-16", "action": "buy", "shares": 14,
                "price": 40.9571}],
}


class TestIntegrityGateCatchesStalePrice:
    def _findings(self, tmp_path, holding):
        p = tmp_path / "portfolio.json"
        p.write_text(json.dumps(_mini_portfolio(holding)), encoding="utf-8")
        return pi.check(p)["findings"]

    def test_stale_price_is_reported(self, tmp_path):
        codes = {f["code"] for f in self._findings(tmp_path, dict(PLTU_STALE))}
        assert "STALE_PRICE" in codes

    def test_arithmetic_gates_stay_green_on_the_same_row(self, tmp_path):
        # The point of the incident: everything else genuinely balances, which
        # is why the row sailed through. If TODAY_LEG had caught it we would not
        # have needed a new check.
        codes = {f["code"] for f in self._findings(tmp_path, dict(PLTU_STALE))}
        assert "TODAY_LEG" not in codes
        assert "STALENESS" not in codes

    def test_stale_price_is_warn_not_error(self, tmp_path):
        p = tmp_path / "portfolio.json"
        p.write_text(json.dumps(_mini_portfolio(dict(PLTU_STALE))), encoding="utf-8")
        rep = pi.check(p)
        stale = [f for f in rep["findings"] if f["code"] == "STALE_PRICE"]
        assert stale and all(f["level"] == "WARN" for f in stale)
        # Detection must never silence a report: publishing stays allowed.
        assert rep["ok"] is True

    def test_healthy_row_does_not_trip_it(self, tmp_path):
        good = dict(PLTU_STALE)
        good.update({"current_price": 29.25, "current_value": 409.5,
                     "pnl_abs": round((29.25 - 40.9571) * 14, 2),
                     "day_low": 28.41, "day_high": 29.81,
                     "today_change": round((29.25 - 27.35) * 14, 2),
                     "today_change_pct": 6.9469})
        codes = {f["code"] for f in self._findings(tmp_path, good)}
        assert "STALE_PRICE" not in codes

    def test_ipo_style_row_is_not_flagged(self, tmp_path):
        # prev_close_date == day_session_date means there is no real prior close
        # (fresh IPO / same-session re-entry). Not a stale print -> stay quiet.
        ipo = dict(PLTU_STALE)
        ipo["prev_close_date"] = ipo["day_session_date"]
        codes = {f["code"] for f in self._findings(tmp_path, ipo)}
        assert "STALE_PRICE" not in codes

    def test_repair_flag_surfaces_in_the_gate(self, tmp_path):
        repaired = dict(PLTU_STALE)
        repaired.update({
            "current_price": 28.82, "current_value": 403.48,
            "pnl_abs": round((28.82 - 40.9571) * 14, 2),
            "today_change": round((28.82 - 27.35) * 14, 2), "today_change_pct": 5.37,
            "stale_price_repair": {"reported": 27.35, "repaired": 28.82,
                                   "basis": "netChange", "source": "Nasdaq API (etf)",
                                   "at": "2026-07-27 10:33 ET"},
        })
        msgs = [f["msg"] for f in self._findings(tmp_path, repaired)
                if f["code"] == "STALE_PRICE"]
        assert msgs and "netChange" in msgs[0]

    def test_incomplete_quote_flag_surfaces(self, tmp_path):
        incomplete = dict(PLTU_STALE)
        incomplete.update({
            "current_price": 28.82, "current_value": 403.48,
            "pnl_abs": round((28.82 - 40.9571) * 14, 2),
            "today_change": round((28.82 - 27.35) * 14, 2), "today_change_pct": 5.37,
            "quote_incomplete": True,
        })
        codes = {f["code"] for f in self._findings(tmp_path, incomplete)}
        assert "STALE_PRICE" in codes
