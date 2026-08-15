# CLAUDE.md — clawock decision runs

You are the model side of a clawock decision run. Claude Code owns
conversation, memory and tools; clawock owns the decision contract. Your job
is one file in, one file out.

## When to engage

When a clawock request file is present (`.clawock/work/<run_id>/request.json`,
the `request_file` path printed by `clawock run prepare`), or when the user
asks to run the investment-decision workflow.

## The loop

1. **Read the request.** `request.json` contains the certified `context`
   (with sha256 fingerprints), the `task`, and `workflow.parameters`
   (evidence and opposing-case minimums, confidence cap without a primary
   source).
2. **Write `decision.json`** next to the request. Minimal shape:

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


3. **Run `clawock run publish`** with the request and your artifact:

   ```bash
   clawock run publish \
     --request .clawock/work/<run_id>/request.json \
     --artifact decision.json=decision.json
   ```

4. **Report the receipt** — `status` and `run_id` — and stop. Do not edit the
   receipt, do not re-grade the decision, do not "improve" the artifact after
   publish; Python settles.

## Non-negotiables

- Every claim in `reasoning` cites an item in `evidence`.
- `opposing_case` must be a real counterargument; publish fails without one.
- Order amounts must reconcile; never invent prices, FX or sizes.
- Confidence above the workflow cap requires a primary source in `evidence`.
