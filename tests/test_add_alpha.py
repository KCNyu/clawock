"""Contracts for low-frequency factor × information add authority."""

import copy
import json
from pathlib import Path

from clawock.decision import add_alpha


ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads(
    (ROOT / "config" / "add-alpha-policy.json").read_text(encoding="utf-8")
)


def _factor(**overrides):
    row = {
        "market_percentile": 0.9, "coverage_pct": 95,
        "sector_universe_size": 5, "usable_for_decisions": False,
    }
    row.update(overrides)
    return row


def _peer(**overrides):
    row = {
        "triggered_rules": ["leader_continuation"],
        "available_peer_count": 4, "usable_for_decisions": False,
    }
    row.update(overrides)
    return row


def _information(**overrides):
    row = {
        "signed_score": 0.12, "attention_rank": 0.9,
        "attention_acceleration": 2.0, "attention_source_type_count": 2,
        "attention_event_count": 2,
        "attention_components": [{"event_id": "attention-1"}],
        "event_components": [{
            "event_id": "positive-1", "direction": 1, "novelty": 1,
            "reliability": 0.9, "price_nonreaction": 1,
        }],
        "usable_for_decisions": False,
    }
    row.update(overrides)
    return row


def test_factor_and_peer_are_one_family_not_fake_independent_sources():
    authority = add_alpha.classify_authority(
        _factor(), _peer(),
        _information(
            signed_score=0, attention_rank=0.5,
            attention_acceleration=1, attention_event_count=0,
            attention_components=[], event_components=[],
        ),
        leveraged=False, policy=POLICY, market="US",
    )

    assert authority["sources"] == ["factor", "peer_residual"]
    assert authority["evidence_families"] == ["price_relative"]
    assert authority["tier"] == "none"
    assert "independent_evidence_families" in authority["blockers"]


def test_attention_acceleration_unlocks_one_nonleveraged_exploration_campaign():
    authority = add_alpha.classify_authority(
        _factor(), _peer(), _information(),
        leveraged=False, policy=POLICY, market="US",
    )
    technical = {
        "usable": True, "stop_state": "intact", "as_of": "2026-08-13",
        "close": 10, "prior_5d_high": 10.2, "prior_5d_low": 9,
        "ma20": 9.5, "chandelier_stop": 8.5,
    }
    next_day = copy.deepcopy(technical)
    next_day["as_of"] = "2026-08-14"

    first = add_alpha.confirmation_setup(
        technical, authority, POLICY, ticker="ABC"
    )
    second = add_alpha.confirmation_setup(
        next_day, authority, POLICY, ticker="ABC"
    )

    assert authority["tier"] == "exploration"
    assert authority["evidence_families"] == [
        "price_relative", "point_in_time_information",
    ]
    assert first["campaign_id"] == second["campaign_id"]
    assert first["max_tranches"] == 1
    assert first["target_tranche_level"] == 0.25


def test_validated_campaign_does_not_reset_when_daily_event_ids_change():
    authority = add_alpha.classify_authority(
        _factor(usable_for_decisions=True), _peer(),
        _information(usable_for_decisions=True),
        leveraged=False, policy=POLICY, market="US",
    )
    technical = {
        "usable": True, "stop_state": "intact", "as_of": "2026-08-13",
        "close": 10, "prior_5d_high": 10.2, "prior_5d_low": 9,
        "ma20": 9.5, "chandelier_stop": 8.5,
    }
    first = add_alpha.confirmation_setup(
        technical, authority, POLICY, ticker="ABC"
    )
    authority["information_event_ids"] = ["tomorrows-headline"]
    second = add_alpha.confirmation_setup(
        technical, authority, POLICY, ticker="ABC"
    )

    assert authority["tier"] == "validated"
    assert first["campaign_id"] == second["campaign_id"]


def test_factor_rank_has_enter_exit_hysteresis_for_an_open_campaign():
    factor = _factor(market_percentile=0.6)
    fresh = add_alpha.classify_authority(
        factor, _peer(triggered_rules=[]), _information(), leveraged=False,
        policy=POLICY, market="US",
    )
    continuing = add_alpha.classify_authority(
        factor, _peer(triggered_rules=[]), _information(), leveraged=False,
        policy=POLICY, market="US", continuing=True,
    )

    assert fresh["tier"] == "none"
    assert continuing["tier"] == "exploration"
    assert "market_rank_hysteresis" in continuing["factor_reasons"]


def test_confirmation_primitives_are_gap_aware_and_invalidation_first():
    levels = add_alpha.confirmation_levels({
        "close": 10, "prior_5d_high": 10.2, "prior_5d_low": 9,
        "ma20": 9.5, "chandelier_stop": 8.5,
    })
    assert levels == {"entry_price": 10.2, "invalidation_price": 9.5}
    assert add_alpha.confirmation_bar_outcome(
        {"open": 10.8, "high": 11, "low": 10.4}, **levels
    ) == {"state": "filled", "price": 10.8, "reason": "gap_through"}
    assert add_alpha.confirmation_bar_outcome(
        {"open": 10, "high": 10.5, "low": 9.4}, **levels
    )["state"] == "invalidated"


def test_leveraged_exploration_is_forbidden_but_validated_is_distinct():
    exploratory = add_alpha.classify_authority(
        _factor(), _peer(), _information(),
        leveraged=True, policy=POLICY, market="US",
    )
    validated = add_alpha.classify_authority(
        _factor(usable_for_decisions=True), _peer(),
        _information(usable_for_decisions=True),
        leveraged=True, policy=POLICY, market="US",
    )

    assert exploratory["tier"] == "none"
    assert "leveraged_requires_validated_evidence" in exploratory["blockers"]
    assert validated["tier"] == "validated"


def test_tiny_negative_news_noise_does_not_veto_but_material_negative_does():
    tiny = add_alpha.classify_authority(
        _factor(), _peer(), _information(signed_score=-0.001),
        leveraged=False, policy=POLICY, market="US",
    )
    material = add_alpha.classify_authority(
        _factor(), _peer(), _information(signed_score=-0.2),
        leveraged=False, policy=POLICY, market="US",
    )

    assert tiny["tier"] == "exploration"
    assert "negative_information" not in tiny["blockers"]
    assert material["tier"] == "none"
    assert "negative_information" in material["blockers"]
