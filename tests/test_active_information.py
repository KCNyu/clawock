"""High-cost invariants for the information-first intraday lane."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from clawock.decision import active_information as ai
from clawock.market_data import primary_disclosures
from clawock.portfolio import instruments
from clawock.harness import intraday_preflight


NOW = datetime(2026, 8, 13, 6, 0, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]
REGISTRY = instruments.load_registry(ROOT / "config" / "instruments.json")


def portfolio(hk=None, us=None):
    return {
        "portfolios": {
            "hk_stocks": {"holdings": hk or []},
            "us_stocks": {"holdings": us or []},
        }
    }


def probe_with(item, status="found"):
    def probe(issuers, **_kwargs):
        return {
            "issuers": {
                issuer: {"status": status, "events": [dict(item)] if item else []}
                for issuer in issuers
            }
        }
    return probe


POSITIVE = {
    "published_at": "2026-08-13T05:45:00+00:00",
    "title": "正面盈利预告及股份回购计划",
    "source_url": "https://example.test/announcement",
    "source_class": "exchange_filing",
    "evidence_tier": "primary",
}


def test_positive_primary_event_becomes_one_board_lot_candidate_before_a_large_move(monkeypatch):
    book = portfolio(hk=[
        {"ticker": "00100", "shares": 120, "lot_size": 20},
    ])

    result = ai.scan(
        book, market="hk", now=NOW, registry=REGISTRY,
        disclosure_probe=probe_with(POSITIVE), quote_fetcher=lambda *_args, **_kwargs: {
            "00100": {"price": 400, "pct_1d": 0.8, "source": "tencent"}
        },
    )

    row = result["candidates"][0]
    assert row["disposition"] == "candidate"
    assert row["session_reaction_pct"] == 0.8
    assert row["exploration_hint"] == {
        "ticker": "00100", "shares": 20, "unit": "one_board_lot",
        "status": "unvalidated_exploration_hint", "is_order": False,
        "requires": ["independent_support", "cash_gate", "risk_gate", "execution_review"],
    }


def test_proxy_and_underlying_are_one_issuer_and_hot_tape_is_wait(monkeypatch):
    us_item = {
        **POSITIVE,
        "title": "Raised guidance after record revenue",
        "raw_title": "Raised guidance after record revenue",
        "source_class": "sec_filing",
        "accession": "0001-26-000001",
    }
    book = portfolio(us=[
        {"ticker": "SPCX", "shares": 1},
        {"ticker": "SPCH", "shares": 240},
    ])

    result = ai.scan(
        book, market="us", now=NOW, registry=REGISTRY,
        disclosure_probe=probe_with(us_item), quote_fetcher=lambda *_args, **_kwargs: {
            "SPCX": {"price": 150, "pct_1d": 5.2, "source": "tencent"}
        },
    )

    assert [row["issuer"] for row in result["scope"]] == ["SPCX"]
    row = result["candidates"][0]
    assert row["held_via"] == ["SPCH", "SPCX"]
    assert row["disposition"] == "wait"
    assert "price_already_reacted" in row["blockers"]
    assert row["exploration_hint"] is None


def test_supporting_item_cannot_create_a_candidate(monkeypatch):
    supporting = {
        **POSITIVE,
        "evidence_tier": "supporting",
        "source_class": "broker_or_media",
    }
    result = ai.scan(
        portfolio(us=[{"ticker": "CRCL", "shares": 2}]),
        market="us", now=NOW, registry=REGISTRY,
        disclosure_probe=probe_with(supporting),
        quote_fetcher=lambda *_args, **_kwargs: {
            "CRCL": {"price": 75, "pct_1d": 0.2, "source": "tencent"}
        },
    )

    assert result["candidates"] == []
    assert result["candidate_count"] == 0


def test_primary_candidate_wakes_the_intraday_alert_without_a_price_anomaly():
    alert, reasons = intraday_preflight.apply_active_information_alert(
        False, [], {"candidates": [{"issuer": "00100"}]},
    )

    assert alert is True
    assert reasons == ["主动一级信息: 00100"]


def test_changed_primary_rows_expand_while_existing_rows_stay_compact():
    active = {
        "candidates": [
            {"event_id": "old", "issuer": "RKLB", "disposition": "wait",
             "category": "results", "direction": "unknown", "detail": "8-K"},
            {"event_id": "new", "issuer": "CRCL", "disposition": "candidate",
             "category": "profit_revision", "direction": "positive",
             "detail": "raised guidance"},
        ],
    }

    text = intraday_preflight.append_active_information_section(
        "BLOCK", active, event_ids={"new"},
    )

    assert "CRCL" in text
    assert "raised guidance" in text
    assert "RKLB[等待]" in text
    assert "详因沿用，不重复展开" in text
    assert "8-K" not in text


def test_provider_cache_is_short_lived_and_carries_provenance(tmp_path):
    calls = []

    def http(url, **_kwargs):
        calls.append(url)
        return {"data": {"data": []}}

    cache = tmp_path / "primary.json"
    first = primary_disclosures.probe_cached(
        ["00100"], market="hk", now=NOW, window_minutes=240,
        budget_s=20, max_issuers=1, cache_path=cache, cache_ttl_seconds=300,
        http=http,
    )
    second = primary_disclosures.probe_cached(
        ["00100"], market="hk", now=NOW + timedelta(minutes=2),
        window_minutes=240, budget_s=20, max_issuers=1,
        cache_path=cache, cache_ttl_seconds=300, http=http,
    )
    third = primary_disclosures.probe_cached(
        ["00100"], market="hk", now=NOW + timedelta(minutes=6),
        window_minutes=240, budget_s=20, max_issuers=1,
        cache_path=cache, cache_ttl_seconds=300, http=http,
    )

    assert len(calls) == 2
    assert first["collection"]["cache_hit"] is False
    assert second["collection"] == {
        "cache_hit": True,
        "fetched_at": NOW.isoformat(),
        "age_seconds": 120,
        "ttl_seconds": 300,
    }
    assert third["collection"]["cache_hit"] is False


def test_provider_cache_separates_result_affecting_budget(tmp_path):
    calls = []

    def http(url, **_kwargs):
        calls.append(url)
        return {"data": {"data": []}}

    cache = tmp_path / "primary.json"
    common = dict(
        issuers=["00100"], market="hk", now=NOW, window_minutes=240,
        max_issuers=1, cache_path=cache, cache_ttl_seconds=300, http=http,
    )
    primary_disclosures.probe_cached(budget_s=20, **common)
    second = primary_disclosures.probe_cached(budget_s=10, **common)

    assert len(calls) == 2
    assert second["collection"]["cache_hit"] is False


def test_sec_403_falls_back_to_healthy_nasdaq_primary_mirror(monkeypatch):
    monkeypatch.setattr(
        "clawock.market_data.filings.lookup_cik", lambda _ticker: "CIK0001876042"
    )

    def http(url, **_kwargs):
        host = urlsplit(url).hostname
        if host == "data.sec.gov":
            raise RuntimeError("SEC 403")
        if host == "api.nasdaq.com":
            return {"data": {"rows": [{
                "companyName": "Circle Internet Group Inc.",
                "formType": "8-K", "filed": "08/13/2026",
                "view": {"htmlLink": "https://mirror.test/crcl-8k"},
            }]}}
        if host == "finnhub.io":
            return []
        raise AssertionError(url)

    result = primary_disclosures.probe(
        ["CRCL"], market="us", now=NOW, window_minutes=240,
        budget_s=20, max_issuers=1, http=http, finnhub_key="test-key",
    )["issuers"]["CRCL"]

    assert result["status"] == "found"
    assert result["partial_degradation"] is True
    assert result["degraded_sources"] == ["sec"]
    assert result["healthy_sources"] == ["finnhub", "nasdaq_filing_mirror"]
    assert result["events"][0]["source_class"] == "sec_filing_mirror"
    # Finnhub had nothing for this filing, so the blocker honestly survives.
    assert result["events"][0]["time_precision"] == "date"


def test_date_only_primary_mirror_event_waits_instead_of_unlocking_exploration():
    mirror_item = {
        **POSITIVE,
        "published_at": None,
        "filed_date": "2026-08-13",
        "observed_at": NOW.isoformat(),
        "time_precision": "date",
        "freshness_status": "same_session_date_time_unavailable",
        "title": "8-K Raised guidance after record revenue",
        "source_class": "sec_filing_mirror",
    }
    result = ai.scan(
        portfolio(us=[{"ticker": "CRCL", "shares": 2}]),
        market="us", now=NOW, registry=REGISTRY,
        disclosure_probe=probe_with(mirror_item), quote_fetcher=lambda *_args, **_kwargs: {
            "CRCL": {"price": 75, "pct_1d": 0.2, "source": "tencent"}
        },
    )

    row = result["candidates"][0]
    assert row["disposition"] == "wait"
    assert row["exploration_hint"] is None
    assert "filing_time_unavailable" in row["blockers"]


# ── #766: a third primary source, and honest attribution of SEC's refusal ────

def test_finnhub_accepted_time_is_read_as_us_market_time_not_utc():
    """Measured 2026-08-19: SEC says 11:10:48Z, Finnhub says 07:10:48 — EDT.

    Reading it as UTC would place every US filing 4-5 hours off. For a
    30-minute intraday window that is the whole difference between "inside this
    window" and "not", so the timezone is load-bearing, not cosmetic.
    """
    now = datetime(2026, 8, 13, 11, 30, tzinfo=timezone.utc)

    def http(url, **_kwargs):
        assert urlsplit(url).hostname == "finnhub.io"
        return [{"form": "8-K", "filedDate": "2026-08-13 00:00:00",
                 "acceptedDate": "2026-08-13 07:10:48",
                 "reportUrl": "https://sec.test/rklb-8k", "symbol": "RKLB"}]

    items, note = primary_disclosures.fetch_finnhub_filings(
        "RKLB", now=now, window_minutes=60, http=http, api_key="test-key",
    )
    assert note is None
    assert items[0]["published_at"] == "2026-08-13T11:10:48+00:00"
    assert items[0]["age_minutes"] == 19
    assert items[0]["time_precision"] == "datetime"


def test_finnhub_midnight_placeholder_is_not_treated_as_a_timestamp():
    """`acceptedDate` at exactly midnight is Finnhub's date-only placeholder."""
    def http(_url, **_kwargs):
        return [{"form": "6-K", "filedDate": "2026-08-13 00:00:00",
                 "acceptedDate": "2026-08-13 00:00:00"}]

    items, _ = primary_disclosures.fetch_finnhub_filings(
        "SKHY", now=NOW, window_minutes=1440, http=http, api_key="test-key",
    )
    assert items == []


