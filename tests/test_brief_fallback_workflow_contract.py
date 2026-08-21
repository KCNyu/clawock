"""The backstop has to be able to run, and its silence has to be visible.

Between 2026-07-07 and 2026-08-21, brief-fallback had 34 scheduled runs. All 34
finished in 11-21 seconds on the "already exists" branch. The only five runs
that ever reached the generation branch were manual dispatches, and all five
failed. Nothing anywhere could see either fact, so the backstop read as healthy.

These assertions cover the three defects behind that, and they are written
against the mechanism rather than the wording, because the wording will change.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "brief-fallback.yml"


@pytest.fixture(scope="module")
def workflow() -> dict:
    # `on:` is the YAML 1.1 boolean True, which is why this reads it back with
    # a lookup rather than the obvious key.
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def job(workflow) -> dict:
    return workflow["jobs"]["fallback"]


@pytest.fixture(scope="module")
def triggers(workflow) -> dict:
    return workflow[True] if True in workflow else workflow["on"]


def _steps_by_name(job) -> dict:
    return {step.get("name", ""): step for step in job["steps"]}


def test_the_provider_chain_is_given_less_time_than_the_job(job):
    """The defect that killed every manual dispatch.

    `timeout` is per attempt, so timeout=900 with MAX_RETRIES=3 is a 45-minute
    budget for the primary alone — inside a job whose limit was 15 minutes. The
    runner killed the job mid-retry and opencode-go was never asked. A budget
    for the whole chain is the only thing that can express "finish in time".
    """
    budget = float(job["env"]["CLAWOCK_LLM_DEADLINE_SECONDS"])
    job_seconds = float(job["timeout-minutes"]) * 60
    assert budget < job_seconds, (
        "the LLM budget must fit inside the job, or the second provider is "
        "unreachable code rather than a fallback"
    )
    assert job_seconds - budget >= 300, (
        "postflight, the dashboard rebuild and the push still have to fit in "
        "what is left"
    )


def test_the_backstop_gets_more_than_one_shot_at_its_window(triggers):
    """Measured drift for this slot is +89..159 minutes, which lands the run at
    or past its own `HOUR >= 10 HKT` gate. One attempt is a coin flip; the skip
    check is idempotent, so extra attempts cost seconds."""
    weekday = [c["cron"] for c in triggers["schedule"] if c["cron"].endswith("1-5")]
    assert len(weekday) >= 3, "one scheduled attempt cannot absorb the measured drift"

    minutes = sorted(int(c.split()[0]) + 60 * int(c.split()[1]) for c in weekday)
    assert minutes[0] >= 25, (
        "nothing may fire before 00:25 UTC — earlier races the primary brief "
        "that is still generating, which is what produced a duplicate on 2026-06-10"
    )
    assert minutes[-1] <= 90, (
        "an attempt scheduled past 01:30 UTC cannot land inside the usefulness "
        "window even with no drift at all"
    )


def test_a_rehearsal_exists_and_can_never_publish(job):
    """Five manual dispatches all failed and nobody learned anything from it,
    because the only way to exercise the chain was to run it for real. A drill
    that could publish would not be a drill."""
    steps = _steps_by_name(job)
    rehearsal = next((n for n in steps if "Rehearsal" in n), None)
    assert rehearsal, "there must be a way to exercise the generation chain on purpose"

    publishing = [name for name, step in steps.items()
                  if "safe_push" in str(step.get("run", ""))
                  or "postflight" in str(step.get("run", ""))
                  or "Commit" in name]
    assert publishing, "this test is worthless if it stops matching the publishing steps"
    for name in publishing:
        assert "!= 'rehearsal'" in steps[name].get("if", ""), (
            f"step {name!r} can run during a rehearsal — a drill must not "
            "publish, commit or push"
        )


def test_the_rehearsal_fails_when_the_chain_produces_nothing(job):
    """A rehearsal that passes whatever happens answers no question at all."""
    steps = _steps_by_name(job)
    rehearsal = next(step for name, step in steps.items() if "Rehearsal" in name)
    run = rehearsal["run"]
    assert "::error::" in run and "exit 1" in run, (
        "the rehearsal must go red when no brief was produced"
    )


def test_the_rehearsal_runs_on_a_trading_day(triggers):
    """preflight on a closed market produces a red that says nothing about
    whether the backstop works — the false-red pattern this repo keeps paying
    for."""
    schedules = [c["cron"] for c in triggers["schedule"]]
    rehearsal = [c for c in schedules if not c.endswith("1-5")]
    assert rehearsal, "the rehearsal must be scheduled, not only dispatchable"
    for cron in rehearsal:
        dow = cron.split()[4]
        assert dow not in {"0", "6", "7"}, f"{cron} falls on a weekend"


def test_every_branch_of_the_skip_decision_is_recorded(job):
    """The whole defect was six weeks of green runs that never entered the
    generation branch, with nothing able to notice."""
    text = WORKFLOW.read_text(encoding="utf-8")
    decision = text.split("id: check", 1)[1].split("- name:", 1)[0]
    branches = set(re.findall(r'branch=([a-z-]+)', decision))
    assert branches == {"rehearsal", "already-exists", "too-late", "generated"}, (
        f"a skip path with no recorded branch is an invisible one: {branches}"
    )

    steps = _steps_by_name(job)
    recorder = next(step for name, step in steps.items() if "Record which branch" in name)
    assert recorder.get("if") == "always()", (
        "the branch record is the only trace a skipped run leaves; it cannot "
        "itself be conditional"
    )


def test_declining_to_help_is_a_warning_not_a_silence():
    """`too-late` means: the primary may have failed and nothing replaced it.
    That is the one outcome that must never scroll past unremarked."""
    text = WORKFLOW.read_text(encoding="utf-8")
    late = text.split('elif [ "$HOUR" -ge 10 ]', 1)[1].split("else", 1)[0]
    assert "::warning::" in late
