"""The research lifecycle must be used by recurring paths, not just shipped.

These tests hold two lines: the surface computes the right work queue from real
artifacts, and the three consumers (daily brief preflight, `system_check.py`,
the `validate` workflow) actually call it.
"""
import copy
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from clawock.evidence import research_surface as rs


ROOT = Path(__file__).resolve().parents[1]
INSTANCE_HARNESS = ROOT / "instances" / "kcnyu" / "src" / "clawock_kcnyu" / "harness"
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


@pytest.mark.parametrize(
    "event_time,now,expected",
    [
        # 00:28 HKT is still 12:28 ET on the event date: an AMC report has not
        # happened merely because the HKT calendar rolled over.
        ("amc", datetime(2026, 7, 30, 0, 28, tzinfo=timezone(timedelta(hours=8))), False),
        ("amc", datetime(2026, 7, 30, 4, 16, tzinfo=timezone(timedelta(hours=8))), True),
        ("bmo", datetime(2026, 7, 29, 9, 29, tzinfo=timezone(timedelta(hours=-4))), False),
        ("bmo", datetime(2026, 7, 29, 9, 30, tzinfo=timezone(timedelta(hours=-4))), True),
        ("unknown", datetime(2026, 7, 29, 23, 59, tzinfo=timezone(timedelta(hours=-4))), False),
        ("unknown", datetime(2026, 7, 30, 0, 0, tzinfo=timezone(timedelta(hours=-4))), True),
    ],
)
def test_earnings_queue_waits_for_the_event_to_mature(dirs, event_time, now, expected):
    event = {
        "ticker": "USTEST",
        "date": "2026-07-29",
        "time": event_time,
        "eps_actual": None,
    }
    surface = rs.summarize(
        portfolio=portfolio(),
        catalysts={"lookback_window_days": 14, "earnings": [event]},
        today=date(2026, 7, 30),
        now=now,
        **dirs,
    )
    assert bool(surface["earnings"]["reviews_due"]) is expected


def test_an_actual_result_matures_the_event_before_the_calendar_boundary(dirs):
    event = {
        "ticker": "USTEST",
        "date": "2026-07-29",
        "time": "amc",
        "eps_actual": 3.65,
    }
    surface = rs.summarize(
        portfolio=portfolio(),
        catalysts={"lookback_window_days": 14, "earnings": [event]},
        today=date(2026, 7, 30),
        now=datetime(2026, 7, 30, 0, 28, tzinfo=timezone(timedelta(hours=8))),
        **dirs,
    )
    assert [row["ticker"] for row in surface["earnings"]["reviews_due"]] == ["USTEST"]


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
    preflight = (INSTANCE_HARNESS / "brief_preflight.py").read_text()
    assert "research_surface" in preflight
    assert "'research_surface': research_surface_ctx," in preflight
    assert "research_surface.summarize(" in preflight


def test_daily_brief_skill_tells_the_model_what_to_do_with_it():
    skill = (ROOT / "skills" / "daily-deep-brief" / "SKILL.md").read_text()
    assert "research_surface" in skill
    for key in ("reviews_due", "overdue_commitments", "ungated_positions"):
        assert key in skill


def _registered_system_checks():
    """Names inside system_check's `checks = [...]` list, position-independent."""
    source = (ROOT / "ops" / "system_check.py").read_text()
    # `self.checks = []` appears earlier in the Result class, so anchor on the
    # registration list itself.
    block = source.split("\n    checks = [", 1)[1].split("]", 1)[0]
    return {line.strip().rstrip(",") for line in block.splitlines() if line.strip()}


def test_system_check_validates_artifacts_before_every_push():
    check = (ROOT / "ops" / "system_check.py").read_text()
    assert "def check_research_artifacts(r):" in check
    assert "check_research_artifacts" in _registered_system_checks()
    assert "research_surface.check()" in check


def test_validate_workflow_runs_the_integrity_check():
    workflow = (ROOT / ".github" / "workflows" / "harness-regression.yml").read_text()
    assert "clawock research --check" in workflow
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


# --- mover-scoped thesis context (intraday + report paths) -------------------

