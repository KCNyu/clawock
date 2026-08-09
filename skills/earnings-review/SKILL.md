---
name: earnings-review
description: Manual, event-driven earnings review for a US or HK holding, backed by first-party filings. Use when a company reports, when a management promise comes due, or when a thesis review needs primary-source numbers. Produces a structured artifact under memory/earnings/<TICKER>/<period>.json whose earnings-quality math, promise ledger, and thesis evidence are computed by the packaged clawock earnings command — not by prose. Never places trades and never changes thesis state.
---

# Earnings Review

Event-driven, never scheduled. Run this when an issuer reports, when a commitment
comes due, or before a thesis review that needs first-party numbers. It is not part
of any cron path.

The output is not a report. It is `memory/earnings/<TICKER>/<period>.json`, and the
Markdown you write afterwards is a rendering of that file.

## What the code owns and what you own

| Owned by `clawock earnings` | Owned by you |
|---|---|
| Source grade `A/B/C` and whether footnote claims are allowed | Reading the filing and paraphrasing what it says |
| Cash conversion, FCF, working-capital gaps, dilution, SBC share, margins | Choosing which segments and footnotes matter |
| Guidance beat / inline / miss | Recording the commitment and its measurable target |
| Promise roll-forward to `met / partial / missed / not_due / unverifiable` | Locating the document that proves the result |
| The release gate over the provenance manifest | Deciding whether the period changes the thesis |

Never assert a computed number in prose. Run the script and quote its output.

## Step 1 — collect first-party documents

Source order is not negotiable:

- **US** — SEC filing (10-K/10-Q/8-K) or issuer IR first; `clawock filings`
  supplies the structured XBRL numbers used to verify them.
- **HK** — HKEX announcement or issuer IR first; `scripts/data/fetch_fundamentals_em.py`
  (Eastmoney) is a secondary *structured* source, never a substitute for a footnote.
- A third-party summary may only fill a gap, and it lowers the grade.

Record each document once in `documents[]` with its `source_class`, a stable
`locator`, `retrieved_at`, and whether it `covers_period`. Store a short paraphrase
and the locator — never long transcript passages.

Grades are mechanical: **A** needs a covering primary document plus a structured
dataset; **B** has the dataset but no covering primary document; **C** is
third-party only. `B`/`C` disable every footnote claim, and the validator enforces
that. A low grade describes the sources, not the company.

## Step 2 — build the comparable history

At least four comparable quarters (or four half-years, or three annual periods).
`basis`, `currency` and `unit` must be identical across every comparable — a
GAAP/non-GAAP or currency switch mid-history is a validation error, not a caveat.
`revenue`, `net_income` and `ocf` are mandatory per period; anything else you omit
becomes an explicit `unavailable` with a reason instead of a number.

## Step 3 — promises and capital allocation

Carry the previous period's ledger forward; a promise may never be dropped, and
`met/partial/missed` are terminal.

```bash
clawock earnings promises \
  memory/earnings/TICKER/<previous>.json memory/earnings/TICKER/<current>.json
```

An overdue promise with no reported result becomes `missed` when this reporting
period covers its due date, and `unverifiable` when the due date has merely passed
with no covering report yet. Log buybacks, dividends, M&A, leverage changes,
divestitures and new-business spend in `capital_allocation[]`.

## Step 4 — provenance and release

Every published number needs two independent sources in `provenance` (see
`clawock.research_provenance`). The release gate refuses the artifact when
any number is single-sourced or the two sources disagree beyond tolerance.

```bash
clawock earnings validate memory/earnings/TICKER/<period>.json
clawock earnings review   memory/earnings/TICKER/<period>.json
```

`review` prints the source grade, the provenance verdict, the quality metrics and
`anomaly_flags`. A non-zero exit means the artifact is not releasable — fix the
artifact, do not narrate around it.

## Step 5 — hand evidence to the thesis, not a verdict

```bash
clawock earnings thesis-evidence memory/earnings/TICKER/<period>.json
```

This emits `evidence[]` rows in the thesis registry's shape plus
`dimension_suggestions`. It deliberately carries no thesis state. To change a
thesis, append these evidence rows to a new version of
`memory/theses/<thesis-id>.json` and run the registry's own drift evaluator:

```bash
clawock thesis drift old.json new.json
```

The registry re-checks freshness itself and will reject a dimension change that
leans on evidence older than the last check.

## Hard limits

- No persona scoring and no aggregate "master score" — a red-line or
  integrity failure is never averaged away by good numbers elsewhere.
- No trade from a single earnings classification. Sizing stays with the existing
  decision and risk contracts.
- A price move or a headline is not a filing fact.
- Missing documents lower the grade. They never justify a fabricated number.
