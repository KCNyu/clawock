# Decision artifact contract

`decision.json` is the single required artifact for workflow version `1.1.0`.
Unknown or missing fields are rejected so a producer cannot silently invent a
parallel schema.

The machine-readable shape is `decision.schema.json` in this directory. JSON
Schema covers structure and primitive types; clawock's Python validator adds the
cross-reference, provenance, opposing-evidence, action/order and arithmetic
invariants that JSON Schema cannot express.

## Top-level fields

- `schema_version`: integer `1`.
- `workflow`: exactly `{"id":"investment-decision","version":"1.1.0"}`.
- `decision_id`: stable non-empty identifier chosen by the calling runtime.
- `as_of`: ISO-8601 timestamp with timezone.
- `subject`: `ticker`, `market`, and quote `currency` strings.
- `evidence`: traceable evidence rows.
- `debate`: one bull and one bear case, each linked to evidence IDs.
- `thesis`: statement, confidence from 0 to 1, and non-empty invalidation conditions.
- `decision`: bounded action, rationale, evidence links, and optional order intent.

## Evidence

Each row contains exactly:

- `id`: unique non-empty string.
- `stance`: `supporting`, `opposing`, or `context`.
- `summary`: the observed fact, not an unsupported conclusion.
- `source`: a stable locator or source name.
- `source_class`: `primary`, `secondary`, `market`, or `agent`.
- `observed_at`: ISO-8601 timestamp with timezone, no later than `as_of`.

The bull case must cite supporting evidence and the bear case must cite opposing
evidence. Every cited ID must exist. The configured workflow parameters control
minimum evidence counts and the maximum confidence allowed without a cited
primary source.

## Decision and order intent

`action` is one of `buy`, `add`, `hold`, `watch`, `trim`, `sell`, `exit`, or
`abstain`. `hold`, `watch`, and `abstain` carry `order: null`. Other actions
carry an order with exactly:

- `side`: `buy` or `sell`, consistent with the action.
- `quantity`, `unit_price`, `gross_amount_quote`.
- `quote_currency`, `base_currency`.
- `fx_quote_to_base`, `gross_amount_base`.

All numeric values must be positive and finite. clawock reconciles the two money
identities to currency cents:

`gross_amount_quote = quantity * unit_price`

`gross_amount_base = gross_amount_quote * fx_quote_to_base`

See `assets/decision.example.json` for a complete watch decision.

## Outcome evidence and evaluation

Copy `assets/outcome.example.json`, preserve the decision/workflow identifiers,
and replace the price, FX, timestamp, and source fields with observed evidence.
Then run:

```bash
clawock workflow evaluate investment-decision \
  --decision decision.json --outcome outcome.json --output evaluation.json
```

The evaluator calculates quote-currency and base-currency market moves in basis
points. `decision_value_bps` applies +1 to long/hold decisions, -1 to
trim/sell/exit decisions, and 0 to watch/abstain. This is a reproducible
directional evaluation, not realized P&L; portfolio cash, fills, fees, taxes and
position size remain outside this artifact.

## Bounded improvement

An external runtime or human can propose only parameters already bounded by
`workflow.json`:

```bash
clawock workflow propose --workspace . --trigger evaluation.json \
  --set min_opposing_evidence=2 \
  --rationale "Weak opposing evidence preceded the measured miss." \
  --expected-effect "Require a second independent opposing source." \
  --output proposal.json

clawock workflow review --proposal proposal.json --decision accepted \
  --reviewer analyst@example --note "Evidence supports a bounded trial." \
  --output review.json

clawock workflow apply --workspace . --proposal proposal.json --review review.json
clawock workflow rollback --workspace . --change-id <change-id>
```

The trigger can also be a rejected `clawock run publish` receipt. A proposal
pins the workflow version/certificate, trigger hash, old/new values and expected
effect. Apply refuses rejected or mismatched reviews, stale parameters, unknown
settings and values outside their declared bounds. Rollback refuses to overwrite
later parameter drift.

This loop never launches a model, edits `SKILL.md`, changes OpenClaw memory/chat
behavior or accepts its own proposal. Reasoning stays in the external runtime;
clawock owns the evidence link, deterministic math and reversible adoption
record.

The bounded parameters change workflow evidence strictness only. They do not
introduce or tune quantitative factors, catalysts, signals, entry/exit rules or
portfolio construction; those remain part of the caller's existing strategy.
