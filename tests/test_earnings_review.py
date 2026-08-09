import copy
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from clawock.decision import earnings as er
from clawock.decision import theses as tr


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "earnings"
US = FIXTURES / "us-ustest-fy2026q1.json"
HK = FIXTURES / "hk-9999hk-fy2025h2.json"
NOW = datetime(2026, 7, 26, tzinfo=timezone.utc)


def load(path):
    return json.loads(path.read_text())


@pytest.fixture
def us():
    return load(US)


@pytest.fixture
def hk():
    return load(HK)


# --- one normalized schema for both markets -------------------------------------

@pytest.mark.parametrize("path", [US, HK], ids=["us", "hk"])
def test_us_and_hk_fixtures_pass_the_same_schema_and_gate(path):
    doc = load(path)
    assert er.validate_artifact(doc, now=NOW) == []
    gate = er.release(doc, now=NOW)
    assert gate["status"] == "pass", gate["errors"]
    assert gate["provenance"] == {
        "status": "pass", "verified_metrics": 3, "total_metrics": 3
    }
    assert gate["quality"]["status"] == "computed"
    assert gate["source_availability"]["grade"] == "A"


def test_schema_document_and_validator_agree_on_required_fields():
    schema = json.loads(er.SCHEMA_FILE.read_text())
    assert set(schema["required"]) == set(er.ARTIFACT_FIELDS)
    assert set(schema["properties"]) == set(er.ARTIFACT_FIELDS)
    assert set(schema["$defs"]["document"]["properties"]["source_class"]["enum"]) == er.SOURCE_CLASSES
    assert set(schema["$defs"]["footnote"]["properties"]["category"]["enum"]) == er.FOOTNOTE_CATEGORIES
    assert set(schema["$defs"]["commitment"]["properties"]["status"]["enum"]) == er.COMMITMENT_STATUSES
    assert set(schema["$defs"]["capital_event"]["properties"]["type"]["enum"]) == er.CAPITAL_EVENTS


# --- basis / currency / period explicitness ------------------------------------

def test_non_gaap_period_cannot_be_compared_against_gaap(us):
    us["comparables"][1]["basis"] = "non_GAAP"
    errors = er.validate_artifact(us, now=NOW)
    assert any("mixed basis cannot be compared" in error for error in errors)


def test_currency_and_unit_switches_are_errors_not_footnotes(us):
    us["comparables"][0]["currency"] = "HKD"
    us["comparables"][2]["unit"] = "thousand"
    errors = er.validate_artifact(us, now=NOW)
    assert any("mixed currency cannot be compared" in error for error in errors)
    assert any("mixed unit cannot be compared" in error for error in errors)


def test_hk_artifact_cannot_claim_a_us_reporting_basis(hk):
    hk["basis"] = "GAAP"
    for row in hk["comparables"]:
        row["basis"] = "GAAP"
    assert any(
        "is not a HK reporting basis" in error
        for error in er.validate_artifact(hk, now=NOW)
    )


def test_short_history_and_out_of_order_history_fail(us):
    short = copy.deepcopy(us)
    short["comparables"] = short["comparables"][2:]
    assert any(
        "quarterly cadence needs at least 4 comparable periods" in error
        for error in er.validate_artifact(short, now=NOW)
    )

    shuffled = copy.deepcopy(us)
    shuffled["comparables"] = [shuffled["comparables"][i] for i in (1, 0, 2, 3)]
    assert any(
        "ordered oldest first" in error
        for error in er.validate_artifact(shuffled, now=NOW)
    )


def test_period_and_publication_dates_must_be_coherent(us):
    early = copy.deepcopy(us)
    early["published_at"] = "2026-01-05T20:05:00+00:00"
    assert any(
        "cannot precede the period end_date" in error
        for error in er.validate_artifact(early, now=NOW)
    )

    future = copy.deepcopy(us)
    future["published_at"] = "2027-04-25T20:05:00+00:00"
    assert any(
        "published_at cannot be in the future" in error
        for error in er.validate_artifact(future, now=NOW)
    )


# --- earnings quality is computed, not asserted --------------------------------

def test_cash_conversion_and_working_capital_anomalies_are_computed(us):
    quality = er.compute_quality(us)
    # OCF 5 against net income 8, receivables +40% against revenue +5.93%
    assert quality["metrics"]["cash_conversion"]["value"] == "0.6250"
    assert quality["metrics"]["receivables_vs_revenue_pp"]["value"] == "34.0678"
    assert quality["anomaly_flags"] == [
        "receivables_outrunning_revenue", "weak_cash_conversion"
    ]
    assert quality["thresholds"]["cash_conversion_min"] == "0.8"


def test_clean_history_produces_no_flags_and_no_invented_guidance(hk):
    quality = er.compute_quality(hk)
    assert quality["anomaly_flags"] == []
    assert quality["metrics"]["cash_conversion"]["value"] == "1.5323"
    assert quality["guidance"]["status"] == "unavailable"
    assert "no guidance was published" in quality["guidance"]["reason"]


