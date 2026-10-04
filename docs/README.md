# Project documentation

The repository root is reserved for files with a real discovery or runtime
contract: GitHub/Python metadata, OpenClaw bootstrap context, and the live
workspace ledgers. Static website source lives in `site/`; Pages combines it with
public runtime outputs through `ops/pages/stage_site.py`. General documentation
belongs here.

## Architecture

- [`harness.md`](architecture/harness.md) — package/profile/runtime boundaries,
  CLI lifecycle, context injection contract, and generation-pinned artifacts.
- [`intraday-agent.md`](architecture/intraday-agent.md) — the intraday agent
  contract: context layering, card blocks, workflow ownership, objective and
  which rules are gates.
- [`data-plane.md`](architecture/data-plane.md) — why the live JSON snapshot is
  separate from Pages, what GitHub officially supports, and the replacement bar.
- [`openclaw-adapter.md`](architecture/openclaw-adapter.md) — OpenClaw as an
  external runtime and the parity contract the adapter must keep.
- [`runtime-protocol.md`](architecture/runtime-protocol.md) — how any external
  agent runtime invokes clawock.
- [`task-queue.md`](architecture/task-queue.md) — the agent-dispatch queue behind
  the dsh task chip: who owns which layer, the versioned ops entry, queue order.

## Product surfaces

- [`decision-map.md`](decision-map.md) — the Decision Map board in Reflect: how
  to read coverage and snapshot age, the payload, and where it runs.
- [`decision-mind-ledger.md`](decision-mind-ledger.md) — the decision-mind
  ledger schema written by `clawock record`.
- [`influencer-radar.md`](influencer-radar.md) — the eight watched sources, how
  hits are linked to holdings, and a worked hit/miss example (moved out of the READMEs).
- [`glossary.md`](glossary.md) — source of truth for cross-document terminology.
- [`data-health.md`](design/data-health.md) — the Data Health card's structure,
  visual rules and the tests that enforce them.
- [DSH patrol chip](design/dsh-patrol-2026-10-03/README.md) and
  [task detail exits](design/dsh-patrol-2026-10-03/details.md) — density tradeoffs,
  motion decisions and before/after captures from an isolated instance.

- [README hero diagrams](design/hero-diagrams-2026-10-03/README.md), with
  [second iteration](design/hero-diagrams-2026-10-03/iteration-2/README.md) — diagram layout evidence.
- [Task chip folding](design/dsh-task-chip-fold-2026-10-04/README.md) — task history layout evidence.
- [Patrol coverage and dispatch Markdown](design/dsh-progress-2026-10-04/README.md), with
  [installed WeChat filter output](design/dsh-progress-2026-10-04/wechat-filter-output.md) — real data provenance, screenshot and remaining rendering limits.
- [Task chip coverage and chat list redesign](design/dsh-task-chip-redesign-2026-10-04/README.md) — critique, decisions, before/after renders and the WeChat filter evidence.

- [Todos workflow](design/todos-workflow-2026-10-04/README.md) — task workflow evidence.

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
