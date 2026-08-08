import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from clawock import entry_gate as eg


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "entry-gates" / "ustest-2026-07-20.json"
NOW = datetime(2026, 7, 26, tzinfo=timezone.utc)


@pytest.fixture
def us():
    return json.loads(FIXTURE.read_text())


def _clear_veto(veto_id, evidence_id="ev-filing"):
    return {
        "id": veto_id,
        "status": "clear",
        "finding": f"{veto_id} not present in the reviewed sources.",
        "evidence_ids": [evidence_id],
        "exception": None,
    }


def leveraged(ticker="LEVTEST"):
    """A leveraged ETF assessment: no company fundamentals, look-through routing."""
    return {
        "schema_version": 1,
        "gate_id": f"entry-{ticker}-2026-07-20",
        "ticker": ticker,
        "market": "HK",
        "instrument_kind": "leveraged_etf",
        "sector": "leveraged_etf",
        "assessed_at": "2026-07-20T08:00:00+00:00",
        "quote": {
            "price": "4.56",
            "currency": "HKD",
            "as_of": "2026-07-20T07:50:00+00:00",
            "source_class": "analyze_hk_stocks",
        },
        "information": {
            "grade": "B",
            "gaps": [
                "only one primary/structured source class; a second is needed to cross-check",
            ],
            "source_classes": ["exchange_data", "hkex_announcement"],
        },
        "mechanism": "The fund pays a swap counterparty to deliver twice the daily return of a named index, and it earns nothing itself.",
        "key_variables": [
            {"id": "kv-index", "variable": "Underlying index composition",
             "why_it_decides": "The exposure is the index, not a company."},
            {"id": "kv-vol", "variable": "Realized volatility of the index",
             "why_it_decides": "Daily rebalancing turns volatility into path decay."},
            {"id": "kv-size", "variable": "Position size against the leverage cap",
             "why_it_decides": "Sizing is the only real risk control on a 2x product."},
        ],
        "checks": [
            {"id": "underlying_exposure", "verdict": "pass",
             "finding": "Prospectus names the index and the 2x daily reset.",
             "evidence_ids": ["ev-prospectus"]},
            {"id": "decay_and_regime", "verdict": "pass",
             "finding": "Regime and decay handled by the existing leverage look-through path.",
             "evidence_ids": ["ev-exchange"]},
            {"id": "sizing_limit", "verdict": "pass",
             "finding": "Sized inside the existing leverage cap.",
             "evidence_ids": ["ev-exchange"]},
            {"id": "liquidity", "verdict": "pass",
             "finding": "Average turnover supports the intended position size.",
             "evidence_ids": ["ev-exchange"]},
        ],
        "vetoes": [
            _clear_veto("integrity_or_governance_red_flag", "ev-prospectus"),
            _clear_veto("unintelligible_revenue_mechanism", "ev-prospectus"),
            _clear_veto("persistent_negative_cash_generation", "ev-prospectus"),
            _clear_veto("destructive_dilution", "ev-prospectus"),
        ],
        "mirror_test": [
            "It is a swap-based fund that delivers twice the daily move of one index.",
            "It earns nothing on its own; the counterparty delivers the index return minus fees.",
            "For it to work the index has to trend rather than chop.",
            "It breaks in a choppy tape, where daily resets grind the position down even with a flat index.",
            "If that happens the position is cut on the leverage rule, not on a view about any company.",
        ],
        "evidence": [
            {"evidence_id": "ev-prospectus", "observed_at": "2026-07-19T02:00:00+00:00",
             "source_class": "hkex_announcement", "locator": "hkex:LEVTEST/prospectus",
             "summary": "Prospectus: named index, 2x daily reset, swap counterparty, fee schedule."},
            {"evidence_id": "ev-exchange", "observed_at": "2026-07-19T02:05:00+00:00",
             "source_class": "exchange_data", "locator": "exchange:LEVTEST/turnover",
             "summary": "Exchange turnover and spread series used for the liquidity check."},
        ],
        "next_evidence": [],
        "verdict": "pass_to_deep_research",
        "routing": "leverage_look_through",
    }


# --- one schema, both markets, both instrument kinds --------------------------

def test_us_company_fixture_passes_and_routes_to_full_report(us):
    assert eg.validate_artifact(us, now=NOW) == []
    result = eg.assess(us, now=NOW)
    assert result["status"] == "pass"
    assert result["verdict"] == "pass_to_deep_research"
    assert result["routing"] == "us_full_report"
    # An expensive, shallow-moat name is still worth researching; the concern is
    # reported, not silently dropped.
    assert result["failed_checks"] == ["moat", "valuation"]
    assert result["checks_passed"] == "4/6"


