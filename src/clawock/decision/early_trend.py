"""Short-history early-trend candidates, separate from mature add authority.

The lane is intentionally an observation before it is an order.  It catches a
20-session breakout that is also exceptional relative to listed peers, even
when a newly listed name has no MA200.  Price and peer residual are one
price-relative family; information remains independent.  Only a non-leveraged,
non-overheated name with both families receives a tiny exploration setup.
"""
from __future__ import annotations
from clawock.safe_io import to_number as _number


PRIMARY_SOURCE_TYPES = {
    "sec_filing", "exchange_announcement", "issuer_announcement",
    "official_macro_schedule",
}
POSITIVE_DIRECTIONS = {1, "1", "positive"}




def classify(technical: dict, peer: dict, information: dict, events: list[dict],
             *, leveraged: bool, policy: dict, market: str) -> dict:
    """Return a visible candidate state without pretending it is validated."""
    close = _number(technical.get("close"))
    prior_high = _number(technical.get("prior_20d_high"))
    residual = _number(peer.get("residual_5d"))
    dispersion = _number(peer.get("dispersion_5d"))
    peers = int(peer.get("available_peer_count") or 0)
    market_policy = (policy.get("markets") or {}).get(str(market).upper()) or {}
    # #666: explicit None check — `early_peer_dispersion_multiple: 0` is legal
    # config (any positive residual counts as leadership) and must not be
    # swallowed into the default, same discipline as the keys below.
    raw_multiple = policy.get("early_peer_dispersion_multiple")
    multiple = float(raw_multiple) if raw_multiple is not None else 1.5
    # #666: explicit None checks, never `X or DEFAULT` — a config value of 0
    # (e.g. `minimum_peer_count: 0` = 不设同行样本下限) is legal and must not
    # be swallowed into the default.
    raw_min_peers = market_policy.get("minimum_peer_count")
    min_peers = int(raw_min_peers) if raw_min_peers is not None else 3
    raw_min_attention_rank = market_policy.get("minimum_attention_rank")
    min_attention_rank = (
        float(raw_min_attention_rank) if raw_min_attention_rank is not None
        else 1.0
    )
    raw_min_acceleration = policy.get("minimum_attention_acceleration")
    min_acceleration = (
        float(raw_min_acceleration) if raw_min_acceleration is not None else 1.0
    )
    raw_min_source_types = policy.get("minimum_attention_source_types")
    min_source_types = (
        int(raw_min_source_types) if raw_min_source_types is not None else 1
    )
    breakout = close is not None and prior_high is not None and close > prior_high
    residual_multiple = (
        residual / dispersion
        if residual is not None and dispersion not in (None, 0) else None
    )
    residual_leader = bool(
        residual is not None and residual > 0
        and residual_multiple is not None and residual_multiple >= multiple
        and peers >= min_peers
    )
    price_candidate = bool(technical.get("usable") and breakout and residual_leader)

    primary_ids = sorted({
        str(event.get("event_id")) for event in events
        if event.get("event_id")
        and event.get("source_type") in PRIMARY_SOURCE_TYPES
        and event.get("direction") in POSITIVE_DIRECTIONS
    })
    attention_rank = _number(information.get("attention_rank"))
    acceleration = _number(information.get("attention_acceleration"))
    source_types = int(information.get("attention_source_type_count") or 0)
    attention_ok = bool(
        attention_rank is not None
        and attention_rank >= min_attention_rank
        and acceleration is not None
        and acceleration >= min_acceleration
        and source_types >= min_source_types
        and int(information.get("attention_event_count") or 0) > 0
    )
    information_modes = []
    if primary_ids:
        information_modes.append("primary_positive_event")
    if attention_ok:
        information_modes.append("attention_acceleration")
    information_ok = bool(information_modes)
    zscore = _number(technical.get("zscore20"))
    # #649: explicit None check, never `X or DEFAULT` — a config value of 0
    # (z≥0 永不追高,最保守) must not be swallowed into the 2.0 default.
    raw_no_chase = policy.get("early_no_chase_zscore")
    overheated = zscore is not None and zscore >= float(
        raw_no_chase if raw_no_chase is not None else 2.0
    )

    blockers = []
    if not breakout:
        blockers.append("no_20d_breakout")
    if not residual_leader:
        blockers.append("no_short_peer_leadership")
    if not information_ok:
        blockers.append("needs_information_confirmation")
    if not primary_ids:
        blockers.append("needs_primary_evidence")
    if overheated:
        blockers.append("overheated_wait_rebreak")
    if leveraged:
        blockers.append("leveraged_requires_validated_evidence")

    if not price_candidate:
        state = "not_candidate"
    elif overheated:
        state = "wait_pullback_rebreak"
    elif not information_ok:
        state = "wait_information"
    elif leveraged:
        state = "candidate_only"
    else:
        state = "exploration_ready"
    return {
        "schema_version": 1,
        "state": state,
        "observed": price_candidate,
        "exploration_ready": state == "exploration_ready",
        "market": str(market).upper(),
        "price_modes": [
            name for name, passed in (
                ("20d_breakout", breakout),
                ("short_peer_residual", residual_leader),
            ) if passed
        ],
        "information_modes": information_modes,
        "evidence_families": [
            name for name, passed in (
                ("price_relative", price_candidate),
                ("point_in_time_information", information_ok),
            ) if passed
        ],
        "primary_event_ids": primary_ids,
        "metrics": {
            "close": close,
            "prior_20d_high": prior_high,
            "residual_5d": residual,
            "peer_dispersion_5d": dispersion,
            "residual_dispersion_multiple": (
                round(residual_multiple, 4) if residual_multiple is not None else None
            ),
            "attention_rank": attention_rank,
            "attention_acceleration": acceleration,
            "zscore20": zscore,
        },
        "blockers": sorted(set(blockers)),
        "discipline": (
            "short-history candidate; price/peer are one family, primary or "
            "attention information is independent, and z>=2 waits for a rebreak"
        ),
    }


