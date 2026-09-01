"""A product that reached kcn but never reached git must be visible (2026-09-01).

The 08:00 brief of 2026-09-01 was delivered to WeChat and Telegram and then
never committed: `brief-sent-2026-09-01.json` said `sent_ok`/`tg_ok`, and
`memory/2026-09-01-pre-open.md` stayed untracked, so the report link printed on
the card kcn actually received 404'd all day and `memory/decisions.jsonl` — whose
only carrier is the daily brief commit — did not move for a trading day.

Every existing gate read success, because each of them reads the delivery half:
the send marker, the ledger's `primary_delivery`, the watchdog's fresh-marker
check, and the model's own wrap-up. So the gate has to read the *other* half.

Behavioural, driven through a scratch workspace and a real `git` repo, so
deleting the check's body or making it blind to an untracked brief turns these
red.
"""
import importlib.util
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
TODAY = date.today().strftime("%Y-%m-%d")


@pytest.fixture(scope="module")
def system_check():
    for path in (ROOT, ROOT / "src"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    spec = importlib.util.spec_from_file_location(
        "kcnyu_system_check_unarchived", ROOT / "ops" / "system_check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def workspace(system_check, monkeypatch, tmp_path):
    """A real git repo — the check asks git whether a path is tracked."""
    ws = tmp_path / "workspace"
    (ws / "memory" / ".tmp").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=ws, check=True)
    subprocess.run(["git", "config", "user.email", "t@e.st"], cwd=ws, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=ws, check=True)
    monkeypatch.setattr(system_check, "WS", ws)
    return ws


def _mark_delivered(ws, **fields):
    payload = {"ts": 1, "sent_ok": True, "tg_ok": True}
    payload.update(fields)
    (ws / "memory" / ".tmp" / f"brief-sent-{TODAY}.json").write_text(
        __import__("json").dumps(payload))


def _write_brief(ws):
    (ws / "memory" / f"{TODAY}-pre-open.md").write_text("# brief\n")
    (ws / "memory" / f"{TODAY}-plan.json").write_text('{"decisions": []}\n')


def _run(system_check, ws):
    result = system_check.Result()
    system_check.check_delivered_but_unarchived(result)
    return result.checks


def test_delivered_and_untracked_is_the_2026_09_01_state(system_check, workspace):
    _mark_delivered(workspace)
    _write_brief(workspace)
    checks = _run(system_check, workspace)
    assert len(checks) == 1
    name, severity, msg = checks[0]
    assert severity == system_check.WARNING
    # 必须点名是哪个文件——「有东西没入库」答不出该去 add 什么。
    assert f"memory/{TODAY}-pre-open.md" in msg
    assert "404" in msg


def test_delivered_and_committed_is_green(system_check, workspace):
    _mark_delivered(workspace)
    _write_brief(workspace)
    subprocess.run(["git", "add", "memory/"], cwd=workspace, check=True)
    subprocess.run(["git", "commit", "-qm", "brief"], cwd=workspace, check=True)
    checks = _run(system_check, workspace)
    assert [s for _, s, _ in checks] == [system_check.OK]


def test_staged_but_uncommitted_still_counts_as_archived(system_check, workspace):
    """`git ls-files` answers "tracked", and staged is tracked.

    The gate deliberately stops at tracked rather than committed: an index entry
    means the next commit carries it, and `check_publish_backlog` already owns
    "committed but not pushed". Overlapping the two would report one state twice.
    """
    _mark_delivered(workspace)
    _write_brief(workspace)
    subprocess.run(["git", "add", "memory/"], cwd=workspace, check=True)
    checks = _run(system_check, workspace)
    assert [s for _, s, _ in checks] == [system_check.OK]


def test_a_day_with_no_delivery_is_silent(system_check, workspace):
    """Weekends, holidays, and every minute before 08:20 on a trading day."""
    _write_brief(workspace)
    assert _run(system_check, workspace) == []


def test_a_marker_that_delivered_nothing_is_someone_elses_failure(
        system_check, workspace):
    """`sent_ok` false is a delivery miss; the watchdog owns that, not this."""
    _mark_delivered(workspace, sent_ok=False, tg_ok=False)
    _write_brief(workspace)
    assert _run(system_check, workspace) == []


def test_an_absent_brief_is_the_miss_detectors_business(system_check, workspace):
    """Nothing on disk is a different failure with its own alert (09:05)."""
    _mark_delivered(workspace)
    checks = _run(system_check, workspace)
    assert [s for _, s, _ in checks] == [system_check.OK]


def test_an_unreadable_marker_does_not_crash_the_gate(system_check, workspace):
    (workspace / "memory" / ".tmp" / f"brief-sent-{TODAY}.json").write_text("{oops")
    _write_brief(workspace)
    assert _run(system_check, workspace) == []