def test_finnhub_without_a_key_is_degraded_not_healthy():
    def http(url, **_kwargs):
        host = urlsplit(url).hostname
        if host == "data.sec.gov":
            raise RuntimeError("SEC unreachable")
        if host == "api.nasdaq.com":
            return {"data": {"rows": []}}
        raise AssertionError(url)

    result = primary_disclosures.probe(
        ["CRCL"], market="us", now=NOW, window_minutes=240,
        budget_s=20, max_issuers=1, http=http, finnhub_key="",
    )["issuers"]["CRCL"]
    assert "finnhub" in result["degraded_sources"]
    assert "finnhub" not in result["healthy_sources"]


def _mirror_and_finnhub_http(finnhub_rows, *, filed="08/13/2026"):
    def http(url, **_kwargs):
        host = urlsplit(url).hostname
        if host == "data.sec.gov":
            raise RuntimeError("SEC unreachable")
        if host == "api.nasdaq.com":
            return {"data": {"rows": [{
                "companyName": "Circle Internet Group Inc.",
                "formType": "8-K", "filed": filed,
                "view": {"htmlLink": "https://mirror.test/crcl-8k"},
            }]}}
        if host == "finnhub.io":
            return finnhub_rows
        raise AssertionError(url)
    return http


def test_a_timestamped_match_clears_the_date_only_blocker():
    """The mirror sees the filing first; Finnhub supplies the time it lacks."""
    http = _mirror_and_finnhub_http([
        {"form": "8-K", "filedDate": "2026-08-13 00:00:00",
         "acceptedDate": "2026-08-13 01:30:00", "symbol": "CRCL"},
    ])
    event = primary_disclosures.probe(
        ["CRCL"], market="us", now=NOW, window_minutes=240,
        budget_s=20, max_issuers=1, http=http, finnhub_key="test-key",
    )["issuers"]["CRCL"]["events"][0]

    assert event["source_class"] == "sec_filing_mirror"
    assert event["time_precision"] == "datetime"
    assert event["published_at"] == "2026-08-13T05:30:00+00:00"
    assert event["precision_source"] == "finnhub_filing"
    # ai turns the date-only precision into the blocker, so clearing it here is
    # what actually reopens the candidate leg.
    assert event["freshness_status"] != "same_session_date_time_unavailable"


