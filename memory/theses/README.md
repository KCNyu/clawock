# Canonical thesis registry

One JSON file per durable investment thesis. Markdown reports may explain a
thesis, but these versioned JSON documents are the machine-readable authority
for assumptions, red lines, valuation anchors, evidence, state, and the next
review trigger.

Validate a document:

```bash
clawock thesis validate memory/theses/<thesis-id>.json
```

Compare two versions:

```bash
clawock thesis drift old.json new.json
```

Missing baselines stay `unknown`. A changed dimension requires a newly observed
evidence ID; price-only evidence may change valuation but cannot change business,
moat, or management state.

Red lines are symmetric: triggering one and leaving `triggered` both require new
evidence observed after the baseline's `checked_at`, and a triggered red line may
not simply be deleted from the next version. `drift` reports
`newly_triggered_red_lines` and `resolved_red_lines` so a reversal is visible
instead of dissolving into `unchanged`.
