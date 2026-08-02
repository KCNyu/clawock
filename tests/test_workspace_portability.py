"""Two things this change must not lose.

1. Dependencies have one source of truth. They used to be declared nine times,
   in nine workflow files, as drifting `pip install` lines — and the comment in
   harness-regression already records what that cost: a missing numpy once
   aborted pytest collection and silently stopped enforcing the whole suite.
2. The engine can be pointed at a book that is not kcn's. That is the entire
   point of the change; without it `clawock doctor` is decoration.

Deliberately small. These are the two invariants that would actually break.
"""
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "data"))

import workspace  # noqa: E402


def test_no_workflow_reinstates_a_hand_written_package_list():
    offenders = []
    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            stripped = line.split("#", 1)[0]
            if "pip install" not in stripped:
                continue
            # Installing the project (optionally with an extra) is the only
            # accepted form; anything else is a package list growing back.
            if not re.search(r"-e\s+'?\.(\[[a-z,]+\])?'?", stripped):
                offenders.append(f"{path.name}:{lineno}: {line.strip()}")

    assert not offenders, (
        "dependencies must come from pyproject.toml, not from the workflow:\n"
        + "\n".join(offenders))


def test_the_declared_extras_cover_what_the_suite_imports():
    extras = tomllib.load(open(ROOT / "pyproject.toml", "rb"))[
        "project"]["optional-dependencies"]
    names = {dep.split(">")[0].split("=")[0].strip().lower()
             for dep in extras["test"]}

    # numpy is required to *collect* tests, not merely to pass one of them.
    assert {"pytest", "pytest-cov", "numpy", "pillow"} <= names, names


def test_the_engine_runs_against_a_workspace_that_is_not_this_one(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "instruments.json").write_text("{}")
    (tmp_path / "portfolio.json").write_text(json.dumps({
        "portfolios": {
            "us_stocks": {"holdings": [
                {"ticker": "AAPL", "shares": 10, "cost_basis": 150.0}]},
            "hk_stocks": {"holdings": [
                {"ticker": "00700", "shares": 100, "cost_basis": 380.0}]},
        }
    }))

    report = workspace.describe(tmp_path)

    assert report["problems"] == []
    assert report["holdings"] == 2
    assert Path(report["workspace"]) == tmp_path

    # And through the entry point a stranger would actually use.
    done = subprocess.run(
        [sys.executable, str(ROOT / "clawock_cli.py"), "doctor",
         "--workspace", str(tmp_path), "--json"],
        capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["holdings"] == 2


def test_an_incomplete_workspace_names_what_is_missing_and_exits_nonzero(tmp_path):
    """Failing is fine; failing without saying why is what wastes an hour."""
    (tmp_path / "portfolio.json").write_text(json.dumps({
        "portfolios": {"us_stocks": {"holdings": [{"ticker": "X", "shares": 1}]}}
    }))

    done = subprocess.run(
        [sys.executable, str(ROOT / "clawock_cli.py"), "doctor",
         "--workspace", str(tmp_path)],
        capture_output=True, text=True, timeout=60)

    assert done.returncode == 1
    assert "config/instruments.json" in done.stdout
    assert "cost_basis" in done.stdout


def test_the_default_workspace_is_unchanged_when_the_override_is_unset(monkeypatch):
    """The live checkout and every cron path must behave exactly as before."""
    monkeypatch.delenv(workspace.ENV_VAR, raising=False)

    assert workspace.workspace_root(ROOT) == ROOT

    monkeypatch.setenv(workspace.ENV_VAR, "/tmp")
    assert workspace.workspace_root(ROOT) == Path("/tmp").resolve()
