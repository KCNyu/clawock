"""The US leg's trend question must be answerable, and both legs must be visible.

`trend_on` on the US leg was `None` for the whole life of the regime split, and
not because the market was ambiguous: `load_spy_series` read benchmark.json,
which is capped at ~60 sessions, and 60 sessions can never answer a 200-day
question. The desk's only read on the direction of the US market was therefore
a ±3% band over ten days of momentum — on 2026-09-05 that returned "chop" while
QQQ sat 7.1% above its own 150-session mean and 3.8% off its high.

The same closes are in the bar store without the cap (QQQ: 191 sessions and one
more each day), so the fix is a wider source for the definition that already
exists — not a new window, band or threshold.

The second half is what the brief prints. It showed one line, 「趋势OFF：杠杆
敞口上限砍半」, which is HSTECH against its 200-day mean and caps the HK
leveraged sleeve only. Read as a market call it says the desk thinks nothing is
going up. Both legs, each with its window, is a stated call instead of an
implied one.
"""
from __future__ import annotations

import json

from clawock.decision import regime
from clawock.harness import brief_render


def _bar_store(tmp_path, ticker, closes, start_day=1):
    bars_dir = tmp_path / "memory" / "bars"
    bars_dir.mkdir(parents=True, exist_ok=True)
    bars = {}
    for i, close in enumerate(closes):
        day = f"2026-{1 + (i + start_day) // 28:02d}-{(i + start_day) % 28 + 1:02d}"
        bars[day] = {"open": close, "high": close, "low": close, "close": close}
    (bars_dir / f"{ticker}.json").write_text(json.dumps({"ticker": ticker, "bars": bars}))
    return bars


def test_the_us_proxy_prefers_whichever_source_has_the_longer_history(tmp_path, monkeypatch):
    monkeypatch.setattr(regime, "WS", tmp_path)
    _bar_store(tmp_path, "QQQ", [100.0 + i for i in range(191)])
    data = tmp_path / "assets" / "data"
    data.mkdir(parents=True)
    (data / "benchmark.json").write_text(json.dumps({"series": {"SPY": [
        {"date": f"2026-07-{d:02d}", "close": 500.0} for d in range(1, 29)]}}))

    dates, closes = regime.load_spy_series()

    assert len(closes) == 191, "the 60-day benchmark window won the race again"
    assert regime._US_PROXY_LABEL == "QQQ", (
        "which index the bull/bear call is about has to be reportable")
    assert dates == sorted(dates)


def test_a_long_enough_history_finally_answers_the_trend_question(tmp_path, monkeypatch):
    """The point of the wider source: 200 closes make `trend_on` a real answer."""
    monkeypatch.setattr(regime, "WS", tmp_path)
    _bar_store(tmp_path, "QQQ", [100.0 + i * 0.5 for i in range(240)])

    dates, closes = regime.load_spy_series()
    history = regime.build_regime_history(dates, closes)
    latest = history[max(history)]

    assert latest["trend_on"] is True, (
        "240 rising closes and the trend question is still unanswered — the "
        "definition never reached data long enough to run")
    assert latest["dist_ma_pct"] > 0


def test_a_short_history_still_says_null_rather_than_guessing(tmp_path, monkeypatch):
    monkeypatch.setattr(regime, "WS", tmp_path)
    _bar_store(tmp_path, "QQQ", [100.0 + i * 0.5 for i in range(120)])

    dates, closes = regime.load_spy_series()
    latest = regime.build_regime_history(dates, closes)[max(dates)]

    assert latest["trend_on"] is None, (
        "120 closes cannot answer a 200-day question; a guess here would be "
        "worse than the None it replaced")


def test_the_brief_prints_both_legs_with_the_window_each_was_measured_over():
    section = brief_render.market_trend_section({"risk_guardrail": {"lev_regime": {
        "index": "HSTECH", "ma_window": 200, "dist_ma_pct": -12.3,
        "trend_on": False, "label": "趋势OFF：杠杆敞口上限砍半",
        "regime_history": {
            "us": {"2026-09-03": {"trend_on": None, "dist_ma_pct": None,
                                  "mom_pct": 0.9, "regime3": "chop"}},
            "meta": {"us_index": "QQQ", "us_bars": 191, "ma_window": 200,
                     "mom_window": 10, "mom_band_pct": 3.0,
                     "note": "US 用 QQQ，共 191 根（<200，trend_on 仍为 null）"},
        }}}})

    assert "HK · HSTECH" in section and "US · QQQ" in section
    assert "200日线" in section and "近10日动量" in section, (
        "a -12.3% and a +0.9% printed without their windows read as comparable")
    assert "未知" in section, "an unanswerable US trend must say so, not read as OFF"
    assert "US 杠杆腿走它自己的 per-name dial" in section, (
        "without this the HK line reads as a call on the whole book")


def test_the_meta_says_how_far_the_us_leg_still_is_from_answering(tmp_path, monkeypatch):
    """A null that says «9 sessions to go» is a schedule; a bare null is a dead end."""
    monkeypatch.setattr(regime, "WS", tmp_path)
    _bar_store(tmp_path, "QQQ", [100.0 + i * 0.5 for i in range(191)])

    _, closes = regime.load_spy_series()

    assert len(closes) == 191
    assert regime.MA_WINDOW - len(closes) == 9
