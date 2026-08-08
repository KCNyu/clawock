import importlib.util
import json
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "harness"))

import _watchdog_common as common  # noqa: E402
from clawock.providers import openclaw as provider  # noqa: E402


def _make_state_db(path):
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE cron_jobs (
                store_key TEXT NOT NULL,
                job_id TEXT NOT NULL,
                job_json TEXT NOT NULL,
                state_json TEXT NOT NULL,
                sort_order INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );
            CREATE TABLE cron_run_logs (
                store_key TEXT NOT NULL,
                job_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                ts INTEGER NOT NULL,
                entry_json TEXT NOT NULL
            );
            """
        )
        job = {
            "id": "job-1",
            "name": "live job",
            "enabled": True,
            "schedule": {"kind": "cron", "expr": "0 8 * * 1-5"},
            "payload": {"model": "provider/current"},
            "state": {"lastRunStatus": "old"},
        }
        state = {"lastRunStatus": "ok", "nextRunAtMs": 2000}
        conn.execute(
            "INSERT INTO cron_jobs VALUES (?, ?, ?, ?, ?, ?)",
            ("store", "job-1", json.dumps(job), json.dumps(state), 0, 1),
        )
        for seq, ts, status in ((2, 200, "ok"), (1, 100, "error")):
            entry = {
                "jobId": "job-1",
                "ts": ts,
                "status": status,
                "action": "finished",
            }
            conn.execute(
                "INSERT INTO cron_run_logs VALUES (?, ?, ?, ?, ?)",
                ("store", "job-1", seq, ts, json.dumps(entry)),
            )


def test_runtime_paths_derive_one_external_installation():
    paths = provider.runtime_paths({
        "CLAWOCK_OPENCLAW_BIN": "/opt/openclaw/bin/openclaw",
        "CLAWOCK_OPENCLAW_HOME": "/srv/openclaw-state",
        "CLAWOCK_OPENCLAW_INSTALL_DIR": "/opt/openclaw/package",
    })

    assert paths.binary == "/opt/openclaw/bin/openclaw"
    assert paths.state_db == Path("/srv/openclaw-state/state/openclaw.sqlite")
    assert paths.sessions_dir == Path("/srv/openclaw-state/agents/main/sessions")
    assert paths.workspace == Path("/srv/openclaw-state/workspace")
    assert paths.install_dir == Path("/opt/openclaw/package")


def test_explicit_runtime_reads_its_own_sqlite(tmp_path):
    paths = provider.OpenClawPaths(
        binary="/opt/openclaw/bin/openclaw",
        home=tmp_path / "external-runtime",
        install_dir=tmp_path / "package",
    )
    paths.state_db.parent.mkdir(parents=True)
    _make_state_db(paths.state_db)

    jobs = provider.read_jobs("sqlite", paths=paths)
    runs = provider.read_runs("job-1", "sqlite", paths=paths)

    assert jobs.source == runs.source == "sqlite"
    assert jobs.entries[0]["name"] == "live job"
    assert [entry["ts"] for entry in runs.entries] == [100, 200]


def test_runtime_binary_override_reaches_read_and_write_commands(monkeypatch):
    monkeypatch.setenv("CLAWOCK_OPENCLAW_BIN", "/opt/openclaw/bin/openclaw")
    seen = []

    class Result:
        stdout = '{"jobs": []}'

    provider.cron_cli_json(
        ["list", "--json"], runner=lambda cmd: seen.append(cmd) or Result())
    edit = provider.build_cron_edit_argv("job-1", {"enabled": True})

    assert seen[0][0] == edit[0] == "/opt/openclaw/bin/openclaw"


def test_auto_falls_back_to_live_sqlite_before_fossil(tmp_path, monkeypatch):
    db = tmp_path / "state" / "openclaw.sqlite"
    db.parent.mkdir()
    _make_state_db(db)
    monkeypatch.setenv("CLAWOCK_OPENCLAW_HOME", str(tmp_path))
    monkeypatch.setattr(provider, "cron_cli_json", lambda _args: None)

    jobs = common.load_jobs()

    assert common.LAST_LOAD_SOURCE == "sqlite"
    assert [job["name"] for job in jobs] == ["live job"]
    assert jobs[0]["payload"]["model"] == "provider/current"
    assert jobs[0]["state"] == {"lastRunStatus": "ok", "nextRunAtMs": 2000}


def test_explicit_sqlite_run_history_is_oldest_first(tmp_path, monkeypatch):
    db = tmp_path / "state" / "openclaw.sqlite"
    db.parent.mkdir()
    _make_state_db(db)
    monkeypatch.setenv("CLAWOCK_OPENCLAW_HOME", str(tmp_path))
    monkeypatch.setattr(
        provider,
        "cron_cli_json",
        lambda _args: (_ for _ in ()).throw(AssertionError("CLI must not run")),
    )

    entries = common.read_runs("job-1", source="sqlite")

    assert common.LAST_RUNS_SOURCE == "sqlite"
    assert [entry["ts"] for entry in entries] == [100, 200]


def test_fossil_source_is_marked_stale(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAWOCK_OPENCLAW_HOME", str(tmp_path))
    jobs_json = tmp_path / "cron" / "jobs.json"
    jobs_json.parent.mkdir()
    jobs_json.write_text(json.dumps([{"id": "old", "name": "stale"}]))
    monkeypatch.setattr(provider, "cron_cli_json", lambda _args: None)

    assert common.load_jobs() == [{"id": "old", "name": "stale"}]
    assert common.LAST_LOAD_SOURCE == "fossil"


def test_timeline_returns_nonzero_for_fossil(monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location(
        "cron_timeline_live_state", ROOT / "scripts" / "data" / "cron_timeline.py"
    )
    timeline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(timeline)
    monkeypatch.setattr(
        timeline,
        "load_openclaw",
        lambda _backend: setattr(timeline, "LAST_OPENCLAW_SOURCE", "fossil") or [],
    )
    monkeypatch.setattr(sys, "argv", ["cron_timeline.py", "--source", "openclaw"])

    assert timeline.main() == 2
    assert "stale pre-6.1 fossil" in capsys.readouterr().err


def test_timeline_returns_nonzero_when_live_state_is_empty(monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location(
        "cron_timeline_empty_state", ROOT / "scripts" / "data" / "cron_timeline.py"
    )
    timeline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(timeline)
    monkeypatch.setattr(
        timeline,
        "load_openclaw",
        lambda _backend: setattr(timeline, "LAST_OPENCLAW_SOURCE", "empty") or [],
    )
    monkeypatch.setattr(
        sys, "argv", ["cron_timeline.py", "--source", "openclaw", "--json"]
    )

    assert timeline.main() == 2
    assert "no live CLI/SQLite state" in capsys.readouterr().err
