"""Capability providers: OpenClaw and GitHub as peers, not as the substrate.

Two capabilities bind this repository to OpenClaw today, and neither is the LLM
step everyone reaches for first:

* **delivery** — `_watchdog_common.send_wechat/send_telegram` shell out to
  `openclaw message send`, and all three postflights deliver through them;
* **run history** — `_cron_cli_json` reads `openclaw cron …`, and the watchdogs,
  `cron_health_check`, `cron_timeline` and `system_check` all depend on it.

Remove OpenClaw and reports stop being delivered and every watchdog goes blind,
before anything about prose generation matters.

Both are already narrow, JSON-returning subprocess calls, and run history
already has two independent implementations — `_watchdog_common.read_runs`
(OpenClaw, with a cli → sqlite → fossil fallback chain) and
`workflow_health.fetch_runs` (GitHub Actions, via `gh run list --json`). They
simply had no common shape. This package is mostly collecting implementations
that exist, not inventing abstractions.
"""
from __future__ import annotations

from clawock.providers.delivery import (  # noqa: F401
    DeliveryProvider,
    DeliveryResult,
    NullDelivery,
    OpenClawDelivery,
)
from clawock.providers.runs import (  # noqa: F401
    GitHubRuns,
    OpenClawRuns,
    Run,
    RunHistoryProvider,
)

__all__ = [
    "DeliveryProvider", "DeliveryResult", "NullDelivery", "OpenClawDelivery",
    "GitHubRuns", "OpenClawRuns", "Run", "RunHistoryProvider",
]
