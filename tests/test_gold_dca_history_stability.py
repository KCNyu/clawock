"""Regression coverage for London-gold history provenance and settlement."""
from datetime import date, timedelta
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "data"))

import fetch_gold_dca as gold  # noqa: E402


def rows(values):
    return [(f"2026-07-{day:02d}", value) for day, value in values]


def dated_rows(count):
    start = date(2025, 1, 1)
    return [
        ((start + timedelta(days=offset)).isoformat(), 100.0 + offset)
        for offset in range(count)
    ]


def spaced_rows(count, span_days):
    start = date(2025, 1, 1)
    return [
        (
            (start + timedelta(days=offset * span_days // (count - 1))).isoformat(),
            100.0 + offset,
        )
        for offset in range(count)
    ]


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


def test_stale_date_absent_from_fresh_feed_is_evicted_outside_bound():
    previous = dated_rows(200)
    fresh = previous[1:]
    coverage_start = previous[40][0]

    stable, advisory = gold.stabilize_history(
        fresh,
        previous,
        {"name": gold.XAU_PRIMARY_SOURCE, "points": len(fresh)},
        {"name": gold.XAU_PRIMARY_SOURCE, "points": len(previous)},
        coverage_start=coverage_start,
    )

    assert previous[0][0] not in dict(stable)
    assert stable == fresh[40 - gold.XAU_SETTLEMENT_DAYS - 1:]
    assert advisory is None


def test_date_bound_keeps_coverage_and_preceding_settlement_window():
    fresh = dated_rows(200)
    coverage_start = fresh[40][0]

    stable, advisory = gold.stabilize_history(
        fresh,
        [],
        {"name": gold.XAU_PRIMARY_SOURCE, "points": len(fresh)},
        coverage_start=coverage_start,
    )

    assert stable == fresh[40 - gold.XAU_SETTLEMENT_DAYS:]
    assert advisory is None


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


def test_london_payload_serializes_both_histories_within_bound():
    oversized = dated_rows(gold.HISTORY_KEEP + 47)
    nav = [[day, 3.0] for day, _ in oversized[-gold.HISTORY_KEEP:]]
    start = oversized[-(gold.HISTORY_KEEP + 10)][0]

    london = gold.compute_london(
        {"current_value": 1000.0, "nav_history": nav},
        {"start_date": start, "daily_amount": 200},
        {"xau_usd": oversized[-1][1], "change_pct": 1.0},
        7.0,
        dict((day, 7.0) for day, _ in oversized),
        oversized,
    )

    expected = oversized[-(gold.HISTORY_KEEP + gold.XAU_SETTLEMENT_DAYS):]
    assert london["hist_series"] == [[day, round(value, 4)] for day, value in expected]
    assert london["fx_hist_series"] == [[day, 7.0] for day, _ in expected]


def test_sliding_coverage_anchor_bounds_retained_london_history():
    start = "2026-01-22"
    first_day = date(2026, 1, 22)
    last_day = date(2029, 7, 30)
    xau = []
    day = first_day
    while day <= last_day:
        if day.weekday() < 5:
            xau.append((day.isoformat(), 2000.0))
        day += timedelta(days=1)
    nav = []
    day = last_day
    while len(nav) < gold.HISTORY_KEEP:
        if day.weekday() < 5:
            nav.append([day.isoformat(), 3.0])
        day -= timedelta(days=1)
    nav.sort()

    coverage_start = gold._london_history_coverage_start(nav, start)
    retained = gold._bounded_london_history(xau, coverage_start)
    max_retained = gold.HISTORY_KEEP + gold.XAU_SETTLEMENT_DAYS

    assert len(xau) == 918
    # Same weekday calendar: 140 NAV dates plus five preceding settlement points.
    assert len(retained) <= max_retained == 145
    assert coverage_start == nav[0][0]


def test_retention_does_not_starve_oldest_nav_purchases():
    daily = 200
    nav = [[day, 3.0] for day, _ in spaced_rows(gold.HISTORY_KEEP, 212)]
    xau = spaced_rows(152, 212)
    coverage_start = gold._london_history_coverage_start(nav, nav[0][0])
    retained, advisory = gold.stabilize_history(
        xau,
        [],
        {"name": gold.XAU_PRIMARY_SOURCE, "points": len(xau)},
        coverage_start=coverage_start,
    )

    dca = gold.build_london_dca(
        nav,
        retained,
        {day: 7.0 for day, _ in xau},
        xau_cur=xau[-1][1],
        usdcny_cur=7.0,
        start=nav[0][0],
        daily=daily,
    )

    assert advisory is None
    assert retained[0][0] == nav[0][0]
    assert dca["principal_cny"] == daily * len(nav)


def test_dashboard_drops_internal_history_but_keeps_provenance_contract():
    builder = (ROOT / "scripts" / "data" / "build_dashboard.py").read_text()
    renderer = (ROOT / "assets" / "js" / "dashboard.render.js").read_text()

    assert "_gold['london'].pop('hist_series', None)" in builder
    assert "_gold['london'].pop('fx_hist_series', None)" in builder
    assert "历史源 ${escapeHtml(" in renderer
    assert 'role="status"' in renderer
    assert "ld.hist_advisory" in renderer
