# Changelog

What changed between the versions of the `clawock` distribution on PyPI.

Only the public package is released, so only changes a package consumer can
observe are listed here. The live KCNyu desk changes many times a day and its
record is the commit history, the dashboard and the evidence page — not this
file. `clawock-kcnyu` is never published; it appears below only where a release
step touched it.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
The newest heading here has to match the version in `pyproject.toml` — CI fails
otherwise, so a release cannot ship an entry that was never written.

## [Unreleased]

### Added

- `clawock.providers.openclaw.run_cron_job(job_id)` asks the runtime to run a scheduled job now, reporting `(ok, output)` like the rest of the adapter instead of raising. It exists because the runtime's transient retry is budgeted by a `consecutiveErrors` counter that only resets on success, so a job scheduled once a day loses its retry after three bad days and needs recovery driven from outside the scheduler (#493).

### Changed

- The command catalog the README links moved to `docs/reference/commands.md` — named after the deleted `scripts/` directory before — and its inventory is now generated from the installed-command registries instead of being hand-maintained, so it lists every command the two distributions install (#489). The old path stays as a pointer because published releases link it.

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
[Unreleased]: https://github.com/KCNyu/clawock/compare/v0.1.2...HEAD
[0.1.2]: https://github.com/KCNyu/clawock/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/KCNyu/clawock/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/KCNyu/clawock/releases/tag/v0.1.0
