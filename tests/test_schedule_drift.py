"""Reconstructing which cron instant a scheduled run belongs to.

GitHub does not report the instant a scheduled run was meant to fire, only when
it actually started. Drift is therefore a reconstruction, and a wrong
reconstruction produces a confident wrong number — which is worse than no number
for an argument that is entirely about numbers.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "schedule_drift", ROOT / "ops" / "ci" / "schedule_drift.py")
drift = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(drift)


def at(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s)


def test_the_reconstructed_instant_is_the_latest_one_at_or_before_the_run():
    # 2026-08-21 is a Friday.
    assert drift.previous_occurrence("25 0 * * 1-5", at("2026-08-21T02:02:49")) \
        == at("2026-08-21T00:25:00")
    # Exactly on time is drift zero, not a jump back a day.
    assert drift.previous_occurrence("25 0 * * 1-5", at("2026-08-21T00:25:00")) \
        == at("2026-08-21T00:25:00")


def test_a_weekday_cron_does_not_match_the_weekend():
    """2026-08-22 is a Saturday: a `1-5` cron's last occurrence is Friday's,
    and a Saturday-morning start belongs to it, not to a Saturday that has no
    occurrence at all."""
    assert drift.previous_occurrence("0 22 * * 1-5", at("2026-08-22T02:00:00")) \
        == at("2026-08-21T22:00:00")


def test_a_run_further_back_than_the_lookback_is_not_guessed_at():
    """A `25 0 * * 1-5` run that started Saturday 01:00 would be 24.5 hours
    after Friday's occurrence — far outside anything GitHub has ever done (the
    worst measured is 213 minutes). Attributing it anyway would invent a
    headline drift figure out of a clock problem."""
    assert drift.previous_occurrence("25 0 * * 1-5", at("2026-08-22T01:00:00")) is None


@pytest.mark.parametrize("dow", ["0", "7"])
def test_sunday_is_accepted_in_both_of_crons_spellings(dow):
    # 2026-08-16 is a Sunday.
    assert drift.previous_occurrence(f"0 23 * * {dow}", at("2026-08-16T23:30:00")) \
        == at("2026-08-16T23:00:00")


def test_python_and_cron_disagree_about_which_day_is_zero():
    """cron: Sunday=0. Python: Monday=0. Getting this backwards shifts every
    weekly workflow's drift by a day and nothing visibly breaks."""
    # 2026-08-21 Friday -> cron dow 5.
    assert drift.previous_occurrence("0 22 * * 5", at("2026-08-21T22:30:00")) \
        == at("2026-08-21T22:00:00")
    # ...and Friday must not satisfy a Saturday cron.
    assert drift.previous_occurrence("0 22 * * 6", at("2026-08-21T22:30:00")) \
        != at("2026-08-21T22:00:00")


def test_a_cron_this_parser_does_not_understand_raises_instead_of_matching():
    """Silently treating an unparsed field as `*` would report a late workflow
    as perfectly punctual."""
    for expr in ["*/5 * * * *", "0 0 1 * *", "0 0 * 3 *", "0 0 *", "0 99 * * *"]:
        with pytest.raises(drift.DriftError):
            drift.previous_occurrence(expr, at("2026-08-21T00:00:00"))


def test_lists_and_ranges_both_parse():
    minutes, hours, dow = drift._cron_fields("0,30 21-22 * * 0-4")
    assert minutes == {0, 30}
    assert hours == {21, 22}
    assert dow == {0, 1, 2, 3, 4}


def test_a_run_older_than_the_lookback_is_left_unattributed():
    """Better an omitted sample than one matched to a guess."""
    assert drift.previous_occurrence("0 22 * * 5", at("2026-08-21T21:00:00")) is None


def test_the_crons_are_read_out_of_the_workflow_files(tmp_path):
    wf = tmp_path / "x.yml"
    wf.write_text("on:\n  schedule:\n    - cron: '25 0 * * 1-5'\n"
                  "    - cron: \"9 1 * * 1-5\"\n  workflow_dispatch:\n")
    assert drift.scheduled_crons(wf) == ["25 0 * * 1-5", "9 1 * * 1-5"]
    assert drift.scheduled_crons(tmp_path / "none.yml") if (tmp_path / "none.yml").exists() else True


def test_the_real_workflows_all_parse():
    """A cron this repository actually uses that the parser cannot read would
    silently drop that workflow out of the measurement."""
    seen = 0
    for path in (ROOT / ".github" / "workflows").glob("*.yml"):
        for expr in drift.scheduled_crons(path):
            drift._cron_fields(expr)   # raises if unsupported
            seen += 1
    assert seen >= 10, "the measurement must cover the scheduled workflows, not a subset"