def exploration_setup(technical: dict, candidate: dict, policy: dict,
                      *, ticker: str) -> dict | None:
    """Create one future-session rebreak intent, never a market-chase order."""
    if not candidate.get("exploration_ready"):
        return None
    close = _number(technical.get("close"))
    prior_high = _number(technical.get("prior_20d_high"))
    invalidation = max(
        value for value in (
            _number(technical.get("ma20")),
            _number(technical.get("chandelier_stop")),
            _number(technical.get("prior_5d_low")),
        ) if value is not None and value > 0
    )
    entry = max(close or 0, prior_high or 0)
    if not entry or invalidation >= entry:
        return None
    # #666: explicit None checks, never `X or DEFAULT` — a config value of 0
    # (e.g. `exploration_tranche_pct: 0` = 禁用探索档) is legal and must not
    # be swallowed into the default.
    raw_tranche_pct = policy.get("exploration_tranche_pct")
    raw_confirmation_sessions = policy.get("confirmation_window_sessions")
    return {
        "setup_id": "early_trend_confirmation",
        "campaign_id": f"{candidate['market']}:{ticker}:early:p1",
        "label": "早期趋势确认",
        "entry_type": "price_above",
        "entry_price": round(entry, 4),
        "invalidation_price": round(invalidation, 4),
        "max_tranches": 1,
        "tranche_pct_of_position": (
            float(raw_tranche_pct) if raw_tranche_pct is not None else 0.025
        ),
        "valid_for_sessions": (
            int(raw_confirmation_sessions)
            if raw_confirmation_sessions is not None else 5
        ),
        "signal_date": technical.get("as_of"),
        "authority_tier": "exploration",
        "target_tranche_level": 0.25,
        "authority_sources": ["early_trend", "information"],
        "evidence_families": ["price_relative", "point_in_time_information"],
        "detail": "次新/短历史早期趋势候选；未来时段再突破才执行，跌破失效位取消",
    }
