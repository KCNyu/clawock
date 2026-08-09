"""The freshness verdict, on synthetic layer readings.

Only `assess()` is tested. The readers talk to git, `gh` and the live site, and a
test that mocked all three would assert my mocks rather than the pipeline. What
has to be right is the judgement: a lag that is expected must not read as a
fault, and a fault must not read as a lag. Both directions cost something real —
the first trains everyone to ignore the tool, the second is the frozen dashboard
it exists to catch.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ops" / "pages"))

import freshness  # noqa: E402

NOW = datetime(2026, 8, 9, 14, 30, tzinfo=timezone.utc)


def _layer(name, minutes_old, *, kind="generation"):
    at = NOW - timedelta(minutes=minutes_old)
    return freshness.Layer(name, kind=kind, generation=at.isoformat(), generated_at=at)


def _status(report, name):
    return next(row["status"] for row in report["layers"] if row["layer"] == name)


def test_one_generation_everywhere_is_consistent():
    report = freshness.assess(
        [_layer("producer", 2), _layer("data plane", 2), _layer("live", 2)], now=NOW)
    assert report["consistent"] and not report["findings"]


def test_a_layer_inside_its_bound_is_a_queue_not_a_fault():
    """Measured against the newest generation, not against the clock.

    `now - layer.generated_at` looks equivalent and is not: at 03:00, with the
    market shut and nothing new produced, every layer would be hours "old" while
    being perfectly in sync — and during the day a healthy live layer reads as
    stale for the entire propagation window. The first live run of this tool
    reported exactly that false alarm.
    """
    report = freshness.assess(
        [_layer("producer", 0), _layer("data plane", 5), _layer("live", 20)], now=NOW)

    assert _status(report, "data plane") == "behind (within bound)"
    assert _status(report, "live") == "behind (within bound)"
    assert not report["findings"], report["findings"]

    # Same shape, two hours later with nothing new produced: still no alarm.
    quiet = freshness.assess(
        [_layer("producer", 120), _layer("data plane", 125), _layer("live", 140)],
        now=NOW + timedelta(hours=2))
    assert not quiet["findings"], quiet["findings"]


def test_a_layer_past_its_bound_is_a_finding():
    report = freshness.assess(
        [_layer("producer", 0), _layer("data plane", 5), _layer("live", 90)], now=NOW)

    assert _status(report, "live") == "STALE"
    assert report["findings"] and "live" in report["findings"][0]
    assert not report["consistent"]


def test_the_deployment_layer_is_judged_on_timing_not_generation_equality():
    """It reports a commit sha, which can never equal a generation id.

    Comparing them marked the layer different on every single run, and the age
    check behind that comparison then declared it stale — a permanent red that
    says nothing about whether Pages actually shipped the live content.
    """
    live = _layer("live", 10)
    deployed_after = freshness.Layer(
        "pages deployment", kind="deployment", generation="c2983234b717",
        generated_at=live.generated_at + timedelta(minutes=1))
    report = freshness.assess([_layer("producer", 10), live, deployed_after], now=NOW)
    assert _status(report, "pages deployment") == "ok"
    assert not report["findings"]

    never_shipped = freshness.Layer(
        "pages deployment", kind="deployment", generation="0000deadbeef",
        generated_at=live.generated_at - timedelta(hours=3))
    stalled = freshness.assess([_layer("producer", 10), live, never_shipped], now=NOW)
    assert _status(stalled, "pages deployment") == "STALE"


def test_an_unreachable_layer_is_a_finding_rather_than_a_silent_pass():
    broken = freshness.Layer("live")
    broken.problems.append("ConnectionError: name resolution failed")
    report = freshness.assess([_layer("producer", 1), broken], now=NOW)
    assert _status(report, "live") == "unreachable"
    assert report["findings"]
