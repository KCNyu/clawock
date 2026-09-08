"""Contracts for the scheduled-workflow punctuality gate.

The defect being fenced off is not a bug in this module — it is that
`assets/data/schedule-drift.json` was measured twice a week for three weeks with
no consumer, while five workflow headers asserted a punctuality budget in prose.
So the enumeration test matters as much as the logic ones: a workflow that
acquires a deadline without declaring it here puts the design straight back into
prose nobody checks.
"""

import datetime as dt
import json
import re
from pathlib import Path

import pytest

from ops.ci import schedule_punctuality as sp


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
CONTRACT = json.loads((ROOT / "config" / "schedule-punctuality.json").read_text())
RULES = CONTRACT["workflows"]


def _scheduled_workflows():
    return sorted(
        path.name for path in WORKFLOW_DIR.glob("*.yml")
        if re.search(r"^\s*-\s*cron:", path.read_text(encoding="utf-8"), re.M)
    )


def _run(scheduled_at, started_at):
    return {"scheduled_at": scheduled_at, "started_at": started_at}


def _drift(workflow, runs):
    return {"generated_at": "2026-09-08T08:19:10Z",
            "workflows": [{"workflow": workflow, "runs": runs}]}


# --- the enumeration gate -------------------------------------------------

def test_every_scheduled_workflow_is_classified():
    missing = set(_scheduled_workflows()) - set(RULES)
    assert not missing, (
        f"{sorted(missing)} run on a schedule but declare no punctuality budget. "
        "Add an entry to config/schedule-punctuality.json — a deadline_hkt, or "
        "null with the reason it has none. A workflow whose timing matters and "
        "says so only in a header comment is how brief-fallback's mitigation "
        "expired without anything noticing.")


def test_the_contract_names_no_workflow_that_stopped_existing():
    stale = set(RULES) - set(_scheduled_workflows())
    assert not stale, f"{sorted(stale)} is in the contract but no longer scheduled"


@pytest.mark.parametrize("name", sorted(RULES))
def test_every_entry_gives_a_reason(name):
    assert RULES[name].get("why", "").strip(), (
        f"{name} must say why it has (or has not) a deadline")


@pytest.mark.parametrize("name", sorted(RULES))
def test_every_deadline_declares_a_known_enforcement(name):
    rule = RULES[name]
    if not rule.get("deadline_hkt"):
        return
    assert rule.get("enforcement") in CONTRACT["enforcement"], (
        f"{name}: enforcement must be one of {sorted(CONTRACT['enforcement'])}")


@pytest.mark.parametrize("name", sorted(RULES))
def test_deadlines_are_well_formed(name):
    deadline = RULES[name].get("deadline_hkt")
    if deadline is not None:
        assert re.fullmatch(r"\d{2}:\d{2}", deadline), f"{name}: {deadline!r}"


# --- deadline_instant -----------------------------------------------------

def test_a_deadline_later_the_same_day_belongs_to_that_day():
    scheduled = dt.datetime(2026, 9, 8, 21, 45, tzinfo=dt.timezone.utc)   # 05:45 HKT
    assert sp.deadline_instant(scheduled, "08:00").strftime("%m-%d %H:%M") == "09-09 08:00"


def test_an_evening_run_is_measured_against_the_next_mornings_deadline():
    """20:50 HKT feeds tomorrow's 08:00 brief, not one that is already over."""
    scheduled = dt.datetime(2026, 9, 8, 12, 50, tzinfo=dt.timezone.utc)   # 20:50 HKT
    assert sp.deadline_instant(scheduled, "08:00").strftime("%m-%d %H:%M") == "09-09 08:00"


# --- verdicts -------------------------------------------------------------

def _five_late():
    return [_run(f"2026-09-0{d}T00:25:00Z", f"2026-09-0{d}T05:00:00Z") for d in range(1, 6)]


def test_a_sustained_breach_of_an_enforced_deadline_is_red():
    rule = {"deadline_hkt": "10:00", "enforcement": "enforced"}
    assert sp.assess_workflow(rule, _five_late())["status"] == "breached"


def test_a_sustained_breach_of_an_accepted_deadline_is_recorded_not_red():
    """`accepted` is a written decision about an unfixable breach, not a lie:
    the row still shows the misses, it just does not redden the daily run."""
    rule = {"deadline_hkt": "10:00", "enforcement": "accepted"}
    verdict = sp.assess_workflow(rule, _five_late())
    assert verdict["status"] == "accepted-breach"
    assert verdict["late"] == 5