def test_the_same_schema_serves_an_hk_company(us):
    hk = copy.deepcopy(us)
    hk.update(gate_id="entry-HKTEST-2026-07-20", ticker="HKTEST", market="HK",
              routing="hk_full_report")
    hk["quote"] = {
        "price": "45.6", "currency": "HKD",
        "as_of": "2026-07-20T07:50:00+00:00", "source_class": "analyze_hk_stocks",
    }
    hk["evidence"][0]["source_class"] = "hkex_announcement"
    hk["evidence"][1]["source_class"] = "eastmoney_fundamentals"
    hk["information"]["source_classes"] = sorted(
        {"news_media", "hkex_announcement", "eastmoney_fundamentals"}
    )
    assert eg.validate_artifact(hk, now=NOW) == []
    assert eg.assess(hk, now=NOW)["routing"] == "hk_full_report"


def test_leveraged_etf_routes_to_look_through_without_company_fundamentals():
    doc = leveraged()
    assert eg.validate_artifact(doc, now=NOW) == []
    result = eg.assess(doc, now=NOW)
    assert result["verdict"] == "pass_to_deep_research"
    assert result["routing"] == "leverage_look_through"
    assert result["checks_passed"] == "4/4"


def test_a_leveraged_etf_may_not_carry_company_fundamental_checks():
    doc = leveraged()
    doc["checks"].append({
        "id": "moat", "verdict": "pass", "finding": "A fund has no moat to grade.",
        "evidence_ids": ["ev-prospectus"],
    })
    assert any(
        "is not a leveraged_etf check" in error
        for error in eg.validate_artifact(doc, now=NOW)
    )


def test_registry_overrides_a_wrong_instrument_kind_declaration():
    doc = leveraged("07226")
    doc["instrument_kind"] = "company"          # the registry knows better
    doc["sector"] = "software"
    errors = eg.validate_artifact(doc, now=NOW)
    assert any("instrument_kind must be leveraged_etf" in error for error in errors)

    unleveraged = leveraged("00100")
    errors = eg.validate_artifact(unleveraged, now=NOW)
    assert any("instrument_kind must be company" in error for error in errors)


# --- information grade is about sources, not quality --------------------------

def test_c_grade_company_is_gray_not_rejected(us):
    thin = copy.deepcopy(us)
    for item in thin["evidence"]:
        item["source_class"] = "news_media"
    thin["information"] = {
        "grade": "C",
        "gaps": [
            "no primary issuer or structured source in the evidence set",
            "no supporting regulatory/exchange dataset",
            "media or analyst material is present and ranks below issuer sources",
        ],
        "source_classes": ["news_media"],
    }
    thin["verdict"] = "gray_needs_evidence"
    thin["next_evidence"] = [{
        "question": "Does the annual filing confirm the seat count and retention claim?",
        "where_to_look": "SEC 10-K, Item 7 plus the revenue recognition note",
    }]
    assert eg.validate_artifact(thin, now=NOW) == []
    result = eg.assess(thin, now=NOW)
    assert result["verdict"] == "gray_needs_evidence"
    assert result["verdict"] != "reject"
    assert any("grade C" in reason for reason in result["reasons"])


def test_a_gray_verdict_must_name_the_missing_evidence(us):
    thin = copy.deepcopy(us)
    thin["checks"][0]["verdict"] = "unknown"
    thin["checks"][0]["evidence_ids"] = []
    thin["verdict"] = "gray_needs_evidence"
    assert any(
        "must name the next evidence needed" in error
        for error in eg.validate_artifact(thin, now=NOW)
    )


def test_unresolved_checks_never_produce_a_score_for_the_missing_part(us):
    doc = copy.deepcopy(us)
    doc["checks"][1]["verdict"] = "unknown"
    doc["checks"][1]["evidence_ids"] = []
    result = eg.decide(doc)
    assert result["verdict"] == "gray_needs_evidence"
    assert result["unresolved_checks"] == ["moat"]
    assert result["checks_passed"] == "4/6"


def test_information_grade_is_recomputed_not_taken_on_trust(us):
    us["information"]["grade"] = "A"
    for item in us["evidence"]:
        item["source_class"] = "analyst_note"
    assert any(
        "information must match the grade computed" in error
        for error in eg.validate_artifact(us, now=NOW)
    )


