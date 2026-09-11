"""Contracts for the off-host brief backstop's rehearsal check.

Two things are under test and only one of them is the code:

  - the verdict logic, including the distinction this module exists for —
    "the rehearsal failed" and "I could not find out" must never produce the
    same answer;
  - the coupling to `brief-fallback.yml`. The rehearsal run is identified by the
    conclusions of two named steps, so a rename in the workflow would silently
    turn every run into `unknown` and the check would go quiet exactly the way
    the thing it replaced did. The workflow file is asserted against here.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ops.ci import backstop_rehearsal as br


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "brief-fallback.yml"
NOW = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)


def _steps(**names):
    return {"jobs": [{"steps": [{"name": n, "conclusion": c}
                                for n, c in names.items()]}]}


def _signature(generation, publish):
    return _steps(**{
        "Set up job": "success",
        br.GENERATION_STEP: generation,
        br.PUBLISH_STEP: publish,
    })


def fake_gh(runs, jobs):
    """A `gh` stand-in: `run list` yields `runs`, `api .../jobs` yields `jobs[id]`."""
    def runner(cmd):
        if cmd[:3] == ["gh", "run", "list"]:
            return json.dumps(runs)
        if cmd[:2] == ["gh", "api"]:
            run_id = int(cmd[2].split("/runs/")[1].split("/")[0])
            return json.dumps(jobs[run_id])
        raise AssertionError(f"unexpected command {cmd}")
    return runner


def _run(run_id, created_at, conclusion="success"):
    return {"databaseId": run_id, "createdAt": created_at,
            "conclusion": conclusion, "event": "schedule",
            "url": f"https://github.com/KCNyu/clawock/actions/runs/{run_id}"}


# --- classify -------------------------------------------------------------

@pytest.mark.parametrize("generation,publish,expected", [
    ("skipped", "skipped", "skipped"),      # already-exists / too-late
    ("success", "skipped", "rehearsal"),
    ("failure", "skipped", "rehearsal"),    # the case that matters
    ("success", "success", "generated"),
])
def test_classify_reads_the_branch_from_step_conclusions(generation, publish, expected):
    steps = {br.GENERATION_STEP: generation, br.PUBLISH_STEP: publish}
    assert br.classify(steps) == expected


def test_classify_returns_none_when_a_step_name_is_missing():
    """A renamed step must read as 'cannot tell', never as a branch."""
    assert br.classify({"Some Renamed Step": "success"}) is None
    assert br.classify({}) is None
    assert br.classify(None) is None


# --- assess ---------------------------------------------------------------

def test_failed_rehearsal_is_reported_as_fail_not_as_a_missing_run():
    runs = [_run(3, "2026-09-08T05:52:02Z"), _run(2, "2026-09-02T08:51:01Z", "failure")]
    jobs = {3: _signature("skipped", "skipped"),
            2: _signature("failure", "skipped")}
    verdict = br.assess(runner=fake_gh(runs, jobs), now=NOW)
    assert verdict["status"] == "fail"
    assert verdict["run_id"] == 2
    assert verdict["age_days"] == 6.1


def test_passing_rehearsal_is_pass():
    runs = [_run(3, "2026-09-08T05:52:02Z"), _run(2, "2026-09-02T08:51:01Z")]
    jobs = {3: _signature("skipped", "skipped"),
            2: _signature("success", "skipped")}
    assert br.assess(runner=fake_gh(runs, jobs), now=NOW)["status"] == "pass"


def test_a_real_fallback_run_is_not_mistaken_for_a_rehearsal():
    """`generated` commits; only the drill leaves the publish step skipped."""
    runs = [_run(9, "2026-09-07T01:00:00Z"), _run(2, "2026-09-02T08:51:01Z")]
    jobs = {9: _signature("success", "success"),      # generated, for real
            2: _signature("success", "skipped")}      # the rehearsal
    verdict = br.assess(runner=fake_gh(runs, jobs), now=NOW)
    assert verdict["run_id"] == 2


def test_stale_passing_rehearsal_is_overdue():
    runs = [_run(2, "2026-08-01T08:51:01Z")]
    jobs = {2: _signature("success", "skipped")}
    verdict = br.assess(runner=fake_gh(runs, jobs), now=NOW)
    assert verdict["status"] == "overdue"


def test_no_rehearsal_in_history_is_overdue_not_pass():
    """A drill that stopped firing is a fact, not an absence of facts."""
    runs = [_run(3, "2026-09-08T05:52:02Z")]
    jobs = {3: _signature("skipped", "skipped")}
    assert br.assess(runner=fake_gh(runs, jobs), now=NOW)["status"] == "overdue"


def test_broken_gh_is_unknown_never_pass_and_never_fail():
    def runner(cmd):
        raise RuntimeError("gh: could not connect")
    assert br.assess(runner=runner, now=NOW)["status"] == "unknown"


def test_unparseable_output_is_unknown():
    assert br.assess(runner=lambda cmd: "not json", now=NOW)["status"] == "unknown"


def test_renamed_steps_are_unknown_not_overdue():
    """The failure mode this check must not have: going quiet after a rename."""
    runs = [_run(3, "2026-09-08T05:52:02Z")]
    jobs = {3: _steps(**{"Totally Renamed": "success"})}
    verdict = br.assess(runner=fake_gh(runs, jobs), now=NOW)
    assert verdict["status"] == "unknown"
    assert "step names" in verdict["reason"]


# --- exit codes -----------------------------------------------------------

@pytest.mark.parametrize("status,strict_exit", [
    ("pass", 0), ("fail", 1), ("overdue", 1), ("unknown", 0),
])
def test_strict_exits_only_on_a_determined_failure(monkeypatch, capsys, status, strict_exit):
    monkeypatch.setattr(br, "assess", lambda: {"status": status, "reason": "r"})
    assert br.main(["--strict"]) == strict_exit
    assert br.main([]) == 0                     # never red without --strict
    capsys.readouterr()


# --- coupling to the workflow --------------------------------------------

def test_the_step_names_this_check_keys_on_still_exist_in_the_workflow():
    text = WORKFLOW.read_text(encoding="utf-8")
    for step in (br.GENERATION_STEP, br.PUBLISH_STEP):
        assert f"- name: {step}" in text, (
            f"backstop_rehearsal.py keys on the step {step!r}, which is no longer "
            f"in {WORKFLOW.name}. Update both together — a rename here makes every "
            "run read as 'unknown' and the check goes silent.")


def test_the_publish_step_is_still_skipped_on_a_rehearsal():
    """The whole discriminator rests on this condition; assert it is still there."""
    text = WORKFLOW.read_text(encoding="utf-8")
    publish = text.split(f"- name: {br.PUBLISH_STEP}", 1)[1].split("- name:", 1)[0]
    assert "branch != 'rehearsal'" in publish


def test_the_rehearsal_verdict_step_runs_even_when_the_chain_failed():
    """`if: always()` — the 2026-09-02 defect: the drill's verdict step was itself
    skipped by the failure it existed to report."""
    text = WORKFLOW.read_text(encoding="utf-8")
    block = text.split("- name: Rehearsal", 1)[1].split("run: |", 1)[0]
    assert "always()" in block


def test_cron_health_runs_this_check_and_does_not_skip_it_on_a_red_verdict():
    cron_health = (ROOT / ".github" / "workflows" / "cron-health.yml").read_text()
    assert "ops/ci/backstop_rehearsal.py --strict" in cron_health
    block = cron_health.split("- name: Off-host brief backstop", 1)[1].split("run:", 1)[0]
    assert "if: always()" in block, (
        "the cron health check exits non-zero on a miss; without always() this "
        "step is skipped on exactly the days somebody is reading the run")


# --- a decided failure is a warning until a date, never forever ------------

def test_an_accepted_failure_warns_until_its_date_then_reddens_again(monkeypatch, capsys):
    monkeypatch.setattr(br, "assess", lambda: {"status": "fail", "reason": "dead"})
    args = ["--strict", "--accepted-until", "2026-10-11", "--accepted-reason", "kcn 定的"]

    real = br._accepted
    monkeypatch.setattr(br, "_accepted", lambda until: real(
        until, today=datetime(2026, 10, 11).date()))
    assert br.main(args) == 0
    out = capsys.readouterr().out
    assert "::warning" in out and "dead" in out and "kcn 定的" in out

    monkeypatch.setattr(br, "_accepted", lambda until: real(
        until, today=datetime(2026, 10, 12).date()))
    assert br.main(args) == 1


def test_acceptance_needs_a_reason_and_a_readable_date(monkeypatch):
    monkeypatch.setattr(br, "assess", lambda: {"status": "fail", "reason": "dead"})
    with pytest.raises(SystemExit):
        br.main(["--strict", "--accepted-until", "2026-10-11"])
    assert br._accepted("not-a-date") is False
    assert br._accepted(None) is False


def test_cron_health_acceptance_is_dated():
    cron_health = (ROOT / ".github" / "workflows" / "cron-health.yml").read_text()
    block = cron_health.split("- name: Off-host brief backstop", 1)[1].split("- name:", 1)[0]
    assert "--accepted-until 20" in block and "--accepted-reason" in block
