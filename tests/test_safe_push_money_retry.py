"""A rebase changes the book being pushed, so the money gate must run again."""
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ops" / "publish" / "safe_push.sh"


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


def test_money_gate_rechecks_the_rebased_book(tmp_path):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-b", "master", str(origin)],
                   check=True, capture_output=True)
    seed = tmp_path / "seed"
    git(tmp_path, "clone", str(origin), str(seed))
    git(seed, "config", "user.name", "test")
    git(seed, "config", "user.email", "test@example.invalid")
    (seed / "portfolio.json").write_text('{"cash": 0}\n')
    git(seed, "add", "portfolio.json")
    git(seed, "commit", "-m", "seed")
    git(seed, "push", "origin", "master")

    runner, rival = tmp_path / "runner", tmp_path / "rival"
    git(tmp_path, "clone", str(origin), str(runner))
    git(tmp_path, "clone", str(origin), str(rival))
    for checkout in (runner, rival):
        git(checkout, "config", "user.name", "test")
        git(checkout, "config", "user.email", "test@example.invalid")
    (runner / "note.txt").write_text("local\n")
    git(runner, "add", "note.txt")
    git(runner, "commit", "-m", "local")
    (rival / "portfolio.json").write_text('{"cash": 1}\n')
    git(rival, "add", "portfolio.json")
    git(rival, "commit", "-m", "remote book")
    git(rival, "push", "origin", "master")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    checker = bin_dir / "clawock"
    checker.write_text('#!/bin/sh\ncat "$CLAWOCK_WORKSPACE/portfolio.json" >> "$CHECK_LOG"\n')
    checker.chmod(0o755)
    log = tmp_path / "checks.txt"
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}",
           "CHECK_LOG": str(log)}
    result = subprocess.run(["bash", str(SCRIPT), "origin", "master"],
                            cwd=runner, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert log.read_text().splitlines() == ['{"cash": 0}', '{"cash": 1}']
