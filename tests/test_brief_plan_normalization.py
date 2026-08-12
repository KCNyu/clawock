"""Regression coverage for brief plan normalization before validation."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
from clawock_kcnyu.harness import brief_postflight  # noqa: E402


def _authored_decision(**updates):
    decision = {
        "ticker": "AAA",
        "strategy_id": "risk_rebalance",
        "action": "cut",
        "condition": {
            "type": "manual",
            "price": None,
            "description": "risk rule",
        },
        "size": {"shares": 1, "pct": None, "note": ""},
        "confidence": 0.8,
        "driven_by": "risk_rule",
        "evidence_event_id": None,
        "regime": "neutral",
        "rationale": "reduce exposure",
    }
    decision.update(updates)
    return decision


def _write_authored_plan(tmp_path, decision):
    path = tmp_path / "2026-07-30-plan.json"
    path.write_text(json.dumps({
        "schema_version": 2,
        "date": "2026-07-30",
        "decisions": [decision],
    }))
    return path


def test_machine_owned_fields_are_normalized_before_validation(tmp_path):
    path = _write_authored_plan(tmp_path, _authored_decision())
    ledger = tmp_path / "decisions.jsonl"

    assert brief_postflight.normalize_plan_json(path, ledger) == []

    normalized = json.loads(path.read_text())
    decision = normalized["decisions"][0]
    assert decision["decision_id"].startswith("dec-")
    assert decision["episode_id"].startswith("ep-")
    assert decision["plan_date"] == "2026-07-30"
    assert decision["created_at"] == "2026-07-30T08:00:00+08:00"
    assert brief_postflight.validate_plan_json(path) == []


def test_semantic_authoring_error_is_not_rewritten_into_a_valid_default(tmp_path):
    path = _write_authored_plan(
        tmp_path,
        _authored_decision(condition={"type": "not-a-real-trigger"}),
    )

    issues = brief_postflight.normalize_plan_json(
        path, tmp_path / "decisions.jsonl"
    )

    assert any("bad condition.type" in issue for issue in issues)
    assert json.loads(path.read_text())["decisions"][0]["condition"] == {
        "type": "not-a-real-trigger"
    }


def test_harness_constraint_still_fails_after_normalization(tmp_path):
    path = _write_authored_plan(
        tmp_path,
        _authored_decision(action="add_only_on_trigger"),
    )
    packet = {
        "tickers": {
            "AAA": {
                "constraints": {
                    "allowed_actions": ["cut"],
                    "actionable_evidence_ids": [],
                    "max_sell_shares": 1,
                }
            }
        }
    }

    assert brief_postflight.normalize_plan_json(
        path, tmp_path / "decisions.jsonl"
    ) == []
    issues = brief_postflight.validate_plan_json(
        path, decision_packet=packet
    )
    assert any(
        "plan.json harness" in issue and "outside harness allowed_actions" in issue
        for issue in issues
    )
    assert brief_postflight.categorize(issues) == "fail"


def test_packet_approved_technical_tactical_add_passes_postflight(tmp_path):
    decision = _authored_decision(
        ticker="00100", strategy_id="tactical_entry",
        action="add_only_on_trigger", driven_by="technical",
        condition={"type": "price_above", "price": 11, "description": "reclaim"},
        size={"shares": 20, "pct": None, "note": "one board lot"},
        technical_setup_id="trend_pullback",
        technical_campaign_id="trend_pullback:2026-07-30",
        invalidation_price=9.5, tranche_number=1,
    )
    path = _write_authored_plan(tmp_path, decision)
    packet = {"tickers": {"00100": {
        "technical": {"setups": [{
            "setup_id": "trend_pullback",
            "campaign_id": "trend_pullback:2026-07-30",
            "entry_type": "price_above", "entry_price": 11,
            "invalidation_price": 9.5, "next_tranche_number": 1,
        }]},
        "constraints": {
            "allowed_actions": ["add_only_on_trigger"],
            "technical_setup_ids": ["trend_pullback"],
            "actionable_evidence_ids": [], "max_sell_shares": 100,
            "max_add_shares": 40, "lot_size": 20,
        },
    }}}

    assert brief_postflight.normalize_plan_json(
        path, tmp_path / "decisions.jsonl"
    ) == []
    assert brief_postflight.validate_plan_json(
        path, decision_packet=packet
    ) == []


def test_free_text_technical_add_without_packet_is_rejected(tmp_path):
    path = _write_authored_plan(tmp_path, _authored_decision(
        strategy_id="tactical_entry", action="add_only_on_trigger",
        driven_by="technical", technical_setup_id="trend_pullback",
        technical_campaign_id="trend_pullback:2026-07-30",
        invalidation_price=9.5, tranche_number=1,
    ))
    assert brief_postflight.normalize_plan_json(
        path, tmp_path / "decisions.jsonl"
    ) == []

    issues = brief_postflight.validate_plan_json(path)

    assert any("catalyst-gate" in issue for issue in issues)


def test_normalization_failure_is_fail_closed(tmp_path, monkeypatch):
    path = _write_authored_plan(tmp_path, _authored_decision())

    def fail_normalization(*_args, **_kwargs):
        raise ValueError("broken ledger")

    monkeypatch.setattr(
        brief_postflight.decision_v2,
        "normalize_authored_plan",
        fail_normalization,
    )
    issues = brief_postflight.normalize_plan_json(
        path, tmp_path / "decisions.jsonl"
    )

    assert issues == ["plan.json 标准化失败: broken ledger"]
    assert brief_postflight.categorize(issues) == "fail"


def test_main_normalizes_before_calling_plan_validation(tmp_path, monkeypatch):
    today = datetime.now().strftime("%Y-%m-%d")
    plan_path = tmp_path / "memory" / f"{today}-plan.json"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text(json.dumps({
        "schema_version": 2,
        "date": today,
        "decisions": [_authored_decision()],
    }))
    observed = {}

    def assert_normalized(path, **_kwargs):
        decision = json.loads(path.read_text())["decisions"][0]
        observed["decision_id"] = decision["decision_id"]
        observed["episode_id"] = decision["episode_id"]
        return []

    monkeypatch.setattr(brief_postflight, "WS", tmp_path)
    monkeypatch.setattr(
        brief_postflight.trading_calendar, "closed_reason", lambda _market: None
    )
    monkeypatch.setattr(
        brief_postflight.workflow_outcomes, "slot_for_job", lambda _job: "slot"
    )
    monkeypatch.setattr(
        brief_postflight.workflow_outcomes, "record_stage", lambda *_a, **_k: None
    )
    monkeypatch.setattr(brief_postflight, "validate_markdown", lambda *_a, **_k: [])
    monkeypatch.setattr(brief_postflight, "validate_plan_json", assert_normalized)
    monkeypatch.setattr(brief_postflight, "already_delivered", lambda _path: True)
    monkeypatch.setattr(sys, "argv", ["brief_postflight.py", "--dry-run"])

    assert brief_postflight.main() == 0
    assert observed["decision_id"].startswith("dec-")
    assert observed["episode_id"].startswith("ep-")


def test_dry_run_validates_normalized_plan_without_rewriting_source(
    tmp_path, monkeypatch
):
    today = datetime.now().strftime("%Y-%m-%d")
    plan_path = tmp_path / "memory" / f"{today}-plan.json"
    plan_path.parent.mkdir(parents=True)
    authored = json.dumps({
        "schema_version": 2,
        "date": today,
        "decisions": [_authored_decision()],
    })
    plan_path.write_text(authored)
    before_mtime = plan_path.stat().st_mtime_ns
    observed = {}
    validate = brief_postflight.validate_plan_json

    def capture_validation(path, **kwargs):
        decision = json.loads(path.read_text())["decisions"][0]
        observed["decision_id"] = decision["decision_id"]
        observed["issues"] = validate(path, **kwargs)
        return observed["issues"]

    monkeypatch.setattr(brief_postflight, "WS", tmp_path)
    monkeypatch.setattr(
        brief_postflight.trading_calendar, "closed_reason", lambda _market: None
    )
    monkeypatch.setattr(
        brief_postflight.workflow_outcomes, "slot_for_job", lambda _job: "slot"
    )
    monkeypatch.setattr(
        brief_postflight.workflow_outcomes, "record_stage", lambda *_a, **_k: None
    )
    monkeypatch.setattr(brief_postflight, "validate_markdown", lambda *_a, **_k: [])
    monkeypatch.setattr(
        brief_postflight, "validate_plan_json", capture_validation
    )
    monkeypatch.setattr(brief_postflight, "already_delivered", lambda _path: True)
    monkeypatch.setattr(sys, "argv", ["brief_postflight.py", "--dry-run"])

    assert brief_postflight.main() == 0
    assert observed["decision_id"].startswith("dec-")
    assert observed["issues"] == []
    assert plan_path.read_text() == authored
    assert plan_path.stat().st_mtime_ns == before_mtime
