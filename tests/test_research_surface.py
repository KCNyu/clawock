"""The research lifecycle must be used by recurring paths, not just shipped.

These tests hold two lines: the surface computes the right work queue from real
artifacts, and the three consumers (daily brief preflight, `system_check.py`,
the `validate` workflow) actually call it.
"""
import copy
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from scripts.data import research_surface as rs


ROOT = Path(__file__).resolve().parents[1]
EARNINGS_FIXTURE = ROOT / "tests" / "fixtures" / "earnings" / "us-ustest-fy2026q1.json"
GATE_FIXTURE = ROOT / "tests" / "fixtures" / "entry-gates" / "ustest-2026-07-20.json"
NOW = datetime(2026, 7, 26, tzinfo=timezone.utc)
TODAY = NOW.date()


def portfolio(ticker="USTEST", first_buy="2026-08-01", shares=10):
    return {
        "portfolios": {
            "us_stocks": {"holdings": [{
                "ticker": ticker,
                "shares": shares,
                "trades": [{"date": first_buy, "action": "buy", "shares": shares,
                            "price": 12.0}],
            }]},
            "hk_stocks": {"holdings": []},
        }
    }


def catalysts(ticker="USTEST", reported="2026-07-20", window=14):
    return {
        "lookback_window_days": window,
        "earnings": [{"ticker": ticker, "date": reported, "quarter": 2, "year": 2026}],
    }


@pytest.fixture
def dirs(tmp_path):
    for name in ("theses", "earnings", "entry-gates"):
        (tmp_path / name).mkdir()
    return {
        "thesis_dir": tmp_path / "theses",
        "earnings_dir": tmp_path / "earnings",
        "entry_gate_dir": tmp_path / "entry-gates",
    }


def write_earnings(dirs, doc):
    path = dirs["earnings_dir"] / doc["ticker"]
    path.mkdir(exist_ok=True)
    (path / f"{doc['period']['label']}.json").write_text(json.dumps(doc))


def write_gate(dirs, doc):
    (dirs["entry_gate_dir"] / f"{doc['ticker']}-2026-07-20.json").write_text(json.dumps(doc))


# --- the work queue ----------------------------------------------------------

def test_reported_earnings_without_an_artifact_is_due(dirs):
    surface = rs.summarize(
        portfolio=portfolio(), catalysts=catalysts(), today=TODAY, now=NOW, **dirs
    )
    assert surface["status"] == "ready"
    assert surface["earnings"]["reviews_due"] == [{
        "ticker": "USTEST",
        "reported_on": "2026-07-20",
        "days_since": 6,
        "reason": "earnings reported with no primary-source artifact covering it",
    }]
    assert surface["earnings"]["detection_window_days"] == 14


def test_an_artifact_published_after_the_report_clears_the_queue(dirs):
    doc = json.loads(EARNINGS_FIXTURE.read_text())
    doc["published_at"] = "2026-07-21T20:00:00+00:00"
    doc["period"] = {"label": "FY2026Q2", "end_date": "2026-06-30"}
    doc["comparables"][-1]["period"] = doc["period"]
    write_earnings(dirs, doc)
    surface = rs.summarize(
        portfolio=portfolio(), catalysts=catalysts(), today=TODAY, now=NOW, **dirs
    )
    assert surface["earnings"]["reviews_due"] == []
    assert surface["earnings"]["artifacts"] == {"USTEST": 1}
    assert surface["earnings"]["latest_period"] == {"USTEST": "FY2026Q2"}


def test_detection_window_never_outruns_the_catalyst_feed(dirs):
    # The feed only carries 14 days, so a report older than that cannot be
    # detected here — that is what stale_ledgers is for.
    surface = rs.summarize(
        portfolio=portfolio(), catalysts=catalysts(reported="2026-06-01"),
        today=TODAY, now=NOW, **dirs,
    )
    assert surface["earnings"]["reviews_due"] == []
    assert rs.review_window_days({"lookback_window_days": 400}) == rs.MAX_REVIEW_WINDOW_DAYS
    assert rs.review_window_days({}) == rs.DEFAULT_REVIEW_WINDOW_DAYS
    assert rs.review_window_days(None) == rs.DEFAULT_REVIEW_WINDOW_DAYS


def test_a_ledger_left_a_full_period_behind_is_stale(dirs):
    doc = json.loads(EARNINGS_FIXTURE.read_text())      # quarterly, FY2026Q1
    write_earnings(dirs, doc)
    surface = rs.summarize(
        portfolio=portfolio(), catalysts={"earnings": []},
        today=date(2026, 12, 1), now=NOW, **dirs,
    )
    stale = surface["earnings"]["stale_ledgers"]
    assert [row["ticker"] for row in stale] == ["USTEST"]
    assert stale[0]["latest_period"] == "FY2026Q1"
    assert stale[0]["cadence"] == "quarterly"
    assert stale[0]["days_behind"] > rs.CADENCE_DAYS["quarterly"] * rs.STALE_LEDGER_FACTOR


