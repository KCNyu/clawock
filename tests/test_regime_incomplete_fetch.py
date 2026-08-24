"""`clawock regime` must survive an incomplete HSTECH fetch (#943).

A short series leaves `compute()` with ma and/or vol as None; the rationale
f-string used to format them unconditionally, so main() died with TypeError,
the preflight subprocess swallowed it, and the stale lev_regime.json kept
feeding the guardrail multiplier with no marker. The contract here: the dial
still publishes a conservative tier/multiplier plus a machine-readable
missing_inputs list, offline.
"""
import json

import pytest

from clawock.decision import regime


@pytest.fixture
def offline_dial(monkeypatch):
    """Pin every network/workspace seam so main() runs on synthetic bars."""
    monkeypatch.setattr(regime, "compute_us", lambda: {
        "names": [], "tier": "green", "label": "test",
        "cut_count": 0, "watch_count": 0})
    monkeypatch.setattr(regime, "load_spy_series", lambda: ([], []))


def _run(monkeypatch, bars):
    monkeypatch.setattr(
        regime, "fetch_hstech",
        lambda: [(f"2026-01-{i + 1:02d}", float(bars[i])) for i in range(len(bars))])
    buf = {}
    import io
    import contextlib
    with contextlib.redirect_stdout(io.StringIO()) as out:
        regime.main(["--dry-run"])
    return json.loads(out.getvalue())


def test_short_fetch_missing_ma_and_vol_stays_conservative(offline_dial, monkeypatch):
    payload = _run(monkeypatch, [100.0] * 15)
    assert payload["missing_inputs"] == ["ma", "vol"]
    assert payload["ma"] is None and payload["vol_annualized"] is None
    assert payload["tier"] in ("amber", "red")
    assert payload["lev_cap_mult"] == pytest.approx((0.5, 0.0)[payload["tier"] == "red"])
    assert "不可用" in payload["rationale"]
    assert "×" in payload["rationale"]


def test_full_history_path_is_unchanged(offline_dial, monkeypatch):
    closes = [100.0 + i for i in range(regime.MA_WINDOW + 25)]
    payload = _run(monkeypatch, closes)
    assert "missing_inputs" not in payload
    assert payload["ma"] is not None and payload["vol_annualized"] is not None
    assert payload["trend_on"] is True
    assert payload["lev_cap_mult"] == 1.0


def test_mid_history_has_vol_but_no_ma(offline_dial, monkeypatch):
    closes = [100.0 + (i % 7) * 0.2 for i in range(regime.MA_WINDOW - 10)]
    payload = _run(monkeypatch, closes)
    assert payload["missing_inputs"] == ["ma"]
    assert payload["vol_annualized"] is not None
