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


def _run(tmp_path, failing=""):
    calls = tmp_path / "calls"
    gh = tmp_path / "gh"
    gh.write_text(f'#!/bin/sh\necho "$@" >> "{calls}"\n'
                  f'[ -n "{failing}" ] && [ "$3" = "{failing}" ] && exit 1\nexit 0\n')
    gh.chmod(0o755)
    result = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True,
                            env={"GH_BIN": str(gh), "PATH": "/usr/bin:/bin"})
    return result, calls.read_text().splitlines()


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