def test_a_ledger_inside_the_normal_reporting_lag_is_not_stale(dirs):
    doc = json.loads(EARNINGS_FIXTURE.read_text())
    write_earnings(dirs, doc)
    surface = rs.summarize(
        portfolio=portfolio(), catalysts={"earnings": []},
        today=date(2026, 7, 26), now=NOW, **dirs,
    )
    assert surface["earnings"]["stale_ledgers"] == []


def test_an_overdue_promise_surfaces_with_its_id_and_age(dirs):
    doc = json.loads(EARNINGS_FIXTURE.read_text())
    doc["management_commitments"][1]["due_date"] = "2026-06-30"      # still not_due
    write_earnings(dirs, doc)
    surface = rs.summarize(
        portfolio=portfolio(), catalysts={"earnings": []}, today=TODAY, now=NOW, **dirs
    )
    overdue = surface["earnings"]["overdue_commitments"]
    assert [row["commitment_id"] for row in overdue] == ["services-breakeven"]
    assert overdue[0]["days_overdue"] == 26
    assert overdue[0]["status"] == "not_due"


def test_a_delivered_promise_is_not_overdue(dirs):
    doc = json.loads(EARNINGS_FIXTURE.read_text())                  # first one is met
    write_earnings(dirs, doc)
    surface = rs.summarize(
        portfolio=portfolio(), catalysts={"earnings": []}, today=TODAY, now=NOW, **dirs
    )
    assert [row["commitment_id"] for row in surface["earnings"]["overdue_commitments"]] == []


def test_a_position_opened_after_the_gate_shipped_without_a_gate_is_flagged(dirs):
    surface = rs.summarize(
        portfolio=portfolio(first_buy="2026-08-01"), catalysts={"earnings": []},
        today=TODAY, now=NOW, **dirs,
    )
    assert surface["entry_gates"]["ungated_positions"] == [{
        "ticker": "USTEST",
        "issue": "opened after the gate shipped with no entry-gate artifact",
        "first_buy": "2026-08-01",
    }]


def test_positions_older_than_the_gate_are_not_retroactively_flagged(dirs):
    surface = rs.summarize(
        portfolio=portfolio(first_buy="2026-01-17"), catalysts={"earnings": []},
        today=TODAY, now=NOW, **dirs,
    )
    assert surface["entry_gates"]["ungated_positions"] == []


def test_holding_a_name_the_gate_rejected_is_flagged(dirs):
    doc = json.loads(GATE_FIXTURE.read_text())
    doc["checks"][0]["verdict"] = "fail"      # business_quality → computed reject
    doc["verdict"] = "reject"
    write_gate(dirs, doc)
    surface = rs.summarize(
        portfolio=portfolio(first_buy="2026-01-17"), catalysts={"earnings": []},
        today=TODAY, now=NOW, **dirs,
    )
    assert surface["entry_gates"]["ungated_positions"] == [{
        "ticker": "USTEST",
        "issue": "held after a reject verdict",
        "gate_id": "entry-USTEST-2026-07-20",
    }]
    assert surface["entry_gates"]["verdicts"] == {"reject": 1}


def test_gray_gate_questions_are_carried_into_the_queue(dirs):
    doc = json.loads(GATE_FIXTURE.read_text())
    for item in doc["evidence"]:
        item["source_class"] = "news_media"
    doc["information"] = {
        "grade": "C",
        "gaps": [
            "no primary issuer or structured source in the evidence set",
            "no supporting regulatory/exchange dataset",
            "media or analyst material is present and ranks below issuer sources",
        ],
        "source_classes": ["news_media"],
    }
    doc["verdict"] = "gray_needs_evidence"
    doc["next_evidence"] = [{"question": "Does the 10-K confirm the seat count?",
                             "where_to_look": "SEC 10-K Item 7"}]
    write_gate(dirs, doc)
    surface = rs.summarize(
        portfolio=portfolio(first_buy="2026-01-17"), catalysts={"earnings": []},
        today=TODAY, now=NOW, **dirs,
    )
    assert surface["entry_gates"]["open_questions"] == [{
        "ticker": "USTEST",
        "question": "Does the 10-K confirm the seat count?",
        "where_to_look": "SEC 10-K Item 7",
    }]


# --- integrity fails closed, work items only warn ----------------------------

def test_an_invalid_earnings_artifact_fails_the_integrity_check(dirs):
    doc = json.loads(EARNINGS_FIXTURE.read_text())
    doc["comparables"][1]["basis"] = "non_GAAP"
    write_earnings(dirs, doc)
    result = rs.check(portfolio=portfolio(first_buy="2026-01-17"),
                      catalysts={"earnings": []}, today=TODAY, now=NOW, **dirs)
    assert result["status"] == "fail"
    assert any("mixed basis" in error for error in result["errors"])


