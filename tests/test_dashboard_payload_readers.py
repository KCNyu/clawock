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
    "recent_plans_dropped",
    "payload_over_cap",
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