def test_missing_inputs_are_unavailable_with_a_reason_not_a_number(us):
    for row in us["comparables"]:
        row.pop("inventory", None)
        row.pop("diluted_shares", None)
    quality = er.compute_quality(us)
    assert quality["metrics"]["inventory_growth_pct"]["status"] == "unavailable"
    assert quality["metrics"]["dilution_pct"]["status"] == "unavailable"
    assert "value" not in quality["metrics"]["dilution_pct"]
    assert "inventory_outrunning_revenue" not in quality["anomaly_flags"]


def test_a_loss_making_period_is_flagged_not_read_as_a_beat(us):
    us["comparables"][-1]["net_income"] = "-8"
    quality = er.compute_quality(us)
    assert "net_income_negative" in quality["metrics"]["cash_conversion"]["flags"]
    assert "weak_cash_conversion" not in quality["metrics"]["cash_conversion"]["flags"]


def test_dilution_and_guidance_miss_are_flagged(us):
    us["comparables"][-1]["diluted_shares"] = "560"     # +10.9% vs 505
    us["guidance"]["actual"] = "100"                    # below the 120 floor
    quality = er.compute_quality(us)
    assert "destructive_dilution" in quality["anomaly_flags"]
    assert quality["guidance"]["verdict"] == "miss"
    assert "guidance_miss" in quality["anomaly_flags"]


# --- source grade gates footnote claims ---------------------------------------

def test_missing_first_party_document_lowers_grade_and_disables_footnotes(hk):
    hk["documents"] = [
        doc for doc in hk["documents"] if doc["source_class"] != "hkex_announcement"
    ]
    availability = er.grade_sources(hk["documents"])
    assert availability["grade"] == "B"
    assert availability["footnote_claims_allowed"] is False
    errors = er.validate_artifact(hk, now=NOW)
    assert any("footnotes are not available at this source grade" in e for e in errors)


def test_third_party_only_artifact_is_grade_c(hk):
    hk["documents"] = [
        {
            "document_id": "summary-only",
            "source_class": "third_party_summary",
            "locator": "vendor:9999.HK/fy2025-recap",
            "retrieved_at": "2026-03-21T02:05:00+00:00",
            "covers_period": True,
        }
    ]
    availability = er.grade_sources(hk["documents"])
    assert availability["grade"] == "C"
    assert availability["footnote_claims_allowed"] is False
    assert any("no structured dataset" in gap for gap in availability["gaps"])


def test_a_footnote_may_not_cite_a_structured_dataset(us):
    us["footnotes"][0]["source_document_id"] = "xbrl-fy2026q1"
    assert any(
        "footnote claims require a primary issuer document" in error
        for error in er.validate_artifact(us, now=NOW)
    )


# --- management promises survive across periods ------------------------------

def _commitment(commitment_id, due_date, status="not_due", actual=None):
    return {
        "commitment_id": commitment_id,
        "statement": f"Commitment {commitment_id}",
        "source_document_id": "ir-deck-fy2026q1",
        "made_at": "2026-01-28",
        "due_date": due_date,
        "target_metric": "free_cash_flow",
        "target_value": "0",
        "actual_value": actual,
        "status": status,
    }


def test_promise_becomes_missed_when_the_reporting_period_covers_its_due_date():
    previous = [_commitment("margin-target", "2026-03-31")]
    merged, errors = er.roll_forward_commitments(
        previous, copy.deepcopy(previous), date(2026, 4, 25),
        report_period_end=date(2026, 3, 31),
    )
    assert errors == []
    assert merged[0]["status"] == "missed"
    # the input ledger is not mutated in place
    assert previous[0]["status"] == "not_due"


def test_overdue_promise_without_a_covering_report_is_unverifiable_not_missed():
    previous = [_commitment("margin-target", "2026-03-31")]
    merged, errors = er.roll_forward_commitments(
        previous, copy.deepcopy(previous), date(2026, 4, 25),
        report_period_end=date(2025, 12, 31),
    )
    assert errors == []
    assert merged[0]["status"] == "unverifiable"


def test_not_yet_due_promise_stays_not_due():
    previous = [_commitment("long-horizon", "2026-12-31")]
    merged, errors = er.roll_forward_commitments(
        previous, copy.deepcopy(previous), date(2026, 4, 25),
        report_period_end=date(2026, 3, 31),
    )
    assert errors == []
    assert merged[0]["status"] == "not_due"


def test_a_promise_may_not_be_dropped_or_softened_later():
    previous = [
        _commitment("kept", "2026-03-31", "missed", "-3"),
        _commitment("vanishing", "2026-03-31", "met", "4"),
    ]
    current = [_commitment("kept", "2026-03-31", "met", "4")]
    merged, errors = er.roll_forward_commitments(
        previous, current, date(2026, 4, 25), report_period_end=date(2026, 3, 31)
    )
    assert any("was already missed" in error for error in errors)
    assert any("disappeared from the ledger" in error for error in errors)
    assert {item["commitment_id"] for item in merged} == {"kept", "vanishing"}