def test_the_stored_note_admits_the_figures_are_a_lower_bound():
    payload = ROOT / "assets" / "data" / "schedule-drift.json"
    if not payload.exists():
        pytest.skip("no capture committed yet")
    import json
    assert "lower bound" in json.loads(payload.read_text(encoding="utf-8"))["note"]


# ── which occurrence, and which crons (#2517, #2526) ─────────────────────────

def test_two_crons_closer_together_than_the_delay_each_keep_their_own_run():
    """05:45 and 05:55 HKT, both delivered ~3h late, arrive minutes apart. The
    earlier cron used to have no sample at all: both runs went to the later one."""
    crons = ["45 21 * * 0-4", "55 21 * * 0-4"]
    samples = drift.attribute([
        ("early", at("2026-10-02T01:04:28"), crons),
        ("late", at("2026-10-02T01:06:20"), crons),
        ("yesterday-early", at("2026-10-01T00:50:00"), crons),
        ("yesterday-late", at("2026-10-01T00:51:46"), crons),
    ])
    assert {s["run_id"]: (s["cron"], s["scheduled_at"]) for s in samples} == {
        "early": ("45 21 * * 0-4", "2026-10-01T21:45:00Z"),
        "late": ("55 21 * * 0-4", "2026-10-01T21:55:00Z"),
        "yesterday-early": ("45 21 * * 0-4", "2026-09-30T21:45:00Z"),
        "yesterday-late": ("55 21 * * 0-4", "2026-09-30T21:55:00Z"),
    }
    assert [s["run_id"] for s in samples][0] == "late", "newest first, like the API"


def test_a_run_that_arrives_after_the_next_occurrence_is_its_own_wave():
    """Runs with a cron instant between them are not regrouped: each takes the
    latest instant before it, as before."""
    samples = drift.attribute([
        ("a", at("2026-08-21T07:03:00"), ["0 7 * * *", "0 10 * * *"]),
        ("b", at("2026-08-21T10:05:00"), ["0 7 * * *", "0 10 * * *"]),
    ])
    assert {s["run_id"]: s["drift_minutes"] for s in samples} == {"a": 3.0, "b": 5.0}


def test_one_occurrence_is_never_given_to_two_runs():
    samples = drift.attribute([
        ("a", at("2026-08-21T22:10:00"), ["0 22 * * *"]),
        ("b", at("2026-08-21T22:12:00"), ["0 22 * * *"]),
    ])
    assert len({s["scheduled_at"] for s in samples}) == len(samples) == 1
    assert samples[0]["run_id"] == "b"


def test_a_run_is_matched_against_the_crons_its_workflow_had_at_the_time():
    """weekly-health moved from 23:00 to 20:17 UTC on 2 October. Every earlier
    run was re-attributed to 20:17 and read 163 minutes later than it was."""
    history = [(at("2026-05-01T00:00:00"), ["0 23 * * 0"]),
               (at("2026-10-02T02:38:54"), ["17 20 * * 0"])]
    before, after = at("2026-09-28T01:20:55"), at("2026-10-04T21:00:00")
    assert drift.crons_at(history, before, ["17 20 * * 0"]) == ["0 23 * * 0"]
    assert drift.crons_at(history, after, ["17 20 * * 0"]) == ["17 20 * * 0"]
    sample, = drift.attribute([("r", before, drift.crons_at(history, before, []))])
    assert (sample["cron"], sample["drift_minutes"]) == ("0 23 * * 0", 140.9)


def test_the_cron_history_is_the_version_live_at_the_oldest_run_and_every_later_one(monkeypatch):
    files = {"new": "    - cron: '17 20 * * 0'\n", "old": "    - cron: '0 23 * * 0'\n",
             "older": "    - cron: '0 1 * * 1'\n"}
    asked = []

    def api(path, token, raw=False):
        asked.append(path)
        if raw:
            return files[path.rsplit("ref=", 1)[1]]
        return [{"sha": sha, "commit": {"committer": {"date": date}}} for sha, date in (
            ("new", "2026-10-02T02:38:54Z"), ("old", "2026-08-24T00:00:00Z"),
            ("older", "2026-06-01T00:00:00Z"))]

    monkeypatch.setattr(drift, "_api", api)
    history = drift.cron_history("weekly-health.yml", at("2026-09-01T00:00:00"), "t")
    assert history == [(at("2026-08-24T00:00:00"), ["0 23 * * 0"]),
                       (at("2026-10-02T02:38:54"), ["17 20 * * 0"])]
    assert not any(path.endswith("ref=older") for path in asked)
