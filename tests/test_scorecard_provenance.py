"""A published scorecard number must name the rows it came from (#1113).

The tamper-evidence half of that issue is already answered by the ledger living
in a public git repository. What was missing is traversal: from a win rate on
the page to the exact slice of `memory/decisions.jsonl` that produced it, and a
way to tell whether that slice still says the same thing. These tests hold the
two properties that make the block worth publishing — it moves when the numbers
could move, and it does not move when only prose changed.
"""
import copy
import json

import pytest

from clawock import scorecard_provenance as prov
from clawock.decision import ledger as dv2
from clawock.evidence import scorecard_verify


def decision(day, ticker="AAA", strategy="core_position", action="hold_and_watch",
             benefit=1.0, capital=100.0):
    d = dv2.legacy_action_to_decision({
        "ticker": ticker, "strategy_id": strategy, "action": action,
        "condition": {"type": "open"}, "confidence": 0.6,
        "driven_by": "technical",
    }, day)
    d["episode_id"] = f"ep-{ticker.lower()}-{day}"
    d["evaluation"] = {
        "status": "settled", "triggered": True,
        "benefit_t1_pct": benefit, "benefit_t5_pct": benefit,
        "outcome": "win" if benefit > 0 else "loss",
        "capital": capital,
    }
    return d


@pytest.fixture
def ledger():
    return [
        decision("2026-07-02", ticker="AAA", benefit=2.0),
        decision("2026-07-03", ticker="BBB", action="cut", benefit=-1.0),
        decision("2026-07-04", ticker="CCC", action="trim", benefit=0.5),
    ]


def metrics_for(rows, cutoff="2026-07-01"):
    return dv2.compute_metrics(rows, window_days=365, cutoff=cutoff)


def test_scorecard_carries_the_window_counts_and_ledger_slice_it_was_computed_from(ledger):
    block = metrics_for(ledger)["provenance"]

    assert block["window"] == {
        "days": 365, "cutoff": "2026-07-01",
        "first_plan_date": "2026-07-02", "last_plan_date": "2026-07-04",
    }
    assert block["counts"]["raw_decisions"] == 3
    assert block["ledger"]["rows_total"] == 3
    assert block["ledger"]["slice_rows"] == 3
    assert block["ledger"]["slice_digest"] == prov.rows_digest(ledger)
    assert block["code"][0]["file"] == "ledger.py"


def test_the_counts_in_the_block_are_the_headline_counts_beside_it(ledger):
    metrics = metrics_for(ledger)

    for key, value in metrics["provenance"]["counts"].items():
        assert metrics[key] == value, f"{key} disagrees with its own provenance"


def test_digest_ignores_prose_and_moves_on_a_regrade(ledger):
    baseline = prov.rows_digest(ledger)

    reworded = copy.deepcopy(ledger)
    reworded[0]["rationale"] = "an entirely different explanation of the same call"
    reworded[0]["name"] = "renamed"
    assert prov.rows_digest(reworded) == baseline, (
        "editing prose must not look like a changed number")

    regraded = copy.deepcopy(ledger)
    regraded[0]["evaluation"]["benefit_t1_pct"] = -9.0
    regraded[0]["evaluation"]["outcome"] = "loss"
    assert prov.rows_digest(regraded) != baseline, (
        "a re-settled outcome is exactly the change a reader must be able to see")


def test_digest_is_order_independent(ledger):
    assert prov.rows_digest(list(reversed(ledger))) == prov.rows_digest(ledger)


def test_verify_passes_against_the_ledger_it_was_computed_from(ledger):
    result = prov.verify(metrics_for(ledger)["provenance"], ledger)

    assert result["ok"]
    assert [c["status"] for c in result["checks"]] == ["pass", "pass", "pass"]


def test_a_later_session_joining_the_ledger_is_growth_not_a_mismatch(ledger):
    block = metrics_for(ledger)["provenance"]

    grown = ledger + [decision("2026-07-05", ticker="DDD", benefit=3.0)]
    result = prov.verify(block, grown)

    assert result["ok"], "appending a later session must not read as tampering"
    statuses = {c["name"]: c["status"] for c in result["checks"]}
    assert statuses["ledger.slice_digest"] == "pass"
    assert statuses["ledger.digest"] == "moved"


