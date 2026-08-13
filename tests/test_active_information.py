"""High-cost invariants for the information-first intraday lane."""
from datetime import datetime, timezone

from clawock_kcnyu import active_information as ai
from clawock_kcnyu.harness import intraday_preflight


NOW = datetime(2026, 8, 13, 6, 0, tzinfo=timezone.utc)


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
            "tickers": {
                issuer: {"status": status, "items": [dict(item)] if item else []}
                for issuer in issuers
            }
        }
    return probe


POSITIVE = {
    "published_at": "2026-08-13T05:45:00+00:00",
    "title": "正面盈利预告及股份回购计划",
    "raw_title": "正面盈利预告及股份回购计划",
    "tier": "primary",
    "source_class": "exchange_filing",
    "signal": "interrupt",
    "triage_rule": "hk-profit-alert",
    "url": "https://example.test/announcement",
}


def test_positive_primary_event_becomes_one_board_lot_candidate_before_a_large_move(monkeypatch):
    monkeypatch.setattr(ai.mover_evidence, "probe", probe_with(POSITIVE))
    book = portfolio(hk=[
        {"ticker": "00100", "shares": 120, "lot_size": 20},
    ])

    result = ai.scan(
        book, market="hk", now=NOW,
        quote_fetcher=lambda *_args, **_kwargs: {
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
        "triage_rule": "us-8k",
        "accession": "0001-26-000001",
    }
    monkeypatch.setattr(ai.mover_evidence, "probe", probe_with(us_item))
    book = portfolio(us=[
        {"ticker": "SPCX", "shares": 1},
        {"ticker": "SPCH", "shares": 240},
    ])

    result = ai.scan(
        book, market="us", now=NOW,
        quote_fetcher=lambda *_args, **_kwargs: {
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
        "tier": "supporting",
        "source_class": "broker_or_media",
    }
    monkeypatch.setattr(ai.mover_evidence, "probe", probe_with(supporting))

    result = ai.scan(
        portfolio(us=[{"ticker": "CRCL", "shares": 2}]),
        market="us", now=NOW,
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