def test_two_matching_filings_refuse_to_guess_and_keep_the_blocker():
    """SKHY filed three 6-Ks on 2026-08-19: (form, date) is not an identity.

    Adopting either timestamp would be a coin flip presented as evidence.
    """
    http = _mirror_and_finnhub_http([
        {"form": "8-K", "filedDate": "2026-08-13 00:00:00",
         "acceptedDate": "2026-08-13 01:30:00", "symbol": "CRCL"},
        {"form": "8-K", "filedDate": "2026-08-13 00:00:00",
         "acceptedDate": "2026-08-13 00:45:00", "symbol": "CRCL"},
    ])
    entry = primary_disclosures.probe(
        ["CRCL"], market="us", now=NOW, window_minutes=240,
        budget_s=20, max_issuers=1, http=http, finnhub_key="test-key",
    )["issuers"]["CRCL"]

    mirror = [e for e in entry["events"] if e["source_class"] == "sec_filing_mirror"]
    assert mirror[0]["time_precision"] == "date"
    assert any("refusing to guess" in note for note in entry["notes"])


def test_a_recovered_time_outside_the_window_drops_the_mirror_row():
    """The mirror kept it only because it could not tell. Now it can."""
    http = _mirror_and_finnhub_http([
        {"form": "8-K", "filedDate": "2026-08-13 00:00:00",
         "acceptedDate": "2026-08-12 20:00:00", "symbol": "CRCL"},
    ])
    entry = primary_disclosures.probe(
        ["CRCL"], market="us", now=NOW, window_minutes=60,
        budget_s=20, max_issuers=1, http=http, finnhub_key="test-key",
    )["issuers"]["CRCL"]

    assert [e for e in entry["events"] if e["source_class"] == "sec_filing_mirror"] == []
    assert any("outside the 60min window" in note for note in entry["notes"])


