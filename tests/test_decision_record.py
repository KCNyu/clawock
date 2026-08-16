"""decision-mind ledger record command: validation, append, settle round-trip."""
import json
import sys
from pathlib import Path

import pytest

from clawock.decision import ledger as decision_v2
from clawock.decision.record import build_record, main, validate_mind_record


def _args(**overrides):
    base = {
        "subject": "00100", "market": "HK", "currency": "HKD",
        "action": "reject", "confidence": 0.65, "driven_by": "fundamental",
        "bull": "营收 +159% YoY", "bear": "资不抵债,净利率 -2368%",
        "bull_evidence": [], "bear_evidence": [],
        "thesis": "先活下来", "invalidation": ["站回 340", "缩量企稳"],
        "emotion": "averaging_down", "note": "摊本冲动被压过",
    }
    return type("Args", (), {**base, **overrides})()


def test_build_record_shape_and_legacy_compat():
    record = build_record(_args())
    assert record["schema_version"] == 0
    assert record["source"] == "conversation"
    assert record["decision_id"].startswith("dec-")
    assert record["mind"]["bear"]["summary"] == "资不抵债,净利率 -2368%"
    assert record["emotion"]["pressure"] == "averaging_down"
    # Legacy-compatible fields so the desk's machinery round-trips this record.
    assert record["condition"]["description"] == "站回 340"
    # A no-op verdict respected is an executed decision; order actions are not.
    assert record["execution"]["status"] == "followed"
    assert build_record(_args(action="add"))["execution"]["status"] == "unknown"
    assert "plan_date" not in record


def test_validation_rejects_weak_records():
    issues = validate_mind_record(build_record(_args()))
    assert issues == []

    no_bear = build_record(_args(bear=""))
    assert any("mind.bear.summary" in issue for issue in validate_mind_record(no_bear))

    no_invalidation = build_record(_args(invalidation=[]))
    assert any("mind.invalidation" in issue for issue in validate_mind_record(no_invalidation))

    bad_confidence = build_record(_args(confidence=1.3))
    assert any("confidence" in issue for issue in validate_mind_record(bad_confidence))

    bad_emotion = build_record(_args(emotion="greedy"))
    assert any("emotion.pressure" in issue for issue in validate_mind_record(bad_emotion))


def test_main_appends_and_survives_settle_round_trip(tmp_path):
    ledger = tmp_path / "decisions.jsonl"
    # A pre-existing legacy entry, shaped like the desk's plan decisions.
    decision_v2.write_decisions([{
        "decision_id": "dec-legacy1234", "plan_date": "2026-08-10",
        "ticker": "00100", "leg": "HK", "action": "trim_on_rebound",
        "condition": {"description": "跌破 730 减 20 股", "price": 730.0, "type": "price_below"},
        "evaluation": {"status": "not_triggered", "outcome": "not_triggered"},
        "execution": {"status": "unknown"},
    }], ledger)

    argv = [
        "--ledger", str(ledger),
        "--subject", "00100", "--market", "HK", "--currency", "HKD",
        "--action", "reject", "--confidence", "0.65", "--driven-by", "fundamental",
        "--bull", "营收 +159% YoY", "--bear", "资不抵债",
        "--thesis", "先活下来",
        "--invalidation", "站回 340", "--invalidation", "缩量企稳",
        "--emotion", "averaging_down", "--note", "忍住没加",
    ]
    assert main(argv) == 0

    rows = decision_v2.load_decisions(ledger)
    assert len(rows) == 2
    conversation = [d for d in rows if d.get("source") == "conversation"]
    assert len(conversation) == 1
    assert conversation[0]["mind"]["invalidation"] == ["站回 340", "缩量企稳"]

    # The daily postflight settles the whole list in place; a conversation
    # record has no plan_date and must survive untouched.
    decision_v2.settle_decisions(rows)
    after = decision_v2.load_decisions(ledger)
    conversation = [d for d in after if d.get("source") == "conversation"]
    assert len(conversation) == 1
    assert conversation[0]["decision_id"] == rows[0]["decision_id"] or \
        conversation[0]["decision_id"] == rows[1]["decision_id"]
    assert conversation[0]["mind"]["bear"]["summary"] == "资不抵债"
    assert all(d["decision_id"] for d in after)


