# Earnings review artifacts

One file per reporting period: `memory/earnings/<TICKER>/<period-label>.json`.
The file is the canonical record — which first-party documents were read, the
comparable history, the promise ledger, and the provenance manifest behind every
published number. Markdown write-ups are renderings of it, never the source.

```bash
clawock earnings validate        memory/earnings/<TICKER>/<period>.json
clawock earnings review          memory/earnings/<TICKER>/<period>.json
clawock earnings thesis-evidence memory/earnings/<TICKER>/<period>.json
clawock earnings promises \
    memory/earnings/<TICKER>/<previous>.json memory/earnings/<TICKER>/<current>.json
```

Shape: `src/clawock/config/earnings_review.schema.json`. Workflow and source policy:
`skills/earnings-review/SKILL.md`. Worked US and HK examples live in
`tests/fixtures/earnings/`.

Rules this directory relies on:

- the newest period's file holds the live promise ledger; earlier files are the
  history, so there is no second commitment store to drift out of sync;
- a promise may never be dropped, and `met` / `partial` / `missed` are terminal;
- `basis`, `currency` and `unit` are constant across a comparable history;
- footnote claims require a primary issuer document covering the period;
- earnings evidence flows into `memory/theses/*.json` through the registry's own
  drift evaluator. Nothing here changes thesis state on its own.
