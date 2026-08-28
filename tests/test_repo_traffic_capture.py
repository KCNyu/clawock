"""Repo traffic capture: the merge has to be lossless, and the precision
boundary between series and snapshots has to survive.

GitHub's Traffic API keeps 14 days. A capture that quietly drops or double
counts a day is worse than no capture, because the mistake is undetectable
after the window closes.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ops" / "growth" / "repo_traffic.py"

spec = importlib.util.spec_from_file_location("repo_traffic", SCRIPT)
repo_traffic = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(repo_traffic)


def _day(ts: str, count: int, uniques: int) -> dict:
    return {"timestamp": ts, "count": count, "uniques": uniques}


def _github(views: list[dict], clones: list[dict], referrers=None, paths=None,
            repo=None) -> dict:
    payload = {
        "views": {"count": sum(d["count"] for d in views),
                  "uniques": 1, "views": views},
        "clones": {"count": sum(d["count"] for d in clones),
                   "uniques": 1, "clones": clones},
        "referrers": referrers if referrers is not None else [],
        "paths": paths if paths is not None else [],
    }
    if repo is not None:
        payload["repo"] = repo
    return payload


NOW = dt.datetime(2026, 8, 22, 3, 38, tzinfo=dt.timezone.utc)
LATER = dt.datetime(2026, 8, 26, 3, 38, tzinfo=dt.timezone.utc)


def test_overlapping_windows_upsert_instead_of_appending():
    """Weekly capture over a 14-day window overlaps by 7 days every time.

    The overlap is deliberate — it is a free consistency check — but only if
    the merge is keyed on the day. Appending would double every overlapping day
    and make the whole series a fiction within one month.
    """
    first, _ = repo_traffic.merge(
        {}, _github([_day("2026-08-20T00:00:00Z", 10, 3), _day("2026-08-21T00:00:00Z", 20, 5)],
                    [_day("2026-08-20T00:00:00Z", 1, 1)]), {}, NOW)
    second, stats = repo_traffic.merge(
        first, _github([_day("2026-08-21T00:00:00Z", 20, 5), _day("2026-08-22T00:00:00Z", 30, 7)],
                       [_day("2026-08-22T00:00:00Z", 2, 2)]), {}, LATER)

    assert [d["timestamp"] for d in second["views"]] == [
        "2026-08-20T00:00:00Z", "2026-08-21T00:00:00Z", "2026-08-22T00:00:00Z"]
    assert [d["count"] for d in second["views"]] == [10, 20, 30]
    assert stats["views_added"] == 1
    assert stats["views_revised"] == 0


def test_a_day_whose_numbers_changed_is_reported_not_hidden():
    """A settled day that comes back different means the key or the source is
    wrong. The value is still taken — GitHub does revise a day in progress —
    but the run has to say so."""
    first, _ = repo_traffic.merge({}, _github([_day("2026-08-21T00:00:00Z", 20, 5)], []), {}, NOW)
    second, stats = repo_traffic.merge(
        first, _github([_day("2026-08-21T00:00:00Z", 99, 9)], []), {}, LATER)

    assert stats["views_revised"] == 1
    assert second["views"][0]["count"] == 99


def test_referrers_and_paths_are_dated_snapshots_never_a_series():
    """The API returns these only as a single 14-day aggregate. Storing them as
    if they were daily would invite exactly the arithmetic that cannot be done
    on them — summing or differencing two overlapping windows."""
    first, _ = repo_traffic.merge(
        {}, _github([], [], referrers=[{"referrer": "Google", "count": 4, "uniques": 4}]), {}, NOW)
    second, _ = repo_traffic.merge(
        first, _github([], [], referrers=[{"referrer": "Google", "count": 6, "uniques": 5}]), {}, LATER)

    snaps = second["referrers_snapshots"]
    assert [s["captured_at"] for s in snaps] == [
        "2026-08-22T03:38:00Z", "2026-08-26T03:38:00Z"]
    assert all(s["window_days"] == 14 for s in snaps)
    assert snaps[0]["rows"][0]["count"] == 4
    assert snaps[1]["rows"][0]["count"] == 6
    assert "referrers" not in second, "aggregates must not masquerade as a merged series"


def test_a_rerun_in_the_same_minute_replaces_its_snapshot_rather_than_duplicating():
    first, _ = repo_traffic.merge({}, _github([], [], referrers=[{"referrer": "a", "count": 1, "uniques": 1}]), {}, NOW)
    second, _ = repo_traffic.merge(first, _github([], [], referrers=[{"referrer": "a", "count": 2, "uniques": 1}]), {}, NOW)
    assert len(second["referrers_snapshots"]) == 1
    assert second["referrers_snapshots"][0]["rows"][0]["count"] == 2


def test_the_stored_note_states_the_precision_boundary():
    merged, _ = repo_traffic.merge({}, _github([], []), {}, NOW)
    assert "must not be" in merged["note"]
    assert "14-day" in merged["note"]


def test_package_downloads_are_advisory_and_never_lose_the_github_half():
    """PyPI and npm both expose longer history through their own APIs, so a
    registry outage is recoverable. The GitHub window is not — a failure there
    must not be papered over by a partial write."""
    merged, _ = repo_traffic.merge(
        {}, _github([_day("2026-08-21T00:00:00Z", 20, 5)], []),
        {"npm_error": "HTTP 503", "pypi": {"last_month": 896}}, NOW)
    assert merged["views"][0]["count"] == 20
    assert merged["package_downloads"][0]["npm_error"] == "HTTP 503"
    assert merged["package_downloads"][0]["pypi"]["last_month"] == 896


def test_authority_counts_are_snapshots_that_accumulate_into_a_curve():
    """Stars/forks are running totals, so the point is the series, not the value.

    Tracking them at all is the correction #1120 asked for: the distribution
    gap is standing, not crawl budget, and the number was previously only
    whatever `gh repo view` printed the day someone ran it.
    """
    first, _ = repo_traffic.merge({}, _github([], [], repo={
        "stargazers_count": 13, "forks_count": 1,
        "subscribers_count": 2, "open_issues_count": 12}), {}, NOW)
    second, _ = repo_traffic.merge(first, _github([], [], repo={
        "stargazers_count": 15, "forks_count": 1,
        "subscribers_count": 2, "open_issues_count": 9}), {}, LATER)

    snaps = second["authority_snapshots"]
    assert [s["captured_at"] for s in snaps] == [
        "2026-08-22T03:38:00Z", "2026-08-26T03:38:00Z"]
    assert [s["stargazers"] for s in snaps] == [13, 15]
    assert snaps[1]["open_issues"] == 9


def test_a_rerun_in_the_same_minute_replaces_the_authority_snapshot():
    first, _ = repo_traffic.merge({}, _github([], [], repo={"stargazers_count": 13}), {}, NOW)
    second, _ = repo_traffic.merge(first, _github([], [], repo={"stargazers_count": 14}), {}, NOW)

    assert len(second["authority_snapshots"]) == 1
    assert second["authority_snapshots"][0]["stargazers"] == 14


def test_a_missing_repo_block_keeps_both_the_traffic_and_the_prior_authority():
    """Authority never ages out, so it must never be able to cost a capture.

    A file written before this section existed, or a caller that did not ask
    for the repo block, keeps its traffic half and its earlier snapshots
    instead of failing over a secondary metric.
    """
    seeded, _ = repo_traffic.merge({}, _github([], [], repo={"stargazers_count": 13}), {}, NOW)
    merged, _ = repo_traffic.merge(
        seeded, _github([_day("2026-08-25T00:00:00Z", 7, 3)], []), {}, LATER)

    assert merged["views"][-1]["count"] == 7
    assert [s["stargazers"] for s in merged["authority_snapshots"]] == [13]


def test_a_missing_token_is_an_error_not_an_empty_reading(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    assert repo_traffic.main([]) == 2
    assert "unrecoverable" in capsys.readouterr().err


def test_the_workflow_captures_often_enough_to_survive_one_miss():
    """The window is 14 days, so weekly would work on paper — until one run
    fails and takes 7 unrecoverable days with it."""
    workflow = (ROOT / ".github" / "workflows" / "repo-traffic.yml").read_text(encoding="utf-8")
    crons = [line for line in workflow.splitlines() if "- cron:" in line]
    assert len(crons) >= 2, "one scheduled capture a week cannot absorb a single failure"
    assert "group: data-write" in workflow, "it commits to master; it must share the writer lane"


@pytest.mark.parametrize("field", ["views", "clones", "referrers_snapshots",
                                   "paths_snapshots", "package_downloads"])
def test_the_committed_file_carries_every_section(field):
    path = ROOT / "assets" / "data" / "repo-traffic.json"
    if not path.exists():
        pytest.skip("no capture committed yet")
    assert field in json.loads(path.read_text(encoding="utf-8"))


def test_a_capture_gap_is_named_at_the_moment_it_is_still_detectable():
    """Days that aged out of the window while nobody was capturing are gone for
    good. A month later the series just looks shorter, so the only chance to
    say so is the run that first sees the discontinuity."""
    stored = [_day("2026-08-01T00:00:00Z", 5, 2)]
    incoming = [_day("2026-08-20T00:00:00Z", 7, 3)]
    assert repo_traffic.find_gap(stored, incoming) == ("2026-08-01", "2026-08-20")


def test_a_contiguous_or_overlapping_window_is_not_a_gap():
    stored = [_day("2026-08-20T00:00:00Z", 5, 2)]
    assert repo_traffic.find_gap(stored, [_day("2026-08-20T00:00:00Z", 5, 2)]) is None
    assert repo_traffic.find_gap(stored, [_day("2026-08-21T00:00:00Z", 6, 2)]) is None
    assert repo_traffic.find_gap([], [_day("2026-08-21T00:00:00Z", 6, 2)]) is None
