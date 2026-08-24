"""The health gate must catch a host crontab line pointing at a deleted file.

The #592 cleanup deleted `ops/growth/indexnow_submit.py` and the Nostr
broadcast script while the host crontab kept scheduling them, so both kept
"running" as silent no-ops that no repository-side gate could see (#663). This
pins the host-crontab anti-no-op check: a crontab command whose absolute path
under the live workspace (or the host tools directory) no longer exists is a
CRITICAL, and a missing or empty crontab is no finding at all — CI runners
have no crontab and must not redden over it.

Behavioural, not textual: the check is driven with a fake `crontab -l` so that
deleting its body, or making it blind to an empty crontab, turns these red.
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def system_check():
    for path in (ROOT, ROOT / "src"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    spec = importlib.util.spec_from_file_location(
        "kcnyu_system_check", ROOT / "ops" / "system_check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def host_roots(system_check, monkeypatch, tmp_path):
    """Point the gate's derived roots at scratch paths so the test never judges
    this machine's real workspace or tools directory."""
    workspace = tmp_path / "workspace"
    tools = tmp_path / "tools"
    launchers = tmp_path / ".local" / "bin"
    workspace.mkdir()
    tools.mkdir()
    launchers.mkdir(parents=True)
    monkeypatch.setattr(system_check, "LIVE_WORKSPACE", workspace)
    monkeypatch.setattr(system_check, "HOST_TOOLS_DIR", tools)
    monkeypatch.setattr(system_check, "LAUNCHER_BIN_DIR", launchers)
    return workspace, tools, launchers


def _run(system_check, monkeypatch, stdout="", returncode=0):
    def fake_crontab(*args, **kwargs):
        return subprocess.CompletedProcess(
            ["crontab", "-l"], returncode, stdout, "")

    monkeypatch.setattr(subprocess, "run", fake_crontab)
    result = system_check.Result()
    system_check.check_host_crontab_targets(result)
    return result.checks


def test_a_workspace_script_behind_python3_that_vanished_is_critical(
        system_check, monkeypatch, host_roots):
    workspace, _, _ = host_roots
    dead = workspace / "ops" / "growth" / "indexnow_submit.py"
    checks = _run(system_check, monkeypatch, stdout=(
        f"0 12 * * * /usr/bin/python3 {dead} >> {workspace}/logs/indexnow.log 2>&1\n"
    ))

    assert checks == [
        ("host crontab targets", system_check.CRITICAL,
         f"crontab points at missing file: {dead}"),
    ]


def test_a_tools_script_that_vanished_is_critical(
        system_check, monkeypatch, host_roots):
    _, tools, _ = host_roots
    dead = tools / "clawock-autoloop" / "run.sh"
    checks = _run(system_check, monkeypatch, stdout=f"0 23 * * * {dead}\n")

    assert checks == [
        ("host crontab targets", system_check.CRITICAL,
         f"crontab points at missing file: {dead}"),
    ]


def test_existing_scripts_keep_the_gate_green(
        system_check, monkeypatch, host_roots):
    workspace, _, _ = host_roots
    live = workspace / "ops" / "host" / "sync_us_cron_dst.py"
    live.parent.mkdir(parents=True)
    live.write_text("")
    checks = _run(system_check, monkeypatch, stdout=(
        f"0 8 * * * /usr/bin/python3 {live} --apply >> "
        f"{workspace}/logs/dst-sync.log 2>&1\n"
    ))

    assert checks == [("host crontab targets", system_check.OK,
                       "1 lines · no missing targets")]


def test_a_redirect_target_is_not_judged_as_a_missing_file(
        system_check, monkeypatch, host_roots):
    workspace, _, _ = host_roots
    live = workspace / "ops" / "host" / "sync_us_cron_dst.py"
    live.parent.mkdir(parents=True)
    live.write_text("")
    checks = _run(system_check, monkeypatch, stdout=(
        f"0 8 * * * /usr/bin/python3 {live} >> {workspace}/logs/never-written.log 2>&1\n"
    ))

    assert checks[0][1] == system_check.OK


def test_an_empty_crontab_is_not_a_finding(system_check, monkeypatch, host_roots):
    assert _run(system_check, monkeypatch, stdout="") == []


def test_an_unreadable_crontab_is_not_a_finding(
        system_check, monkeypatch, host_roots):
    assert _run(system_check, monkeypatch, stdout="", returncode=1) == []


def test_a_host_without_the_crontab_binary_is_not_a_finding(
        system_check, monkeypatch, host_roots):
    def no_crontab(*args, **kwargs):
        raise FileNotFoundError("no crontab on this host")

    monkeypatch.setattr(subprocess, "run", no_crontab)
    result = system_check.Result()
    system_check.check_host_crontab_targets(result)
    assert result.checks == []


def test_absolute_paths_outside_the_host_roots_are_not_judged(
        system_check, monkeypatch, host_roots):
    checks = _run(system_check, monkeypatch, stdout=(
        "0 9 * * * /usr/bin/python3 /opt/missing_thing.py\n"))

    assert checks == [("host crontab targets", system_check.OK,
                       "1 lines · no missing targets")]


def test_a_vanished_launcher_is_critical_not_skipped(
        system_check, monkeypatch, host_roots):
    """Every watchdog command in the contract starts with a ~/.local/bin
    launcher; before this root joined the audit those tokens were skipped, so
    a renamed launcher would have silenced the whole fallback layer invisibly
    (#775 class)."""
    launchers = host_roots[-1]
    dead = launchers / "clawock-brief-watchdog"
    checks = _run(system_check, monkeypatch, stdout=f"*/10 0-1 * * * {dead}\n")

    assert checks == [
        ("host crontab targets", system_check.CRITICAL,
         f"crontab points at missing file: {dead}"),
    ]


def test_a_present_launcher_stays_clean(system_check, monkeypatch, host_roots):
    launchers = host_roots[-1]
    alive = launchers / "clawock-intraday-watchdog"
    alive.write_text("#!/bin/sh\n")
    checks = _run(system_check, monkeypatch, stdout=f"*/10 22-23 * * * {alive}\n")

    assert checks == [("host crontab targets", system_check.OK,
                       "1 lines · no missing targets")]
