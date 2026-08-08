"""Guards for the memory-index assertion in ops/system_check.py.

The index fell 23 files behind for five days in July 2026 and nothing reported
it: every dreaming note since 07-23 and both weekly reviews were invisible to
semantic recall, and it surfaced only because someone read `openclaw memory
status` by hand while chasing a different bug.

Two properties matter more than the individual cases below:

* the check reads the index tables directly, because `openclaw memory status`
  costs ~16s (too slow for a pre-push hook) and its `Dirty:` line clears before
  the embed pass — so it says `no` while vectors are missing;
* it can only ever WARN. Recall quality is not a publishing invariant, and per
  kcn's standing preference this belongs on the daily-review line rather than in
  a per-failure alert.

Every fixture is a throwaway index + workspace, so a refactor that keeps the
behaviour stays green while each defect the check exists for turns it red.
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = str(ROOT / "ops")


@pytest.fixture(scope="module")
def sc():
    if SCRIPTS not in sys.path:
        sys.path.insert(0, SCRIPTS)
    return pytest.importorskip("system_check")


def _write_index(db: Path, sources: dict[str, int]) -> None:
    conn = sqlite3.connect(db)
    conn.execute(
        "create table memory_index_sources "
        "(path TEXT, source TEXT, hash TEXT, mtime INTEGER, size INTEGER)"
    )
    conn.executemany(
        "insert into memory_index_sources values (?, 'memory', 'h', 0, ?)",
        list(sources.items()),
    )
    conn.commit()
    conn.close()


@pytest.fixture
def box(tmp_path, sc, monkeypatch):
    """A healthy live box: workspace, index, both dist patches, fresh reindex."""
    workspace = tmp_path / "workspace"
    (workspace / "memory" / "dreaming").mkdir(parents=True)
    (workspace / "logs").mkdir()
    (workspace / "MEMORY.md").write_text("index\n")
    (workspace / "memory" / "2026-07-27.md").write_text("today\n")
    (workspace / "memory" / "dreaming" / "2026-07-26.md").write_text("dreamt\n")

    db = tmp_path / "agent.sqlite"
    _write_index(db, {
        "MEMORY.md": len("index\n"),
        "memory/2026-07-27.md": len("today\n"),
        "memory/dreaming/2026-07-26.md": len("dreamt\n"),
    })

    dist = tmp_path / "openclaw" / "dist"
    dist.mkdir(parents=True)
    (dist / "embeddings-aaa.js").write_text("const o = { threads: 1, batchSize: 512 };")
    (dist / "tools-bbb.js").write_text("const MEMORY_SEARCH_TOOL_TIMEOUT_MS = 60000;")

    log = workspace / "logs" / "memory_index.log"
    stamp = (datetime.now().astimezone() - timedelta(hours=3)).isoformat(timespec="seconds")
    log.write_text(f"{stamp} reindex done in 15s: indexed=3/3 counts=(9, 3) (chunk delta 0)\n")

    monkeypatch.setattr(sc, "LIVE_WORKSPACE", workspace)
    monkeypatch.setattr(sc, "MEMORY_INDEX_DB", db)
    monkeypatch.setattr(sc, "OPENCLAW_INSTALL", tmp_path / "openclaw")
    monkeypatch.setattr(sc, "MEMORY_INDEX_LOG", log)
    return {"workspace": workspace, "db": db, "dist": dist, "log": log}


def _run(sc):
    r = sc.Result()
    sc.check_memory_index(r)
    assert len(r.checks) == 1
    name, severity, message = r.checks[0]
    assert name == "memory index"
    return severity, message


def test_healthy_box_reports_ok(sc, box):
    severity, message = _run(sc)
    assert severity == sc.OK, message
    assert "3 files embedded" in message


def test_unembedded_file_is_reported(sc, box):
    """The July failure: dreaming notes written but never embedded."""
    (box["workspace"] / "memory" / "dreaming" / "2026-07-27.md").write_text("new\n")
    severity, message = _run(sc)
    assert severity == sc.WARNING
    assert "never embedded" in message
    assert "memory/dreaming/2026-07-27.md" in message


def test_file_changed_since_indexing_is_reported(sc, box):
    """A source indexed once and edited since is stale, and the ratio hides it."""
    (box["workspace"] / "memory" / "2026-07-27.md").write_text("today, plus an edit\n")
    severity, message = _run(sc)
    assert severity == sc.WARNING
    assert "changed since indexing" in message
    assert "memory/2026-07-27.md" in message


def test_gitignored_trees_count_as_index_scope(sc, box):
    """openclaw embeds memory/.tmp and memory/.dreams too — verified on a clean
    472/472 index. Excluding them would under-report the backlog."""
    tmp_dir = box["workspace"] / "memory" / ".tmp"
    tmp_dir.mkdir()
    (tmp_dir / "report-prose-hk-open.md").write_text("prose\n")
    severity, message = _run(sc)
    assert severity == sc.WARNING
    assert "memory/.tmp/report-prose-hk-open.md" in message


def test_wiped_timeout_patch_is_reported(sc, box):
    """Every openclaw upgrade restores the stock 15s deadline this box cannot meet."""
    (box["dist"] / "tools-bbb.js").write_text("const MEMORY_SEARCH_TOOL_TIMEOUT_MS = 15e3;")
    severity, message = _run(sc)
    assert severity == sc.WARNING
    assert "stock 15s" in message


def test_wiped_threads_patch_is_reported(sc, box):
    (box["dist"] / "embeddings-aaa.js").write_text("const o = { threads: 4 };")
    severity, message = _run(sc)
    assert severity == sc.WARNING
    assert "threads:1" in message


def test_stalled_nightly_reindex_is_reported(sc, box):
    """The drain is a cron job; if it stops, the backlog returns silently."""
    stamp = (datetime.now().astimezone() - timedelta(hours=40)).isoformat(timespec="seconds")
    box["log"].write_text(f"{stamp} reindex done in 15s: indexed=3/3 counts=(9, 3)\n")
    severity, message = _run(sc)
    assert severity == sc.WARNING
    assert "40h ago" in message


def test_normal_gap_between_nightly_runs_is_not_a_finding(sc, box):
    """05:10 daily means a healthy box is routinely ~24h since the last run."""
    stamp = (datetime.now().astimezone() - timedelta(hours=26)).isoformat(timespec="seconds")
    box["log"].write_text(f"{stamp} reindex done in 15s: indexed=3/3 counts=(9, 3)\n")
    severity, _ = _run(sc)
    assert severity == sc.OK


def test_reap_only_log_reads_as_never_reindexed(sc, box):
    """The reaper writes to the same log every 15 min; its mtime proves nothing."""
    box["log"].write_text("2026-07-27T11:00:00+08:00 reaped worker 528196\n")
    severity, message = _run(sc)
    assert severity == sc.WARNING
    assert "never completed" in message


def test_host_without_a_live_index_skips(sc, box, tmp_path, monkeypatch):
    """CI and fresh checkouts have no openclaw install; that is not a finding."""
    monkeypatch.setattr(sc, "MEMORY_INDEX_DB", tmp_path / "absent.sqlite")
    severity, message = _run(sc)
    assert severity == sc.OK
    assert "skipped" in message


def test_unreadable_index_warns_rather_than_crashing(sc, box):
    box["db"].write_text("not a database")
    severity, _ = _run(sc)
    assert severity == sc.WARNING


def test_check_can_never_block_a_push(sc, box):
    """Everything wrong at once must still leave the exit code at warn.

    A degraded index is a recall problem, not a correctness one — blocking a
    publish over it would trade a real invariant for a soft one.
    """
    (box["workspace"] / "memory" / "unembedded.md").write_text("new\n")
    (box["dist"] / "tools-bbb.js").write_text("const MEMORY_SEARCH_TOOL_TIMEOUT_MS = 15e3;")
    (box["dist"] / "embeddings-aaa.js").write_text("const o = { threads: 4 };")
    box["log"].unlink()

    r = sc.Result()
    sc.check_memory_index(r)
    assert r.critical_count() == 0
    assert r.warn_count() == 1


def test_check_is_registered_in_main(sc):
    """A check nobody runs is the failure mode this issue was about."""
    source = (ROOT / "ops" / "system_check.py").read_text()
    # `self.checks = []` appears earlier in the Result class, so anchor on the
    # registration list itself.
    body = source.split("\n    checks = [", 1)[1].split("]", 1)[0]
    registered = {line.strip().rstrip(",") for line in body.splitlines() if line.strip()}
    assert "check_memory_index" in registered
