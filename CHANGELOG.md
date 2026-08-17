# Changelog

What changed between the versions of the `clawock` distribution on PyPI.

Only the public package is released, so only changes a package consumer can
observe are listed here. The live KCNyu desk changes many times a day and its
record is the commit history, the dashboard and the evidence page — not this
file. Historical repository-only adapters appear below only where a release
step touched it.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
The newest heading here has to match the version in `pyproject.toml` — CI fails
otherwise, so a release cannot ship an entry that was never written.

## [0.1.7] — 2026-08-17

The Python package's code is identical to 0.1.6. This version exists because the
two distributions ride one version train and the npm half of 0.1.6 never
shipped: `clawock-dsh` is the release.

### Fixed

- **`clawock-dsh` on npm was a different build than its version number
  claimed, and 0.1.6 never got there at all.** npm's `latest` was 0.1.5, whose
  tarball is the pre-#708 layout — `client.js` at the root, no
  `lib/typert.*`, no `./typert` or `./remote` export, no `zod` dependency —
  so `dsh plugin add clawock-dsh` installed a plugin that registers and then
  shows no data. Both 0.1.6 publish attempts died inside npm itself
  (`Exit handler never called!`): the plugin's `package-lock.json` had been
  regenerated on a machine behind a mirror registry, so all 169 `resolved`
  URLs pointed at a host the GitHub runner cannot reach and every fetch
  stalled through npm's retry ladder. The lockfile is back on
  registry.npmjs.org, the publish job pins the npm that does the publishing
  and records which registry it used, and — because "publish exited 0" was
  never evidence — it now downloads the registry copy back and asserts
  file-for-file, export-for-export and dependency-for-dependency that it is
  what was packed. ([#732], [#728])

### Changed

- **The DSH plugin follows the official Harness client rules instead of a
  reverse-engineered shape.** Styles ship as CSS Modules whose
  `<style data-plugin="clawock-dsh">` tag the module loader owns and removes on
  unload, so nothing touches `document` while the bundle is loading; the UI
  store is a `createDecisionMindStore()` factory called inside `apply` rather
  than a module-level singleton shared across plugin reloads; the trace cache
  lives in the plugin instance and reaches the view through its props; the
  scroll container comes from an element ref instead of a global selector; and
  the browser bundle carries no business `any` — it consumes the same wire
  types the host declares. The generated Typert reflection is now emitted by
  the official generator running in place over the real source tree (the
  package moved to `examples/dsh/packages/clawock-dsh` because rc.6 discovers
  packages only under a workspace root's `packages/`), the build is
  reproducible, and CI rebuilds `lib/` on every plugin change and fails if the
  committed artifacts differ. ([#729], [#730], [#731])
- **Installing the plugin from a checkout goes through the official
  installer.** `ops/host/install_dsh_plugin.sh` packs the package and hands the
  tarball to `dsh plugin --profile web add`, which installs it the way a
  registry package is installed and reconciles the profile's bundle rows
  itself. It no longer hand-copies a source directory and hand-edits the
  profile manifest — a directory spec is only *linked*, which is how a plugin
  dependency went uninstalled and crash-looped dsh in the first place. The
  tarball's file name carries a content hash, because pnpm keys a `file:`
  tarball by path and would otherwise serve the previous build from its store
  while every step reported success. ([#731])

## [0.1.6] — 2026-08-17

### Fixed

- **The `clawock-dsh` plugin marked T+1 against a price the rest of the system
  had already disowned.** It read `current_price` out of the portfolio
  snapshots, a field whose vintage follows whichever job wrote it — measured
  across 15 snapshots on one ticker it was the previous close 7 times, that
  day's close 3 times and an intraday print 5 times, and it is carried forward
  once a position closes (one ticker sat frozen at 213 for five sessions while
  its real closes ran 222.32 / 220.61 / 223.47 / 219.51 / 215.33). Settlement
  moved to the canonical `memory/bars/` store for exactly this reason; the
  panel had not followed. On the live book 82% of T+1 deltas disagreed with the
  canonical close and 10 verdicts inverted outright. T+1 now reads
  `memory/bars/<ticker>.json`, and a fill with no canonical bar shows no
  verdict rather than falling back. ([#717], [#719])
- **"T+1" was not T+1 for most fills.** The close was whichever snapshot
  happened to come next, with no ceiling, so fills predating the snapshot
  series were marked against a close up to 144 days later — still labelled
  T+1. A close is now only a T+1 verdict when it lands within four calendar
  days (a Friday fill settles against Monday; one holiday makes four), and the
  scorecard renders the denominator it is computed over. ([#710], [#716])
- **One dead zone, applied everywhere.** The verdict text, the trace node and
  the result chip each carried their own threshold, so a sell at +0.5% rendered
  a grey "持平" chip next to a red node, and a buy at exactly 0% was painted
  green while the text read 跌. The reading is now decided once, host-side, and
  the client only maps it to CSS. ([#713], [#716])
- **`decision_packet_summary` refused to run once the book reached ten
  holdings.** The whole-book summary and a single-ticker section query shared
  one 24KB budget, but the summary is O(holdings) — it crossed the line at
  33,543 bytes and exited non-zero. It is the brief's resident input, so the
  brief had no way into its own analysis. The summary now has its own budget
  and reports how close it is to it. ([#723], [#724])
- **A conversation-source ledger row could take down anything that read the
  ledger.** Rows written by the decision-mind path carry `decided_at` and no
  `created_at` / `plan_date`; two readers subscripted those keys directly, so
  the first such row made episode assignment raise `KeyError` — discarding an
  already-generated brief — and turned the README metrics refresh red every
  night. Both readers now route mind rows the way the validator already did.
  ([#718], [#720])
- **The canonical bar store started only at 2026-05-01**, so fills older than
  that had no close to settle against. It now starts 2025-12-01, a month before
  the oldest recorded fill. ([#719])

### Added

- **`ops/host/install_dsh_plugin.sh`** installs the DSH plugin with its runtime
  dependencies and verifies every export entry imports before handing it to the
  harness. The previous path linked the source directory into the profile
  without ever installing its dependencies, so the first plugin release to
  declare one could not load at all. ([#709], [#716])
- **A packaged-install contract test** (`tests/dsh_plugin_package_contract.mjs`)
  packs `clawock-dsh`, installs the tarball into an empty project and imports
  each export entry, which is the only place a declared-but-never-installed
  dependency is visible. ([#709], [#716])
- **`config/intraday-delivery.json`** switches intraday delivery between the
  semantic-delta receipts and a full block on every slot. Absent, unreadable or
  ambiguous configuration keeps the reviewed default. ([#726])

## [0.1.5] — 2026-08-16

### Fixed

- **The `clawock-dsh` DSH plugin's T+1 result color was inverted for sell
  actions.** It applied one sign rule to every action, so a rising price after
  a *sell* (a loss for the seller — 卖飞) rendered green, and a falling price
  after a *buy* rendered green too. The color is now action-aware: rising is
  good (green) for a buyer, bad (red) for a seller, and vice versa. ([#665])

### Added

- **`clawock record --source <harness>`** is now the single write path for the
  decision-mind ledger (`memory/decisions.jsonl`); every harness (OpenClaw,
  Claude, Codex, DSH, CLI) tags its own conversational judgments through it
  instead of hand-writing JSONL, and `validate_decision` accepts the resulting
  schema-version-0 records from any of them. ([#661], [#662])
- **The DSH plugin's Decision Studio tab is now a single "决策轨迹" (decision
  trace) timeline** built from real trade fills, not a separate, disconnected
  ledger view: each row pairs an actual execution with its T+1 result chip and
  expands into the plan → execution → outcome sequence. It renders only the
  most recent activity by default, with a "show all" control for the rest.
  ([#676], [#684])

## [0.1.4] — 2026-08-16

### Fixed

- **Harness-agnostic examples and the `clawock-dsh` skill now match the real
  validator.** The tutorial taught `--artifact decision=...`, a six-field
  decision shape and a fixed `.clawock/work/request.json` path; the validator
  requires the artifact to be named `decision.json`, nine top-level fields
  (schema_version / workflow / decision_id / as_of / subject / evidence /
  debate / thesis / decision) and the `<run_id>`-scoped request file
  `prepare` actually writes. The examples were rewritten against the pack's
  `decision.example.json` and the whole prepare → decision.json → publish
  loop is verified end-to-end. (`clawock-dsh` npm package bumped to 0.1.4.)
- **No more double-writer races on a missing brief.** The 09:05 watchdog no
  longer queues a local re-run and the off-host fallback at the same time —
  two LLMs writing the same artifacts produced duplicate WeChat/Telegram
  pushes. The re-run is now evidence-gated (a run that ended OK today does not
  stack another queue entry).
- **Report delivery gaps are now named.** When a postflight sender dies
  mid-send (claim present, no completion marker), the watchdog says "WeChat
  delivery unconfirmed" out loud instead of silently only mirroring Telegram.
- **User risk overrides settle the ledger.** An overridden risk_rule cut is
  settled (`execution.status=overridden_by_user`) instead of accumulating as
  `unknown` forever and flooding the open queue when the override TTL expires.
- **The 30-bar data-quality gate is restored.** The short-history fallback now
  requires a registry `listing_date` within 45 days, so a mature name with a
  partial feed can no longer enter the universe with half a signal set.

### Changed

- The AI watch list (智谱 / 迅策) now rides the brief's `market` bundle — the
  model boundary can actually read it — and its thresholds
  (`opportunity_near_pct`, `early_no_chase_zscore`) moved into
  `add-alpha-policy.json` as a single source shared with the intraday radar.
- Intraday slots fetch each code once per slot instead of three times
  (~540 → ~180 requests/day).
- Intraday push gating: opportunity/early-trend sub-state flips around a price
  threshold no longer retrigger a full push every slot.

## [0.1.3] — 2026-08-15

### Added

- **Harness-agnostic decision contract.** The workflow is files + CLI, so the
  same decision run works from a pure CLI, an OpenClaw skill, a Claude Code
  instruction, a Codex `AGENTS.md`, or a DeepSeek Harness agent — see
  `examples/harness-agnostic/` (each runnable, executed by `release.yml`).
- **`clawock-dsh` skill package on npm.** DSH users install one command:
  `dsh plugin --profile web add clawock-dsh`. A pure `dsh.skills` package (no
  Node code) that walks the agent through prepare → `decision.json` → publish.
- **README rewritten around the live record.** First-line hook (90 days live,
  −15.95%, every loss on the page), four-line scorecard reconciliation
  (ledger / directional hit / shadow portfolio / real account), reproducible
  auditing (`clawock audit-resettle`), and the influencer radar (Trump /
  Musk) now documented in both languages. Live numbers are maintained by
  `ops/growth/refresh_readme_metrics.py` placeholders, refreshed weekly by CI.
- `ops/publish/publish_dsh_plugin.sh` — single entry point for publishing the
  npm side of a release, shared by `release.yml` and manual bumps.

### Changed

- README.zh.md and README.md now share a locked 12-section structure (CI
  parity tests); the information-layer tables are checked against
  `config/information-layers.json` and the per-run block counts against the
  preflights themselves.

## [Unreleased]

### Added

- `clawock.providers.openclaw.run_cron_job(job_id)` asks the runtime to run a scheduled job now, reporting `(ok, output)` like the rest of the adapter instead of raising. It exists because the runtime's transient retry is budgeted by a `consecutiveErrors` counter that only resets on success, so a job scheduled once a day loses its retry after three bad days and needs recovery driven from outside the scheduler (#493).

### Changed

- Harness phases, strategies, scheduling, watchdogs, automation and providers
  now have one executable owner: the root `clawock` distribution. KCNyu is a
  declarative profile plus workspace resources/state; the repository-only
  `clawock-kcnyu` distribution, entry-point bridge and `CLAWOCK_INSTANCE`
  selector are removed (#536, #537, #538, #539).
- The command catalog the README links moved to `docs/reference/commands.md` — named after the deleted `scripts/` directory before — and its inventory is now generated from the distribution's CLI and standalone-command registries instead of being hand-maintained, so it lists every installed command (#489). The old path stays as a pointer because published releases link it.

## [0.1.2] — 2026-08-11

Mostly documentation and repository policy. It is a release because `README.md`
is shipped verbatim as the PyPI `long_description`, and a published page cannot
be re-rendered — the same reason 0.1.1 existed.

### Fixed

- The numeric provenance advisory now recognises `%`, `pp`, `x`/`×` and `σ`, and
  matches context per unit rather than against one flat set of numbers, so a
  figure like `2.3x` is no longer waved through by a match on an unrelated
  quantity. The intraday insights sidecar is normalised before publication:
  model-owned narrative is kept, the `generated_at` stamp is the harness's own
  UTC clock, and a missing or malformed sidecar stays warn-only so report
  delivery is not held hostage to it. ([#485])
- The README's widest claim about the system — "26 fetch and compute modules
  across 8 layers" — had no artifact behind it and had survived #429, which
  moved every module it counted. The catalog is now
  `config/information-layers.json`: every packaged command sits in exactly one
  layer or on an exclusion list with the reason it is not information
  collection, and the tables in both READMEs are checked against it. The
  partition covers both distributions' command registries, so nothing counted
  can be typed by hand. Re-derived, the count is 39, and two layer names that no
  longer described their members were corrected. ([#476])

### Added

- `SECURITY.md` naming GitHub private vulnerability reporting — now enabled on
  the repository, so the channel it points at exists — a
  `CONTRIBUTING.md` stating which parts of the repository can accept a patch
  (the package can; the live book cannot), and a bug-report issue template.
  Installable packages need a disclosure channel; a repository someone only
  reads does not. ([#477])
- The runtime-coupling ratchet now also enumerates shell entry points naming the
  live host, against a per-file allowlist with a reason each. Its Python count
  stays 0, and the claim now states what it covers. ([#478])

## [0.1.1] — 2026-08-10

### Fixed

- The PyPI project page rendered six broken images, including the logo and the
  hero card — the first two things a visitor saw. `pyproject.toml` ships
  `README.md` verbatim as `long_description`, and PyPI has no repository to
  resolve a relative path against. Every asset and document reference in the
  README is now absolute. An already-published version cannot be re-rendered, so
  this needed a new release rather than a fix in place. ([#468])
- The instance package restated its version as a literal, so the 0.1.1 build
  would have announced 0.1.0. It reads `importlib.metadata` now, and the two
  distributions' versions are checked against each other. ([#469])

## [0.1.0] — 2026-08-10

First release. `pip install clawock` gets the runtime-neutral decision-workflow
package: the lifecycle CLI (`clawock init` → `run prepare` → `run publish`),
packaged workflows installable as Agent Skills, the context/tool contracts,
generation-pinned artifact publication with receipts, and the deterministic
portfolio, market-data, decision and evidence domains.

Published through GitHub trusted publishing, with no API token. Before it
uploads, the release job installs the exact artifact into a clean virtualenv
under `env -i` — no checkout, no runtime, no workspace, no inherited
environment — and completes one full run. ([#436], [#379])

[#379]: https://github.com/KCNyu/clawock/issues/379
[#436]: https://github.com/KCNyu/clawock/pull/436
[#468]: https://github.com/KCNyu/clawock/pull/468
[#469]: https://github.com/KCNyu/clawock/pull/469
[#476]: https://github.com/KCNyu/clawock/issues/476
[#485]: https://github.com/KCNyu/clawock/pull/485
[#477]: https://github.com/KCNyu/clawock/issues/477
[#478]: https://github.com/KCNyu/clawock/issues/478
[#661]: https://github.com/KCNyu/clawock/pull/661
[#662]: https://github.com/KCNyu/clawock/pull/662
[#665]: https://github.com/KCNyu/clawock/issues/665
[#676]: https://github.com/KCNyu/clawock/pull/676
[#684]: https://github.com/KCNyu/clawock/pull/684
[Unreleased]: https://github.com/KCNyu/clawock/compare/v0.1.7...HEAD
[0.1.7]: https://github.com/KCNyu/clawock/compare/v0.1.6...v0.1.7
[0.1.6]: https://github.com/KCNyu/clawock/compare/v0.1.5...v0.1.6
[0.1.5]: https://github.com/KCNyu/clawock/compare/v0.1.4...v0.1.5
[0.1.2]: https://github.com/KCNyu/clawock/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/KCNyu/clawock/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/KCNyu/clawock/releases/tag/v0.1.0
[#709]: https://github.com/KCNyu/clawock/issues/709
[#710]: https://github.com/KCNyu/clawock/issues/710
[#713]: https://github.com/KCNyu/clawock/issues/713
[#716]: https://github.com/KCNyu/clawock/pull/716
[#717]: https://github.com/KCNyu/clawock/issues/717
[#718]: https://github.com/KCNyu/clawock/issues/718
[#719]: https://github.com/KCNyu/clawock/pull/719
[#720]: https://github.com/KCNyu/clawock/pull/720
[#723]: https://github.com/KCNyu/clawock/pull/723
[#724]: https://github.com/KCNyu/clawock/pull/724
[#726]: https://github.com/KCNyu/clawock/pull/726
[#728]: https://github.com/KCNyu/clawock/pull/728
[#729]: https://github.com/KCNyu/clawock/issues/729
[#730]: https://github.com/KCNyu/clawock/issues/730
[#731]: https://github.com/KCNyu/clawock/issues/731
[#732]: https://github.com/KCNyu/clawock/issues/732
[#733]: https://github.com/KCNyu/clawock/pull/733
