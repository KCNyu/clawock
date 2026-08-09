# Repository ownership: product, instance, operations and state

The terminal shape is a portable `clawock` product plus a separately installed
KCNyu live instance. Directory ownership is part of the product contract: no
generic script or data bucket is an acceptable final home.

## The deciding question

Ask whether a third party using clawock with their own agent, book and deployment
needs the behavior unchanged.

- **Yes: product.** Put it in a named domain under `src/clawock/` and expose it
  through the installed `clawock` CLI or an importable package API.
- **No, it is this investment desk's behavior: instance.** Put it in the
  separately packaged `instances/kcnyu/src/clawock_kcnyu/` adapter.
- **No, it wires a host, repository or delivery surface: operations.** Put it in
  the specific `ops/` domain that owns that external side effect.
- **It is generated or user-authored state:** keep it in the workspace data
  paths; never ship it in either wheel.

File size, language and test coverage do not decide ownership. Stable commands
are APIs; historical Python or shell paths are not.

## Canonical owners

| Path | Owner |
|---|---|
| `src/clawock/decision/` | decision records, risk governance, theses, entry/earnings lifecycle, signals and outcome evaluation |
| `src/clawock/portfolio/` | ledger math, reconciliation, FX, risk, integrity and shadow accounting |
| `src/clawock/market_data/` | portable providers, canonical bars, sessions, quotes, filings and market context |
| `src/clawock/evidence/` | provenance, run cards, research surface and public evidence generation |
| `src/clawock/context/`, `harness/`, `publish/`, `workflows/`, `adapters/` | runtime-neutral contracts, artifact protocol and cross-runtime integration |
| `instances/kcnyu/` | KCNyu schedule contract, harness phases, workflow outcomes, heartbeat and watchdog behavior |
| `ops/host/` | this host's cron, scheduler inspection, session maintenance and launcher wiring |
| `ops/publish/` | the only protected-branch and data-plane publisher implementation |
| `ops/ci/` | coverage and scheduled-workflow health used by GitHub Actions |
| `ops/growth/` | IndexNow, Nostr and project broadcast delivery |
| `ops/pages/` | Pages source/artifact assembly from the published generation |
| `site/` | static site and browser source |
| `portfolio.json`, `assets/data/`, `memory/`, `logs/` | live instance and generated state; never wheel contents |

`ops/` may call installed product and instance commands. Product code must not
import `ops/` or `clawock_kcnyu`. The public `clawock` wheel must not include or
depend on the KCNyu wheel. `clawock-kcnyu` is repository-only and must never be
published to PyPI.

## OpenClaw compatibility surface

OpenClaw requires selected Markdown and skill files at workspace-relative paths,
so root `AGENTS.md`, `TOOLS.md`, `SOUL.md`, `IDENTITY.md`, `USER.md` and the
main-session context files remain at the repository root. Location compatibility
does not make old scripts APIs: those files instruct the runtime to use installed
`clawock` / `clawock-kcnyu` commands and the named `ops/` entry points only.

## Remaining `scripts/data/` inventory

This directory is a temporary migration surface, not an owner. Its remaining
files already have terminal destinations:

- dashboard aggregation and portable backtest/evaluation logic → named product
  domains under `src/clawock/`;
- KCNyu gold, influencer, intraday gate and GitHub-hosted LLM automation → named
  modules under `clawock_kcnyu`;
- files with no consumer or completed one-off jobs → delete.

Do not add new files there, create `ops/data`, or preserve old-path shims. A move
is complete only after runtime commands, workflows, cron, docs and isolated-wheel
verification all use the terminal owner.

## Publication boundary

The KCNyu harness may request a dashboard rebuild and publication, but the git
identity, retry and data-plane mechanisms belong only to `ops/publish/`. The
browser consumes the complete published generation; generated outputs are state,
not source-package data and not independently staged by arbitrary callers.
