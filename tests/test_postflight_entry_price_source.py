"""The ledger entry price must never be fabricated from snapshot vintage (#1003).

brief_postflight.log_decisions used to backfill simulated_entry_price from
portfolio.json current_price whenever the plan omitted it, justifying the write
with brief_preflight._resolve_pending_outcomes — a function the v2 refactor
(a563b3c0) deleted. The live resolver, decision_v2.settle_decisions, derives
every entry/fill from canonical memory/bars and never reads this field; the
only consumers left render it as the public dashboard's plannedPrice when
execution_price is absent, so the backfill published fetch-vintage quotes as a
price nobody ever planned. These tests pin the contract both ways: nothing is
invented, and what the model authored survives.
"""
import json

from clawock.decision import ledger as decision_v2
from clawock.harness import brief_postflight


def _decision(entry_price=None):
    d = {
        "schema_version": 2,
        "decision_id": "dec-20260824-00100-add_only_on_trigger",
        "episode_id": "ep-20260824-00100-add_only_on_trigger",
        "plan_date": "2026-08-24",
        "created_at": "2026-08-24T08:10:00+08:00",
        "ticker": "00100",
        "leg": "HK",
        "strategy_id": "tactical_entry",
        "action": "add_only_on_trigger",
        "condition": {"type": "price_above", "price": 300.0,
                      "description": "breakout", "valid_for_sessions": 1},
        "confidence": 0.7,
        "driven_by": "technical",
        "size": {"shares": 100},
    }
    if entry_price is not None:
        d["simulated_entry_price"] = entry_price
    return d


def _setup(tmp_path, decisions):
    # A portfolio quote that disagrees with everything authored, on purpose:
    # under the old backfill exactly this number leaked into the ledger and
    # onto the public dashboard's plannedPrice.
    (tmp_path / "portfolio.json").write_text(json.dumps(
        {"portfolios": {
            "hk_stocks": {"holdings": [
                {"ticker": "00100", "current_price": 123.45}]},
            "us_stocks": {"holdings": []},
        }}), encoding="utf-8")
    plan = {"schema_version": 2, "date": "2026-08-24", "decisions": decisions}
    mem = tmp_path / "memory"
    mem.mkdir(parents=True, exist_ok=True)
    (mem / "2026-08-24-plan.json").write_text(
        json.dumps(plan, ensure_ascii=False), encoding="utf-8")


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(brief_postflight, "WS", tmp_path)
    # LEDGER reaches load/upsert/write as a definition-time default argument,
    # so patching the module attribute alone would silently leave the real
    # workspace ledger wired in. Patch the bound defaults instead — the real
    # file I/O stays under test.
    ledger_path = tmp_path / "memory" / "decisions.jsonl"
    monkeypatch.setattr(
        decision_v2.load_decisions, "__defaults__", (ledger_path,))
    monkeypatch.setattr(
        decision_v2.write_decisions, "__defaults__", (ledger_path,))
    monkeypatch.setattr(
        decision_v2.upsert_plan_decisions, "__defaults__",
        (ledger_path, None, True))
    monkeypatch.setattr(decision_v2, "BARS_DIR", tmp_path / "memory" / "bars")
    monkeypatch.setattr(decision_v2, "_BAR_CACHE", {})
    monkeypatch.setattr(decision_v2, "_SESSION_CACHE", {})


def _ledger_rows(tmp_path):
    text = (tmp_path / "memory" / "decisions.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def test_missing_entry_price_is_never_invented_from_portfolio_vintage(
        tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    _setup(tmp_path, [_decision()])

    brief_postflight.log_decisions("2026-08-24")

    rows = _ledger_rows(tmp_path)
    assert len(rows) == 1
    assert rows[0].get("simulated_entry_price") is None
    plan_after = json.loads(
        (tmp_path / "memory" / "2026-08-24-plan.json").read_text(encoding="utf-8"))
    assert plan_after["decisions"][0].get("simulated_entry_price") is None


def test_model_authored_entry_price_survives_log_decisions(
        tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    _setup(tmp_path, [_decision(entry_price=299.5)])

    brief_postflight.log_decisions("2026-08-24")

    rows = _ledger_rows(tmp_path)
    assert rows[0]["simulated_entry_price"] == 299.5