# --- hard vetoes cannot be outscored -----------------------------------------

def test_a_triggered_veto_beats_a_perfect_check_tally(us):
    doc = copy.deepcopy(us)
    for check in doc["checks"]:
        check["verdict"] = "pass"           # 6/6, the best possible tally
    doc["vetoes"][0].update(
        status="triggered",
        finding="Auditor resigned citing unresolved related-party transfers.",
        evidence_ids=["ev-10q"],
    )
    doc["verdict"] = "reject"
    assert eg.validate_artifact(doc, now=NOW) == []
    result = eg.assess(doc, now=NOW)
    assert result["verdict"] == "reject"
    assert result["checks_passed"] == "6/6"
    assert result["triggered_vetoes"] == ["integrity_or_governance_red_flag"]


def test_stated_verdict_cannot_disagree_with_the_computed_one(us):
    doc = copy.deepcopy(us)
    doc["vetoes"][3].update(
        status="triggered",
        finding="Share count up 40% year over year with no stated use of proceeds.",
        evidence_ids=["ev-xbrl"],
    )
    doc["verdict"] = "pass_to_deep_research"     # the fudge
    assert any(
        "disagrees with the computed verdict" in error
        for error in eg.validate_artifact(doc, now=NOW)
    )


def test_a_triggered_veto_needs_evidence(us):
    doc = copy.deepcopy(us)
    doc["vetoes"][1].update(status="triggered", evidence_ids=[])
    doc["verdict"] = "reject"
    assert any("triggered without evidence" in e for e in eg.validate_artifact(doc, now=NOW))


def test_encoded_industry_exception_lifts_a_veto_but_an_improvised_one_does_not(us):
    doc = copy.deepcopy(us)
    doc["sector"] = "biotechnology_clinical_stage"
    doc["vetoes"][2].update(
        status="triggered",
        finding="Operating cash flow negative in all four reported periods.",
        evidence_ids=["ev-xbrl"],
        exception={
            "reason": "Clinical-stage program with financing through the next readout.",
            "evidence_id": "ev-10q",
        },
    )
    assert eg.validate_artifact(doc, now=NOW) == []
    assert eg.decide(doc)["verdict"] == "pass_to_deep_research"

    improvised = copy.deepcopy(doc)
    improvised["sector"] = "software"          # no encoded exception for this sector
    errors = eg.validate_artifact(improvised, now=NOW)
    assert any("encodes no exception for sector 'software'" in error for error in errors)

    unbacked = copy.deepcopy(doc)
    unbacked["vetoes"][2]["exception"]["evidence_id"] = "ev-does-not-exist"
    assert any(
        "exception needs an evidence_id present in evidence[]" in error
        for error in eg.validate_artifact(unbacked, now=NOW)
    )


def test_integrity_veto_encodes_no_exception_at_all(us):
    doc = copy.deepcopy(us)
    doc["vetoes"][0].update(
        status="triggered",
        finding="Regulator sanctioned the CFO over disclosure conduct.",
        evidence_ids=["ev-10q"],
        exception={"reason": "It was a long time ago.", "evidence_id": "ev-10q"},
    )
    errors = eg.validate_artifact(doc, now=NOW)
    assert any("does not encode any exception" in error for error in errors)


def test_a_disqualifying_check_failure_rejects_while_a_soft_one_does_not(us):
    hard = copy.deepcopy(us)
    hard["checks"][0]["verdict"] = "fail"        # business_quality
    hard["verdict"] = "reject"
    assert eg.validate_artifact(hard, now=NOW) == []
    assert eg.decide(hard)["verdict"] == "reject"

    soft = copy.deepcopy(us)
    soft["checks"][4]["verdict"] = "fail"        # dilution
    assert eg.decide(soft)["verdict"] == "pass_to_deep_research"


# --- quotes come from the workspace pipelines --------------------------------

def test_a_generic_web_price_is_a_hard_error_not_a_gray_verdict(us):
    us["quote"]["source_class"] = "web_search"
    errors = eg.validate_artifact(us, now=NOW)
    assert any("must be a workspace pipeline" in error for error in errors)


def test_a_stale_quote_downgrades_the_verdict_to_gray(us):
    doc = copy.deepcopy(us)
    doc["quote"]["as_of"] = "2026-07-15T13:35:00+00:00"     # five days before the assessment
    freshness = eg.quote_freshness(doc)
    assert freshness["status"] == "stale"
    assert freshness["age_minutes"] > eg.MAX_QUOTE_AGE_MINUTES
    assert eg.decide(doc)["verdict"] == "gray_needs_evidence"


