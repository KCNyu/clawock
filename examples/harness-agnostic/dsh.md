# DeepSeek Harness (DSH)

clawock makes no assumption about the harness that hosts the model. This file
shows the same decision run driven from a DeepSeek Harness agent — the agent
calls the clawock CLI through its bash tool, and the contract is byte-for-byte
the same as the pure-CLI example.

## What the agent needs to know

Give the DSH agent a workspace instruction (e.g. in its system prompt or a
workspace context file) covering three steps:

1. **Prepare.** When asked to run an investment decision, execute:

   ```bash
   clawock run prepare --workspace /path/to/book
   ```

   and read the emitted `request_file` (printed on stdout; the path looks like
   `.clawock/work/<run_id>/request.json`). It contains the certified context
   (per-file sha256 fingerprints), the task, and the workflow gates
   (`min_supporting_evidence`, `min_opposing_evidence`,
   `max_confidence_without_primary_source`).

2. **Decide.** Write `decision.json` next to the request. Shape:

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


   Rules: every reasoning claim cites evidence; `opposing_case` is required
   and must be a real counterargument; proposed order amounts must reconcile;
   confidence above the cap needs a primary source.

3. **Publish and report.**

   ```bash
   clawock run publish \
     --request /path/to/book/.clawock/work/<run_id>/request.json \
     --artifact decision.json=/path/to/book/decision.json
   ```

   Report the receipt's `status` and `run_id` to the user. Do not edit the
   receipt; do not re-grade the decision. Python settles.

## Why this is the same workflow

The prepare → request → decision → publish loop is files and a CLI. DSH (or
any harness) only ever performs step 2 — reading a JSON file and writing one
— and invokes the CLI for steps 1 and 3. Everything clawock certifies
(evidence, opposition, reconciliation, generation receipt) is independent of
which harness performed step 2, which is the entire point of the
harness-agnostic contract.
