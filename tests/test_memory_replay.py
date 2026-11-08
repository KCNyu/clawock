"""Replay candidates: duplicates, contradictions and unused high-salience topics land in
`memory/.replay/` only; the store and DREAMS.md are untouched."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPLAY = ROOT / "ops/host/shared-memory/scripts/replay.py"
NOW = "2026-11-08T12:00:00+08:00"


def topic(store, slug, body, *, salience="normal", status="hypothesis", updated="2026-01-01"):
    (store / f"{slug}.md").write_text(f"""---
name: {slug}
description: "{slug}"
metadata:
  type: project
  scope: engineering
  updated: {updated}
  salience: {salience}
  status: {status}
  publish: private
  agent: test
---

{body}
""")


@pytest.fixture
def world(tmp_path):
    store = tmp_path / "store"
    (store / "indexes").mkdir(parents=True)
    (store / "archive").mkdir()
    (store / "MEMORY.md").write_text("# Index\n\n- `indexes/MEMORY-host.md` — host\n")
    (store / "indexes/MEMORY-host.md").write_text("# Host\n")
    shared = "# Same\n\nalpha beta gamma delta repeated durable rule. " * 3
    topic(store, "dup-a", shared)
    topic(store, "dup-b", shared)
    topic(store, "stale-rule", "# Stale\n\nalpha beta gamma delta policy must enable the pipeline. " * 2,
          status="stale")
    topic(store, "live-rule", "# Live\n\nalpha beta gamma delta policy never enable the pipeline. " * 2,
          status="verified")
    topic(store, "high-unused", "# Unused\n\nzulu yankee xray whiskey unique high rule.", salience="high")
    topic(store, "high-used", "# Used\n\nquebec romeo sierra tango unique high rule.", salience="high")
    workspace = tmp_path / "workspace"
    (workspace / "memory" / ".dreams").mkdir(parents=True)
    (workspace / "DREAMS.md").write_text("current dreams\n")
    state = tmp_path / "state"
    state.mkdir()
    (state / "recall.jsonl").write_text(json.dumps(
        {"ts": "2026-11-01T00:00:00+08:00", "source": "python-search", "topics": ["high-used"]}) + "\n")
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "result.env").write_text("TASK=one\nRESULT=ok\nNOTE=high-used\n")
    env = {**os.environ,
           "SHARED_MEMORY_DIR": str(store), "SHARED_MEMORY_STATE": str(state),
           "AGENT_DISPATCH_LOG_DIR": str(tasks), "SHARED_MEMORY_REPLAY_SESSIONS": "0"}
    return store, workspace, state, tasks, env


def run(world, *args, env_extra=None):
    store, workspace, state, tasks, env = world
    out = workspace / "memory" / ".replay"
    proc = subprocess.run([sys.executable, str(REPLAY), "--store", str(store), "--state", str(state),
                           "--workspace", str(workspace), "--out", str(out), "--now", NOW, *args],
                          env={**env, **(env_extra or {})}, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads((out / "candidates.json").read_text()), out


def tree_hash(root):
    return hashlib.sha256(b"".join(
        p.relative_to(root).as_posix().encode() + b"\0" + p.read_bytes()
        for p in sorted(root.rglob("*")) if p.is_file())).hexdigest()


def test_candidates_are_written_next_to_dreams_and_do_not_touch_the_store(world):
    store, workspace, *_ = world
    before_store = tree_hash(store)
    before_dreams = (workspace / "DREAMS.md").read_text()
    report, out = run(world)
    assert tree_hash(store) == before_store
    assert (workspace / "DREAMS.md").read_text() == before_dreams
    assert (workspace / "memory" / ".replay").is_dir()
    assert report["counts"]["duplicate-merge"] >= 1
    assert report["counts"]["contradiction"] >= 1
    assert report["counts"]["unused-high-salience"] >= 1
    slugs = {slug for row in report["candidates"] for slug in row["slugs"]}
    assert {"dup-a", "dup-b", "stale-rule", "live-rule", "high-unused"} <= slugs
    assert "high-used" not in {slug for row in report["candidates"] if row["kind"] == "unused-high-salience"
                               for slug in row["slugs"]}
    for name in ("candidates.json", "report.md"):
        path = out / name
        assert path.is_file() and oct(path.stat().st_mode & 0o777) == "0o600"
    assert oct(out.stat().st_mode & 0o777) == "0o700"
    assert "high-unused" in (out / "report.md").read_text()


def test_a_recent_task_mention_suppresses_unused(world):
    store, workspace, state, tasks, env = world
    (tasks / "result.env").write_text("TASK=two\nRESULT=ok\nNOTE=high-unused\n")
    report, _ = run(world)
    unused = {slug for row in report["candidates"] if row["kind"] == "unused-high-salience"
              for slug in row["slugs"]}
    assert "high-unused" not in unused


def test_the_replay_output_is_gitignored_and_not_wired_into_commit_dreaming():
    assert "memory/.replay/" in (ROOT / ".gitignore").read_text()
    assert "replay.py" not in (ROOT / "ops/host/commit_dreaming.sh").read_text()
