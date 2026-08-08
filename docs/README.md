# Project documentation

The repository root is reserved for files with a real discovery or publishing
contract: GitHub metadata, OpenClaw bootstrap context, Jekyll entry points, and
website-root verification files. General documentation belongs here.

## Architecture

- [`data-plane.md`](architecture/data-plane.md) — why the live JSON snapshot is
  separate from Pages, what GitHub officially supports, and the replacement bar.
- [`harness.md`](architecture/harness.md) — package/instance/runtime boundaries,
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

- [`scripts.md`](reference/scripts.md) — detailed script and harness catalog.

## Legal

- [`third-party-data.md`](legal/third-party-data.md) — data-provider terms,
  attribution, and redistribution boundaries.

## Archive

Historical designs live under `archive/`. They are retained for context, are
excluded from the public Pages build, and must not be used as current runbooks.

## Why some website files stay at the root

`index.html`, `briefs.md`, `_config.yml`, `_layouts/`, `robots.txt`,
`manifest.webmanifest`, and verification files have root-path or Jekyll
discovery semantics. Moving them without changing the complete Pages build
pipeline would alter public URLs or break verification, so they intentionally
remain at the repository root.
