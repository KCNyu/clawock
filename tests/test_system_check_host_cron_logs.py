"""The health gate must catch a host cron job that crashes on every run (#776).

`check_host_crontab_targets` gates the deleted-script half of this family: the
line fires, the file is gone, nothing sees it (#663). The other half is the file
being *there* and dying every time — which is how the DST synchroniser failed
eight days running on one `FileNotFoundError` with every repository-side gate
still green (#775). Host cron hands out no exit code, so the criterion is the
honest one: the last thing the job wrote looks like a crash.

Behavioural, driven through a fake `crontab -l` and scratch logs, so deleting
the check's body or making it blind to a traceback turns these red.
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]

TRACEBACK_TAIL = (
    "US cron DST: ok · daylight · openclaw=0 watchdog=0\n"
    "Traceback (most recent call last):\n"
    '  File "/x/sync_us_cron_dst.py", line 216, in <module>\n'
    "    raise SystemExit(main())\n"
    "FileNotFoundError: [Errno 2] No such file or directory: "
    "'/root/config/cron-schedules.json'\n"
)


@pytest.fixture(scope="module")
def system_check():
    for path in (ROOT, ROOT / "src"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    spec = importlib.util.spec_from_file_location(
        "kcnyu_system_check_logs", ROOT / "ops" / "system_check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def workspace(system_check, monkeypatch, tmp_path):
    ws = tmp_path / "workspace"
    (ws / "logs").mkdir(parents=True)
    monkeypatch.setattr(system_check, "LIVE_WORKSPACE", ws)
    return ws


def _crontab(workspace, *log_names):
    return "".join(
        f"20 6 * * * /usr/bin/python3 {workspace}/ops/host/job.py >> "
        f"{workspace}/logs/{name} 2>&1\n"
        for name in log_names
    )


def _run(system_check, monkeypatch, stdout="", returncode=0):
    def fake_crontab(*args, **kwargs):
        return subprocess.CompletedProcess(["crontab", "-l"], returncode, stdout, "")

    monkeypatch.setattr(subprocess, "run", fake_crontab)
    result = system_check.Result()
    system_check.check_host_cron_logs(result)
    return result.checks


def test_a_log_ending_in_a_traceback_warns(system_check, monkeypatch, workspace):
    (workspace / "logs" / "dst-sync.log").write_text(TRACEBACK_TAIL)

    checks = _run(system_check, monkeypatch, _crontab(workspace, "dst-sync.log"))

    assert len(checks) == 1
    name, severity, message = checks[0]
    assert (name, severity) == ("host cron logs", system_check.WARNING)
    assert "dst-sync.log" in message
    assert "cron-schedules.json" in message, "the operator needs the failing line itself"


def test_a_log_whose_last_run_succeeded_stays_green(
        system_check, monkeypatch, workspace):
    """A crash earlier in the file is history; the last run is the question."""
    (workspace / "logs" / "dst-sync.log").write_text(
        TRACEBACK_TAIL + "US cron DST: ok · daylight · openclaw=0 watchdog=0\n")

    checks = _run(system_check, monkeypatch, _crontab(workspace, "dst-sync.log"))

    assert checks == [("host cron logs", system_check.OK,
                       "1 host cron logs · none end on a crash")]


def test_trailing_blank_lines_do_not_hide_the_crash(
        system_check, monkeypatch, workspace):
    (workspace / "logs" / "dst-sync.log").write_text(TRACEBACK_TAIL + "\n\n   \n")

    checks = _run(system_check, monkeypatch, _crontab(workspace, "dst-sync.log"))

    assert checks[0][1] == system_check.WARNING


def test_only_the_tail_is_read(system_check, monkeypatch, workspace):
    """The publisher's log is already several MB; this must not slurp it."""
    log = workspace / "logs" / "publish_dashboard.log"
    log.write_text(("· data-plane: already holds this generation\n" * 200000)
                   + "· data-plane: already holds this generation\n")
    assert log.stat().st_size > system_check.HOST_CRON_LOG_TAIL_BYTES * 100

    checks = _run(system_check, monkeypatch,
                  _crontab(workspace, "publish_dashboard.log"))

    assert checks[0][1] == system_check.OK


def test_a_shell_failure_line_counts_as_a_crash(system_check, monkeypatch, workspace):
    (workspace / "logs" / "gold_dca.log").write_text(
        "/bin/bash: line 1: python4: command not found\n")

    checks = _run(system_check, monkeypatch, _crontab(workspace, "gold_dca.log"))

    assert checks[0][1] == system_check.WARNING


def test_each_crashed_job_is_reported_separately(
        system_check, monkeypatch, workspace):
    (workspace / "logs" / "dst-sync.log").write_text(TRACEBACK_TAIL)
    (workspace / "logs" / "gc_sessions.log").write_text(
        "PermissionError: [Errno 13] Permission denied: '/root/x'\n")
    (workspace / "logs" / "indexnow.log").write_text("IndexNow HTTP 200 — 91 URL(s)\n")

    checks = _run(system_check, monkeypatch, _crontab(
        workspace, "dst-sync.log", "gc_sessions.log", "indexnow.log"))

    assert len(checks) == 2
    assert {c[1] for c in checks} == {system_check.WARNING}
    assert {"dst-sync.log", "gc_sessions.log"} == {c[2].split()[0] for c in checks}


def test_a_never_written_log_is_not_a_finding(system_check, monkeypatch, workspace):
    """A job that has not run yet, and `gitgc.log`, which is legitimately empty."""
    (workspace / "logs" / "gitgc.log").write_text("")

    assert _run(system_check, monkeypatch,
                _crontab(workspace, "gitgc.log", "never-written.log")) == []


def test_logs_outside_the_workspace_are_not_judged(
        system_check, monkeypatch, workspace, tmp_path):
    foreign = tmp_path / "elsewhere.log"
    foreign.write_text(TRACEBACK_TAIL)

    checks = _run(system_check, monkeypatch,
                  f"0 9 * * * /usr/bin/some-tool >> {foreign} 2>&1\n")

    assert checks == []


def test_an_empty_crontab_is_not_a_finding(system_check, monkeypatch, workspace):
    assert _run(system_check, monkeypatch, stdout="") == []


def test_an_unreadable_crontab_is_not_a_finding(system_check, monkeypatch, workspace):
    assert _run(system_check, monkeypatch, stdout="x", returncode=1) == []


def test_a_host_without_the_crontab_binary_is_not_a_finding(
        system_check, monkeypatch, workspace):
    def no_crontab(*args, **kwargs):
        raise FileNotFoundError("no crontab on this host")

    monkeypatch.setattr(subprocess, "run", no_crontab)
    result = system_check.Result()
    system_check.check_host_cron_logs(result)
    assert result.checks == []
