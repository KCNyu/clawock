import copy
import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.data import thesis_registry as tr


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 26, tzinfo=timezone.utc)


def evidence(evidence_id="fund-1", observed_at="2026-07-01T10:00:00+00:00",
             kind="fundamental"):
    return {
        "evidence_id": evidence_id,
        "observed_at": observed_at,
        "source_class": "issuer_filing",
        "locator": f"filing:{evidence_id}",
        "kind": kind,
        "summary": f"Evidence {evidence_id}",
    }


def thesis(ticker="TEST", thesis_id="test-core"):
    return {
        "schema_version": 1,
        "thesis_id": thesis_id,
        "ticker": ticker,
        "strategy_scope": ["core_position"],
        "summary": "Demand and unit economics support durable growth.",
        "created_at": "2026-07-01T11:00:00+00:00",
        "checked_at": "2026-07-02T11:00:00+00:00",
        "state": "intact",
        "dimensions": {
            "business": {"state": "intact", "evidence_ids": ["fund-1"]},
            "moat": {"state": "intact", "evidence_ids": ["fund-1"]},
            "management": {"state": "intact", "evidence_ids": ["fund-1"]},
            "valuation": {"state": "weakening", "evidence_ids": ["value-1"]},
        },
        "assumptions": [
            {
                "id": f"a-{index}",
                "claim": f"Assumption {index}",
                "test": f"Metric {index} stays above threshold",
                "cadence": "quarterly",
                "status": "supported",
                "evidence_ids": ["fund-1"],
            }
            for index in range(1, 4)
        ],
        "red_lines": [
            {
                "id": "solvency",
                "condition": "Liquidity runway falls below 12 months",
                "severity": "fatal",
                "status": "clear",
                "required_action": "Exit the position",
                "evidence_ids": [],
            }
        ],
        "valuation_anchors": [
            {
                "id": "sales",
                "metric": "EV/Sales",
                "value": "8.0",
                "currency": "USD",
                "period": "FY2026",
                "evidence_ids": ["value-1"],
            }
        ],
        "evidence": [
            evidence(),
            evidence("value-1", kind="valuation"),
        ],
        "next_review_trigger": {
            "type": "earnings",
            "description": "Review after the next quarterly filing",
        },
    }


def test_canonical_schema_and_validator_exist():
    schema = json.loads(tr.SCHEMA_FILE.read_text())
    assert tr.SCHEMA_FILE == ROOT / "src" / "clawock" / "config" / "thesis.schema.json"
    assert schema["$schema"].endswith("2020-12/schema")
    assert set(schema["properties"]["dimensions"]["required"]) == set(tr.DIMENSIONS)
    assert tr.validate_thesis(thesis(), now=NOW) == []


def test_missing_baseline_is_unknown_not_reconstructed():
    result = tr.evaluate_drift(None, thesis(), now=NOW)
    assert result["status"] == "unknown"
    assert result["overall"] == "unknown"
    assert result["errors"] == ["missing historical baseline"]


def test_wording_only_change_is_unchanged():
    old = thesis()
    new = copy.deepcopy(old)
    new["summary"] = "Same economics, clearer wording."
    new["checked_at"] = "2026-07-03T11:00:00+00:00"

    result = tr.evaluate_drift(old, new, now=NOW)
    assert result["status"] == "pass"
    assert result["overall"] == "unchanged"
    assert {row["direction"] for row in result["dimensions"].values()} == {"unchanged"}


def test_price_only_change_can_move_valuation_but_not_business():
    old = thesis()
    new = copy.deepcopy(old)
    new["checked_at"] = "2026-07-04T11:00:00+00:00"
    new["evidence"].append(
        evidence("price-2", "2026-07-03T10:00:00+00:00", "price")
    )
    new["dimensions"]["valuation"] = {
        "state": "damaged", "evidence_ids": ["value-1", "price-2"]
    }

    result = tr.evaluate_drift(old, new, now=NOW)
    assert result["status"] == "pass"
    assert result["dimensions"]["valuation"]["direction"] == "weakened"
    assert result["dimensions"]["valuation"]["new_evidence_ids"] == ["price-2"]
    for name in ("business", "moat", "management"):
        assert result["dimensions"][name]["direction"] == "unchanged"

    bad = copy.deepcopy(new)
    bad["dimensions"]["business"] = {
        "state": "weakening", "evidence_ids": ["fund-1", "price-2"]
    }
    assert any(
        "business cannot use price-only evidence" in error
        for error in tr.validate_thesis(bad, now=NOW)
    )


