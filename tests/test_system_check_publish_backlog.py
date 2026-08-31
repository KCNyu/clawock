"""Commits that were made and never left the machine (#1241, #1242).

On 2026-08-31 a CRITICAL from `cron runtime contract` made the pre-push hook
refuse every push to master. The publisher kept committing on schedule, the
`data-plane` branch kept publishing fine, the dashboard looked alive — and six
commits sat unpushed for eight hours with nothing measuring it. The refusal went
to the stderr of a cron step, which nobody reads.

These drive both new checks through fakes, including the branches that only a
bad day reaches: a green run of the happy path proves nothing about them.
"""
import importlib.util
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def system_check():
    for path in (ROOT, ROOT / "src"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    spec = importlib.util.spec_from_file_location(
        "kcnyu_system_check_backlog", ROOT / "ops" / "system_check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(branch="master", count="0", oldest_epoch=None, rev_list_rc=0):
    """A fake `git` answering the three questions the check asks."""
    stamp = str(int(oldest_epoch if oldest_epoch is not None else time.time()))

    def run(argv, **kwargs):
        if argv[:3] == ["git", "rev-parse", "--abbrev-ref"]:
            return subprocess.CompletedProcess(argv, 0, branch + "\n", "")
        if argv[:3] == ["git", "rev-list", "--count"]:
            return subprocess.CompletedProcess(argv, rev_list_rc, count + "\n", "")
        if argv[:2] == ["git", "log"]:
            return subprocess.CompletedProcess(argv, 0, stamp + "\n", "")
        raise AssertionError(f"unexpected command {argv}")

    return run


def _backlog(system_check, monkeypatch, **kwargs):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(subprocess, "run", _git(**kwargs))
    result = system_check.Result()
    system_check.check_publish_backlog(result)
    return result.checks


def test_an_empty_backlog_reports_that_it_is_empty(system_check, monkeypatch):
    checks = _backlog(system_check, monkeypatch, count="0")
    assert checks == [("publish backlog", system_check.OK, "nothing unpushed")]


def test_the_incident_shape_is_a_warning(system_check, monkeypatch):
    """Six commits, oldest eight hours old — 2026-08-31, exactly."""
    checks = _backlog(system_check, monkeypatch, count="6",
                      oldest_epoch=time.time() - 8 * 3600)

    (name, severity, message), = checks
    assert (name, severity) == ("publish backlog", system_check.WARNING)
    assert "6 commit(s) unpushed" in message and "8.0h" in message


def test_one_commit_sitting_all_evening_is_also_caught(system_check, monkeypatch):
    """The quiet-session shape: under the count bound, over the time bound."""
    checks = _backlog(system_check, monkeypatch, count="1",
                      oldest_epoch=time.time() - 5 * 3600)

    assert checks[0][1] == system_check.WARNING


def test_a_normal_publish_cycle_is_not_a_backlog(system_check, monkeypatch):
    checks = _backlog(system_check, monkeypatch, count="1",
                      oldest_epoch=time.time() - 300)

    assert checks[0][1] == system_check.OK


def test_it_can_never_block_the_push_that_would_clear_it(system_check, monkeypatch):
    """The reason this is WARN and not CRITICAL, asserted rather than trusted.

    This check runs inside `.githooks/pre-push`. A CRITICAL here would refuse
    the very push that empties the backlog, and the measurement would become
    the thing keeping the number up.
    """
    for count, age in (("6", 8 * 3600), ("400", 96 * 3600)):
        checks = _backlog(system_check, monkeypatch, count=count,
                          oldest_epoch=time.time() - age)
        assert checks[0][1] != system_check.CRITICAL


def test_a_branch_that_does_not_publish_is_not_measured(system_check, monkeypatch):
    """Every interactive worktree is ahead of master and none of them publish."""
    assert _backlog(system_check, monkeypatch, branch="claude/some-task",
                    count="12") == []


def test_a_pr_checkout_on_actions_is_not_a_backlog(system_check, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(subprocess, "run", _git(count="99"))
    result = system_check.Result()
    system_check.check_publish_backlog(result)

    assert result.checks == []


def test_a_checkout_without_the_origin_ref_says_nothing(system_check, monkeypatch):
    """A fresh clone answers `rev-list` non-zero; that is absence, not health."""
    assert _backlog(system_check, monkeypatch, count="", rev_list_rc=128) == []


# --- model chain -----------------------------------------------------------

def _chain(system_check, monkeypatch, errors):
    fake = type(sys)("cron_runs")
    fake.load_job_map = lambda *a, **k: ({"job-1": "盘中盯盘"}, "cli")
    fake.load_entries = lambda *a, **k: ([{"error": e} for e in errors], {"cli"})
    monkeypatch.setitem(sys.modules, "cron_runs", fake)
    result = system_check.Result()
    system_check.check_model_chain_health(result)
    return result.checks[0]


ALL_THREE_FAILED = (
    "FallbackSummaryError: All models failed (3): "
    "minimax/MiniMax-M3: MiniMax response-header timeout after 60000ms (timeout) | "
    "minimax-2/MiniMax-M3: MiniMax response-header timeout after 60000ms (timeout) | "
    "zen/deepseek-v4-flash: 401 Insufficient balance. Manage your billing here: "
    "https://opencode.ai/workspace/wrk_x/billing (billing)"
)


def test_a_billing_dead_hop_is_named_and_the_timeouts_are_not(
        system_check, monkeypatch):
    """The distinction is the whole check.

    A timeout is the chain working: the retry succeeds and the report ships. A
    `401 Insufficient balance` never fixes itself, and retrying it only spends a
    round trip per slot — while the chain still reports as three hops long.
    """
    name, severity, message = _chain(system_check, monkeypatch, [ALL_THREE_FAILED])

    assert (name, severity) == ("model chain", system_check.WARNING)
    assert "zen/deepseek-v4-flash" in message
    assert "minimax" not in message, (
        "a hop that times out at the top of the hour is not a hop that is gone"
    )


def test_timeouts_alone_are_not_a_chain_failure(system_check, monkeypatch):
    only_timeouts = (
        "FallbackSummaryError: All models failed (2): "
        "minimax/MiniMax-M3: timeout after 60000ms (timeout) | "
        "minimax-2/MiniMax-M3: timeout after 60000ms (timeout)"
    )
    name, severity, _ = _chain(system_check, monkeypatch, [only_timeouts])

    assert (name, severity) == ("model chain", system_check.OK)


def test_a_dead_hop_is_reported_once_however_many_runs_hit_it(
        system_check, monkeypatch):
    """Every slot hits it; the desk needs one line, not forty."""
    _, _, message = _chain(system_check, monkeypatch, [ALL_THREE_FAILED] * 20)

    assert message.count("zen/deepseek-v4-flash") == 1
    assert message.startswith("1 hop(s)")


def test_a_host_without_openclaw_is_not_reported_as_healthy(
        system_check, monkeypatch):
    fake = type(sys)("cron_runs")
    fake.load_job_map = lambda *a, **k: ({}, "empty")
    monkeypatch.setitem(sys.modules, "cron_runs", fake)
    result = system_check.Result()
    system_check.check_model_chain_health(result)

    assert result.checks == [], "no chain to judge is not the same as a good one"
