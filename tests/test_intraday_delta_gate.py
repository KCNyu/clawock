import json
import sys
import copy
import io
import subprocess
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
from clawock.automation import cron_heartbeat  # noqa: E402
from clawock.harness import intraday_delta as gate  # noqa: E402
from clawock.harness import intraday_preflight as preflight  # noqa: E402


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

    `clawock-intraday-delta --market hk` still prints the
    current breach/price state, which is useful by hand. What is gone is its
    power to suppress a slot: no tracked trigger sources, and no job pinned to
    them. If this ever comes back, it comes back through the contract, not by
    someone editing a live cron.
    """
    assert not (ROOT / "config" / "cron-triggers").exists()
    contract = json.loads((ROOT / "config" / "cron-schedules.json").read_text())
    assert "trigger" not in contract["payload_profiles"]["intraday"]


def test_semantic_delta_ignores_small_quote_churn_but_sees_real_state_changes():
    previous = {
        "session": "us:2026-08-13",
        "breaches": [{"ticker": "SPCH", "kind": "move", "level": "high",
                      "direction": "down"}],
        "setups": [], "plans": [], "primary_events": {},
        "primary_source_health": {"degraded": ["RKLB"], "partial": []},
    }
    current = json.loads(json.dumps(previous))

    quiet = gate.compare_semantic_states(current, previous)
    assert quiet["changed"] is False

    current["primary_events"]["filing-1"] = {
        "issuer": "RKLB", "disposition": "reject", "blockers": ["adverse"]
    }
    changed = gate.compare_semantic_states(current, previous)
    assert changed["changed"] is True
    assert changed["changed_event_ids"] == ["filing-1"]
    assert "primary_events" in changed["components"]


def test_delivery_state_advances_only_when_postflight_persists_it(tmp_path):
    ctx = {
        "market": "hk", "semantic_state": {"session": "hk:2026-08-14"},
        "heartbeat": {"slot": "2026-08-14T10:00:00+08:00"},
    }
    path = gate.delivered_state_path(tmp_path, "hk")

    assert gate.load_delivered_state(tmp_path, "hk") == {}
    gate.persist_delivered_state(tmp_path, ctx)

    assert path.exists()
    assert gate.load_delivered_state(tmp_path, "hk")["state"] == ctx["semantic_state"]


def test_material_move_buckets_ignore_churn_but_surface_real_repricing():
    def state(move):
        return gate.semantic_state(
            "us", "2026-08-13", signals_detail=[],
            anomalies=[{"ticker": "SPCH", "move_pct": move}], setups={},
            plans={}, active_information={},
        )

    assert gate.compare_semantic_states(state(18.8), state(18.5))["changed"] is False
    assert gate.compare_semantic_states(state(8.1), state(7.8))["changed"] is True
    assert gate.compare_semantic_states(state(23.3), state(11.6))["changed"] is True


def test_us_session_does_not_reset_at_hong_kong_midnight():
    before = datetime(2026, 8, 13, 23, 30, tzinfo=ZoneInfo("Asia/Hong_Kong"))
    after = datetime(2026, 8, 14, 0, 30, tzinfo=ZoneInfo("Asia/Hong_Kong"))

    assert gate.market_session_date("us", before) == "2026-08-13"
    assert gate.market_session_date("us", after) == "2026-08-13"
    assert gate.market_session_date("hk", after) == "2026-08-14"


def test_naive_session_time_is_explicitly_interpreted_as_hong_kong():
    naive = datetime(2026, 8, 14, 0, 30)

    assert gate.market_session_date("us", naive) == "2026-08-13"
    assert gate.market_session_date("hk", naive) == "2026-08-14"


def _wire_preflight(monkeypatch, tmp_path):
    """Run the real main while replacing unrelated network/analysis producers."""
    now = datetime(2026, 8, 14, 1, 33, tzinfo=ZoneInfo("Asia/Hong_Kong"))
    signals = [{"ticker": "SPCH", "level": "STOP", "line": "STOP SPCH"}]
    setups = {"rows": [{
        "label": "SPCH", "setup_id": "confirmed_breakout",
        "holdings": ["SPCH"], "entry_price": 7.2,
        "invalidation_price": 6.8,
    }]}
    active = {
        "collection": {"cache_hit": False},
        "candidates": [{
            "event_id": "filing-1", "issuer": "CRCL",
            "disposition": "wait", "category": "results",
            "direction": "unknown", "detail": "8-K awaiting detail",
        }],
        "degraded_issuers": ["BAD"],
        "partially_degraded_issuers": ["CRCL"],
    }
    block = "🇺🇸 美股盯盘 | 08/13 13:33 ET\n| SPCH | 10 | 6 | 7 | +1% | +2% | +3 |"

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz else now.replace(tzinfo=None)

    monkeypatch.setattr(preflight, "WS", tmp_path)
    monkeypatch.setattr(preflight, "TMP", tmp_path / "memory" / ".tmp")
    monkeypatch.setattr(preflight, "datetime", FixedDateTime)
    monkeypatch.setattr(preflight.trading_calendar, "closed_reason", lambda *_a: None)
    monkeypatch.setattr(
        preflight.cron_heartbeat, "record",
        lambda *_a, **_k: {"job": "US intraday", "slot": now.isoformat()},
    )
    monkeypatch.setattr(preflight, "run_analyze", lambda _m: (0, block, ""))
    monkeypatch.setattr(preflight, "parse_signals", lambda _s: (
        {"alert": 0, "watch": 0, "stop": 1, "trim": 0}, signals,
    ))
    monkeypatch.setattr(preflight, "parse_anomalies", lambda _s: [])
    monkeypatch.setattr(
        preflight.subprocess, "run",
        lambda *_a, **_k: subprocess.CompletedProcess([], 0),
    )
    monkeypatch.setattr(preflight.active_information, "scan_workspace", lambda *_a, **_k: active)
    monkeypatch.setattr(preflight.research_surface, "movers_thesis_context", lambda *_a: {})
    monkeypatch.setattr(preflight.mover_news, "probe", lambda *_a, **_k: {})
    monkeypatch.setattr(
        preflight.plan_surface, "open_decisions_context", lambda **_k: {"open": []},
    )
    monkeypatch.setattr(preflight.known_catalysts, "for_movers", lambda *_a, **_k: {})
    monkeypatch.setattr(preflight, "collect_provisional_setups", lambda _m: setups)
    monkeypatch.setattr(
        preflight, "collect_early_trend_candidates", lambda _m: {"rows": []})
    # #611: the radar and reinvest collectors run the real universe + Tencent
    # fetches when left unpatched, so the suite depended on the live market
    # (radar empty today, full_delta tomorrow) and the network. Both are pure
    # producers here: empty radar rows, identity pass-through for the plan ctx.
    monkeypatch.setattr(
        preflight, "collect_opportunity_radar", lambda _m: {"rows": []})
    monkeypatch.setattr(
        preflight, "attach_reinvest_candidates",
        lambda ctx, radar, signals_detail=None: ctx)
    monkeypatch.setattr(preflight, "quote_coverage", lambda *_a, **_k: {
        "refreshed": 1, "active": 1, "unrefreshed": [],
    })
    monkeypatch.setattr(preflight, "collect_peers", lambda _m: {})
    current = gate.semantic_state(
        "us", "2026-08-13", signals_detail=signals, anomalies=[],
        setups=setups, plans={"open": []}, active_information=active,
    )

    def run(previous):
        path = gate.delivered_state_path(tmp_path, "us")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"state": previous}))
        with redirect_stdout(io.StringIO()):
            assert preflight.main(["--market", "us"]) == 0
        return json.loads((preflight.TMP / "intraday-context-us-latest.json").read_text())

    return current, run


def test_preflight_main_selects_receipt_for_equal_delivered_state(
    monkeypatch, tmp_path
):
    current, run = _wire_preflight(monkeypatch, tmp_path)

    ctx = run(current)

    assert ctx["delivery_mode"] == "unchanged_receipt"
    assert "本轮无新的加仓/减仓条件" in ctx["raw_wechat_block"]
    assert "一级源降级：BAD" in ctx["raw_wechat_block"]


def test_preflight_main_selects_full_delta_and_preserves_primary_context(
    monkeypatch, tmp_path
):
    current, run = _wire_preflight(monkeypatch, tmp_path)
    previous = copy.deepcopy(current)
    previous["setups"] = []

    ctx = run(previous)

    assert ctx["delivery_mode"] == "full_delta"
    assert ctx["semantic_delta"]["components"] == ["setups"]
    assert "CRCL[等待]" in ctx["raw_wechat_block"]
    assert "8-K awaiting detail" not in ctx["raw_wechat_block"]
    assert "一级源降级：BAD" in ctx["raw_wechat_block"]
    assert "镜像已检查：CRCL" in ctx["raw_wechat_block"]


def test_preflight_main_expands_a_changed_primary_event(monkeypatch, tmp_path):
    current, run = _wire_preflight(monkeypatch, tmp_path)
    previous = copy.deepcopy(current)
    previous["primary_events"] = {}

    ctx = run(previous)

    assert ctx["delivery_mode"] == "full_delta"
    assert ctx["semantic_delta"]["changed_event_ids"] == ["filing-1"]
    assert "8-K awaiting detail" in ctx["raw_wechat_block"]


def test_preflight_main_selects_full_delta_for_risk_change(monkeypatch, tmp_path):
    current, run = _wire_preflight(monkeypatch, tmp_path)
    previous = copy.deepcopy(current)
    previous["breaches"] = []

    ctx = run(previous)

    assert ctx["delivery_mode"] == "full_delta"
    assert ctx["semantic_delta"]["components"] == ["breaches"]


def test_setup_sub_state_churn_is_not_a_delta():
    """#610: opportunity/early_trend sub-states flip on raw quote churn around
    a threshold (close vs prior, zscore20 vs 2.0). The gate compares the lane
    identity, not the churny sub-state; row appearance/disappearance still
    counts, and non-lane setup ids keep their full identity."""
    base = dict(market="hk", session_date="2026-08-14",
                signals_detail=[], anomalies=[], plans={"open": []},
                active_information={})
    row = {"label": "00100", "holdings": ["00100"]}

    s_breakout = gate.semantic_state(
        **base, setups={"rows": [{**row, "setup_id": "opportunity:breakout"}]})
    s_wait = gate.semantic_state(
        **base, setups={"rows": [{**row, "setup_id": "opportunity:wait_rebreak"}]})
    s_early = gate.semantic_state(
        **base, setups={"rows": [{**row, "setup_id": "early_trend:wait_information"}]})
    s_early_ready = gate.semantic_state(
        **base, setups={"rows": [{**row, "setup_id": "early_trend:exploration_ready"}]})

    assert s_breakout["setups"] == s_wait["setups"]
    assert s_early["setups"] == s_early_ready["setups"]
    assert gate.compare_semantic_states(s_breakout, s_wait)["changed"] is False

    # appearance/disappearance is a real delta
    s_none = gate.semantic_state(**base, setups={"rows": []})
    assert s_none["setups"] != s_breakout["setups"]
    assert "setups" in gate.compare_semantic_states(s_breakout, s_none)["components"]

    # non-lane setup ids keep their full identity (e.g. provisional entry rules)
    s_conf = gate.semantic_state(
        **base, setups={"rows": [{**row, "setup_id": "confirmed_breakout"}]})
    assert s_conf["setups"][0]["setup_id"] == "confirmed_breakout"
    assert gate.compare_semantic_states(s_breakout, s_conf)["changed"] is True