def test_a_refused_default_user_agent_is_named_as_configuration(monkeypatch):
    """Not "SEC is flaky" — a 403 on the unconfigured UA never self-heals."""
    from urllib.error import HTTPError

    monkeypatch.setattr(
        "clawock.market_data.filings.lookup_cik", lambda _t: "CIK0001876042"
    )
    monkeypatch.setattr(
        "clawock.market_data.filings.sec_user_agent_configured", lambda: False
    )

    def http(url, **_kwargs):
        host = urlsplit(url).hostname
        if host == "data.sec.gov":
            raise HTTPError(url, 403, "Forbidden", {}, None)
        if host == "api.nasdaq.com":
            return {"data": {"rows": []}}
        if host == "finnhub.io":
            return []
        raise AssertionError(url)

    entry = primary_disclosures.probe(
        ["CRCL"], market="us", now=NOW, window_minutes=240,
        budget_s=20, max_issuers=1, http=http, finnhub_key="test-key",
    )["issuers"]["CRCL"]

    assert "sec" in entry["degraded_sources"]
    assert any("sec_user_agent_unconfigured" in note for note in entry["notes"])
    assert any("SEC_USER_AGENT" in note for note in entry["notes"])


def test_a_403_with_a_configured_user_agent_is_still_reported_as_an_outage(
    monkeypatch
):
    """Don't blame configuration for something configuration already satisfied."""
    from urllib.error import HTTPError

    monkeypatch.setattr(
        "clawock.market_data.filings.lookup_cik", lambda _t: "CIK0001876042"
    )
    monkeypatch.setattr(
        "clawock.market_data.filings.sec_user_agent_configured", lambda: True
    )

    def http(url, **_kwargs):
        host = urlsplit(url).hostname
        if host == "data.sec.gov":
            raise HTTPError(url, 403, "Forbidden", {}, None)
        if host == "api.nasdaq.com":
            return {"data": {"rows": []}}
        if host == "finnhub.io":
            return []
        raise AssertionError(url)

    entry = primary_disclosures.probe(
        ["CRCL"], market="us", now=NOW, window_minutes=240,
        budget_s=20, max_issuers=1, http=http, finnhub_key="test-key",
    )["issuers"]["CRCL"]

    assert "sec" in entry["degraded_sources"]
    assert not any("sec_user_agent_unconfigured" in n for n in entry["notes"])
    assert any("HTTPError" in note for note in entry["notes"])