def test_quote_age_and_source_gaps_are_visible_in_the_output(us):
    result = eg.assess(us, now=NOW)
    assert result["quote_freshness"]["age_minutes"] == 25
    assert result["quote_freshness"]["source_class"] == "analyze_us_stocks"
    assert result["information"]["gaps"]


# --- narrative discipline ----------------------------------------------------

def test_mirror_test_must_be_five_distinct_sentences(us):
    short = copy.deepcopy(us)
    short["mirror_test"] = short["mirror_test"][:4]
    assert any("exactly 5 sentences" in e for e in eg.validate_artifact(short, now=NOW))

    repeated = copy.deepcopy(us)
    repeated["mirror_test"][4] = repeated["mirror_test"][0]
    assert any("must be distinct" in e for e in eg.validate_artifact(repeated, now=NOW))


def test_key_variables_stay_between_three_and_seven(us):
    doc = copy.deepcopy(us)
    doc["key_variables"] = doc["key_variables"][:2]
    assert any("3-7 items" in e for e in eg.validate_artifact(doc, now=NOW))


def test_a_check_verdict_needs_evidence(us):
    doc = copy.deepcopy(us)
    doc["checks"][0]["evidence_ids"] = []
    assert any("claims pass without evidence" in e for e in eg.validate_artifact(doc, now=NOW))


def test_every_defined_veto_must_be_answered(us):
    doc = copy.deepcopy(us)
    doc["vetoes"] = doc["vetoes"][:2]
    errors = eg.validate_artifact(doc, now=NOW)
    assert sum("vetoes must state a status" in error for error in errors) == 2


def test_evidence_cannot_be_observed_in_the_future(us):
    doc = copy.deepcopy(us)
    doc["evidence"][0]["observed_at"] = "2027-01-01T00:00:00+00:00"
    assert any("cannot be in the future" in e for e in eg.validate_artifact(doc, now=NOW))


# --- config and CLI ----------------------------------------------------------

def test_schema_document_and_validator_agree(us):
    schema = json.loads(eg.SCHEMA_FILE.read_text())
    assert set(schema["required"]) == set(eg.ARTIFACT_FIELDS)
    assert set(schema["properties"]) == set(eg.ARTIFACT_FIELDS)
    assert set(schema["properties"]["verdict"]["enum"]) == eg.VERDICTS
    assert set(schema["properties"]["quote"]["properties"]["source_class"]["enum"]) == eg.QUOTE_SOURCES
    assert set(schema["properties"]["vetoes"]["items"]["properties"]["id"]["enum"]) == set(eg.VETOES)
    assert set(schema["properties"]["checks"]["items"]["properties"]["id"]["enum"]) == set(
        eg.COMPANY_CHECKS + eg.LEVERAGED_CHECKS
    )
    assert set(schema["properties"]["evidence"]["items"]["properties"]["source_class"]["enum"]) == eg.EVIDENCE_CLASSES


def test_veto_config_exceptions_are_encoded_with_evidence_requirements():
    vetoes = eg.load_vetoes()
    assert set(vetoes) == {
        "integrity_or_governance_red_flag", "unintelligible_revenue_mechanism",
        "persistent_negative_cash_generation", "destructive_dilution",
    }
    assert vetoes["integrity_or_governance_red_flag"]["exceptions"] == []
    assert vetoes["unintelligible_revenue_mechanism"]["exceptions"] == []
    for veto in vetoes.values():
        for exception in veto["exceptions"]:
            assert exception["sector"] and exception["note"]
            assert exception["requires_evidence"] is True


def test_cli_passes_on_the_fixture_and_prints_one_json_object(capsys):
    assert eg.main(["assess", str(FIXTURE)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] == "pass_to_deep_research"


def test_cli_fails_closed_on_a_fudged_verdict(tmp_path, capsys):
    doc = json.loads(FIXTURE.read_text())
    doc["checks"][0]["verdict"] = "fail"        # business_quality → computed reject
    path = tmp_path / "fudged.json"
    path.write_text(json.dumps(doc))
    assert eg.main(["validate", str(path)]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "fail"


def test_cli_fails_closed_on_unreadable_artifact(tmp_path, capsys):
    path = tmp_path / "broken.json"
    path.write_text("{nope")
    assert eg.main(["assess", str(path)]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "fail"