def test_fatal_red_line_dominates_cheaper_valuation():
    old = thesis()
    new = copy.deepcopy(old)
    new["checked_at"] = "2026-07-05T11:00:00+00:00"
    new["state"] = "broken"
    new["evidence"] += [
        evidence("liquidity-2", "2026-07-04T10:00:00+00:00", "filing"),
        evidence("cheap-2", "2026-07-04T10:01:00+00:00", "valuation"),
    ]
    new["red_lines"][0]["status"] = "triggered"
    new["red_lines"][0]["evidence_ids"] = ["liquidity-2"]
    new["dimensions"]["business"] = {
        "state": "broken", "evidence_ids": ["fund-1", "liquidity-2"]
    }
    new["dimensions"]["valuation"] = {
        "state": "intact", "evidence_ids": ["value-1", "cheap-2"]
    }

    result = tr.evaluate_drift(old, new, now=NOW)
    assert result["status"] == "pass"
    assert result["overall"] == "weakened"
    assert result["triggered_red_lines"] == ["solvency"]
    assert result["dimensions"]["valuation"]["direction"] == "improved"
    assert result["dimensions"]["business"]["new_evidence_ids"] == ["liquidity-2"]


def test_changed_dimension_rejects_stale_evidence():
    old = thesis()
    new = copy.deepcopy(old)
    new["checked_at"] = "2026-07-04T11:00:00+00:00"
    new["evidence"].append(
        evidence("old-news-new-id", "2026-07-02T10:00:00+00:00", "filing")
    )
    new["dimensions"]["business"] = {
        "state": "weakening",
        "evidence_ids": ["fund-1", "old-news-new-id"],
    }

    result = tr.evaluate_drift(old, new, now=NOW)
    assert result["status"] == "fail"
    assert result["dimensions"]["business"]["direction"] == "unknown"
    assert any("business changed using stale evidence" in e for e in result["errors"])


def test_mismatched_ticker_and_invalid_state_transitions_fail():
    old = thesis()
    wrong = copy.deepcopy(old)
    wrong["ticker"] = "OTHER"
    wrong["checked_at"] = "2026-07-03T11:00:00+00:00"
    assert "ticker mismatch" in tr.evaluate_drift(old, wrong, now=NOW)["errors"]

    broken = copy.deepcopy(old)
    broken["state"] = "broken"
    reopened = copy.deepcopy(broken)
    reopened["state"] = "intact"
    reopened["checked_at"] = "2026-07-03T11:00:00+00:00"
    result = tr.evaluate_drift(broken, reopened, now=NOW)
    assert result["status"] == "fail"
    assert any("terminal" in error for error in result["errors"])


def test_new_red_line_trigger_needs_new_fresh_evidence():
    old = thesis()
    new = copy.deepcopy(old)
    new["state"] = "broken"
    new["checked_at"] = "2026-07-03T11:00:00+00:00"
    new["red_lines"][0]["status"] = "triggered"
    new["red_lines"][0]["evidence_ids"] = ["fund-1"]

    result = tr.evaluate_drift(old, new, now=NOW)
    assert result["status"] == "fail"
    assert any("triggered without new evidence" in e for e in result["errors"])


def test_decision_link_preserves_historical_thesis_id():
    original = [{"ticker": "TEST", "thesis_id": "test-core", "action": "hold_and_watch"}]
    untouched = copy.deepcopy(original)
    resolved = tr.resolve_decision_links(original, [thesis()])

    assert original == untouched
    assert resolved[0]["thesis_id"] == "test-core"
    assert resolved[0]["thesis_ref"]["status"] == "resolved"
    assert tr.resolve_decision_links(
        [{"ticker": "WRONG", "thesis_id": "test-core"}], [thesis()]
    )[0]["thesis_ref"]["status"] == "mismatch"
    assert tr.resolve_decision_links(
        [{"ticker": "OTHER", "thesis_id": "historic-id"}], []
    )[0]["thesis_ref"] == {"status": "unknown", "thesis_id": "historic-id"}


def test_registry_summary_marks_missing_ticker_unknown(tmp_path):
    (tmp_path / "TEST.json").write_text(json.dumps(thesis()))
    summary = tr.registry_summary(tmp_path, ["TEST", "MISSING"])
    assert summary["status"] == "ready"
    assert summary["theses"]["TEST"]["status"] == "resolved"
    assert summary["theses"]["MISSING"] == {"status": "unknown"}


def test_cli_fails_closed_on_invalid_document(tmp_path):
    invalid = thesis()
    invalid["ticker"] = ""
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(invalid))
    assert tr.main(["validate", str(path)]) == 1


def test_validator_fails_closed_on_malformed_nested_json():
    malformed = thesis()
    malformed["strategy_scope"] = [{}]
    malformed["dimensions"]["business"] = []
    malformed["evidence"][0]["evidence_id"] = {}
    malformed["red_lines"][0]["evidence_ids"] = [{}]
    errors = tr.validate_thesis(malformed, now=NOW)
    assert errors
    assert tr.evaluate_drift([], {}, now=NOW)["status"] == "fail"


