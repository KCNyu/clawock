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

- [`how-the-desk-works.md`](how-the-desk-works.md) — the detail behind the README:
  information layers, what each run reads, decision gates, grading rules, what was
  tested and failed, the twelve code-enforced rules ([中文](how-the-desk-works.zh.md)).
- [`decision-map.md`](decision-map.md) — the Decision Map board in Reflect: how
  to read coverage and snapshot age, the payload, and where it runs.
- [`decision-mind-ledger.md`](decision-mind-ledger.md) — the decision-mind
  ledger schema written by `clawock record`.
- [`influencer-radar.md`](influencer-radar.md) — the eight watched sources, how
  hits are linked to holdings, and a worked hit/miss example (moved out of the READMEs).
- [`glossary.md`](glossary.md) — source of truth for cross-document terminology.
- [`data-health.md`](design/data-health.md) — the Data Health card's structure,
  visual rules and the tests that enforce them.

## Operations

- [`release.md`](operations/release.md) — publishing to PyPI/npm, and running the
  latest code on the host without a release.
- [`cron-schedules.md`](operations/cron-schedules.md) — generated human view of
  the tracked cron contract.
- [`research-cadence.md`](operations/research-cadence.md) — which research
  question runs daily, which runs on an event, and why.
- [`skills-store-policy.md`](operations/skills-store-policy.md) — registry
  discovery and installation policy.

- [`agent-discovery.md`](operations/agent-discovery.md) — public machine documentation,
  documented engine discovery paths and a bounded citation measurement protocol.

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

A document here describes how the project works now. The record of one task — measurements,
before/after captures, command output, proposed patches, what was and was not verified —
belongs in that task's pull request, where it stays attached to the change it explains.
Write the conclusion into the document that owns the subject; do not add a dated folder.

## Why OpenClaw files stay at the root

`AGENTS.md`, `TOOLS.md`, `SOUL.md`, `IDENTITY.md`, `USER.md`, `MEMORY.md`,
`HEARTBEAT.md`, `BOOTSTRAP.md`, `skills/` and `memory/` participate in the live
OpenClaw workspace contract. They remain at their required runtime paths until
an adjacent context-parity canary proves a supported alternative. Website files
have no such constraint and therefore live under `site/`.

- [持仓外候选发现](architecture/stock-discovery.md)：免费全市场筛选、研究交接与参考实现。
