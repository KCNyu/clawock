"""Unit tests for the walkforward measurement splits (#1098/#1099).

The splits classify a fill by price structure vs the prior 20-day high
(breakout / near_high / deep_dip) and by the 20-day volatility regime
(high_vol / low_vol vs the ticker's own trailing median). They only annotate
fill rows; they change no fill, no authority tier and no live behaviour.
"""
from clawock.evaluation import add_alpha_walkforward as awf


def _bars(closes, highs=None, start_day=1, start_month=1):
    """Synthetic daily bars with ISO dates; highs default to closes."""
    rows = []
    month, day = start_month, start_day
    for i, close in enumerate(closes):
        rows.append({
            "date": f"2026-{month:02d}-{day:02d}",
            "open": close,
            "high": (highs[i] if highs else close),
            "low": close,
            "close": close,
        })
        day += 1
        if day > 28:
            day, month = 1, month + 1
    return rows


def test_structure_bucket_breakout_near_deep():
    # prior 20d high = 100 (rows before the signal date)
    bars = _bars([90] * 19 + [100], highs=[100] * 20)
    signal = "2026-02-01"
    # 105 >= prior high -> breakout
    assert awf._structure_bucket(bars, signal, 105) == "breakout"
    # 100 == prior high -> breakout (fills at the level count)
    assert awf._structure_bucket(bars, signal, 100) == "breakout"
    # 96 / 100 = 0.96 > 0.92 -> near_high
    assert awf._structure_bucket(bars, signal, 96) == "near_high"
    # 92 / 100 = 0.92 is NOT > 0.92 -> deep_dip (#856: <= 92% is the deep dip)
    assert awf._structure_bucket(bars, signal, 92) == "deep_dip"
    assert awf._structure_bucket(bars, signal, 80) == "deep_dip"


def test_structure_bucket_needs_prior_history():
    assert awf._structure_bucket([], "2026-02-01", 100) is None
    # 只有一根历史 bar 也按「已有先例」处理(取可得的前期高点)
    assert awf._structure_bucket(_bars([100]), "2026-02-01", 100) == "breakout"


def test_vol_regime_high_vs_low():
    # 前半 noisy、尾部完美线性(波动率为 0)→ recent vol < 自身中位数
    calm = _bars(
        [100.0 + 0.1 * i + (0.3 if i % 2 else 0.0) for i in range(25)]
        + [100.0 + 0.1 * i for i in range(25, 45)]
    )
    assert awf._vol_regime(calm, "2026-03-15") == "low_vol"
    # 前半线性、尾部剧烈摆动 → recent vol 高于自身中位数
    spiky = _bars(
        [100.0 + 0.1 * i for i in range(40)] + [140, 105, 135, 110, 130]
    )
    assert awf._vol_regime(spiky, "2026-03-15") == "high_vol"


def test_vol_regime_needs_history():
    assert awf._vol_regime(_bars([100.0] * 25), "2026-02-01") is None


def test_split_summary_groups_by_bucket():
    rows = [
        {"return": 1.0, "date": "2026-01-01", "ticker": "A", "structure": "breakout"},
        {"return": -1.0, "date": "2026-01-02", "ticker": "B", "structure": "breakout"},
        {"return": 2.0, "date": "2026-01-03", "ticker": "C", "structure": "deep_dip"},
        {"return": 0.5, "date": "2026-01-04", "ticker": "D", "structure": None},
    ]
    split = awf._split_summary(rows, "structure")
    assert set(split) == {"breakout", "deep_dip"}
    assert split["breakout"]["n"] == 2
    assert split["breakout"]["hit_rate"] == 0.5
    assert split["deep_dip"]["n"] == 1
    assert awf._split_summary(rows, "missing_key") == {}
