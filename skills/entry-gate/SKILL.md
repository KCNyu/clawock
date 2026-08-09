---
name: entry-gate
description: Pre-investment screening gate for a name that is not yet researched or held. Use before spending a deep-research run or opening new exposure, to answer only "is this understandable and researchable enough to proceed?". Grades information richness separately from investment quality, applies deterministic hard vetoes from config/entry-gate-vetoes.json, and returns pass_to_deep_research / reject / gray_needs_evidence via the packaged clawock entry-gate command. Recommends research; never sizes or places a trade.
---

# Entry Gate

Manual, run once per candidate name. It is cheap on purpose: it decides whether the
expensive work is worth doing, and its output routes straight into the full-report
mode of the market's analysis skill.

Write `memory/entry-gates/<TICKER>-<YYYY-MM-DD>.json` and let the script decide.
You supply findings and evidence; the verdict is computed.

## What the script computes, and will overrule you on

- `information.grade` (A/B/C) from the evidence source classes you cite;
- `quote_freshness` from `quote.as_of` against `assessed_at`;
- `verdict` and `routing` — a stated verdict that disagrees with the computed one is
  a validation error, not a note;
- whether a hard veto's industry exception is actually encoded for this sector.

Vetoes are resolved **before** any check is counted, so `checks_passed` can never
rescue a vetoed name.

## Step 1 — quote and instrument kind

Use the workspace pipelines, never a web price:

```bash
clawock analyze-us {TICKER}   # US
clawock analyze-hk {TICKER}   # HK
```

`quote.source_class` must be one of the pipeline names, or validation fails outright.
A quote older than 24h makes the verdict gray rather than pass.

Set `instrument_kind`. A leveraged ETF has **no** company fundamentals to grade: it
takes the `underlying_exposure` / `decay_and_regime` / `sizing_limit` / `liquidity`
checks and routes to `leverage_look_through`. When the ticker is in
`config/instruments.json`, the registry's `leverage_multiple` overrules your
declaration.

## Step 2 — mechanism and key variables

`mechanism` is one sentence: **who pays, why, and what makes it repeat.** If you
cannot write it from primary sources, that is the `unintelligible_revenue_mechanism`
veto, not a writing problem.

Then 3–7 `key_variables`, each with why it decides the outcome — not a metric dump.

## Step 3 — checks, each carrying evidence

Company: `business_quality`, `moat`, `management_governance`, `valuation`,
`dilution`, `downside`. Every `pass`/`fail` needs at least one `evidence_ids` entry;
`unknown` is the honest answer when you have not verified it, and it makes the
verdict gray.

A failed `business_quality`, `management_governance` or `downside` (or, for a
leveraged ETF, `underlying_exposure` or `sizing_limit`) is a reject. A failed
`moat`, `valuation`, `dilution`, `decay_and_regime` or `liquidity` is not: an
expensive or shallow-moat name is still worth understanding, and sizing stays with
the existing risk and decision contracts.

## Step 4 — the four hard vetoes

State a status for every veto in `config/entry-gate-vetoes.json`:
integrity/governance, unintelligible revenue mechanism, persistent negative cash
generation, destructive dilution. `triggered` requires evidence.

Two of them encode industry exceptions (clinical-stage biotech, pre-revenue
infrastructure). An exception applies only when the artifact's `sector` matches the
encoded one and the exception cites its own evidence row. Integrity and
unintelligible-mechanism encode none — there is no sector where they are acceptable.

## Step 5 — mirror test and verdict

Exactly five distinct sentences: what it does, why it earns, what must stay true,
what would break it, and what you would do then.

```bash
clawock entry-gate validate memory/entry-gates/<TICKER>-<date>.json
clawock entry-gate assess   memory/entry-gates/<TICKER>-<date>.json
```

- `pass_to_deep_research` → go run `us-stock-analysis` / `hk-stock-analysis`
  **Mode 4 (Full Report)**, or the leverage look-through path for a leveraged ETF.
  Carry `key_variables` in as the questions the report must answer.
- `gray_needs_evidence` → `next_evidence` must name the question and where to look.
  Nothing else happens until that evidence exists.
- `reject` → record it and stop. Thin sourcing alone never lands here; a `C` grade
  is gray, because information richness is not investment quality.

## Hard limits

- A `C` information grade describes the sources, never the company.
- No aggregate score, no persona voting, no "average" that can dilute a veto.
- This gate opens no position and changes no thesis. A qualified name goes to full
  research; exposure still goes through the decision, risk, and settlement chain.
