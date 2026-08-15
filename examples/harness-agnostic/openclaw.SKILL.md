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
you:

- `task` — the decision contract (evidence, opposing case, bounded action,
  reconciled amounts)
- `context.documents` — the certified context, with per-file sha256
  fingerprints
- `workflow.parameters` — gates like `min_supporting_evidence`,
  `min_opposing_evidence`, `max_confidence_without_primary_source`

## What to produce

Write `decision.json` in the same directory. The schema is the package's
`investment-decision` workflow; when in doubt, keep the fields minimal and
explicit:

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


Rules that are not negotiable:

1. Every claim in `reasoning` cites an item in `evidence`.
2. `opposing_case` is required and must be a genuine counterargument, not a
   strawman — the contract refuses to publish without it.
3. If you propose an order, the currency amounts must reconcile; let the
   numbers come out of the context, never invent them.
4. Confidence above `max_confidence_without_primary_source` requires a
   primary source in `evidence`.

## After writing

Run the publish step (normally via `clawock run publish` in the workspace)
and report the receipt's `status` and `run_id` to the user. Never edit the
receipt. Never re-grade your own decision — Python settles.
