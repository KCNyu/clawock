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
    # #1642: nothing was measured, so the label may not claim a reading.
    assert "趋势OFF" not in payload["label"] and "波动过热" not in payload["label"]
    assert "数据不足" in payload["label"] and payload["hk"]["label"] == payload["label"]


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
    assert payload["label"].startswith("200日线数据不足")


def test_compute_survives_zero_close(monkeypatch):
    """#1492: one 0.0 close (bad tick / halted-session gap) used to divide by
    closes[i-1] == 0 inside the vol return calc and blow up ZeroDivisionError,
    which neither main() nor compute_us() caught — one bad print crashed the
    whole regime run instead of degrading gracefully like the missing-inputs
    path above."""
    clean = [100.0 + i for i in range(regime.MA_WINDOW + 25)]
    closes = clean[:-5] + [0.0] + clean[-5:]  # zero tick near the end
    ma, vol = regime.compute(closes)  # must not raise
    # The bad print is dropped, not averaged in as a 0 or a -100% return.
    assert (ma, vol) == regime.compute(clean)
    assert ma is not None and vol is not None


def test_compute_all_non_positive_closes_returns_none(monkeypatch):
    """Degenerate case: nothing survives the non-positive filter."""
    ma, vol = regime.compute([0.0, -1.0, 0.0])
    assert (ma, vol) == (None, None)
