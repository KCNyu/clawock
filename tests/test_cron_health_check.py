"""Cron health: what counts as evidence that a scheduled job did its work."""
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "data"))

import cron_health_check  # noqa: E402

HKT = ZoneInfo("Asia/Hong_Kong")


class _Runs:
    def __init__(self, runs):
        self._runs = runs

    def history(self, job, limit=20):
        return self._runs


def _run(status, when):
    return SimpleNamespace(status=status, started_at=when.isoformat())


def test_the_run_provider_is_advisory_and_can_never_fail_the_check():
    """#262 prerequisite. Today the commit IS the receipt, so moving the outputs
    off master makes every job with a commit contract report a false miss.

    The provider answers a DIFFERENT question though — "did the job run", not
    "did the job produce" — so it lands as a second signal to be compared before
    anything depends on it. An advisory signal that can break the health check is
    worse than no advisory signal.
    """
    class Exploding:
        def history(self, job, limit=20):
            raise RuntimeError("provider down")

    assert cron_health_check.runs_finished_today("job", Exploding()) is None
    assert cron_health_check.runs_finished_today(None) is None, (
        "a job with no id has no provider evidence, which is not the same as zero")


def test_only_todays_finished_runs_count_as_evidence():
    today = datetime.now(HKT)
    provider = _Runs([
        _run("ok", today),
        _run("ok", today),
        _run("error", today),                      # ran, did not succeed
        _run("running", today),                    # not finished
        _run("ok", today - timedelta(days=1)),     # yesterday is not today's evidence
    ])

    assert cron_health_check.runs_finished_today("job", provider) == 2
