"""T+0 history keeps complete bytes and serializes read-modify-write."""
from __future__ import annotations

import errno
import io
import json
import multiprocessing
from pathlib import Path

import pytest

from clawock.decision import setups
from clawock.safe_io import file_lock


def _snapshot(ticker: str) -> dict:
    return {
        "as_of": "2026-09-20T10:00:00+08:00",
        "session_date": {"hk": "2026-09-20"},
        "rows": {ticker: {
            "current": 10, "market": "hk", "grade_label": "中性", "range_pos": 50,
        }},
    }


def _append(path: str, started, done) -> None:
    setups.HIST = Path(path)
    started.set()
    setups.persist_history(_snapshot("CHILD"))
    done.set()


def test_interrupted_history_write_retains_previous_bytes(tmp_path, monkeypatch):
    history = tmp_path / "t0_setups_history.jsonl"
    history.write_text('{"old": true}\n', encoding="utf-8")
    before = history.read_bytes()
    monkeypatch.setattr(setups, "HIST", history)
    real_open = io.open

    class InterruptedWriter:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.handle.__exit__(*args)

        def write(self, text):
            self.handle.write(text[:len(text) // 2])
            self.handle.flush()
            raise OSError(errno.ENOSPC, "injected disk full after partial write")

    def interrupted_open(file, mode="r", *args, **kwargs):
        handle = real_open(file, mode, *args, **kwargs)
        return InterruptedWriter(handle) if "w" in mode else handle

    monkeypatch.setattr(io, "open", interrupted_open)
    with pytest.raises(OSError, match="injected disk full"):
        setups.persist_history(_snapshot("NEW"))
    assert history.read_bytes() == before


def test_history_append_waits_for_the_cross_process_lock(tmp_path):
    history = tmp_path / "t0_setups_history.jsonl"
    history.write_text(json.dumps({"old": True}) + "\n", encoding="utf-8")
    ctx = multiprocessing.get_context("spawn")
    started, done = ctx.Event(), ctx.Event()

    with file_lock(str(history)):
        child = ctx.Process(target=_append, args=(str(history), started, done))
        child.start()
        assert started.wait(5), "child did not reach persist_history"
        assert not done.wait(0.3), "writer ignored the history lock"

    assert done.wait(5), "writer did not continue after the lock was released"
    child.join(5)
    assert child.exitcode == 0
    rows = [json.loads(line) for line in history.read_text().splitlines()]
    assert rows[0] == {"old": True}
    assert "CHILD" in rows[1]["rows"]
