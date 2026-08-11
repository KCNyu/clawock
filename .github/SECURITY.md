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

## What is in scope

- The published package `clawock` (`src/clawock/`) and the instance distribution
  `clawock-kcnyu` (`instances/kcnyu/`).
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
