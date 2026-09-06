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


# ── the schedule, once ──────────────────────────────────────────────────────

def _listing(source, jobs):
    from clawock.providers.openclaw import CronRead
    return CronRead(jobs, source)


def _counting_reader(system_check, monkeypatch, result):
    reads = []
    monkeypatch.setattr(system_check, "openclaw_read_jobs",
                        lambda *a, **k: reads.append(1) or result)
    system_check._cron_listing.cache_clear()
    return reads


def test_the_schedule_is_read_once_for_the_whole_run(system_check, monkeypatch):
    """Two checks need the cron listing. Each used to fetch its own, and the
    fetch is an `openclaw cron list --json` subprocess: two 3.1-3.3s spawns
    inside a 10.3s run, inside the pre-push hook, once per push attempt.

    Counted at the provider, not at the memo, so this says the same thing about
    the code that has no memo.
    """
    from clawock.providers import openclaw

    spawns = []
    monkeypatch.setattr(openclaw, "cron_cli_json", lambda *a, **k: spawns.append(1) or {
        "jobs": [{"id": "job-a", "name": "cron a", "enabled": True,
                  "status": "ok", "state": {"lastRunStatus": "ok"},
                  "schedule": {"kind": "cron", "expr": "0 8 * * 1-5"}}]})
    if hasattr(system_check, "_cron_listing"):
        system_check._cron_listing.cache_clear()

    for call in (lambda: system_check.check_cron_paths_exist(system_check.Result()),
                 lambda: system_check._cron_jobs_without_prompt_report({})):
        try:
            call()
        except Exception:  # noqa: BLE001 — the spawn count is the assertion
            pass

    assert len(spawns) == 1, (
        f"the schedule was fetched {len(spawns)} times in one run; each fetch "
        f"is a subprocess")


def test_a_new_run_does_not_inherit_the_last_snapshot(system_check, monkeypatch):
    """The memo is for the seconds one process lives. `main()` clears it, and so
    must anything that drives these checks twice against different stores."""
    first = _listing("cli", [{"id": "one", "name": "one", "enabled": True}])
    second = _listing("cli", [{"id": "two", "name": "two", "enabled": True}])
    monkeypatch.setattr(system_check, "openclaw_read_jobs", lambda *a, **k: first)
    system_check._cron_listing.cache_clear()

    assert system_check._cron_listing()[0].entries[0]["id"] == "one"
    monkeypatch.setattr(system_check, "openclaw_read_jobs", lambda *a, **k: second)
    assert system_check._cron_listing()[0].entries[0]["id"] == "one", (
        "the memo did not hold, so both checks pay for their own read")
    system_check._cron_listing.cache_clear()
    assert system_check._cron_listing()[0].entries[0]["id"] == "two"


def test_prompt_report_coverage_still_declines_a_non_cli_listing(
        system_check, monkeypatch):
    """It reads the CLI's flattened `status` to skip a job that is running, and
    the SQLite view carries the nested state only. Before the shared read, a CLI
    that could not answer left this with no findings; that has to stay true, or
    a running job gets named as uncovered."""
    jobs = [{"id": "job-a", "name": "cron a", "enabled": True,
             "state": {"lastRunStatus": "ok"}}]
    _counting_reader(system_check, monkeypatch, _listing("sqlite", jobs))

    assert system_check._cron_jobs_without_prompt_report({}) == []


def test_coverage_that_could_not_be_counted_says_so(system_check, monkeypatch):
    """An empty list of uncovered jobs means "every job is covered" OR "no job
    was looked at", and the report showed the same green line either way. The
    check's own header refuses that merge for sessions; this is the other half.
    """
    jobs = [{"id": "job-a", "name": "cron a", "enabled": True,
             "state": {"lastRunStatus": "ok"}}]
    _counting_reader(system_check, monkeypatch, _listing("sqlite", jobs))
    monkeypatch.setattr(system_check, "openclaw_is_installed", lambda: True)

    reason = system_check._cron_coverage_blind()

    assert reason and "sqlite" in reason, reason
    assert system_check._cron_jobs_without_prompt_report({}) == [], (
        "the list is empty either way — which is the whole point")


def test_a_machine_with_no_runtime_is_not_called_blind(system_check, monkeypatch):
    """A CI runner and an agent worktree have no schedule to fail to read.
    Warning there would be the false alarm this gate exists to avoid."""
    _counting_reader(system_check, monkeypatch, _listing("sqlite", []))
    monkeypatch.setattr(system_check, "openclaw_is_installed", lambda: False)

    assert system_check._cron_coverage_blind() is None


def test_a_cli_listing_is_not_blind(system_check, monkeypatch):
    _counting_reader(system_check, monkeypatch, _listing("cli", []))
    monkeypatch.setattr(system_check, "openclaw_is_installed", lambda: True)

    assert system_check._cron_coverage_blind() is None


def test_an_unreadable_schedule_is_reported_not_swallowed(
        system_check, monkeypatch):
    def explode(*_args, **_kwargs):
        raise RuntimeError("no runtime here")

    monkeypatch.setattr(system_check, "openclaw_read_jobs", explode)
    system_check._cron_listing.cache_clear()

    result = system_check.Result()
    system_check.check_cron_paths_exist(result)

    assert [s for _, s, _ in result.checks] == [system_check.WARNING]
    assert "no runtime here" in result.checks[0][2]
    assert system_check._cron_jobs_without_prompt_report({}) == []


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
