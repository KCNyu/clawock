# Decision artifact contract

`decision.json` is the single required artifact for workflow version `1.0.0`.
Unknown or missing fields are rejected so a producer cannot silently invent a
parallel schema.

The machine-readable shape is `decision.schema.json` in this directory. JSON
Schema covers structure and primitive types; clawock's Python validator adds the
cross-reference, provenance, opposing-evidence, action/order and arithmetic
invariants that JSON Schema cannot express.

## Top-level fields

- `schema_version`: integer `1`.
- `workflow`: exactly `{"id":"investment-decision","version":"1.0.0"}`.
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

See `assets/decision.example.json` for a complete hold decision.
