"""The host starts the two pre-open scans itself (#2516).

GitHub delivered their schedules hours after the brief, so the brief read the
previous session's macro block. The script is the trigger the brief depends on:
it must ask for both workflows, and say so when one request fails.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ops" / "host" / "dispatch_preopen_scans.sh"


def _run(tmp_path, failing="", conclusions=None, no_run_for=""):
    """`conclusions` maps a workflow to what each of its dispatched runs ends as,
    in order (default: success); `no_run_for` accepts the dispatch but starts nothing."""
    calls = tmp_path / "calls"
    gh = tmp_path / "gh"
    for workflow, sequence in (conclusions or {}).items():
        (tmp_path / f"{workflow}.conclusions").write_text("\n".join(sequence) + "\n")
    # `workflow run <wf> …` dispatches and starts run N; `run list … --workflow <wf> …`
    # prints "<N> <conclusion>" for the newest run, or nothing when there is none.
    # Every workflow already has yesterday's run (id 1, success).
    gh.write_text(f"""#!/bin/sh
echo "$@" >> "{calls}"
if [ "$1" = workflow ]; then
  [ "$3" = "{failing}" ] && exit 1
  [ "$3" = "{no_run_for}" ] || echo run >> "{tmp_path}/$3.runs"
  exit 0
fi
while [ "$1" != --workflow ]; do shift; done
n=$(cat "{tmp_path}/$2.runs" 2>/dev/null | wc -l | tr -d ' ')
result=$(sed -n "${{n}}p" "{tmp_path}/$2.conclusions" 2>/dev/null)
case "$result" in "") result=success ;; running) result= ;; esac
echo "$((n + 1)) $result"
""")
    gh.chmod(0o755)
    result = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True,
                            env={"GH_BIN": str(gh), "PATH": "/usr/bin:/bin",
                                 "PREOPEN_SCAN_SETTLE_SECONDS": "0",
                                 "PREOPEN_SCAN_WAIT_SECONDS": "0",
                                 "PREOPEN_SCAN_POLL_SECONDS": "0"})
    dispatched = [c for c in calls.read_text().splitlines() if c.startswith("workflow run")]
    return result, dispatched


def test_both_scans_are_dispatched_on_master(tmp_path):
    result, calls = _run(tmp_path)
    assert result.returncode == 0
    assert calls == ["workflow run macro-scan.yml -R KCNyu/clawock --ref master",
                     "workflow run sentiment-scan.yml -R KCNyu/clawock --ref master"]


def test_one_failed_dispatch_is_reported_and_does_not_skip_the_other(tmp_path):
    result, calls = _run(tmp_path, failing="macro-scan.yml")
    assert result.returncode == 1
    assert len(calls) == 2
    assert "dispatch FAILED for macro-scan.yml" in result.stdout
    assert "dispatched sentiment-scan.yml" in result.stdout


def test_a_scan_cancelled_while_waiting_in_the_queue_is_dispatched_again(tmp_path):
    """The shared concurrency group cancels a waiting run when another member
    queues behind it; that happened to the sentiment scan on the first live run."""
    result, calls = _run(tmp_path, conclusions={"sentiment-scan.yml": ["cancelled"]})
    assert result.returncode == 0
    assert [c.split()[2] for c in calls] == [
        "macro-scan.yml", "sentiment-scan.yml", "sentiment-scan.yml"]
    assert "sentiment-scan.yml was cancelled in the queue — dispatched again" in result.stdout


def test_a_retry_that_is_cancelled_again_is_a_failure(tmp_path):
    """A second dispatch is not a scan that ran (#2549)."""
    result, calls = _run(tmp_path,
                         conclusions={"sentiment-scan.yml": ["cancelled", "cancelled"]})
    assert result.returncode == 1
    assert [c.split()[2] for c in calls] == [
        "macro-scan.yml", "sentiment-scan.yml", "sentiment-scan.yml"]
    assert "macro-scan.yml finished: success" in result.stdout
    assert "sentiment-scan.yml FAILED: run ended cancelled" in result.stdout


def test_a_scan_that_fails_is_a_failure_and_the_other_still_runs(tmp_path):
    result, calls = _run(tmp_path, conclusions={"macro-scan.yml": ["failure"]})
    assert result.returncode == 1
    assert [c.split()[2] for c in calls] == ["macro-scan.yml", "sentiment-scan.yml"]
    assert "macro-scan.yml FAILED: run ended failure" in result.stdout
    assert "sentiment-scan.yml finished: success" in result.stdout


def test_a_scan_still_running_when_the_wait_is_spent_is_not_reported_as_done(tmp_path):
    result, _ = _run(tmp_path, conclusions={"macro-scan.yml": ["running"]})
    assert result.returncode == 1
    assert "macro-scan.yml FAILED: run ended running" in result.stdout


def test_an_accepted_dispatch_that_starts_no_run_is_a_failure(tmp_path):
    """Yesterday's successful run must not be read as today's."""
    result, _ = _run(tmp_path, no_run_for="sentiment-scan.yml")
    assert result.returncode == 1
    assert "sentiment-scan.yml FAILED: run ended missing" in result.stdout