def test_preflight_and_review_skills_are_read_only_registry_consumers():
    preflight = (ROOT / "scripts" / "harness" / "brief_preflight.py").read_text()
    daily = (ROOT / "skills" / "daily-deep-brief" / "SKILL.md").read_text()
    review = (ROOT / "skills" / "portfolio-risk-review" / "SKILL.md").read_text()
    assert "'thesis_registry': thesis_registry_ctx" in preflight
    assert "'thesis_id':                action.get('thesis_id')" in preflight
    assert "daily brief 不在每天晨报里重写 canonical baseline" in daily
    assert "registry is read-only" in review


def _triggered_baseline():
    """A thesis whose severe red line is already triggered."""
    old = thesis()
    old["state"] = "damaged"
    old["red_lines"][0]["severity"] = "severe"
    old["red_lines"][0]["status"] = "triggered"
    old["red_lines"][0]["evidence_ids"] = ["fund-1"]
    assert tr.validate_thesis(old, now=NOW) == []
    return old


def test_clearing_a_red_line_without_new_evidence_fails():
    old = _triggered_baseline()
    new = copy.deepcopy(old)
    new["checked_at"] = "2026-07-05T11:00:00+00:00"
    new["red_lines"][0]["status"] = "clear"
    new["red_lines"][0]["evidence_ids"] = []

    result = tr.evaluate_drift(old, new, now=NOW)
    assert result["status"] == "fail"
    assert any(
        "red line solvency left triggered without new evidence" in error
        for error in result["errors"]
    )


def test_clearing_a_red_line_with_stale_evidence_fails():
    old = _triggered_baseline()
    new = copy.deepcopy(old)
    new["checked_at"] = "2026-07-05T11:00:00+00:00"
    new["red_lines"][0]["status"] = "clear"
    # observed before the baseline's checked_at, so it proves nothing new
    new["evidence"].append(evidence("late-id-old-fact", "2026-07-01T12:00:00+00:00", "filing"))
    new["red_lines"][0]["evidence_ids"] = ["late-id-old-fact"]

    result = tr.evaluate_drift(old, new, now=NOW)
    assert result["status"] == "fail"
    assert any("left triggered using stale evidence" in e for e in result["errors"])


def test_resolved_red_line_with_fresh_evidence_passes_and_is_reported():
    old = _triggered_baseline()
    new = copy.deepcopy(old)
    new["checked_at"] = "2026-07-05T11:00:00+00:00"
    new["evidence"].append(evidence("refinanced-2", "2026-07-04T10:00:00+00:00", "filing"))
    new["red_lines"][0]["status"] = "clear"
    new["red_lines"][0]["evidence_ids"] = ["refinanced-2"]

    result = tr.evaluate_drift(old, new, now=NOW)
    assert result["status"] == "pass", result["errors"]
    assert result["resolved_red_lines"] == ["solvency"]
    assert result["triggered_red_lines"] == []
    assert result["newly_triggered_red_lines"] == []


def test_dropping_a_triggered_red_line_is_not_a_resolution():
    old = _triggered_baseline()
    new = copy.deepcopy(old)
    new["checked_at"] = "2026-07-05T11:00:00+00:00"
    new["red_lines"] = [
        {
            "id": "other",
            "condition": "Customer concentration exceeds 40%",
            "severity": "warning",
            "status": "clear",
            "required_action": "Reassess sizing",
            "evidence_ids": [],
        }
    ]

    result = tr.evaluate_drift(old, new, now=NOW)
    assert result["status"] == "fail"
    assert any("dropped while triggered" in error for error in result["errors"])


def test_newly_triggered_red_line_is_reported_separately():
    old = thesis()
    new = copy.deepcopy(old)
    new["state"] = "broken"
    new["checked_at"] = "2026-07-05T11:00:00+00:00"
    new["evidence"].append(evidence("runway-2", "2026-07-04T10:00:00+00:00", "filing"))
    new["red_lines"][0]["status"] = "triggered"
    new["red_lines"][0]["evidence_ids"] = ["runway-2"]
    new["dimensions"]["business"] = {"state": "broken", "evidence_ids": ["fund-1", "runway-2"]}

    result = tr.evaluate_drift(old, new, now=NOW)
    assert result["status"] == "pass", result["errors"]
    assert result["newly_triggered_red_lines"] == ["solvency"]
    assert result["resolved_red_lines"] == []
    assert result["overall"] == "weakened"


def test_failure_results_keep_the_full_drift_shape():
    keys = set(tr.evaluate_drift(None, thesis(), now=NOW))
    assert keys == set(tr.evaluate_drift([], {}, now=NOW))
    assert {"resolved_red_lines", "newly_triggered_red_lines", "triggered_red_lines"} <= keys
