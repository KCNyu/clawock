---
name: investment-decision
description: Use this skill when the user wants to run a clawock investment decision — a request file is present or the workspace has clawock installed.
---

# clawock investment-decision

You are the model side of a clawock decision run. DeepSeek Harness owns
conversation, memory and tools; clawock owns the decision contract. Your job
is one file in, one file out: read a request, write a decision, let Python
validate it. The model can never grade itself.

## Prerequisites

`clawock` must be installed (Python ≥ 3.11):

```bash
python -m pip install clawock
```

If a workspace is not initialized yet:

```bash
clawock workflow install investment-decision --workspace ./book
clawock init ./book --workflow investment-decision
```

## The loop

### 1. Prepare

```bash
clawock run prepare --workspace ./book
```

Read the emitted request file (the `request_file` path printed on stdout,
e.g. `.clawock/work/<run_id>/request.json`). It contains:

- `task` — the decision contract (evidence, opposing case, bounded action,
  reconciled amounts)
- `context.documents` — the certified context with per-file sha256
  fingerprints
- `workflow.parameters` — gates: `min_supporting_evidence`,
  `min_opposing_evidence`, `max_confidence_without_primary_source`

### 2. Decide

Write `decision.json` next to the request:

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
2. `opposing_case` is required; publish fails without it.
3. Proposed order amounts must reconcile — never invent prices, FX or sizes.
4. Confidence above `max_confidence_without_primary_source` needs a primary
   source in `evidence`.

### 3. Publish and report

```bash
clawock run publish \
  --request ./book/.clawock/work/<run_id>/request.json \
  --artifact decision.json=./book/decision.json
```

Report the receipt's `status` and `run_id` to the user. Never edit the
receipt, never re-grade the decision, never "improve" the artifact after
publish — Python settles.

## What clawock does on its side

- Certifies the context (fingerprints) before you read it
- Validates evidence, opposing case and money/FX reconciliation at publish
- Emits a generation receipt binding your decision to the certified context

## Learn more

The live proof runs on a real HK + US desk: <https://kcnyu.github.io/clawock/>
The same contract from other harnesses (OpenClaw skill, Claude Code
instruction, Codex AGENTS.md, pure CLI):
<https://github.com/KCNyu/clawock/tree/master/examples/harness-agnostic>
