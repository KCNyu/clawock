---
name: investment-decision
description: Read the clawock request file, write decision.json, let clawock validate. Use when a clawock run request is present in .clawock/work/.
---

# clawock investment-decision

You are the model side of a clawock decision run. Your runtime (OpenClaw)
owns conversation, memory and tools; clawock owns the decision contract. Your
entire job is one file in, one file out.

## When to run

A `run prepare` has written a request file, normally at
`.clawock/work/request.json`. Open it first; it tells you:

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
  "decision": {
    "action": "hold",
    "symbol": null,
    "strategy": "core_position",
    "confidence": 0.4,
    "reasoning": "No actionable setup this session.",
    "opposing_case": "Holding is itself a stance; the case against it is ...",
    "evidence": [
      {"source": "CONTEXT.md", "claim": "..."}
    ]
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
