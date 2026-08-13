"""Low-frequency add campaigns from price-relative and information features.

The implementation borrows Qlib's useful boundary — signal selection, target
position and order timing are separate — without importing its China-centric
backtester.  It is intentionally not an HFT strategy:

* ranks are produced once per completed HK or US session;
* factor and peer residuals share one price-relative evidence family;
* point-in-time news attention/surprise is a separate family;
* a small exploration campaign may collect one prospective fill while a
  pre-registered interaction warms up;
* technical prices only schedule that authorised tranche.
"""
from __future__ import annotations

import hashlib
import json


POLICY_VERSION = 2


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def confirmation_levels(technical: dict) -> dict | None:
    """Return the production entry/invalidation pair for an alpha campaign.

    This is deliberately a public pure function: the live packet, replay and
    ledger must not each invent a slightly different five-day confirmation.
    The caller supplies only values known at the signal-session close.
    """
    close = _number(technical.get("close"))
    prior_high = _number(technical.get("prior_5d_high"))
    prior_low = _number(technical.get("prior_5d_low"))
    chandelier = _number(technical.get("chandelier_stop"))
    ma20 = _number(technical.get("ma20"))
    if close is None or prior_high is None:
        return None
    entry = max(close, prior_high)
    invalidation_candidates = [
        value for value in (prior_low, chandelier, ma20)
        if value is not None and 0 < value < entry
    ]
    if not invalidation_candidates:
        return None
    return {
        "entry_price": round(entry, 4),
        "invalidation_price": round(max(invalidation_candidates), 4),
    }


def confirmation_bar_outcome(
    bar: dict, *, entry_price: float, invalidation_price: float
) -> dict:
    """Evaluate one future OHLC bar, with risk-line ambiguity fail-closed."""
    low = _number(bar.get("low"))
    high = _number(bar.get("high"))
    open_ = _number(bar.get("open"))
    if low is None or high is None or open_ is None:
        return {"state": "not_evaluable", "reason": "ohlc_missing"}
    if low <= invalidation_price:
        return {"state": "invalidated", "reason": "invalidation_traded"}
    if high < entry_price:
        return {"state": "waiting", "reason": "entry_not_traded"}
    return {
        "state": "filled",
        "price": max(open_, entry_price),
        "reason": "gap_through" if open_ >= entry_price else "intraday_cross",
    }


def _market_policy(policy: dict, market: str) -> dict:
    markets = policy.get("markets") or {}
    return markets.get(str(market).upper()) or {}


def _factor_support(
    factor: dict, market_policy: dict, *, continuing: bool = False
) -> tuple[bool, list[str]]:
    rank = _number(factor.get("market_percentile"))
    coverage = _number(factor.get("coverage_pct"))
    sector_size = int(factor.get("sector_universe_size") or 0)
    reasons = []
    threshold = market_policy[
        "exit_market_percentile" if continuing else "enter_market_percentile"
    ]
    if rank is not None and rank >= threshold:
        reasons.append(
            "market_rank_hysteresis" if continuing else "market_top_rank"
        )
    if coverage is not None and coverage >= market_policy["minimum_factor_coverage_pct"]:
        reasons.append("factor_coverage_sufficient")
    if sector_size >= market_policy["minimum_sector_universe_size"]:
        reasons.append("industry_comparison_sufficient")
    return len(reasons) == 3, reasons


def _peer_support(peer: dict, market_policy: dict) -> tuple[bool, list[str], list[str]]:
    triggered = set(peer.get("triggered_rules") or peer.get("usable_rules") or [])
    negatives = sorted(triggered & {"laggard_avoidance"})
    positives = sorted(triggered & {"leader_continuation", "mean_reversion"})
    peer_count = int(peer.get("available_peer_count") or 0)
    return (
        bool(positives)
        and not negatives
        and peer_count >= market_policy["minimum_peer_count"],
        positives,
        negatives,
    )


def _information_support(
    info: dict, policy: dict, market_policy: dict
) -> tuple[bool, list[str], list[str]]:
    signed = _number(info.get("signed_score"))
    attention_rank = _number(info.get("attention_rank"))
    attention_acceleration = _number(info.get("attention_acceleration"))
    attention_source_types = int(info.get("attention_source_type_count") or 0)
    components = info.get("event_components") or []
    positive_events = [
        str(row.get("event_id"))
        for row in components
        if _number(row.get("direction")) == 1
        and (_number(row.get("novelty")) or 0) >= policy["minimum_event_novelty"]
        and (_number(row.get("reliability")) or 0) >= policy["minimum_event_reliability"]
        and (_number(row.get("price_nonreaction")) or 0) >= policy["minimum_price_nonreaction"]
        and row.get("event_id")
    ]
    modes = []
    if signed is not None and signed >= policy["minimum_information_score"] and positive_events:
        modes.append("positive_surprise")
    # Attention is deliberately unsigned. It only becomes informative when
    # price-relative evidence independently says this is a leader, never alone.
    attention_events = [
        str(row.get("event_id"))
        for row in (info.get("attention_components") or [])
        if row.get("event_id")
    ]
    if (
        attention_rank is not None
        and attention_rank >= market_policy["minimum_attention_rank"]
        and attention_acceleration is not None
        and attention_acceleration >= policy["minimum_attention_acceleration"]
        and attention_source_types >= policy["minimum_attention_source_types"]
        and int(info.get("attention_event_count") or 0) > 0
    ):
        modes.append("attention_acceleration")
    return bool(modes), modes, sorted(set(positive_events + attention_events))