def _thesis(ticker="USTEST", state=None, red_line_status="triggered"):
    # A triggered *severe* red line forces state damaged/broken — the registry
    # validator enforces that, so the fixture has to respect it.
    state = state or ("damaged" if red_line_status == "triggered" else "weakening")
    return {
        "schema_version": 1,
        "thesis_id": f"{ticker.lower()}-core",
        "ticker": ticker,
        "strategy_scope": ["core_position"],
        "summary": "Platform economics carry the position.",
        "created_at": "2026-01-01T00:00:00+00:00",
        "checked_at": "2026-04-26T00:00:00+00:00",
        "state": state,
        "dimensions": {
            name: {"state": "unknown", "evidence_ids": []}
            for name in ("business", "moat", "management", "valuation")
        },
        "assumptions": [
            {"id": f"a-{i}", "claim": f"Assumption {i}", "test": "Metric holds",
             "cadence": "quarterly", "status": "unknown", "evidence_ids": []}
            for i in range(1, 4)
        ],
        "red_lines": [
            {"id": "cash-conversion",
             "condition": "OCF/net income below 0.8 for two periods",
             "severity": "severe", "status": red_line_status,
             "required_action": "Cut the position by half",
             "evidence_ids": ["ev-1"] if red_line_status == "triggered" else []},
            {"id": "dormant", "condition": "Customer concentration above 40%",
             "severity": "warning", "status": "clear",
             "required_action": "Reassess sizing", "evidence_ids": []},
        ],
        "valuation_anchors": [],
        "evidence": [{
            "evidence_id": "ev-1", "observed_at": "2026-04-25T00:00:00+00:00",
            "source_class": "issuer_filing", "locator": "filing:ev-1",
            "kind": "fundamental", "summary": "Cash conversion below threshold.",
        }],
        "next_review_trigger": {"type": "earnings", "description": "Next filing"},
    }


def test_nothing_moved_means_no_lookup(dirs):
    assert rs.movers_thesis_context([], now=NOW, thesis_dir=dirs["thesis_dir"],
                                    entry_gate_dir=dirs["entry_gate_dir"]) == {}
    assert rs.movers_thesis_context(None, now=NOW) == {}


def test_a_moving_name_surfaces_its_triggered_red_line_and_required_action(dirs):
    (dirs["thesis_dir"] / "USTEST.json").write_text(json.dumps(_thesis()))
    out = rs.movers_thesis_context(["USTEST"], now=NOW, thesis_dir=dirs["thesis_dir"],
                                   entry_gate_dir=dirs["entry_gate_dir"])
    entry = out["USTEST"]
    assert entry["status"] == "resolved"
    assert entry["state"] == "damaged"
    assert entry["red_lines"] == [{
        "id": "cash-conversion", "status": "triggered", "severity": "severe",
        "required_action": "Cut the position by half",
    }]
    assert entry["next_review_trigger"]["type"] == "earnings"


def test_clear_red_lines_are_left_out_of_a_report_sized_block(dirs):
    (dirs["thesis_dir"] / "USTEST.json").write_text(
        json.dumps(_thesis(red_line_status="watch")))
    entry = rs.movers_thesis_context(["USTEST"], now=NOW, thesis_dir=dirs["thesis_dir"],
                                     entry_gate_dir=dirs["entry_gate_dir"])["USTEST"]
    assert [row["id"] for row in entry["red_lines"]] == ["cash-conversion"]
    assert entry["red_lines"][0]["status"] == "watch"


def test_a_mover_without_a_baseline_reads_unknown(dirs):
    out = rs.movers_thesis_context(["NOBASELINE"], now=NOW,
                                   thesis_dir=dirs["thesis_dir"],
                                   entry_gate_dir=dirs["entry_gate_dir"])
    assert out["NOBASELINE"]["status"] == "unknown"
    assert "no canonical thesis baseline" in out["NOBASELINE"]["reason"]


def test_a_rejected_gate_is_flagged_on_the_moving_name(dirs):
    (dirs["thesis_dir"] / "USTEST.json").write_text(json.dumps(_thesis()))
    doc = json.loads(GATE_FIXTURE.read_text())
    doc["checks"][0]["verdict"] = "fail"
    doc["verdict"] = "reject"
    write_gate(dirs, doc)
    entry = rs.movers_thesis_context(["USTEST"], now=NOW, thesis_dir=dirs["thesis_dir"],
                                     entry_gate_dir=dirs["entry_gate_dir"])["USTEST"]
    assert entry["entry_gate"] == {"verdict": "reject", "gate_id": "entry-USTEST-2026-07-20"}


def test_a_broken_artifact_degrades_to_unknown_and_never_raises(dirs):
    (dirs["thesis_dir"] / "USTEST.json").write_text("{not json")
    out = rs.movers_thesis_context(["USTEST"], now=NOW, thesis_dir=dirs["thesis_dir"],
                                   entry_gate_dir=dirs["entry_gate_dir"])
    assert out["USTEST"]["status"] == "unknown"
    assert "invalid" in out["USTEST"]["reason"]