def test_one_bad_day_is_a_warning_not_a_verdict():
    runs = _five_late()[:1] + [
        _run(f"2026-09-0{d}T00:25:00Z", f"2026-09-0{d}T01:00:00Z") for d in range(2, 7)]
    verdict = sp.assess_workflow({"deadline_hkt": "10:00", "enforcement": "enforced"}, runs)
    assert verdict["status"] == "late-sometimes"
    assert verdict["late"] == 1


def test_punctual_runs_are_ok():
    runs = [_run(f"2026-09-0{d}T00:25:00Z", f"2026-09-0{d}T00:40:00Z") for d in range(1, 6)]
    assert sp.assess_workflow({"deadline_hkt": "10:00"}, runs)["status"] == "ok"


def test_fewer_samples_than_the_window_cannot_reach_a_verdict():
    """Three late runs are not evidence that the bet is structurally lost."""
    runs = _five_late()[:3]
    verdict = sp.assess_workflow({"deadline_hkt": "10:00", "enforcement": "enforced"}, runs)
    assert verdict["status"] == "late-sometimes"


def test_no_deadline_short_circuits():
    assert sp.assess_workflow({"deadline_hkt": None}, _five_late())["status"] == "no-deadline"


def test_a_workflow_with_no_drift_samples_is_unmeasured_not_ok():
    verdict = sp.assess_workflow({"deadline_hkt": "08:00"}, [])
    assert verdict["status"] == "unmeasured"


# --- report + exit codes --------------------------------------------------

def test_report_flags_only_enforced_breaches():
    contract = {"enforcement": {"enforced": "", "accepted": ""}, "workflows": {
        "a.yml": {"deadline_hkt": "10:00", "enforcement": "enforced", "why": "x"},
        "b.yml": {"deadline_hkt": "10:00", "enforcement": "accepted", "why": "x"},
    }}
    drift = {"generated_at": "2026-09-08T08:19:10Z", "workflows": [
        {"workflow": "a.yml", "runs": _five_late()},
        {"workflow": "b.yml", "runs": _five_late()},
    ]}
    result = sp.report(contract=contract, drift=drift)
    assert result["breached"] == ["a.yml"]
    assert result["status"] == "breached"


def test_an_unreadable_drift_file_is_unknown_and_never_red(capsys):
    """A missing measurement must not be reported as a met deadline, and must
    not redden a run either — same rule as backstop_rehearsal's `unknown`."""
    result = sp.report(contract=CONTRACT, drift=None)
    assert result["status"] == "unknown"
    capsys.readouterr()


def test_the_real_loader_also_reaches_unknown_when_the_file_is_gone(monkeypatch, tmp_path):
    """Not just the injected seam: the production path with no drift file on
    disk must reach the same verdict."""
    monkeypatch.setattr(sp, "DRIFT", tmp_path / "nope.json")
    assert sp.report()["status"] == "unknown"
    assert sp.main(["--strict"]) == 0


def test_strict_exits_1_only_on_a_breach(monkeypatch, capsys):
    monkeypatch.setattr(sp, "report", lambda: {"status": "breached", "breached": ["a.yml"],
                                               "measured_at": "2026-09-08T08:19:10Z",
                                               "workflows": {}})
    assert sp.main(["--strict"]) == 1
    assert sp.main([]) == 0
    monkeypatch.setattr(sp, "report", lambda: {"status": "unknown", "reason": "no file",
                                               "workflows": {}})
    assert sp.main(["--strict"]) == 0
    capsys.readouterr()


# --- coupling to the daily run -------------------------------------------

def test_cron_health_runs_the_gate_and_does_not_skip_it_on_a_red_verdict():
    cron_health = (WORKFLOW_DIR / "cron-health.yml").read_text(encoding="utf-8")
    assert "ops/ci/schedule_punctuality.py --strict" in cron_health
    block = cron_health.split("- name: Scheduled-workflow punctuality", 1)[1].split("run:", 1)[0]
    assert "if: always()" in block


def test_the_repo_still_produces_the_measurement_this_gate_consumes():
    """The gate is only as alive as its input; repo-traffic writes the samples."""
    traffic = (WORKFLOW_DIR / "repo-traffic.yml").read_text(encoding="utf-8")
    assert "schedule_drift.py" in traffic
