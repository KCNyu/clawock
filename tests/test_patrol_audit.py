"""Exercise the host supervisor without dispatching tasks or sending messages."""
import json
import os
from pathlib import Path
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "ops/host/patrol.sh"


@pytest.fixture
def patrol(tmp_path):
    dispatch = tmp_path / "dispatch"
    dispatch.mkdir()
    (dispatch / "limits.env").write_text("MAX_RUNNING=2\n")
    (dispatch / "resource-pressure.sh").write_text("memory_pressure_reason() { :; }\n")
    gh = tmp_path / "gh"
    gh.write_text('#!/bin/sh\ncat "$PATROL_STATE_DIR/issues.json"\nexit "${GH_EXIT:-0}"\n')
    gh.chmod(0o755)
    env = dict(os.environ, PATROL_DISPATCH_DIR=str(dispatch),
               PATROL_STATE_DIR=str(tmp_path), PATROL_TASKS_DIR=str(tmp_path / "tasks"),
               PATH=f"{tmp_path}:{os.environ['PATH']}")

    def run(command, issues=(), gh_exit=0):
        (tmp_path / "issues.json").write_text(json.dumps(issues))
        return subprocess.run(
            ["bash", "-c", 'source "$1"; ' + command, "test", str(SCRIPT)],
            env=dict(env, GH_EXIT=str(gh_exit)), capture_output=True, text=True, timeout=5,
        )

    return run


def test_only_ungated_issues_are_reported(patrol):
    result = patrol("audit_ungated 0", [
        {"number": 1, "title": "[patrol] gated", "body": "<!-- patrol-gate: passed -->"},
        {"number": 2, "title": "[patrol] bypass", "body": "no gate marker"},
        {"number": 3, "title": "[patrol] empty", "body": None},
    ])
    assert result.returncode == 0, result.stderr
    assert result.stdout == "#2 [patrol] bypass\n#3 [patrol] empty\n"


def test_successful_empty_audit_is_quiet(patrol):
    result = patrol("audit_ungated 0")
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_failed_query_is_not_a_clean_audit(patrol):
    # Even if gh emits valid empty JSON, its failure must propagate.
    result = patrol("audit_ungated 0", gh_exit=1)
    assert result.returncode != 0


def completed_round(tmp_path):
    rid = "patrol-recent-20260921-120000"
    task = tmp_path / "tasks" / rid
    task.mkdir(parents=True)
    (task / "meta.env").write_text("CREATED='2026-09-21 12:00:00'\n")
    (task / "result.env").write_text("STATE=ok\nOUTCOME=DONE\n")
    (tmp_path / "round-no").write_text("5\n")
    (tmp_path / "current-round").write_text(rid + "\n")
    (tmp_path / "recent-since").write_text("older\n")


ADOPT = '''
round_active() { return 1; }
prepare_worktree() { echo 'must not reset an adopted worktree' >&2; return 99; }
snapshot_issues() { return 99; }
notify() { printf '%s\\n' "$1" >>"$STATE/notifications"; }
run_round
'''


def test_bypass_reaches_log_and_notification(patrol, tmp_path):
    completed_round(tmp_path)
    result = patrol(ADOPT, [{"number": 2, "title": "[patrol] bypass", "body": ""}])
    assert result.returncode == 0, result.stdout + result.stderr
    assert "#2 [patrol] bypass" in (tmp_path / "ungated.log").read_text()
    assert "#2 [patrol] bypass" in (tmp_path / "notifications").read_text()
    assert not (tmp_path / "current-round").exists()


def test_failed_audit_keeps_round_for_retry_without_advancing_cursor(patrol, tmp_path):
    completed_round(tmp_path)
    result = patrol(ADOPT, gh_exit=1)
    assert result.returncode != 0
    assert "bypass status unknown" in result.stdout
    assert (tmp_path / "current-round").exists()
    assert (tmp_path / "recent-since").read_text() == "older\n"
    assert not (tmp_path / "rounds.tsv").exists()
    assert not (tmp_path / "notifications").exists()

    retry = patrol(ADOPT)
    assert retry.returncode == 0, retry.stdout + retry.stderr
    assert not (tmp_path / "current-round").exists()
    assert (tmp_path / "recent-since").read_text() == "2026-09-21 12:00:00\n"
    assert len((tmp_path / "rounds.tsv").read_text().splitlines()) == 1
