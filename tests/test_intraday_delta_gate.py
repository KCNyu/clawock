import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "data"))

import cron_heartbeat  # noqa: E402
import intraday_delta_gate as gate  # noqa: E402


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


def test_trigger_scripts_fail_open_and_force_low_frequency_review():
    for market in ("hk", "us"):
        script = (
            ROOT / "config" / "cron-triggers" / f"intraday-{market}.js"
        ).read_text()
        assert "fire: true" in script
        assert "evaluations >= 6" in script
        assert ">= 0.01" in script
        assert ">= 1.0" in script
        assert "--record ${state}" in script
