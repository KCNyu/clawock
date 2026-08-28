"""Runtime-neutral vocabulary shared by decision workflow components."""

ACTIVE_ACTIONS = {
    "cut", "trim_on_rebound", "t_only", "add_only_on_trigger", "add_on_breakout",
}
SELL_ACTIONS = {"cut", "trim_on_rebound", "t_only"}
ADD_ACTIONS = ACTIVE_ACTIONS - SELL_ACTIONS
PASSIVE_ACTIONS = {"hold_and_watch", "watch"}

# The Judge's strategy frames (skills/daily-deep-brief/SKILL.md § Strategy frame
# menu). The brief already requires the Judge to name one to three of these per
# action, in a markdown table nothing can read back. Naming them here lets a
# decision carry the frame it was decided under as data (#1117).
STRATEGY_FRAMES = {
    "momentum", "mean_reversion", "breakout", "relative_strength",
    "earnings_setup", "sentiment_shift", "technical_breakdown",
    "sector_rotation",
}
