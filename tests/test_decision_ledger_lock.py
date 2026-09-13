"""Ledger writers serialize across processes (#1482).

`write_decisions` is atomic but a load -> mutate -> write in one process could
still overwrite another process's change made between its load and its write.
"""
from __future__ import annotations

import json
import multiprocessing
import time

from clawock.decision import execution
from clawock.decision import ledger as decision_v2


def _rows():
    return [
        {"decision_id": "d1", "execution": {"status": "unknown"}},
        {"decision_id": "d2", "execution": {"status": "unknown"}},
    ]


def _slow_settle(path: str, held, release):
    """Stand-in for a cron settle: load, hold the lock a while, write its copy."""
    from pathlib import Path

    from clawock.decision import ledger

    with ledger.ledger_lock(Path(path)):
        rows = ledger.load_decisions(Path(path))
        held.set()
        release.wait(5)
        rows[1]["evaluation"] = {"status": "settled"}
        ledger.write_decisions(rows, Path(path))


def test_mark_followed_waits_for_a_concurrent_settle(tmp_path, monkeypatch):
    path = tmp_path / "decisions.jsonl"
    decision_v2.write_decisions(_rows(), path)
    monkeypatch.setattr(decision_v2, "LEDGER", path)

    ctx = multiprocessing.get_context("fork")
    held, release = ctx.Event(), ctx.Event()
    child = ctx.Process(target=_slow_settle, args=(str(path), held, release))
    child.start()
    try:
        assert held.wait(5), "settle process never took the lock"
        # Release shortly after mark-followed starts waiting; without the lock it
        # would load the pre-settle copy and write it back after the settle.
        ctx.Process(target=lambda: (time.sleep(0.3), release.set())).start()
        execution.main(["d1"])
    finally:
        release.set()
        child.join(5)

    rows = {r["decision_id"]: r for r in map(json.loads, path.read_text().splitlines())}
    assert rows["d1"]["execution"]["status"] == "followed"
    assert rows["d2"].get("evaluation") == {"status": "settled"}, "the settle was lost"


def test_ledger_lock_is_reentrant_in_one_process(tmp_path):
    path = tmp_path / "decisions.jsonl"
    decision_v2.write_decisions(_rows(), path)
    with decision_v2.ledger_lock(path):
        # upsert without a preloaded ledger takes the lock itself.
        inserted, updated = decision_v2.upsert_plan_decisions(
            {"decisions": [{"decision_id": "d3"}]}, path)
    assert (inserted, updated) == (1, 0)
    assert len(decision_v2.load_decisions(path)) == 3
