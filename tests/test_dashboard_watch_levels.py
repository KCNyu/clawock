"""Watch Levels resolve a plan's free-form keys against the book — in the right unit.

`computeWatchRows` lives in both dashboard bundles (Hero strip and the Plan
card). Its book/derisk branch read every such key as a percent threshold, so
the 2026-09-17 plan's `book_force_derisk_usd: -300` — a USD P&L line — rendered
as "目标 -300.0% · 现 -21.0% · +279.0pp" (#1531). The inverse, a `_pct` key read
as an amount (-22042%), was fixed on 2026-05-31 and must stay fixed.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from clawock.publish import dashboard

ROOT = Path(__file__).resolve().parents[1]
BUNDLES = ("dashboard.hero.js", "dashboard.render.js")
TOTALS = {
    "us": {"pnl_usd": -929.62, "pnl_pct": -20.9544},
    "hk": {"pnl_hkd": -48648.44, "pnl_pct": -44.19},
}


def test_large_plan_summary_retains_watch_levels_for_both_page_surfaces(tmp_path, monkeypatch):
    memory = tmp_path / 'memory'
    memory.mkdir()
    levels = {'book_force_derisk_usd': -300}
    (memory / '2026-09-28-plan.json').write_text(json.dumps({
        'date': '2026-09-28', 'summary': 'x' * 200,
        'watch_levels': levels, 'decisions': [],
    }))
    monkeypatch.setattr(dashboard, 'WS_ROOT', tmp_path)
    monkeypatch.setattr(dashboard, 'MAX_PLAN_BYTES', 100)
    plan = dashboard.load_plans()[0]['plan']
    assert plan['truncated'] is True
    assert plan['watch_levels'] == levels


def _watch_rows(bundle, levels, holdings=()):
    source = (ROOT / "site" / "assets" / "js" / bundle).read_text(encoding="utf-8")
    fn = re.search(r"^  function computeWatchRows\(\) \{.*?^  \}$", source,
                   re.MULTILINE | re.DOTALL).group(0)
    data = {"recent_plans": [{"date": "2026-09-17", "plan": {"watch_levels": levels}}],
            "totals": TOTALS, "indices": {}, "watch_holdings": list(holdings)}
    script = (
        "const DATA = " + json.dumps(data) + ";\n"
        "const safe = (o, ...ks) => ks.reduce((v, k) => v == null ? undefined : v[k], o);\n"
        "const flatHoldings = () => DATA.watch_holdings;\n"
        + fn + "\nprocess.stdout.write(JSON.stringify(computeWatchRows().rows));\n"
    )
    out = subprocess.run([shutil.which("node"), "-e", script], check=True,
                         capture_output=True, text=True).stdout
    return {row["who"] + "/" + str(row["val"]): row for row in json.loads(out)}


def _ordered_rows(bundle, levels, holdings=()):
    return list(_watch_rows(bundle, levels, holdings).values())


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required to run the bundle")
@pytest.mark.parametrize("bundle", BUNDLES)
def test_book_amount_and_percent_guards_keep_their_units(bundle):
    rows = _watch_rows(bundle, {
        "book_force_derisk_usd": -300,
        "book_force_derisk_hkd": -50000,
        "book_force_derisk_us_pct": -25,
    })

    usd = rows["账面 US/-300"]
    assert (usd["isPct"], usd["ccy"], usd["cur"]) == (False, "USD", -929.62)
    assert usd["label"] == "强制减仓"
    hkd = rows["账面 HK/-50000"]
    assert (hkd["isPct"], hkd["ccy"], hkd["cur"]) == (False, "HKD", -48648.44)

    pct = rows["账面 US/-25"]
    assert (pct["isPct"], pct["ccy"], pct["cur"]) == (True, "%", -20.9544)
    assert pct["dist"] == pytest.approx(4.0456)


SPCH = {"ticker": "SPCH", "region": "us", "current_price": 9.61, "pnl_percent": -20.32}


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required to run the bundle")
@pytest.mark.parametrize("bundle", BUNDLES)
def test_a_holding_percent_key_is_not_read_as_a_price(bundle):
    # spch_breakdown_pct: -4 rendered as "$-4.00 · 现 $9.61 · +340.2%" (#2196).
    # The key does not say what the -4% is measured from, so no distance.
    rows = _watch_rows(bundle, {"spch_breakdown_pct": -4, "spch_stop": 9}, [SPCH])
    pct = rows["SPCH/-4"]
    assert (pct["isPct"], pct["ccy"], pct["cur"], pct["dist"]) == (True, "%", None, None)
    assert pct["label"] == "破位"
    price = rows["SPCH/9"]
    assert (price["isPct"], price["ccy"], price["cur"]) == (False, "USD", 9.61)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required to run the bundle")
@pytest.mark.parametrize("bundle", BUNDLES)
def test_a_crossed_guard_is_fired_and_sorts_first_however_far_past(bundle):
    # book_force_derisk_usd: -300 against a -$929.62 book was the faintest row
    # on the card because only |distance| decided urgency (#2195).
    rows = _ordered_rows(bundle, {
        "spch_5d_ma_reclaim": 9.55,   # above the level: an upside trigger that fired
        "spch_stop": 9.5,             # above a stop: not fired, 1.2% away
        "book_force_derisk_usd": -300,
    }, [SPCH])
    assert [(r["who"], r["fired"], r["side"]) for r in rows] == [
        ("账面 US", True, "below"),
        ("SPCH", True, "above"),
        ("SPCH", False, "below"),
    ]
