"""Runtime-neutral vocabulary shared by decision workflow components."""

ACTIVE_ACTIONS = {
    "cut", "trim_on_rebound", "t_only", "add_only_on_trigger", "add_on_breakout",
}
SELL_ACTIONS = {"cut", "trim_on_rebound", "t_only"}
ADD_ACTIONS = ACTIVE_ACTIONS - SELL_ACTIONS
PASSIVE_ACTIONS = {"hold_and_watch", "watch"}