def test_a_gate_whose_verdict_no_longer_matches_fails_the_integrity_check(dirs):
    doc = json.loads(GATE_FIXTURE.read_text())
    doc["vetoes"][0].update(status="triggered", evidence_ids=["ev-10q"])
    write_gate(dirs, doc)                       # still claims pass_to_deep_research
    result = rs.check(portfolio=portfolio(first_buy="2026-01-17"),
                      catalysts={"earnings": []}, today=TODAY, now=NOW, **dirs)
    assert result["status"] == "fail"
    assert any("disagrees with the computed verdict" in e for e in result["errors"])


def test_an_artifact_filed_under_the_wrong_ticker_directory_fails(dirs):
    doc = json.loads(EARNINGS_FIXTURE.read_text())
    wrong = dirs["earnings_dir"] / "OTHER"
    wrong.mkdir()
    (wrong / "FY2026Q1.json").write_text(json.dumps(doc))
    result = rs.check(portfolio=portfolio(first_buy="2026-01-17"),
                      catalysts={"earnings": []}, today=TODAY, now=NOW, **dirs)
    assert result["status"] == "fail"
    assert any("does not match its directory" in error for error in result["errors"])


def test_work_items_warn_and_never_fail_a_publish(dirs):
    result = rs.check(portfolio=portfolio(first_buy="2026-08-01"),
                      catalysts=catalysts(), today=TODAY, now=NOW, **dirs)
    assert result["status"] == "warn"
    assert any("earnings review due" in warning for warning in result["warnings"])
    assert any("ungated position" in warning for warning in result["warnings"])
    assert result["errors"] == []


def test_a_clean_workspace_passes(dirs):
    result = rs.check(portfolio=portfolio(first_buy="2026-01-17"),
                      catalysts={"earnings": []}, today=TODAY, now=NOW, **dirs)
    assert result == {
        "status": "pass", "errors": [], "warnings": [],
        "counts": {"earnings_artifacts": 0, "entry_gates": 0, "theses": 0},
    }


def test_malformed_json_is_reported_not_ignored(dirs):
    (dirs["entry_gate_dir"] / "broken.json").write_text("{oops")
    (dirs["earnings_dir"] / "USTEST").mkdir()
    (dirs["earnings_dir"] / "USTEST" / "FY2026Q1.json").write_text("[")
    result = rs.check(portfolio=portfolio(first_buy="2026-01-17"),
                      catalysts={"earnings": []}, today=TODAY, now=NOW, **dirs)
    assert result["status"] == "fail"
    assert len(result["errors"]) == 2


def test_missing_directories_are_not_an_error(tmp_path):
    result = rs.check(portfolio=portfolio(first_buy="2026-01-17"),
                      catalysts={"earnings": []}, today=TODAY, now=NOW,
                      thesis_dir=tmp_path / "nope", earnings_dir=tmp_path / "nope",
                      entry_gate_dir=tmp_path / "nope")
    assert result["status"] == "pass"


def test_live_repository_artifacts_are_valid_right_now():
    """The same call the pre-push gate and the validate job make."""
    assert rs.check(now=NOW)["status"] in {"pass", "warn"}


# --- the consumers actually call it ------------------------------------------

def test_brief_preflight_puts_the_surface_in_the_daily_context():
    preflight = (ROOT / "scripts" / "harness" / "brief_preflight.py").read_text()
    assert "import research_surface" in preflight
    assert "'research_surface': research_surface_ctx," in preflight
    assert "research_surface.summarize(" in preflight


def test_daily_brief_skill_tells_the_model_what_to_do_with_it():
    skill = (ROOT / "skills" / "daily-deep-brief" / "SKILL.md").read_text()
    assert "research_surface" in skill
    for key in ("reviews_due", "overdue_commitments", "ungated_positions"):
        assert key in skill


def test_system_check_validates_artifacts_before_every_push():
    check = (ROOT / "scripts" / "system_check.py").read_text()
    assert "def check_research_artifacts(r):" in check
    assert "check_research_artifacts,\n    ]" in check
    assert "research_surface.check()" in check


def test_validate_workflow_runs_the_integrity_check():
    workflow = (ROOT / ".github" / "workflows" / "harness-regression.yml").read_text()
    assert "python3 scripts/data/research_surface.py --check" in workflow
    # and a bad artifact must be able to red that job
    for pattern in ("memory/theses/**", "memory/earnings/**", "memory/entry-gates/**"):
        assert pattern in workflow
    for pattern in ("memory/theses/*", "memory/earnings/*", "memory/entry-gates/*"):
        assert pattern in workflow


def test_cli_check_exits_nonzero_only_on_integrity_failure(tmp_path, capsys, monkeypatch):
    assert rs.main(["--check"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] in {"pass", "warn"}
    assert rs.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ready"
