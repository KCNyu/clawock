# Project documentation

The repository root is reserved for files with a real discovery or runtime
contract: GitHub/Python metadata, OpenClaw bootstrap context, and the live
workspace ledgers. Static website source lives in `site/`; Pages combines it with
public runtime outputs through `ops/pages/stage_site.py`. General documentation
belongs here.

## Architecture

- [`data-plane.md`](architecture/data-plane.md) — why the live JSON snapshot is
  separate from Pages, what GitHub officially supports, and the replacement bar.
- [`harness.md`](architecture/harness.md) — package/profile/runtime boundaries,
  CLI lifecycle, context injection contract, and generation-pinned artifacts.

## Operations

- [`cron-schedules.md`](operations/cron-schedules.md) — generated human view of
  the tracked cron contract.
- [`price-alerts.md`](operations/price-alerts.md) — current alert path and the
  retired polling design.
- [`skills-store-policy.md`](operations/skills-store-policy.md) — registry
  discovery and installation policy.
- [`research-cadence.md`](operations/research-cadence.md) — which research
  question runs daily, which runs on an event, and why.

## Reference

- [`commands.md`](reference/commands.md) — the generated command inventory plus the hand-written harness detail.

## Legal

- [`third-party-data.md`](legal/third-party-data.md) — data-provider terms,
  attribution, and redistribution boundaries.

## Archive

Historical designs live under `archive/`. They are retained for context, are
excluded from the public Pages build, and must not be used as current runbooks.

## Why OpenClaw files stay at the root

`AGENTS.md`, `TOOLS.md`, `SOUL.md`, `IDENTITY.md`, `USER.md`, `MEMORY.md`,
`HEARTBEAT.md`, `BOOTSTRAP.md`, `skills/` and `memory/` participate in the live
OpenClaw workspace contract. They remain at their required runtime paths until
an adjacent context-parity canary proves a supported alternative. Website files
have no such constraint and therefore live under `site/`.
