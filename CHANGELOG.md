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

Nothing yet.

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
[Unreleased]: https://github.com/KCNyu/clawock/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/KCNyu/clawock/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/KCNyu/clawock/releases/tag/v0.1.0
