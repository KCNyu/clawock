"""master's own CI conclusion had no reader (#1425 fallout).

On 2026-09-09 `validate` went red at 19:20Z and stayed red across **five
consecutive master pushes over eighteen hours**, every one of them a pure data
commit. `system_check` knew only the local workspace, `workflow_health.py`
filters to `event == "schedule"`, and the pull requests that did go red were
read by their authors as their own diff. Nothing measured master itself.

Everything here is driven through fakes, because the branches worth pinning are
the ones only a bad day reaches — a red master, an unfinished newest run, an
unreachable `gh`. A green live run exercises none of them, which is the same
reason the incident lasted eighteen hours.
"""
import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# Bare, not `from ops.ci import …`: conftest puts `ops/ci` on the path and
# `system_check` imports it by that name too, so this is the same module object
# it will reach. Two copies would make every monkeypatch below a no-op.
import master_ci_state as mcs

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 10, 13, 20, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def system_check():
    for path in (ROOT, ROOT / "src"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    spec = importlib.util.spec_from_file_location(
        "kcnyu_system_check_master_ci", ROOT / "ops" / "system_check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(conclusion, status="completed", sha="3a81d86b26ca", hours_ago=1.0,
         run_id=34440620504):
    started = NOW - timedelta(hours=hours_ago)
    return {
        "conclusion": conclusion,
        "status": status,
        "databaseId": run_id,
        "headSha": sha,
        "createdAt": started.isoformat().replace("+00:00", "Z"),
    }


def _runner(runs, gh_rc=0, stacked="0", raises=None, stdout=None):
    """A fake `gh`/`git` answering only the questions the module asks."""

    def run(argv, **kwargs):
        if argv[:2] == ["gh", "run"]:
            if raises is not None:
                raise raises
            body = json.dumps(runs) if stdout is None else stdout
            return subprocess.CompletedProcess(argv, gh_rc, body, "")
        if argv[:3] == ["git", "rev-list", "--count"]:
            return subprocess.CompletedProcess(argv, 0, stacked + "\n", "")
        raise AssertionError(f"unexpected command {argv}")

    return run


def _state(monkeypatch, runs, **kwargs):
    monkeypatch.setattr(mcs.shutil, "which", lambda _: "/usr/bin/gh")
    return mcs.read_state(runner=_runner(runs, **kwargs), now=NOW,
                          use_cache=False)


# ---------------------------------------------------------------- the fact


def test_a_green_master_says_so(monkeypatch):
    state = _state(monkeypatch, [_run("success")])
    assert state.state == "green"
    assert "3a81d86b" in state.summary()


def test_the_incident_shape_carries_both_numbers(monkeypatch):
    """2026-09-09/10, exactly. The hours and the stack are what turn "master is
    red" into something somebody acts on."""
    state = _state(monkeypatch, [_run("failure", sha="455aba24beef",
                                      hours_ago=18.0)], stacked="5")
    assert state.state == "red"
    assert (state.hours, state.stacked) == (18.0, 5)
    message = state.summary()
    assert "failure" in message and "455aba24" in message
    assert "18.0h ago" in message
    assert "5 commit(s) pushed on top since" in message
    assert "34440620504" in message


def test_an_unfinished_newest_run_is_not_a_verdict(monkeypatch):
    """master's newest run is usually still going; the answer is the one below
    it, not `unknown` and not the unfinished one's absent conclusion."""
    state = _state(monkeypatch, [
        _run(None, status="in_progress", sha="ffffffffffff"),
        _run("failure", sha="455aba24beef", hours_ago=3.0),
    ], stacked="2")
    assert (state.state, state.short_sha) == ("red", "455aba24")


# ------------------------------------------------- `unknown` is not `red`


@pytest.mark.parametrize("kwargs", [
    {"gh_rc": 1},
    {"raises": subprocess.TimeoutExpired("gh", 8)},
    {"stdout": "not json at all"},
])
def test_an_unreachable_gh_is_unknown_not_red(monkeypatch, kwargs):
    """A dropped connection, a rate limit and a garbled body are not evidence
    about master. A verdict here would teach its readers to skip the line."""
    assert _state(monkeypatch, [], **kwargs).state == "unknown"


def test_nothing_finished_yet_is_unknown(monkeypatch):
    assert _state(monkeypatch, [_run(None, status="in_progress")]).state == "unknown"


def test_no_gh_binary_is_unknown(monkeypatch):
    monkeypatch.setattr(mcs.shutil, "which", lambda _: None)
    assert mcs.read_state(runner=_runner([]), now=NOW,
                          use_cache=False).state == "unknown"


# ------------------------------------------------------------- the cache


def _counting_runner(runs, calls):
    inner = _runner(runs)

    def run(argv, **kwargs):
        if argv[:2] == ["gh", "run"]:
            calls.append(argv)
        return inner(argv, **kwargs)

    return run


def test_three_push_attempts_pay_for_one_gh_call(monkeypatch, tmp_path):
    """`safe_push.sh` attempts up to three times and each attempt is a fresh
    process, so an in-process memo would buy nothing. Measured: the `gh` call is
    1.4s against a 9.3s budget that `test_system_check_reads_without_spawning`
    exists to defend."""
    monkeypatch.setattr(mcs, "_CACHE", tmp_path / "runs.json")
    monkeypatch.setattr(mcs.shutil, "which", lambda _: "/usr/bin/gh")
    calls = []
    runner = _counting_runner([_run("failure", hours_ago=18.0)], calls)
    for _ in range(3):
        assert mcs.read_state(runner=runner, now=NOW).state == "red"
    assert len(calls) == 1


def test_a_cache_hit_still_reports_the_red_getting_older(monkeypatch, tmp_path):
    """Only the run LIST is cached. Age and the stack on top are recomputed from
    local git, or a stale red would keep claiming the hour it was first seen."""
    monkeypatch.setattr(mcs, "_CACHE", tmp_path / "runs.json")
    monkeypatch.setattr(mcs.shutil, "which", lambda _: "/usr/bin/gh")
    runner = _runner([_run("failure", hours_ago=1.0)], stacked="1")
    assert mcs.read_state(runner=runner, now=NOW).hours == pytest.approx(1.0)
    later = mcs.read_state(runner=_runner([], stacked="4"),
                           now=NOW + timedelta(hours=4))
    assert later.state == "red"
    assert later.hours == pytest.approx(5.0)
    assert later.stacked == 4


def test_an_expired_cache_asks_again(monkeypatch, tmp_path):
    monkeypatch.setattr(mcs, "_CACHE", tmp_path / "runs.json")
    monkeypatch.setattr(mcs.shutil, "which", lambda _: "/usr/bin/gh")
    calls = []
    runner = _counting_runner([_run("success")], calls)
    mcs.read_state(runner=runner, now=NOW)
    real_time = mcs.time.time
    monkeypatch.setattr(mcs.time, "time",
                        lambda: real_time() + mcs.CACHE_TTL + 1)
    mcs.read_state(runner=runner, now=NOW)
    assert len(calls) == 2


def test_a_corrupt_cache_is_not_a_verdict(monkeypatch, tmp_path):
    """A half-written cache must read as "ask again", never as `unknown` — an
    `unknown` is reported as silence, which is the outcome this module exists
    to avoid."""
    cache = tmp_path / "runs.json"
    cache.write_text('{"at": 99999999999, "runs": ')
    monkeypatch.setattr(mcs, "_CACHE", cache)
    monkeypatch.setattr(mcs.shutil, "which", lambda _: "/usr/bin/gh")
    assert mcs.read_state(runner=_runner([_run("success")]),
                          now=NOW).state == "green"


def test_the_daily_gate_does_not_read_the_hosts_cache(monkeypatch, tmp_path):
    """The cache is a pre-push economy. The once-a-day ask is the whole point of
    the daily gate; letting it answer from a saved list would make the day pass
    without anybody having asked."""
    seen = {}
    monkeypatch.setattr(mcs, "read_state",
                        lambda **kw: seen.update(kw) or mcs.State("green"))
    mcs.main([])
    assert seen == {"use_cache": False}


# ------------------------------------------------------ reader 1: the CLI


def test_strict_reddens_only_a_determined_red(monkeypatch, capsys):
    monkeypatch.setattr(mcs, "read_state", lambda **kw: mcs.State("red", "failure"))
    assert mcs.main(["--strict"]) == 1
    monkeypatch.setattr(mcs, "read_state",
                        lambda **kw: mcs.State("unknown", reason="gh down"))
    assert mcs.main(["--strict"]) == 0
    monkeypatch.setattr(mcs, "read_state", lambda **kw: mcs.State("green"))
    assert mcs.main(["--strict"]) == 0


def test_without_strict_it_only_reports(monkeypatch):
    monkeypatch.setattr(mcs, "read_state", lambda **kw: mcs.State("red", "failure"))
    assert mcs.main([]) == 0


def test_the_daily_gate_actually_runs_it():
    """A gate nobody wired in is the failure this whole change is about.

    Parsed, not grepped: the step above it exits non-zero on any missed slot
    (5 of its last 6 runs), so without `if: always()` this one is skipped on
    exactly the days it matters — the same trap the two steps before it carry a
    comment about."""
    yaml = pytest.importorskip("yaml")
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "cron-health.yml").read_text())
    steps = workflow["jobs"]["check"]["steps"]
    gate = [s for s in steps if "master_ci_state.py" in (s.get("run") or "")]
    assert len(gate) == 1, "the daily master-CI gate is not wired in"
    assert "--strict" in gate[0]["run"]
    assert gate[0].get("if") == "always()"
    assert "GH_TOKEN" in (gate[0].get("env") or {})


