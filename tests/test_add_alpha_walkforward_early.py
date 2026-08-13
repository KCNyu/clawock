"""No-lookahead contracts for the early-candidate diagnostic replay."""
from clawock.evaluation import add_alpha_walkforward as replay


def test_early_replay_uses_signal_close_then_future_closes_only(monkeypatch):
    bars = []
    for day in range(1, 36):
        close = 10.0 if day < 30 else 11.0 + (day - 30) * .1
        bars.append({
            "date": f"2026-07-{day:02d}",
            "open": close, "high": close, "low": close, "close": close,
        })
    signal_date = bars[29]["date"]
    config = {
        "symbols": [{"ticker": "ABC", "region": "us", "sector": "test"}],
        "leveraged_proxies": [],
    }
    policy = {
        "minimum_attention_acceleration": 1.25,
        "minimum_attention_source_types": 1,
        "early_peer_dispersion_multiple": 1.5,
        "early_no_chase_zscore": 99,
        "confirmation_window_sessions": 5,
        "minimum_evidence_families": 2,
        "minimum_information_score": .08,
        "minimum_event_novelty": .5,
        "minimum_event_reliability": .5,
        "minimum_price_nonreaction": .6,
        "markets": {"US": {
            "minimum_attention_rank": .75, "minimum_peer_count": 3,
            "minimum_factor_coverage_pct": 80, "minimum_sector_universe_size": 4,
            "enter_market_percentile": .75, "exit_market_percentile": .55,
        }},
    }
    news_policy = {"information_overlay": {}}
    factor_history = [{
        "as_of": signal_date,
        "rows": {"ABC": {"feature_as_of": signal_date, "composite_score": .5}},
    }]

    monkeypatch.setattr(
        replay.peer_residuals, "build_taxonomy",
        lambda _config, _peers: ({"ABC": {"signal_ticker": "ABC"}}, _config),
    )
    monkeypatch.setattr(
        replay.peer_residuals, "_canonical_taxonomy_items",
        lambda taxonomy: list(taxonomy.items()),
    )
    monkeypatch.setattr(
        replay.peer_residuals, "metrics_at",
        lambda *_args: {
            "residual_blend_5d": .2, "peer_dispersion_5d": .05,
            "available_peer_count": 4,
        },
    )
    monkeypatch.setattr(
        replay, "_json",
        lambda path: {"basket_weight_cap": .4}
        if str(path).endswith("peer-residual-rules.json") else {},
    )

    metrics = replay.evaluate(
        config, policy, news_policy, {"ABC": {"bars": bars}},
        factor_history, [], [],
    )

    t1 = metrics["early_trend"]["us"]["observed"]["t1"]
    t5 = metrics["early_trend"]["us"]["observed"]["t5"]
    assert t1["n"] == 1 and t5["n"] == 1
    assert t1["mean_return"] == round(bars[30]["close"] / bars[29]["close"] - 1, 6)
    assert t5["mean_return"] == round(bars[34]["close"] / bars[29]["close"] - 1, 6)
    assert metrics["early_trend"]["us"]["information_confirmed"]["t1"]["n"] == 0
    assert metrics["coverage"]["early_trend"]["lookahead"].startswith(
        "features_recomputed_at_each_snapshot_date"
    )
