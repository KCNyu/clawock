"""Regression coverage for London-gold history provenance and settlement."""
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "data"))

import fetch_gold_dca as gold  # noqa: E402


def rows(values):
    return [(f"2026-07-{day:02d}", value) for day, value in values]


def test_settled_outlier_is_quarantined_but_latest_five_dates_win():
    previous = rows((day, 100.0 + day) for day in range(1, 11))
    fresh = list(previous)
    fresh[1] = ("2026-07-02", 130.0)  # settled: reject 27% rewrite
    fresh[-1] = ("2026-07-10", 140.0)  # latest five: accept provisional close

    stable, advisory = gold.stabilize_history(
        fresh,
        previous,
        {"name": gold.XAU_PRIMARY_SOURCE, "points": len(fresh)},
        {"name": gold.XAU_PRIMARY_SOURCE, "points": len(previous)},
    )

    stable = dict(stable)
    assert stable["2026-07-02"] == 102.0
    assert stable["2026-07-10"] == 140.0
    assert "沿用 1 个已结算点" in advisory
    assert "2026-07-02" in advisory


def test_small_settled_revision_is_accepted():
    previous = rows((day, 100.0) for day in range(1, 8))
    fresh = list(previous)
    fresh[0] = ("2026-07-01", 100.2)

    stable, advisory = gold.stabilize_history(
        fresh,
        previous,
        {"name": gold.XAU_PRIMARY_SOURCE, "points": len(fresh)},
        {"name": gold.XAU_PRIMARY_SOURCE, "points": len(previous)},
    )

    assert dict(stable)["2026-07-01"] == 100.2
    assert advisory is None


def test_primary_feed_recovery_replaces_fallback_reference():
    fallback = rows((day, 200.0) for day in range(1, 8))
    primary = rows((day, 100.0) for day in range(1, 8))

    stable, advisory = gold.stabilize_history(
        primary,
        fallback,
        {"name": gold.XAU_PRIMARY_SOURCE, "points": len(primary)},
        {"name": gold.XAU_FALLBACK_SOURCE, "points": len(fallback)},
    )

    assert dict(stable)["2026-07-01"] == 100.0
    assert advisory is None


def test_empty_fetch_preserves_reference_and_emits_advisory():
    previous = rows((day, 100.0 + day) for day in range(1, 4))

    stable, advisory = gold.stabilize_history(
        [],
        previous,
        {"name": "unavailable", "points": 0},
        {"name": gold.XAU_PRIMARY_SOURCE, "points": len(previous)},
    )

    assert stable == previous
    assert "抓取失败" in advisory
    assert "3 个参考点" in advisory


def test_first_empty_fetch_is_also_visible():
    stable, advisory = gold.stabilize_history(
        [],
        [],
        {"name": "unavailable", "points": 0},
    )

    assert stable == []
    assert advisory == "伦敦金历史抓取失败，暂无可用参考点"


def test_london_payload_persists_reference_and_visible_provenance():
    xau = [("2026-07-01", 100.0), ("2026-07-02", 101.0)]
    derived = {"current_value": 1000.0, "nav_history": [
        ["2026-07-01", 3.0], ["2026-07-02", 3.1],
    ]}
    source = {"name": gold.XAU_PRIMARY_SOURCE, "points": len(xau)}

    london = gold.compute_london(
        derived,
        {"start_date": "2026-07-01", "daily_amount": 200},
        {"xau_usd": 102.0, "change_pct": 1.0},
        7.0,
        {"2026-07-01": 7.0, "2026-07-02": 7.0},
        xau,
        hist_source=source,
        fx_hist_source={"name": "frankfurter_usdcny", "points": 2},
        hist_advisory="test advisory",
    )

    assert london["hist_source"] == source
    assert london["hist_series"] == [
        ["2026-07-01", 100.0], ["2026-07-02", 101.0],
    ]
    assert london["fx_hist_series"] == [
        ["2026-07-01", 7.0], ["2026-07-02", 7.0],
    ]
    assert london["hist_advisory"] == "test advisory"
    assert london["dca_equiv"]["oz_held"] > 0


def test_dashboard_drops_internal_history_but_keeps_provenance_contract():
    builder = (ROOT / "scripts" / "data" / "build_dashboard.py").read_text()
    renderer = (ROOT / "assets" / "js" / "dashboard.render.js").read_text()

    assert "_gold['london'].pop('hist_series', None)" in builder
    assert "_gold['london'].pop('fx_hist_series', None)" in builder
    assert "历史源 ${escapeHtml(" in renderer
    assert 'role="status"' in renderer
    assert "ld.hist_advisory" in renderer
