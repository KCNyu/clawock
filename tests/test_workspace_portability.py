"""Two things this change must not lose.

1. Dependencies have one source of truth. They used to be declared nine times,
   in nine workflow files, as drifting `pip install` lines — and the comment in
   ci.yml already records what that cost: a missing numpy once
   aborted pytest collection and silently stopped enforcing the whole suite.
2. The engine can be pointed at a book that is not kcn's. That is the entire
   point of the change; without it `clawock doctor` is decoration.

Deliberately small. These are the two invariants that would actually break.
"""
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clawock import workspace  # noqa: E402


def test_no_workflow_reinstates_a_hand_written_package_list():
    offenders = []
    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            stripped = line.split("#", 1)[0]
            if "pip install" not in stripped:
                continue
            # Installing the project (optionally with an extra) is the accepted
            # form; anything else is a package list growing back. Installing a
            # distribution this workflow just built is not a package list — it is
            # the artifact under test, and naming it is the point.
            if re.search(r"pip install [^|;]*\bdist/\*", stripped):
                continue
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
        [sys.executable, "-m", "clawock.cli", "doctor",
         "--workspace", str(tmp_path), "--json"],
        capture_output=True, text=True, timeout=60, cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")})
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["holdings"] == 2


def test_an_incomplete_workspace_names_what_is_missing_and_exits_nonzero(tmp_path):
    """Failing is fine; failing without saying why is what wastes an hour."""
    (tmp_path / "portfolio.json").write_text(json.dumps({
        "portfolios": {"us_stocks": {"holdings": [{"ticker": "X", "shares": 1}]}}
    }))

    done = subprocess.run(
        [sys.executable, "-m", "clawock.cli", "doctor",
         "--workspace", str(tmp_path)],
        capture_output=True, text=True, timeout=60, cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")})

    assert done.returncode == 1
    assert "config/instruments.json" in done.stdout
    assert "cost_basis" in done.stdout


def test_the_default_workspace_is_unchanged_when_the_override_is_unset(monkeypatch):
    """The live checkout and every cron path must behave exactly as before."""
    monkeypatch.delenv(workspace.ENV_VAR, raising=False)

    assert workspace.workspace_root(ROOT) == ROOT

    monkeypatch.setenv(workspace.ENV_VAR, "/tmp")
    assert workspace.workspace_root(ROOT) == Path("/tmp").resolve()


def test_the_money_clis_target_the_checkout_they_are_in(monkeypatch):
    """The realized command from a worktree once rewrote the live ledger.

    Its `--path` default was `/root/.openclaw/workspace/portfolio.json`, so the
    command line pointed at production wherever it ran; the library callers
    were never affected because they pass their own dict. The legacy backfill
    was worse — the same absolute root also aimed `SNAP_DIR` at the real
    `memory/snapshots/`, which it rewrites in place.
    """
    probe = (
        "import sys; sys.path[:0] = [%r, %r];"
        "from clawock.portfolio import realized as rr, snapshots as sr;"
        " import backfill_snapshot_realized as bf;"
        "print(rr.PORTFOLIO_PATH); print(bf.SNAP_DIR);"
        "print(hasattr(sr, 'PORTFOLIO_PATH'))"
    ) % (str(ROOT / "src"), str(ROOT / "ops" / "host"))
    env = {k: v for k, v in os.environ.items() if k != workspace.ENV_VAR}

    done = subprocess.run([sys.executable, "-c", probe], cwd=str(ROOT), env=env,
                          capture_output=True, text=True, timeout=60)

    assert done.returncode == 0, done.stderr
    ledger, snapshots, dead_constant = done.stdout.split()
    assert Path(ledger) == ROOT / "portfolio.json"
    assert Path(snapshots) == ROOT / "memory" / "snapshots"
    assert dead_constant == "False", (
        "the snapshots module's unused PORTFOLIO_PATH named production and had no "
        "reader; re-adding one is re-adding a loaded gun")


def test_the_entry_point_imports_without_the_scripts_directory(tmp_path):
    """The defect this file failed to catch once already.

    `pyproject.toml` shipped only `clawock_cli`, which reached
    `scripts/data/workspace.py` through a source-relative `sys.path` hack. An
    editable install keeps the source tree importable, so `pip install -e .`
    passed for a reason unrelated to what it proved; a real wheel raised
    ModuleNotFoundError on first use.

    Importing the console entry point with only the repo root visible — no
    `scripts/` anywhere — is the cheap proxy for "does the wheel work".
    """
    done = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path[:] = [p for p in sys.path if 'scripts' not in p];"
         " from clawock.cli import main; print('ok')"],
        cwd=tmp_path, capture_output=True, text=True, timeout=60,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")})

    assert done.returncode == 0, done.stderr
    assert "ok" in done.stdout


def test_no_build_metadata_is_tracked():
    """`clawock.egg-info/` was committed by the packaging change and is pure
    build output — it goes stale instantly and conflicts across runners."""
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, timeout=60)

    offenders = [line for line in tracked.stdout.splitlines()
                 if ".egg-info" in line or line.startswith(("build/", "dist/"))]

    assert not offenders, f"build metadata is tracked: {offenders}"