def test_a_missing_registry_directory_never_breaks_a_reporting_cron(tmp_path):
    out = rs.movers_thesis_context(["USTEST"], now=NOW,
                                   thesis_dir=tmp_path / "gone",
                                   entry_gate_dir=tmp_path / "gone")
    assert out["USTEST"]["status"] == "unknown"


def test_intraday_and_report_preflights_carry_mover_thesis():
    for name in ("intraday_preflight.py", "report_preflight.py"):
        source = (INSTANCE_HARNESS / name).read_text()
        assert "research_surface" in source, name
        assert "research_surface.movers_thesis_context(" in source, name
        assert "'mover_thesis'" in source, name
        # scoped to the names the slot already flagged, never the whole book
        assert "[a['ticker'] for a in anomalies]" in source, name


def test_both_stock_skills_frame_it_as_attribution_not_a_trigger():
    for name in ("us-stock-analysis", "hk-stock-analysis"):
        skill = (ROOT / "skills" / name / "SKILL.md").read_text()
        assert "mover_thesis" in skill, name
        assert "catalyst-gate" in skill, name


def test_calendar_coverage_is_reported_per_market():
    import sys
    sys.path.insert(0, str(ROOT / "scripts" / "data"))
    from clawock.market_data import sessions as trading_calendar

    coverage = trading_calendar.coverage(date(2026, 7, 26))
    assert set(coverage) == {"us", "hk"}
    for market, row in coverage.items():
        assert row["covers_current_year"] is True, market
        assert trading_calendar.LATEST_YEAR in row["years"], market


def test_system_check_watches_the_calendar_horizon():
    check = (ROOT / "ops" / "system_check.py").read_text()
    assert "def check_trading_calendar_horizon(r):" in check
    assert "check_trading_calendar_horizon" in _registered_system_checks()
    # the table is hand-maintained, so the gate must escalate rather than assume
    assert "covers_current_year" in check and "covers_next_year" in check


# --- earnings look-through: we hold the fund, the company reports -------------

def test_catalyst_tickers_come_from_holdings_not_a_hand_synced_list():
    from clawock.market_data import calendar as fetch_catalysts

    book = {"portfolios": {"us_stocks": {"holdings": [
        {"ticker": "MSFU", "shares": 20},     # 2x MSFT
        {"ticker": "PLTU", "shares": 14},     # 2x PLTR
        {"ticker": "CRCL", "shares": 2},      # reports itself
        {"ticker": "SOXL", "shares": 5},      # sector fund: nobody reports
        {"ticker": "TQQQ", "shares": 3},      # index fund: nobody reports
        {"ticker": "RKLX", "shares": 0},      # closed position
    ]}}}
    assert fetch_catalysts.us_earnings_tickers(book) == ["CRCL", "MSFT", "PLTR"]


@pytest.mark.parametrize("ticker,issuer", [
    ("MSFU", "MSFT"), ("PLTU", "PLTR"), ("RKLX", "RKLB"), ("SPCH", "SPCX"),
    ("CRCL", "CRCL"), ("SOXL", None), ("TQQQ", None), ("07226", None),
])
def test_earnings_issuer_resolution(ticker, issuer):
    from clawock.market_data import calendar as fetch_catalysts

    assert fetch_catalysts.earnings_issuer(ticker) == issuer


def test_a_report_by_a_tracked_company_marks_the_fund_position_due(dirs):
    book = {"portfolios": {"us_stocks": {"holdings": [
        {"ticker": "MSFU", "shares": 20,
         "trades": [{"date": "2026-01-05", "action": "buy", "shares": 20, "price": 40}]},
    ]}, "hk_stocks": {"holdings": []}}}
    surface = rs.summarize(
        portfolio=book,
        catalysts={"lookback_window_days": 14,
                   "earnings": [{"ticker": "MSFT", "date": "2026-07-29",
                                 "eps_actual": 1.0}]},
        today=date(2026, 7, 30), now=datetime(2026, 7, 30, tzinfo=timezone.utc), **dirs,
    )
    due = surface["earnings"]["reviews_due"]
    assert [row["ticker"] for row in due] == ["MSFT"]
    assert due[0]["held_via"] == "MSFU"


def test_a_fund_with_no_issuer_never_becomes_due(dirs):
    book = {"portfolios": {"us_stocks": {"holdings": [
        {"ticker": "TQQQ", "shares": 10, "trades": []},
    ]}, "hk_stocks": {"holdings": []}}}
    surface = rs.summarize(
        portfolio=book,
        catalysts={"lookback_window_days": 14,
                   "earnings": [{"ticker": "NASDAQ_100", "date": "2026-07-29"}]},
        today=date(2026, 7, 30), now=datetime(2026, 7, 30, tzinfo=timezone.utc), **dirs,
    )
    assert surface["earnings"]["reviews_due"] == []