def test_validate_decision_accepts_mind_records_and_rejects_weak_ones():
    from clawock.decision.ledger import validate_decision
    # A well-formed conversation record passes the desk's row validator.
    good = build_record(_args())
    assert validate_decision(good) == []
    # A plan-style record still requires the plan fields (no cross-contamination).
    weak = build_record(_args(bear=""))
    assert any("mind.bear.summary" in issue for issue in validate_decision(weak))
    legacy = {"decision_id": "dec-x", "plan_date": "2026-08-10", "ticker": "00100",
              "action": "hold", "confidence": 0.5, "condition": {"type": "manual"}}
    assert any("missing episode_id" in issue for issue in validate_decision(legacy))


def test_validate_decision_accepts_every_source_v0_mind_record():
    """#664: every harness in record.SOURCES writes a valid v0 mind record, and
    the desk's row validator must route each one to the mind rules — not the
    v2 plan rules that demand episode_id/plan_date."""
    from clawock.decision.ledger import validate_decision
    from clawock.decision import record as decision_record
    for source in sorted(decision_record.SOURCES):
        rec = build_record(_args(source=source))
        assert rec["source"] == source
        assert rec["schema_version"] == 0
        assert validate_decision(rec) == [], \
            f"v0 mind record from {source!r} failed the desk validator"


def test_source_param_distinguishes_harnesses(tmp_path):
    """Any harness (OpenClaw/Claude Code/Codex/CLI) records into the same
    ledger; `--source` says which one wrote the verdict."""
    ledger = tmp_path / "decisions.jsonl"

    def argv_for(source, ticker):
        return [
            "--ledger", str(ledger),
            "--source", source,
            "--subject", ticker, "--market", "US", "--currency", "USD",
            "--action", "watch", "--confidence", "0.55", "--driven-by", "mixed",
            "--bull", "支撑仍在", "--bear", "宏观逆风",
            "--invalidation", "跌破支撑",
        ]

    assert main(argv_for("openclaw", "PLTU")) == 0
    assert main(argv_for("claude", "MSFU")) == 0
    assert main(argv_for("codex", "RKLX")) == 0

    rows = decision_v2.load_decisions(ledger)
    sources = {d["source"] for d in rows}
    assert sources == {"openclaw", "claude", "codex"}
    by_ticker = {d["subject"]["ticker"]: d for d in rows}
    # execution.source follows the recording harness, so settlement and
    # post-hoc marking can tell who recorded what.
    assert by_ticker["PLTU"]["execution"]["source"] == "openclaw"
    # IDs stay unique across sources (stable id seeds on the source value).
    assert len({d["decision_id"] for d in rows}) == 3


def test_validation_rejects_unknown_source(tmp_path):
    ledger = tmp_path / "decisions.jsonl"
    argv = [
        "--ledger", str(ledger),
        "--source", "chatgpt-web",
        "--subject", "00100", "--action", "reject", "--confidence", "0.65",
        "--bull", "ok", "--bear", "counter", "--invalidation", "cond",
    ]
    # argparse rejects the choice before any file is touched.
    with pytest.raises(SystemExit):
        main(argv)
    assert not ledger.exists()


def test_main_rejects_invalid_record(tmp_path):
    ledger = tmp_path / "decisions.jsonl"
    argv = [
        "--ledger", str(ledger),
        "--subject", "00100", "--action", "reject", "--confidence", "0.65",
        "--bull", "ok", "--bear", "", "--invalidation", "cond",
    ]
    assert main(argv) == 1
    assert not ledger.exists()
