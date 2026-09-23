# Project documentation

The repository root is reserved for files with a real discovery or runtime
contract: GitHub/Python metadata, OpenClaw bootstrap context, and the live
workspace ledgers. Static website source lives in `site/`; Pages combines it with
public runtime outputs through `ops/pages/stage_site.py`. General documentation
belongs here.

## Architecture

- [`harness.md`](architecture/harness.md) — package/profile/runtime boundaries,
  CLI lifecycle, context injection contract, and generation-pinned artifacts.
- [`data-plane.md`](architecture/data-plane.md) — why the live JSON snapshot is
  separate from Pages, what GitHub officially supports, and the replacement bar.
- [`openclaw-adapter.md`](architecture/openclaw-adapter.md) — OpenClaw as an
  external runtime and the parity contract the adapter must keep.
- [`runtime-protocol.md`](architecture/runtime-protocol.md) — how any external
  agent runtime invokes clawock.

## Product surfaces

- [`decision-map.md`](decision-map.md) — the Decision Map board in Reflect: how
  to read coverage and snapshot age, the payload, and where it runs.
- [`decision-mind-ledger.md`](decision-mind-ledger.md) — the decision-mind
  ledger schema written by `clawock record`.
- [`glossary.md`](glossary.md) — source of truth for cross-document terminology.

## Operations

- [`release.md`](operations/release.md) — publishing to PyPI/npm, and running the
  latest code on the host without a release.
- [`cron-schedules.md`](operations/cron-schedules.md) — generated human view of
  the tracked cron contract.
- [`research-cadence.md`](operations/research-cadence.md) — which research
  question runs daily, which runs on an event, and why.
- [`skills-store-policy.md`](operations/skills-store-policy.md) — registry
  discovery and installation policy.

## Reference

- [`commands.md`](reference/commands.md) — the generated command inventory plus
  the hand-written harness detail (`scripts.md` is a moved-page stub pointing here).
- [`tool-operations.md`](reference/tool-operations.md) — per-task tool detail;
  routing lives in the root `TOOLS.md`.
- [`product-profile-operations.md`](reference/product-profile-operations.md) —
  what belongs to the product, profiles, operations and runtime state.

## Legal

- [`third-party-data.md`](legal/third-party-data.md) — data-provider terms,
  attribution, and redistribution boundaries.

Everything under `docs/` is published with the Pages build
(`ops/pages/stage_site.py`). Keep this index current when adding or removing docs.

## Why OpenClaw files stay at the root

`AGENTS.md`, `TOOLS.md`, `SOUL.md`, `IDENTITY.md`, `USER.md`, `MEMORY.md`,
`HEARTBEAT.md`, `BOOTSTRAP.md`, `skills/` and `memory/` participate in the live
OpenClaw workspace contract. They remain at their required runtime paths until
an adjacent context-parity canary proves a supported alternative. Website files
have no such constraint and therefore live under `site/`.
