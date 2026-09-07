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
from datetime import date, timedelta
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]

# FROZEN, not read from the clock (2026-09-08). This used to be
# `TODAY = date.today().strftime(...)` at module scope: read ONCE at import,
# while `check_delivered_but_unarchived` calls `date.today()` again when the
# test body runs. A full-suite run that starts before 00:00 and reaches this
# module after it writes `brief-sent-<yesterday>.json` and then asks a check
# looking for `<today>` — four of these went red that way on 2026-09-07→08, with
# nobody having touched any code. CI runs in UTC, so the crossing is 16:00 UTC.
#
# The existing `test_time_dependent_assertions` gate states the rule this
# violates ("要么冻住时钟，要么从同一个时钟推出期望值") but could not see it: no
# date literal appears in any assertion here, so its regex had nothing to match.
# It now also rejects module-level clock reads.
TODAY = "2026-09-01"          # the day the gate was written for


class _FrozenDate(date):
    """`date` with a `today()` that cannot move. Subclassed rather than stubbed
    so any other `date` use inside the check keeps working."""

    @classmethod
    def today(cls):
        return cls.fromisoformat(TODAY)


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
    # Freeze the check's clock to the same day the fixtures write. Both halves
    # now come from one value that cannot advance mid-run.
    monkeypatch.setattr(system_check, "date", _FrozenDate)
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


def test_the_outcome_does_not_depend_on_what_day_it_is(system_check, workspace,
                                                       monkeypatch):
    """The 2026-09-07→08 red, encoded.

    That night a full-suite run started before 00:00 HKT and reached this module
    after it. `TODAY` had been read from the clock at import; the check read it
    again at run time; the fixtures wrote one day and the check looked for the
    next. Four tests here went red with nobody having touched any code.

    So: move the real clock across midnight between two runs and require the
    same answer. The fixture freezes the check's clock, which is what makes that
    true — revert the freeze and this test reproduces the failure directly
    rather than waiting for a midnight.
    """
    _mark_delivered(workspace)
    _write_brief(workspace)
    before = _run(system_check, workspace)

    class _NextDay(_FrozenDate):
        @classmethod
        def today(cls):
            return date.fromisoformat(TODAY) + timedelta(days=1)

    monkeypatch.setattr(system_check, "date", _NextDay)
    # The check is asked on "the next day"; the workspace is untouched. A gate
    # whose subject is "today's brief" must still answer about the day it is
    # given, not silently about the day the fixtures happened to write.
    after = _run(system_check, workspace)

    assert [s for _, s, _ in before] == [system_check.WARNING]
    # Crossing midnight makes today's brief ABSENT, not archived — a different
    # true answer, reached deliberately. What must never happen is the two
    # halves disagreeing about which day they mean inside ONE run.
    assert [s for _, s, _ in after] == []
