"""Network/build ceilings shared by cron contracts and their postflights.

The inner retry ladders stay intact. A whole agent turn must reserve this
post-delivery chain plus time to collect data, judge and deliver the product.
"""
GIT_CALL_TIMEOUT_SECONDS = 120
PUSH_ATTEMPTS = 3
PUSH_RETRY_BACKOFF_STEP_SECONDS = 3
DEPLOY_REQUEST_TIMEOUT_SECONDS = 120
PUBLISH_NETWORK_CALLS = 2 + PUSH_ATTEMPTS
PUBLISH_BUDGET_SECONDS = (
    PUBLISH_NETWORK_CALLS * GIT_CALL_TIMEOUT_SECONDS
    + sum(attempt * PUSH_RETRY_BACKOFF_STEP_SECONDS for attempt in range(1, PUSH_ATTEMPTS))
    + DEPLOY_REQUEST_TIMEOUT_SECONDS
)
DASHBOARD_FETCH_TIMEOUT_SECONDS = 60
DASHBOARD_LOCK_WAIT_SECONDS = 90
DASHBOARD_BUILD_TIMEOUT_SECONDS = 30
# 300 recorded builds (logs/dashboard_build_status.json history to 2026-10-05):
# median 3.2s, p95 15.3s, max 39.4s. The step is a read-only view that never
# gates the publish, so its ceiling is sized to that, not to the 180s it had.
DECISION_MAP_TIMEOUT_SECONDS = 90
SAFE_PUSH_ATTEMPTS = 3
PREPUSH_ATTEMPT_SECONDS = 90
PUSH_RETRY_BACKOFF_SECONDS = 9
PUSH_TIMEOUT_SECONDS = SAFE_PUSH_ATTEMPTS * PREPUSH_ATTEMPT_SECONDS + PUSH_RETRY_BACKOFF_SECONDS
# Local git steps of a postflight: `git add` and `git commit`, each through
# `_harness_common.git_cmd`.
GIT_STEP_TIMEOUT_SECONDS = 30
GIT_STEPS_PER_POSTFLIGHT = 2
# `sync_gha_data_files`: one fetch, one batch restore, and — when the batch
# fails — a per-file fallback that shares ONE deadline instead of 10s a file.
GHA_SYNC_FETCH_TIMEOUT_SECONDS = 15
GHA_SYNC_RESTORE_TIMEOUT_SECONDS = 10
GHA_SYNC_TIMEOUT_SECONDS = GHA_SYNC_FETCH_TIMEOUT_SECONDS + 2 * GHA_SYNC_RESTORE_TIMEOUT_SECONDS
#: Every step of the chain that carries its own ceiling, by name. The total is
#: derived from this one list, so a step added to the chain is added here or the
#: equation in the tests no longer matches (#2565: three steps were missing and
#: the contract gate compared the budget with itself). `workflow_outcomes.publish()`
#: runs in-process between them without a timeout of its own; it is a local
#: SQLite write (max 3.0s over the same 300 builds) inside the reserve below.
POST_DELIVERY_STEPS = {
    'gha_data_sync': GHA_SYNC_TIMEOUT_SECONDS,
    'dashboard_fetch': DASHBOARD_FETCH_TIMEOUT_SECONDS,
    'dashboard_lock_wait': DASHBOARD_LOCK_WAIT_SECONDS,
    'dashboard_build': DASHBOARD_BUILD_TIMEOUT_SECONDS,
    'decision_map': DECISION_MAP_TIMEOUT_SECONDS,
    'publish_generation': PUBLISH_BUDGET_SECONDS,
    'git_add_commit': GIT_STEPS_PER_POSTFLIGHT * GIT_STEP_TIMEOUT_SECONDS,
    'push': PUSH_TIMEOUT_SECONDS,
}
POST_DELIVERY_BUDGET_SECONDS = sum(POST_DELIVERY_STEPS.values())
PRE_DELIVERY_RESERVE_SECONDS = 300