def test_verify_fails_when_a_row_inside_the_published_window_is_regraded(ledger):
    block = metrics_for(ledger)["provenance"]

    regraded = copy.deepcopy(ledger)
    regraded[1]["evaluation"]["benefit_t1_pct"] = 12.0
    regraded[1]["evaluation"]["outcome"] = "win"
    result = prov.verify(block, regraded)

    assert not result["ok"]
    failed = [c for c in result["checks"] if c["status"] == "fail"]
    assert [c["name"] for c in failed] == ["ledger.slice_digest"]


def test_recorded_cutoff_makes_the_window_reproducible_off_the_clock(ledger):
    """The point of the cutoff being recorded rather than recomputed.

    `compute_metrics` defaults to "30 days before now", so a verifier running on
    a later day would score a different population and report a mismatch that is
    not a change to the published number.
    """
    first = metrics_for(ledger, cutoff="2026-07-03")
    second = dv2.compute_metrics(
        ledger, window_days=365,
        cutoff=first["provenance"]["window"]["cutoff"])

    assert second["provenance"]["ledger"]["slice_digest"] == \
        first["provenance"]["ledger"]["slice_digest"]
    assert first["raw_decisions"] == second["raw_decisions"] == 2


def test_recompute_reproduces_the_published_counts(ledger):
    block = metrics_for(ledger)["provenance"]

    assert scorecard_verify.recompute_headline(block, ledger)["ok"]

    dropped = [row for row in ledger if row["ticker"] != "BBB"]
    assert not scorecard_verify.recompute_headline(block, dropped)["ok"]


def _published(tmp_path, metrics, rows):
    payload = tmp_path / "dashboard.json"
    payload.write_text(json.dumps({"decision_metrics": metrics}), encoding="utf-8")
    ledger_file = tmp_path / "decisions.jsonl"
    ledger_file.write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return payload, ledger_file


def test_cli_check_reports_ok_then_fails_after_the_ledger_is_regraded(tmp_path, ledger, capsys):
    metrics = metrics_for(ledger)
    payload, ledger_file = _published(tmp_path, metrics, ledger)

    assert scorecard_verify.main(
        ["--check", "--metrics", str(payload), "--ledger", str(ledger_file)]) == 0
    assert "OK" in capsys.readouterr().out

    regraded = copy.deepcopy(ledger)
    regraded[0]["evaluation"]["benefit_t1_pct"] = -4.0
    _published(tmp_path, metrics, regraded)

    assert scorecard_verify.main(
        ["--check", "--metrics", str(payload), "--ledger", str(ledger_file)]) == 1
    assert "MISMATCH" in capsys.readouterr().out


def test_the_page_prints_the_slice_the_scorecard_came_from():
    """Frontend contract: provenance nobody can see is provenance nobody can use.

    The block is small enough to publish, so the card carries the four things a
    reader needs to go from a number to its rows — the file, the row count, the
    window, and the digest — plus the command that recomputes them.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    js = (root / "site" / "assets" / "js" / "dashboard.render.js").read_text(
        encoding="utf-8")
    tile = js.split("function renderPlanReview()", 1)[1].split("\n  function ", 1)[0]

    assert "calib.provenance" in tile, "the card never reads the provenance block"
    for field in ("slice_digest", "slice_rows", "code_commit",
                  "first_plan_date", "last_plan_date"):
        assert field in tile, f"the card drops {field} from what it shows"
    assert "scorecard-provenance --check" in tile, (
        "printing a digest without the command that checks it is decoration")

    html = (root / "site" / "index.html").read_text(encoding="utf-8")
    assert 'id="plan-provenance"' in html, "the line has nowhere to render"


def test_the_weekly_review_prompt_does_not_pay_for_publication_bookkeeping(ledger):
    """The block is for a public reader, not for the model.

    `decision_metrics` rides into the weekly-review prompt whole, and the block
    is ~1KB of digests and field names that answers none of the four review
    questions — the same reason `signal_provenance` is stripped there.
    """
    from clawock.automation import weekly_review as weekly

    metrics = metrics_for(ledger)
    assert "provenance" in metrics

    payload = weekly.build_prompt_payload({
        "week": "2026-W28", "window": "2026-07-01 -> 2026-07-08",
        "bundle_evidence": {}, "plans": [], "decision_episodes": [],
        "decision_metrics": metrics, "snapshots": [],
        "current_risk": {}, "input_warnings": [],
    })

    assert "provenance" not in payload["decision_metrics"]
    assert payload["decision_metrics"]["settled_episodes"] == \
        metrics["settled_episodes"], "dropping the block must not cost a number"
