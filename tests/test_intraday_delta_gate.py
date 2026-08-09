import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
from clawock_kcnyu.automation import cron_heartbeat  # noqa: E402
from clawock_kcnyu.harness import intraday_delta as gate  # noqa: E402


def _portfolio(path):
    path.write_text(json.dumps({
        "portfolios": {
            "us_stocks": {"holdings": [
                {"ticker": "LOSS", "shares": 1, "cost_basis": 100},
                {"ticker": "OK", "shares": 1, "cost_basis": 100},
            ]},
            "hk_stocks": {"holdings": []},
        }
    }))


def test_normalized_breaches_change_only_at_material_buckets():
    holdings = [
        {"ticker": "LOSS", "cost_basis": 100},
        {"ticker": "MOVE", "cost_basis": 100},
    ]
    rows = gate.normalized_breaches(holdings, {
        "LOSS": {"price": 81.5, "pct_1d": -2.9},
        "MOVE": {"price": 100, "pct_1d": 5.1},
    })

    assert rows == [
        {"ticker": "LOSS", "kind": "pnl", "level": "hard_stop"},
        {
            "ticker": "MOVE", "kind": "move", "level": "high",
            "direction": "up",
        },
    ]


def test_snapshot_has_prices_condition_hash_and_exact_slot(monkeypatch, tmp_path):
    _portfolio(tmp_path / "portfolio.json")
    monkeypatch.setattr(gate, "WS", tmp_path)
    monkeypatch.setattr(gate, "PORTFOLIO", tmp_path / "portfolio.json")
    at = datetime(2026, 7, 24, 22, 34, tzinfo=ZoneInfo("Asia/Hong_Kong"))

    snap = gate.snapshot(
        "us",
        at=at,
        fetcher=lambda _requests, **_kwargs: {
            "LOSS": {"price": 81, "pct_1d": -4},
            "OK": {"price": 101, "pct_1d": 1},
        },
    )

    assert snap["slot"] == "2026-07-24T22:30:00+08:00"
    assert snap["quote_coverage"] == {"priced": 2, "active": 2}
    assert snap["error"] is None
    assert len(snap["condition_hash"]) == 64
    assert any(
        row["ticker"] == "LOSS" and row["level"] == "hard_stop"
        for row in snap["conditions"]["breaches"]
    )


def test_no_change_heartbeat_is_terminal(monkeypatch, tmp_path):
    monkeypatch.setattr(cron_heartbeat, "LOCAL_PATH", tmp_path / "local.json")
    monkeypatch.setattr(cron_heartbeat, "PUBLIC_PATH", tmp_path / "public.json")
    event = gate.record_gate(
        "hk", "no_change", "2026-07-24T10:30:00+08:00",
        "unchanged", "abc",
    )

    assert event["state"] == "no_change"
    assert event["reasoning_invoked"] is False
    assert event["should_alert"] is False


def test_the_gate_is_no_longer_wired_in_front_of_the_cron():
    """Kept as a read-only diagnostic, removed as a pre-model gate (2026-07-27).

    `clawock-kcnyu-intraday-delta --market hk` still prints the
    current breach/price state, which is useful by hand. What is gone is its
    power to suppress a slot: no tracked trigger sources, and no job pinned to
    them. If this ever comes back, it comes back through the contract, not by
    someone editing a live cron.
    """
    assert not (ROOT / "config" / "cron-triggers").exists()
    contract = json.loads((ROOT / "config" / "cron-schedules.json").read_text())
    assert "trigger" not in contract["payload_profiles"]["intraday"]
