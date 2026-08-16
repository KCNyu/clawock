---
name: investment-decision
description: Read the clawock request file, write decision.json, let clawock validate. Use when a clawock run request is present in .clawock/work/.
---

# clawock investment-decision

You are the model side of a clawock decision run. Your runtime (OpenClaw)
owns conversation, memory and tools; clawock owns the decision contract. Your
entire job is one file in, one file out.

## When to run

A `run prepare` has written a request file (the `request_file` path it
printed, e.g. `.clawock/work/<run_id>/request.json`). Open it first; it tells
you. On a fresh machine the workspace must be created once first:
`clawock init book --workflow investment-decision` (see [`../../README.md`](../../README.md)
— "From zero").

- `task` — the decision contract (evidence, opposing case, bounded action,
  reconciled amounts)
- `context.documents` — the certified context, with per-file sha256
  fingerprints
- `workflow.parameters` — gates like `min_supporting_evidence`,
  `min_opposing_evidence`, `max_confidence_without_primary_source`

## What to produce

Write `decision.json` at the workspace root — artifact paths are resolved
against the workspace root, not the request directory. The schema is the
package's `investment-decision` workflow; when in doubt, keep the fields
minimal and explicit:

```json
{
  "schema_version": 1,
  "workflow": {"id": "investment-decision", "version": "1.1.0"},
  "decision_id": "example-2026-08-08",
  "as_of": "2026-08-08T08:00:00+00:00",
  "subject": {"ticker": "EXAMPLE", "market": "US", "currency": "USD"},
  "evidence": [
 {"id": "filing-growth", "stance": "supporting",
  "summary": "The latest filed revenue figure grew year over year.",
  "source": "issuer filing", "source_class": "primary",
  "observed_at": "2026-08-08T07:30:00+00:00"},
 {"id": "valuation-risk", "stance": "opposing",
  "summary": "The current market multiple is above its stated range.",
  "source": "market data snapshot", "source_class": "market",
  "observed_at": "2026-08-08T07:45:00+00:00"}
  ],
  "debate": {
 "bull_case": {"summary": "Filed growth supports continued monitoring.",
"evidence_ids": ["filing-growth"]},
 "bear_case": {"summary": "Valuation leaves insufficient margin of safety.",
"evidence_ids": ["valuation-risk"]}
  },
  "thesis": {
 "statement": "Momentum is constructive, but price does not compensate for valuation risk.",
 "confidence": 0.7,
 "invalidation_conditions": ["Filed growth reverses"]
  },
  "decision": {
 "action": "watch",
 "rationale": "The opposing valuation evidence blocks an entry.",
 "evidence_ids": ["filing-growth", "valuation-risk"],
 "order": null
  }
}
```


Rules that are enforced by `clawock run publish`, not by this file:

1. `debate.bull_case` and `debate.bear_case` are both required and each cites
   evidence; the bear case must cite opposing-stance evidence — publish
   refuses without it. Python checks that linkage, not sincerity: make the
   bear case a genuine counterargument, never a strawman — that honesty is
   the model's contract.
2. Every `evidence` row needs a `stance` (`supporting` | `opposing` |
   `context`), a `source_class` (`primary` | `secondary` | `market` |
   `agent`) and an `observed_at` no later than `as_of`.
3. All `evidence_ids` references must exist (decision and both debate cases);
   conclusions in `thesis.statement` and `decision.rationale` should be
   backed by cited evidence.
4. If you propose an order, the currency amounts must reconcile to the cent;
   let the numbers come out of the context, never invent them.
5. Confidence above `max_confidence_without_primary_source` requires a cited
   primary source.

## After writing

Run the publish step (normally via `clawock run publish` in the workspace)
and report the receipt's `status` and `run_id` to the user. Never edit the
receipt. Never re-grade your own decision — Python settles.
