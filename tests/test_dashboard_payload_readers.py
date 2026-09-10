"""Every block the dashboard publishes has to be read by the page it is for.

维度 E — 写了没人读. `dashboard.json` is built on every generation and fetched by
every visitor who opens a detail tab, and it has a hard 200,000-byte cap whose
overflow is a real loss: `build_dashboard` drops `recent_plans` and then trims
the embedded snapshot series until the payload fits. So a block nobody renders
is not free — it is paid for out of the same budget as the history the page
actually shows.

Two were being paid for on 2026-09-06:

* `current_holdings_extremes` — the 最强最弱 table read it until 46b87e04
  (2026-08-23) merged four per-ticker tables into one. The reader went; the
  producer stayed. `today_ranges`, its sibling from that same merge, survived
  because the merged table reads it — which is what makes this an omission
  rather than a decision.
* `lookthrough_exposure` — a fail-soft wrapper around
  `clawock.instruments.compute_lookthrough_exposure` whose only consumer was
  this key. The brief reads the canonical function directly and is unaffected.

`magnitude_metrics` was the third, and it went the other way: its own test says
the signed error "shows up here and in no other number on the dashboard", which
was true of the number and false of the dashboard. It is now a row on the
honesty card.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"


def _budget_degradation_keys() -> tuple[str, ...]:
    from clawock.publish import dashboard

    return dashboard.BUDGET_DEGRADATION_KEYS

#: Keys that are artifact metadata rather than content: they describe how the
#: payload was cut, and their readers are `clawock validate-sidecar`, the
#: dashboard build itself and the tests around them — never the page. Adding to
#: this list is a claim that a key is not for the reader; make it deliberately.
METADATA_KEYS = {
    "snapshots_total",
    "snapshots_embedded_cap",
    "plans_count",
    "recent_plans_cap",
    "decision_schema_version",
    # The size-cap ladder's markers come from the producer's own list, not a
    # copy kept in step by hand. Two of the three were here and
    # `snapshots_trimmed_for_budget` was not, so the day the second lever fired
    # this gate would have reddened on a key the build had just written itself.
    *_budget_degradation_keys(),
}

SITE_SUFFIXES = {".js", ".html", ".css", ".md"}


def _site_text() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in sorted(SITE.rglob("*"))
        if path.is_file() and path.suffix in SITE_SUFFIXES and "min.js" not in path.name
    )


def test_every_published_block_has_a_reader_on_the_page(freshly_built_dashboard):
    """Built from the real tree, so the set is what today's generation carries."""
    payload = json.loads(freshly_built_dashboard.read_text(encoding="utf-8"))
    site = _site_text()

    unread = sorted(
        key for key in payload
        if key not in METADATA_KEYS
        and not re.search(r"\b" + re.escape(key) + r"\b", site)
    )
    assert not unread, (
        "these blocks are published on every generation and named nowhere under "
        f"site/: {unread}. Either render them or stop paying for them out of the "
        "200,000-byte cap — the overflow path drops recent_plans and trims the "
        "snapshot series, so unread bytes are taken from the history the page "
        "does show.")


def test_the_metadata_allowlist_does_not_outlive_its_keys():
    """An allowlist that keeps names the payload no longer has stops describing
    anything, and quietly grants an exemption to whatever is added with that
    name later."""
    source = (ROOT / "src" / "clawock" / "publish" / "dashboard.py").read_text(
        encoding="utf-8")
    for key in sorted(METADATA_KEYS):
        assert f"'{key}'" in source or f'"{key}"' in source, (
            f"{key} is exempted here but the build no longer writes it")


def test_every_marker_the_size_ladder_writes_is_one_this_gate_knows_about():
    """The ladder is DRIVEN here, not described.

    `snapshots_trimmed_for_budget` was the one marker of three missing from
    `METADATA_KEYS`, so the day the second lever fired this gate would have gone
    red on a key the build had just written itself — on the one generation
    already in trouble. Nothing caught it: the ladder had never been executed.
    Its only coverage was a test that re-implemented the trim loop beside it and
    a `grep` of the source for the marker's name. A lever that fires only on a
    bad day is not exercised by a good one (#1230).

    So: push a payload past the cap for real, three times, and assert that every
    key the ladder adds is one this gate will let through.
    """
    from clawock.publish import dashboard

    def ladder(monkeyed_cap, snapshots, plans):
        out = {
            "snapshots": [{"date": f"2026-01-{i:02d}", "pad": "x" * 400}
                          for i in range(1, snapshots + 1)],
            "recent_plans": [{"pad": "y" * 400} for _ in range(plans)],
        }
        before = set(out)
        original = dashboard.MAX_OUT_BYTES
        dashboard.MAX_OUT_BYTES = monkeyed_cap
        try:
            dashboard.apply_size_budget(out)
        finally:
            dashboard.MAX_OUT_BYTES = original
        return set(out) - before

    # Lever 1 only: dropping the plans is enough.
    first = ladder(14_000, snapshots=30, plans=20)
    assert first == {"recent_plans_dropped"}, first

    # Levers 1 and 2: the plans go, then the oldest snapshots.
    second = ladder(14_000, snapshots=60, plans=20)
    assert second == {"recent_plans_dropped", "snapshots_trimmed_for_budget"}

    # All three: the floor of 30 snapshots holds and it publishes over cap.
    third = ladder(2_000, snapshots=60, plans=20)
    assert third == {"recent_plans_dropped", "snapshots_trimmed_for_budget",
                     "payload_over_cap"}

    written = first | second | third
    assert written == set(dashboard.BUDGET_DEGRADATION_KEYS), (
        "the ladder writes a marker the producer does not declare, so the page "
        f"gate cannot know it is metadata: {written ^ set(dashboard.BUDGET_DEGRADATION_KEYS)}")
    assert written <= METADATA_KEYS, (
        "a size-cap marker would redden `every published block has a reader` on "
        "the very generation that needed the lever")


def test_the_snapshot_floor_survives_the_ladder():
    """`decision_metrics` reads `snapshots[-30:]`; trimming past that changes
    what the window means instead of shortening a chart. Driven, because the
    floor is inside the loop nothing used to run."""
    from clawock.publish import dashboard

    out = {
        "snapshots": [{"date": f"2026-01-{i:02d}", "pad": "x" * 400}
                      for i in range(1, 61)],
        "recent_plans": [],
    }
    original = dashboard.MAX_OUT_BYTES
    dashboard.MAX_OUT_BYTES = 2_000
    try:
        dashboard.apply_size_budget(out)
    finally:
        dashboard.MAX_OUT_BYTES = original

    assert len(out["snapshots"]) == dashboard.MIN_SNAPSHOTS_UNDER_BUDGET
    # Oldest-first: the recent shape is what the equity curve is read for.
    assert out["snapshots"][-1]["date"] == "2026-01-60"
    assert out["snapshots_trimmed_for_budget"] == 30
