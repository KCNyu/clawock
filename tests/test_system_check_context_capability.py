"""The health gate must look at a realized run, not only at the workspace.

`clawock context audit` verifies that the workspace still holds the documents
and capability roots. It stays green when the loss happens at assembly time —
the run itself came back with no skills or a narrowed tool set — which is the
failure #380 exists to prevent. This pins the gate that reads a real report.

Behavioural rather than textual: the check is driven with synthetic session
stores so that deleting its body, or making it blind to an empty catalog, turns
these red.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CRON = ["AGENTS.md", "SOUL.md", "TOOLS.md", "IDENTITY.md", "USER.md"]
INTERACTIVE = [*CRON, "HEARTBEAT.md", "MEMORY.md"]


@pytest.fixture(scope="module")
def system_check():
    for path in (ROOT, ROOT / "src", ROOT / "instances" / "kcnyu" / "src"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    spec = importlib.util.spec_from_file_location(
        "kcnyu_system_check", ROOT / "ops" / "system_check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _report(files, *, skills, provider, tools=("read", "memory_search")):
    return {
        "provider": provider,
        "injectedWorkspaceFiles": [
            {"name": name, "missing": False, "rawChars": 8,
             "injectedChars": 8, "truncated": False}
            for name in files
        ],
        "skills": {
            "hash": "h" if skills else "empty",
            "entries": [{"name": name} for name in skills],
        },
        "tools": {"entries": [
            {"name": name, "summaryHash": name, "schemaHash": f"{name}1"}
            for name in tools
        ]},
    }


def _run(system_check, monkeypatch, tmp_path, sessions):
    store = tmp_path / "sessions"
    store.mkdir(exist_ok=True)
    (store / "sessions.json").write_text(json.dumps(sessions), encoding="utf-8")

    class Paths:
        sessions_dir = store

    monkeypatch.setattr(system_check, "_OPENCLAW_PATHS", Paths)
    # This fixture describes a world with these sessions and no schedule. Without
    # saying so, the job-coverage check (#473) would read the real machine's cron
    # list and report all eleven live jobs as uncovered by synthetic sessions —
    # two different worlds compared against each other.
    monkeypatch.setattr("clawock.providers.openclaw.cron_cli_json",
                        lambda argv: {"jobs": []})
    result = system_check.Result()
    system_check.check_context_capability(result)
    return result.checks[0]


def test_a_healthy_pair_of_live_profiles_passes(system_check, monkeypatch, tmp_path):
    _, severity, message = _run(system_check, monkeypatch, tmp_path, {
        "agent:main:main": {
            "updatedAt": 20,
            "systemPromptReport": _report(
                INTERACTIVE, skills=("trading",), provider="minimax"),
        },
        "agent:main:cron:job-a": {
            "updatedAt": 19,
            "systemPromptReport": _report(
                CRON, skills=("trading",), provider="minimax"),
        },
    })
    assert severity == system_check.OK, message
    assert "interactive" in message and "isolated-cron" in message


def test_a_run_that_lost_its_skills_is_reported(system_check, monkeypatch, tmp_path):
    _, severity, message = _run(system_check, monkeypatch, tmp_path, {
        "agent:main:main": {
            "updatedAt": 20,
            "systemPromptReport": _report(
                INTERACTIVE, skills=(), provider="minimax"),
        },
    })
    # Warning, not critical: this gate blocks pre-push, and a narrowed context
    # says nothing about whether the book reconciles.
    assert severity == system_check.WARNING
    assert "skills_present" in message


def test_a_backend_that_delegates_skills_does_not_redden_the_gate(
        system_check, monkeypatch, tmp_path):
    """The live WeChat route runs on claude-cli, which gets the catalog as a
    plugin instead of a prompt block. Failing it would redden a working host
    every day, which is how a real warning stops being read."""
    _, severity, _ = _run(system_check, monkeypatch, tmp_path, {
        "agent:main:openclaw-weixin:direct:peer": {
            "updatedAt": 20,
            "systemPromptReport": _report(
                INTERACTIVE, skills=(), provider="claude-cli"),
        },
    })
    assert severity == system_check.OK


def test_only_the_newest_run_of_each_profile_is_judged(
        system_check, monkeypatch, tmp_path):
    """Old sessions are history. Judging them would report a loss that has
    already been fixed, and never clear."""
    _, severity, _ = _run(system_check, monkeypatch, tmp_path, {
        "agent:main:cron:old": {
            "updatedAt": 1,
            "systemPromptReport": _report(CRON, skills=(), provider="minimax"),
        },
        "agent:main:cron:new": {
            "updatedAt": 2,
            "systemPromptReport": _report(
                CRON, skills=("trading",), provider="minimax"),
        },
    })
    assert severity == system_check.OK


def test_a_host_without_a_session_store_is_not_a_finding(
        system_check, monkeypatch, tmp_path):
    """CI and any clean clone have no runtime beside them."""
    class Paths:
        sessions_dir = tmp_path / "absent"

    monkeypatch.setattr(system_check, "_OPENCLAW_PATHS", Paths)
    result = system_check.Result()
    system_check.check_context_capability(result)
    assert result.checks[0][1] == system_check.OK