def test_new_promises_join_the_ledger():
    previous = [_commitment("old", "2026-12-31")]
    current = previous + [_commitment("new", "2026-12-31")]
    merged, errors = er.roll_forward_commitments(
        previous, current, date(2026, 4, 25), report_period_end=date(2026, 3, 31)
    )
    assert errors == []
    assert [item["commitment_id"] for item in merged] == ["old", "new"]


def test_terminal_status_requires_an_actual_value(us):
    us["management_commitments"][0]["actual_value"] = None
    assert any(
        "claims met without an actual_value" in error
        for error in er.validate_artifact(us, now=NOW)
    )


# --- the release gate and the thesis boundary --------------------------------

def test_release_is_blocked_by_a_failing_provenance_manifest(us):
    us["provenance"]["metrics"][0]["verification"]["value"] = "900"
    gate = er.release(us, now=NOW)
    assert gate["status"] == "fail"
    assert any(error.startswith("provenance: ") for error in gate["errors"])
    assert gate["quality"]["status"] == "unavailable"


def test_release_is_blocked_when_a_number_has_only_one_source(us):
    metric = us["provenance"]["metrics"][0]
    metric["verification"]["source_class"] = metric["source"]["source_class"]
    gate = er.release(us, now=NOW)
    assert gate["status"] == "fail"
    assert any("independent source" in error for error in gate["errors"])


def test_thesis_evidence_never_carries_a_state_change(us):
    handoff = er.to_thesis_evidence(us)
    assert handoff["state_change"] is None
    assert handoff["thesis_id"] == "ustest-core"
    assert {row["dimension"] for row in handoff["dimension_suggestions"]} <= {
        "business", "moat", "management", "valuation"
    }
    assert all("state" not in row for row in handoff["dimension_suggestions"])


def test_generated_evidence_is_accepted_by_the_thesis_registry(us):
    """The handoff must satisfy the registry's own validator, including its
    rule that business/moat/management may not lean on price-only evidence."""
    handoff = er.to_thesis_evidence(us)
    assert len(handoff["evidence"]) >= 3

    thesis = {
        "schema_version": 1,
        "thesis_id": "ustest-core",
        "ticker": "USTEST",
        "strategy_scope": ["core_position"],
        "summary": "Platform economics carry the position; services is the swing factor.",
        "created_at": "2026-01-01T00:00:00+00:00",
        "checked_at": "2026-04-26T00:00:00+00:00",
        "state": "weakening",
        "dimensions": {
            name: {
                "state": "weakening" if name == "business" else "unknown",
                "evidence_ids": [
                    row["evidence_id"] for row in handoff["dimension_suggestions"]
                    if row["dimension"] == name
                ],
            }
            for name in ("business", "moat", "management", "valuation")
        },
        "assumptions": [
            {
                "id": f"a-{index}",
                "claim": f"Assumption {index}",
                "test": "Metric stays above threshold",
                "cadence": "quarterly",
                "status": "supported",
                "evidence_ids": [],
            }
            for index in range(1, 4)
        ],
        "red_lines": [
            {
                "id": "cash-conversion",
                "condition": "OCF/net income stays below 0.8 for two periods",
                "severity": "severe",
                "status": "watch",
                "required_action": "Cut the position by half",
                "evidence_ids": [],
            }
        ],
        "valuation_anchors": [],
        "evidence": handoff["evidence"],
        "next_review_trigger": {
            "type": "earnings",
            "description": "Review after the FY2026Q2 filing",
        },
    }
    assert tr.validate_thesis(thesis, now=NOW) == []


# --- CLI ---------------------------------------------------------------------

def test_cli_review_passes_and_prints_one_json_object(capsys):
    assert er.main(["review", str(US)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "pass"


def test_cli_fails_closed_on_invalid_artifact(tmp_path, capsys):
    broken = load(US)
    broken["comparables"][1]["basis"] = "non_GAAP"
    path = tmp_path / "broken.json"
    path.write_text(json.dumps(broken))
    assert er.main(["validate", str(path)]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "fail"


def test_cli_fails_closed_on_unreadable_artifact(tmp_path, capsys):
    path = tmp_path / "not-json.json"
    path.write_text("{oops")
    assert er.main(["review", str(path)]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "fail"


def test_cli_promises_rolls_forward_between_two_artifacts(tmp_path, capsys):
    previous = load(US)
    previous["management_commitments"] = [_commitment("margin-target", "2026-03-31")]
    current = load(US)
    current["management_commitments"] = [_commitment("margin-target", "2026-03-31")]
    old_path, new_path = tmp_path / "q4.json", tmp_path / "q1.json"
    old_path.write_text(json.dumps(previous))
    new_path.write_text(json.dumps(current))

    assert er.main(["promises", str(old_path), str(new_path), "--as-of", "2026-04-25"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["commitments"][0]["status"] == "missed"


def test_thesis_evidence_cli_reports_the_gate_verdict(capsys):
    assert er.main(["thesis-evidence", str(HK)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["state_change"] is None
    assert payload["ticker"] == "9999.HK"
