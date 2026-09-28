# Security policy

## Reporting a vulnerability

Use GitHub private vulnerability reporting: **Security → Report a vulnerability**
on <https://github.com/KCNyu/clawock/security/advisories/new>. That channel is
private to the maintainer until an advisory is published, and it needs no email
address from either side.

Please do **not** open a public issue for a suspected vulnerability, and never
paste a credential, token or API key into one. If you believe a secret is
exposed in this repository or its history, report it through the private channel
so it can be rotated before it is pointed at.

This is a single-maintainer project. Reports are read on a best-effort basis;
there is no response-time commitment, and none should be inferred from this file.

## Known exposures

Values are never written here — only provider, where and when, and what was done.

| Provider | In public history | Removed from the tree | Rotation |
|---|---|---|---|
| Finnhub, Alpha Vantage, Polygon.io | `c4657808b` (2026-03-11, `TOOLS.md` and three scripts), `bbb479ce9` (2026-03-22) | `f749443a4` (2026-04-05), `36711fae4` (2026-05-16) | owner action, tracked in #2033; this row records the date once done |

History is not rewritten: a rewrite changes every later commit SHA and does not
make a value that has already been cloned unusable — rotation does. The CI step
`No credential-shaped values in the added lines` (`ops/ci/commit_secret_scan.py`)
scans every commit a PR or code push brings, Markdown included.

## What is in scope

- The published package `clawock` (`src/clawock/`) and its declarative profiles.
- Repository operations that hold credentials or write to protected paths:
  `ops/publish/`, `.github/workflows/`, `.githooks/`.
- Anything that could let a third party publish to this repository, its Pages
  site, or its data plane.

## What is out of scope

- The **content** of the published market data, positions, briefs and scorecard.
  Those are generated output, not a security boundary; if a number is wrong,
  that is a bug — open a regular issue.
- Third-party data providers and their APIs. Report those to the provider.
- The live brokerage account itself, which is operated by the maintainer outside
  this repository. Nothing here can place an order: execution is human, by
  design.

## Supported versions

Only the latest version published on [PyPI](https://pypi.org/project/clawock/)
is supported. Fixes ship as a new release rather than as patches to older tags.
