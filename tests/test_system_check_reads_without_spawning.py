"""`ops/system_check.py` runs inside `.githooks/pre-push`, once per push ATTEMPT.

`safe_push.sh` attempts up to three times, so every second this script spends is
paid up to three times before anything is published. Profiled per check on the
live host, 2026-09-07 (11 cron jobs, 200 Python files):

    check_model_chain_health   37.32s   61.1%
    check_scripts_compile      10.49s   17.2%
    ...                                        61.06s total

Neither number was work. `check_model_chain_health` read the run history through
`auto`, which shells out to `openclaw cron runs --id` **once per job** —
33.66s where the same live SQLite answers in 0.16s, a conclusion
`ops/host/cron_token_audit.py` had already written down on 2026-07-18 and this
caller never got. `check_scripts_compile` spawned `python3 -m py_compile` **once
per file** — 200 interpreter startups to do what the builtin does in
milliseconds, and it left a `__pycache__` behind for each one: a check that
writes into the tree it is checking.

After: 8.7 / 9.0 / 9.5s for the same 25 checks and the same verdicts.

These tests are behavioural — the process is denied, not counted — because the
defect was never visible in what the checks *said*, only in what they did.
"""
import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def system_check():
    for path in (ROOT, ROOT / "src", ROOT / "ops" / "host"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    spec = importlib.util.spec_from_file_location(
        "spawnless_system_check", ROOT / "ops" / "system_check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ── the cron history ────────────────────────────────────────────────────────

def _state_db(path, runs):
    """A live openclaw store: two jobs, and the run rows given."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE cron_jobs (
                store_key TEXT NOT NULL, job_id TEXT NOT NULL,
                job_json TEXT NOT NULL, state_json TEXT NOT NULL,
                sort_order INTEGER NOT NULL, updated_at INTEGER NOT NULL);
            CREATE TABLE cron_run_logs (
                store_key TEXT NOT NULL, job_id TEXT NOT NULL,
                seq INTEGER NOT NULL, ts INTEGER NOT NULL,
                entry_json TEXT NOT NULL);
            """
        )
        for order, job_id in enumerate(("job-a", "job-b")):
            job = {"id": job_id, "name": f"cron {job_id}", "enabled": True,
                   "schedule": {"kind": "cron", "expr": "0 8 * * 1-5"}}
            conn.execute("INSERT INTO cron_jobs VALUES (?, ?, ?, ?, ?, ?)",
                         ("store", job_id, json.dumps(job), "{}", order, 1))
        for seq, (job_id, ts, error) in enumerate(runs, start=1):
            entry = {"jobId": job_id, "ts": ts, "status": "error",
                     "action": "finished", "runId": f"cron:{seq}", "error": error}
            conn.execute("INSERT INTO cron_run_logs VALUES (?, ?, ?, ?, ?)",
                         ("store", job_id, seq, ts, json.dumps(entry)))


def _no_cli(monkeypatch):
    """Deny the openclaw CLI. A per-job shell-out is the defect itself."""
    from clawock.providers import openclaw

    def refuse(*_args, **_kwargs):
        raise AssertionError(
            "system_check spawned the openclaw CLI — that is one process per "
            "job inside the pre-push hook")

    monkeypatch.setattr(openclaw, "cron_cli_json", refuse)


def test_a_dead_hop_is_still_named_without_spawning_a_cli_per_job(
        system_check, tmp_path, monkeypatch):
    _state_db(tmp_path / "state" / "openclaw.sqlite",
              [("job-a", 200, "opencode: Insufficient balance (billing)"),
               ("job-b", 100, "minimax: timeout after 180s")])
    monkeypatch.setenv("CLAWOCK_OPENCLAW_HOME", str(tmp_path))
    _no_cli(monkeypatch)

    result = system_check.Result()
    system_check.check_model_chain_health(result)

    assert result.checks, "the check produced no row at all"
    name, severity, message = result.checks[0]
    assert name == "model chain"
    assert severity == system_check.WARNING, (name, severity, message)
    assert "opencode" in message, message
    assert "minimax" not in message, (
        "a timeout is the chain working as designed; only billing/auth counts")


def test_a_healthy_chain_is_read_from_the_store_too(
        system_check, tmp_path, monkeypatch):
    _state_db(tmp_path / "state" / "openclaw.sqlite",
              [("job-a", 200, "minimax: timeout after 180s")])
    monkeypatch.setenv("CLAWOCK_OPENCLAW_HOME", str(tmp_path))
    _no_cli(monkeypatch)

    result = system_check.Result()
    system_check.check_model_chain_health(result)

    assert [(n, s) for n, s, _ in result.checks] == [("model chain",
                                                      system_check.OK)]


# ── compiling the sources ───────────────────────────────────────────────────

def _workspace(tmp_path, files):
    for relative, source in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    return tmp_path


def _no_subprocess(monkeypatch, system_check):
    def refuse(*_args, **_kwargs):
        raise AssertionError(
            "check_scripts_compile spawned a process — that is one interpreter "
            "startup per file inside the pre-push hook")

    monkeypatch.setattr(system_check.subprocess, "run", refuse)


def test_a_file_that_does_not_compile_is_still_critical(
        system_check, tmp_path, monkeypatch):
    workspace = _workspace(tmp_path, {
        "src/clawock/fine.py": "x = 1\n",
        "src/clawock/broken.py": "def f(:\n",
        "ops/also_fine.py": "y = 2\n",
    })
    monkeypatch.setattr(system_check, "WS", workspace)
    _no_subprocess(monkeypatch, system_check)

    result = system_check.Result()
    system_check.check_scripts_compile(result)

    name, severity, message = result.checks[0]
    assert severity == system_check.CRITICAL, (severity, message)
    assert "broken.py" in message and "fine.py" not in message, message


def test_checking_the_tree_does_not_write_into_it(
        system_check, tmp_path, monkeypatch):
    """py_compile's whole job is to emit bytecode; the check only ever wanted
    the verdict. A health check must not modify what it inspects."""
    workspace = _workspace(tmp_path, {"src/clawock/fine.py": "x = 1\n"})
    monkeypatch.setattr(system_check, "WS", workspace)
    _no_subprocess(monkeypatch, system_check)

    result = system_check.Result()
    system_check.check_scripts_compile(result)

    assert [s for _, s, _ in result.checks] == [system_check.OK]
    assert not list(workspace.rglob("__pycache__")), (
        "the check left bytecode behind in the tree it was checking")


def test_the_real_repository_still_compiles(system_check):
    """The check has to keep answering the question it exists for."""
    result = system_check.Result()
    system_check.check_scripts_compile(result)
    assert [s for _, s, _ in result.checks] == [system_check.OK], result.checks


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
