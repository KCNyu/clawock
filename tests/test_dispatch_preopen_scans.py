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


def _run(tmp_path, failing="", cancelled_once=""):
    calls = tmp_path / "calls"
    gh = tmp_path / "gh"
    # `workflow run <wf> …` dispatches; `run list … --workflow <wf> …` reports the
    # newest run's conclusion — "cancelled" the first time for `cancelled_once`.
    gh.write_text(f"""#!/bin/sh
echo "$@" >> "{calls}"
if [ "$1" = workflow ]; then
  [ -n "{failing}" ] && [ "$3" = "{failing}" ] && exit 1
  exit 0
fi
case "$*" in *"--workflow {cancelled_once or 'none'} "*)
  [ -e "{tmp_path}/seen" ] || {{ touch "{tmp_path}/seen"; echo cancelled; exit 0; }} ;;
esac
echo success
""")
    gh.chmod(0o755)
    result = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True,
                            env={"GH_BIN": str(gh), "PATH": "/usr/bin:/bin",
                                 "PREOPEN_SCAN_SETTLE_SECONDS": "0"})
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
    result, calls = _run(tmp_path, cancelled_once="sentiment-scan.yml")
    assert result.returncode == 0
    assert [c.split()[2] for c in calls] == [
        "macro-scan.yml", "sentiment-scan.yml", "sentiment-scan.yml"]
    assert "sentiment-scan.yml was cancelled in the queue — dispatched again" in result.stdout