# --- HK results watch: the only free advance signal (issue #99) ---------------

def _hk_positions():
    return [{"ticker": "00100", "region": "hk_stocks", "first_buy": "2026-01-05"},
            {"ticker": "CRCL", "region": "us_stocks", "first_buy": "2026-01-05"}]


def test_a_board_meeting_notice_flags_results_as_expected():
    feed = {"00100": [{"title": "董事会会议召开日期", "time": "2026-07-20 16:31:29"}]}
    out = rs.hk_results_expected(_hk_positions(), date(2026, 7, 26),
                                 fetch=lambda t: feed.get(t, []))
    assert out == [{
        "ticker": "00100", "status": "expected", "notice_date": "2026-07-20",
        "days_since_notice": 6,
        "reason": "board-meeting notice published; results follow, date is in the "
                  "announcement document and not in any free feed",
    }]


def test_us_holdings_are_not_probed_by_the_hk_watch():
    calls = []
    rs.hk_results_expected(
        [{"ticker": "CRCL", "region": "us_stocks"}], date(2026, 7, 26),
        fetch=lambda t: calls.append(t) or [],
    )
    assert calls == []


def test_an_artifact_after_the_notice_clears_the_expectation():
    feed = {"00100": [{"title": "董事会会议召开日期", "time": "2026-07-20 16:31:29"}]}
    artifacts = {"00100": [{"published_at": "2026-07-24T09:00:00+00:00"}]}
    assert rs.hk_results_expected(_hk_positions(), date(2026, 7, 26),
                                  artifacts=artifacts,
                                  fetch=lambda t: feed.get(t, [])) == []


def test_an_old_notice_falls_out_of_the_window():
    feed = {"00100": [{"title": "董事会会议召开日期", "time": "2026-01-05 16:31:29"}]}
    assert rs.hk_results_expected(_hk_positions(), date(2026, 7, 26),
                                  fetch=lambda t: feed.get(t, [])) == []


def test_a_dead_notice_feed_reports_unknown_rather_than_silence():
    def boom(ticker):
        raise OSError("connection reset")

    out = rs.hk_results_expected(_hk_positions(), date(2026, 7, 26), fetch=boom)
    assert out[0]["status"] == "unknown"
    assert "notice feed unavailable" in out[0]["reason"]


def test_the_watch_is_opt_in_and_the_daily_brief_opts_in():
    surface = rs.summarize(portfolio={"portfolios": {"hk_stocks": {"holdings": []},
                                                     "us_stocks": {"holdings": []}}},
                           catalysts={"earnings": []}, today=TODAY, now=NOW)
    assert surface["earnings"]["hk_results_expected"] == []
    preflight = (INSTANCE_HARNESS / "brief_preflight.py").read_text()
    assert "hk_watch=True" in preflight


# --- one look-through rule, three consumers -----------------------------------

@pytest.mark.parametrize("symbol,kind,issuer,tracks", [
    ("PLTU", "look_through", "PLTR", "PLTR"),
    ("MSFU", "look_through", "MSFT", "MSFT"),
    ("SPCH", "look_through", "SPCX", "SPCX"),
    ("CRCL", "issuer", "CRCL", None),
    ("00100", "issuer", "00100", None),
    ("SOXL", "index_fund", None, "SEMICONDUCTOR"),
    ("TQQQ", "index_fund", None, "NASDAQ_100"),
    ("07226", "index_fund", None, "HSTECH"),
    ("", "index_fund", None, None),
])
def test_registry_look_through_is_the_single_rule(symbol, kind, issuer, tracks):
    import sys
    sys.path.insert(0, str(ROOT / "scripts" / "data"))
    from clawock.portfolio import instruments as instrument_registry

    resolved = instrument_registry.look_through(symbol)
    assert (resolved["kind"], resolved["issuer"], resolved["tracks"]) == (kind, issuer, tracks)
    assert instrument_registry.issuer_for(symbol) == issuer


def test_news_digest_queries_issuers_and_records_the_fund_it_reads_for():
    digest = (ROOT / "scripts" / "data" / "gh_action_news_digest.py").read_text()
    # index funds are dropped rather than searched
    assert "if not issuer:\n            continue" in digest
    # the held fund stays visible in the artifact and in the prompt
    assert "'held_via': held_via or {}," in digest
    assert "持仓映射" in digest
