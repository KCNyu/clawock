"""Behavior contracts for the short-history candidate lane."""
from clawock.decision import early_trend


POLICY = {
    "minimum_attention_acceleration": 1.25,
    "minimum_attention_source_types": 1,
    "early_peer_dispersion_multiple": 1.5,
    "early_no_chase_zscore": 2.0,
    "exploration_tranche_pct": 0.025,
    "confirmation_window_sessions": 5,
    "markets": {
        "HK": {"minimum_attention_rank": .65, "minimum_peer_count": 3},
        "US": {"minimum_attention_rank": .75, "minimum_peer_count": 3},
    },
}


def test_short_history_breakout_is_visible_but_overheated_never_chases():
    candidate = early_trend.classify(
        {"usable": True, "close": 376.8, "prior_20d_high": 374.4,
         "zscore20": 2.14},
        {"residual_5d": .2133, "dispersion_5d": .1063,
         "available_peer_count": 5},
        {"attention_rank": .875, "attention_acceleration": 2.3669,
         "attention_source_type_count": 2, "attention_event_count": 9},
        [], leveraged=False, policy=POLICY, market="HK",
    )

    assert candidate["observed"] is True
    assert candidate["state"] == "wait_pullback_rebreak"
    assert candidate["information_modes"] == ["attention_acceleration"]
    assert "needs_primary_evidence" in candidate["blockers"]
    assert early_trend.exploration_setup({}, candidate, POLICY, ticker="00100") is None


def test_primary_event_can_promote_a_cool_nonleveraged_candidate_to_exploration():
    technical = {
        "usable": True, "as_of": "2026-08-13", "close": 10.5,
        "prior_20d_high": 10, "prior_5d_low": 9, "ma20": 9.5,
        "chandelier_stop": 8.8, "zscore20": 1.2,
    }
    candidate = early_trend.classify(
        technical,
        {"residual_5d": .12, "dispersion_5d": .05,
         "available_peer_count": 4},
        {},
        [{"event_id": "sec-1", "source_type": "sec_filing", "direction": 1}],
        leveraged=False, policy=POLICY, market="US",
    )
    setup = early_trend.exploration_setup(
        technical, candidate, POLICY, ticker="ABC"
    )

    assert candidate["state"] == "exploration_ready"
    assert candidate["primary_event_ids"] == ["sec-1"]
    assert setup["setup_id"] == "early_trend_confirmation"
    assert setup["tranche_pct_of_position"] == .025


def test_exploration_tranche_pct_zero_is_not_swallowed_into_default():
    """#666: `exploration_tranche_pct: 0` (0 = 禁用探索档) is legal config;
    `X or DEFAULT` would silently swallow it into 0.025."""
    technical = {
        "usable": True, "as_of": "2026-08-13", "close": 10.5,
        "prior_20d_high": 10, "prior_5d_low": 9, "ma20": 9.5,
        "chandelier_stop": 8.8, "zscore20": 1.2,
    }
    candidate = early_trend.classify(
        technical,
        {"residual_5d": .12, "dispersion_5d": .05,
         "available_peer_count": 4},
        {},
        [{"event_id": "sec-1", "source_type": "sec_filing", "direction": 1}],
        leveraged=False, policy=POLICY, market="US",
    )
    policy = dict(POLICY, exploration_tranche_pct=0)
    setup = early_trend.exploration_setup(
        technical, candidate, policy, ticker="ABC"
    )

    assert setup["tranche_pct_of_position"] == 0.0


def test_primary_source_precedes_syndication_and_accepts_numeric_direction():
    candidate = early_trend.classify(
        {"usable": True, "close": 11, "prior_20d_high": 10, "zscore20": 1},
        {"residual_5d": .2, "dispersion_5d": .05,
         "available_peer_count": 4},
        {},
        [
            {"event_id": "wire", "source_type": "finnhub_syndication",
             "direction": "positive"},
            {"event_id": "filing", "source_type": "issuer_announcement",
             "direction": "1"},
        ],
        leveraged=False, policy=POLICY, market="US",
    )

    assert candidate["primary_event_ids"] == ["filing"]
    assert candidate["information_modes"] == ["primary_positive_event"]
    assert "needs_primary_evidence" not in candidate["blockers"]


def test_leveraged_candidate_never_gets_unvalidated_exploration():
    candidate = early_trend.classify(
        {"usable": True, "close": 11, "prior_20d_high": 10, "zscore20": 1},
        {"residual_5d": .2, "dispersion_5d": .05,
         "available_peer_count": 4},
        {"attention_rank": .9, "attention_acceleration": 2,
         "attention_source_type_count": 2, "attention_event_count": 2},
        [], leveraged=True, policy=POLICY, market="US",
    )
    assert candidate["observed"] is True
    assert candidate["exploration_ready"] is False
    assert "leveraged_requires_validated_evidence" in candidate["blockers"]


def test_peer_dispersion_multiple_zero_is_not_swallowed_into_default():
    """#666: `early_peer_dispersion_multiple: 0` means any positive residual
    counts as peer leadership; `X or DEFAULT` would silently restore 1.5."""
    candidate = early_trend.classify(
        {"usable": True, "close": 11, "prior_20d_high": 10, "zscore20": 1},
        {"residual_5d": .01, "dispersion_5d": .05,
         "available_peer_count": 4},
        {}, [], leveraged=False,
        policy=dict(POLICY, early_peer_dispersion_multiple=0), market="US",
    )

    assert candidate["observed"] is True
    assert "no_short_peer_leadership" not in candidate["blockers"]


def test_missing_dispersion_multiple_still_defaults_to_one_point_five():
    policy = {k: v for k, v in POLICY.items()
              if k != "early_peer_dispersion_multiple"}
    weak = early_trend.classify(
        {"usable": True, "close": 11, "prior_20d_high": 10, "zscore20": 1},
        {"residual_5d": .04, "dispersion_5d": .05,
         "available_peer_count": 4},
        {}, [], leveraged=False, policy=policy, market="US",
    )
    strong = early_trend.classify(
        {"usable": True, "close": 11, "prior_20d_high": 10, "zscore20": 1},
        {"residual_5d": .2, "dispersion_5d": .05,
         "available_peer_count": 4},
        {}, [], leveraged=False, policy=policy, market="US",
    )

    assert weak["observed"] is False, "0.8x residual must stay below the 1.5 default"
    assert strong["observed"] is True, "4x residual clears the 1.5 default"
