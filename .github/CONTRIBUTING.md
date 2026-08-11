# Contributing to clawock

This repository is two things at once, and which one you are touching decides
whether a patch can be merged at all. Read that split first; it is the whole
policy.

## The product is open. The live book is not.

- **Product — patches welcome.** The portable package under `src/clawock/`, its
  tests under `tests/`, the CLI, the workflow packs under `skills/`, the docs,
  and the operations code under `ops/`. These are what `pip install clawock`
  gives someone with their own agent, their own broker and their own deployment.
  Bugs here affect every user, and a fix is a real contribution.

- **Instance — not a contribution surface.** `portfolio.json`, `memory/`,
  `assets/data/`, `logs/`, the published site data, and
  `instances/kcnyu/` are one investment desk's live state and its adapter. They
  are written continuously by scheduled automation through protected paths and
  deploy keys, and they record real positions. A pull request that edits
  generated data or the KCNyu instance will be closed — not because the work is
  unwelcome, but because merging it would rewrite a live ledger.

`docs/reference/product-vs-instance.md` states the ownership rule per directory.
The deciding question there is the same one to ask before opening a PR: *would a
third party running clawock with their own book need this change?*

If your idea is instance-shaped but generalisable — a provider, a gate, a metric
— the useful form is a product-level change with the desk-specific part left
configurable. Say so in the issue and it can be scoped that way before you write
code.

## Open an issue first

For anything beyond a typo, please open an issue before writing the patch. Say
what is broken, how you observed it, and what a fix would have to demonstrate to
count as fixed. This is the same rule the maintainer's own automation follows,
and it exists because most of the expensive mistakes in this repository were
plausible changes that nothing could check afterwards.

Use the bug report template for defects. For a suspected vulnerability, do not
open an issue at all — see [`SECURITY.md`](SECURITY.md).

## Working on a change

```bash
git clone https://github.com/KCNyu/clawock
cd clawock
pip install -e .
pytest -q
```

- Branch from current `master`; never push to `master` directly.
- Every pull request must pass the required checks (`validate`, `lint`, and the
  CodeQL analyses). They run the behavior tests, schema and ledger checks, the
  generated cron contract, and a dashboard rebuild sanity pass.
- A behavior change needs a test that fails without it. Assertions that only
  search source text for a string are not accepted as behavior coverage; call
  the thing and check what it produced.
- Do not include generated artifacts in a code PR. Running the full suite can
  rewrite published files in a working checkout — check `git status` before
  staging, and never `git add -A`.
- Numbers that appear in the README or on the site have to come from an
  artifact something checks. Do not add a hand-typed count.

## Review and merge

The maintainer owns the merge. Both AI agents that work in this repository
authenticate as the same GitHub account, so **neither posts its review as a PR
comment** — a review that appears to come from the maintainer's own account is
the maintainer talking to themself. Findings stay in the interactive handoff.
Do not add a signature or a prefix to work around this; it is an identity
problem, not a labelling one.

Outside contributors are not part of that constraint: normal review comments on
your PR are how it will be discussed.

## License

By contributing you agree that your contribution is licensed under the
repository's MIT license. Note that third-party market data, news and generated
output are **not** covered by it — see `THIRD_PARTY_LICENSES` and `NOTICE`.
