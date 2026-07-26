# Canonical thesis registry

One JSON file per durable investment thesis. Markdown reports may explain a
thesis, but these versioned JSON documents are the machine-readable authority
for assumptions, red lines, valuation anchors, evidence, state, and the next
review trigger.

Validate a document:

```bash
python3 scripts/data/thesis_registry.py validate memory/theses/<thesis-id>.json
```

Compare two versions:

```bash
python3 scripts/data/thesis_registry.py drift old.json new.json
```

Missing baselines stay `unknown`. A changed dimension requires a newly observed
evidence ID; price-only evidence may change valuation but cannot change business,
moat, or management state.