def classify_authority(
    factor: dict,
    peer: dict,
    information: dict,
    *,
    leveraged: bool,
    policy: dict,
    market: str,
    continuing: bool = False,
) -> dict:
    """Return a stateful-campaign eligibility tier and auditable blockers."""
    market_policy = _market_policy(policy, market)
    factor_ok, factor_reasons = _factor_support(
        factor, market_policy, continuing=continuing
    )
    peer_ok, peer_reasons, peer_negatives = _peer_support(peer, market_policy)
    info_ok, info_modes, event_ids = _information_support(
        information, policy, market_policy
    )

    price_relative_ok = factor_ok or peer_ok
    families = [
        name for name, passed in (
            ("price_relative", price_relative_ok),
            ("point_in_time_information", info_ok),
        ) if passed
    ]
    sources = [
        name for name, passed in (
            ("factor", factor_ok),
            ("peer_residual", peer_ok),
            ("information", info_ok),
        ) if passed
    ]
    blockers = []
    signed = _number(information.get("signed_score"))
    if peer_negatives:
        blockers.append("peer_laggard_avoidance")
    if (
        signed is not None
        and signed <= -float(policy["minimum_information_score"])
    ):
        blockers.append("negative_information")
    if len(families) < policy["minimum_evidence_families"]:
        blockers.append("independent_evidence_families")
    validated_price = bool(
        (factor_ok and factor.get("usable_for_decisions"))
        or (peer_ok and peer.get("usable_for_decisions"))
    )
    validated_info = bool(info_ok and information.get("usable_for_decisions"))
    validated = validated_price and validated_info
    if leveraged and not validated:
        blockers.append("leveraged_requires_validated_evidence")
    if not blockers and validated:
        tier = "validated"
    elif not blockers and policy.get("exploration_enabled"):
        tier = "exploration"
    else:
        tier = "none"
    return {
        "schema_version": 2,
        "policy_version": POLICY_VERSION,
        "tier": tier,
        "market": str(market).upper(),
        "continuing_campaign": bool(continuing),
        "sources": sources,
        "evidence_families": families,
        "factor_reasons": factor_reasons,
        "peer_rules": peer_reasons,
        "information_modes": info_modes,
        "information_event_ids": event_ids,
        "blockers": sorted(set(blockers)),
        "discipline": (
            "one price-relative family plus point-in-time information authorise "
            "capital; technical confirmation only schedules the tranche"
        ),
    }


def confirmation_setup(
    technical: dict,
    authority: dict,
    policy: dict,
    *,
    ticker: str,
) -> dict | None:
    """Build a multi-session, gap-aware execution intent for one campaign."""
    if authority.get("tier") not in {"exploration", "validated"}:
        return None
    if not technical.get("usable") or technical.get("stop_state") != "intact":
        return None
    signal_date = str(technical.get("as_of") or "")[:10]
    if not signal_date:
        return None
    levels = confirmation_levels(technical)
    if levels is None:
        return None
    tier = authority["tier"]
    policy_hash = hashlib.sha256(
        json.dumps(policy, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:8]
    market = authority["market"]
    if tier == "exploration":
        # Exploration buys evidence; it is not a recurring trading rule. One
        # fill per ticker/policy version prevents a fresh daily snapshot from
        # silently resetting the cap and pyramiding an unvalidated idea.
        campaign_id = f"{market}:{ticker}:explore:p{POLICY_VERSION}:{policy_hash}"
    else:
        # Daily headlines and attention events churn. They are provenance for
        # the decision, not campaign identity: including their IDs silently
        # resets the tranche cap every morning. A new campaign requires an
        # explicit policy version, not a new syndication headline.
        campaign_id = f"{market}:{ticker}:validated:p{POLICY_VERSION}:{policy_hash}"
    return {
        "setup_id": "alpha_confirmation",
        "campaign_id": campaign_id,
        "label": "低频交互加仓确认",
        "entry_type": "price_above",
        "entry_price": levels["entry_price"],
        "invalidation_price": levels["invalidation_price"],
        "max_tranches": (
            policy["validated_max_tranches"]
            if tier == "validated" else policy["exploration_max_tranches"]
        ),
        "tranche_pct_of_position": (
            policy["validated_tranche_pct"]
            if tier == "validated" else policy["exploration_tranche_pct"]
        ),
        "authority_tier": tier,
        "target_tranche_level": 0.25 if tier == "exploration" else 1.0,
        "authority_sources": list(authority.get("sources") or []),
        "evidence_families": list(authority.get("evidence_families") or []),
        "signal_date": signal_date,
        "valid_for_sessions": int(policy["confirmation_window_sessions"]),
        "detail": (
            "relative-price plus point-in-time information selected the name; "
            "the next 1–5 local sessions use a gap-aware price confirmation"
        ),
    }