# --------------------------------------------- reader 2: the pre-push hook


def _check(system_check, monkeypatch, state, branch="master"):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(mcs, "read_state", lambda **kw: state)

    def run(argv, **kwargs):
        assert argv[:3] == ["git", "rev-parse", "--abbrev-ref"]
        return subprocess.CompletedProcess(argv, 0, branch + "\n", "")

    monkeypatch.setattr(subprocess, "run", run)
    result = system_check.Result()
    system_check.check_master_ci_conclusion(result)
    return result.checks


def test_the_hook_warns_on_red_and_never_blocks_the_fix(system_check, monkeypatch):
    """CRITICAL would refuse the very push that turns master green — the same
    reasoning that keeps `check_publish_backlog` at WARNING."""
    state = mcs.State("red", "failure", sha="455aba24beef",
                      run_id=1, hours=18.0, stacked=5)
    (name, severity, message), = _check(system_check, monkeypatch, state)
    assert (name, severity) == ("master CI", system_check.WARNING)
    assert severity != system_check.CRITICAL
    assert "18.0h ago" in message


def test_the_hook_reports_green(system_check, monkeypatch):
    (name, severity, _), = _check(system_check, monkeypatch,
                                  mcs.State("green", sha="3a81d86b26ca"))
    assert (name, severity) == ("master CI", system_check.OK)


def test_the_hook_is_silent_on_unknown(system_check, monkeypatch):
    assert _check(system_check, monkeypatch,
                  mcs.State("unknown", reason="gh down")) == []


def test_a_task_branch_judges_its_own_pr_not_master(system_check, monkeypatch):
    assert _check(system_check, monkeypatch, mcs.State("red", "failure"),
                  branch="claude/some-task") == []


def test_inside_actions_the_hook_does_not_judge_its_own_runs(
        system_check, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(mcs, "read_state", lambda **kw: mcs.State("red", "failure"))
    result = system_check.Result()
    system_check.check_master_ci_conclusion(result)
    assert result.checks == []


def test_it_is_registered_in_the_check_list(system_check):
    """A check nothing calls is a check nobody reads — the whole failure this
    one exists for."""
    body = (ROOT / "ops" / "system_check.py").read_text().split("def main(")[1]
    assert "check_master_ci_conclusion," in body
