"""Runtime-neutral vocabulary shared by decision workflow components."""

from clawock.safe_io import to_strict_finite_number

ACTIVE_ACTIONS = {
    "cut", "trim_on_rebound", "t_only", "add_only_on_trigger", "add_on_breakout",
}
SELL_ACTIONS = {"cut", "trim_on_rebound", "t_only"}
ADD_ACTIONS = ACTIVE_ACTIONS - SELL_ACTIONS
PASSIVE_ACTIONS = {"hold_and_watch", "watch"}

SWAP_SELL_ACTIONS = ("cut", "trim_on_rebound")


def positive_whole_shares(value):
    """Authored order size, before normalization can truncate or coerce it."""
    shares = to_strict_finite_number(value)
    if shares is None or shares <= 0 or int(shares) != shares:
        return None
    return int(shares)


def is_risk_swap_buy(decision):
    """A risk-rule buy's shape, not permission to buy (the packet owns that)."""
    return (decision.get("action") == "add_only_on_trigger"
            and decision.get("strategy_id") == "risk_rebalance"
            and decision.get("driven_by") == "risk_rule"
            and not decision.get("technical_setup_id"))


def paired_swap_sells(decision, decisions, *, sources=None):
    """Sized sell legs in the same group; optionally restrict the sources."""
    group = decision.get("decision_group_id")
    paired = []
    for other in decisions:
        if (not group or other is decision
                or other.get("ticker") == decision.get("ticker")
                or (sources is not None and str(other.get("ticker") or "") not in sources)
                or other.get("action") not in SWAP_SELL_ACTIONS
                or other.get("decision_group_id") != group):
            continue
        shares = to_strict_finite_number((other.get("size") or {}).get("shares"))
        if shares is not None and shares > 0 and int(shares) == shares:
            paired.append(other)
    return paired

# The Judge's strategy frames (skills/daily-deep-brief/SKILL.md § Strategy frame
# menu). The brief already requires the Judge to name one to three of these per
# action, in a markdown table nothing can read back. Naming them here lets a
# decision carry the frame it was decided under as data (#1117).
STRATEGY_FRAMES = {
    "momentum", "mean_reversion", "breakout", "relative_strength",
    "earnings_setup", "sentiment_shift", "technical_breakdown",
    "sector_rotation",
}
