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

Read the emitted request file (`.clawock/work/request.json`). It contains:

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
  "decision": {
    "action": "hold",
    "strategy": "core_position",
    "confidence": 0.4,
    "reasoning": "claim, citing evidence from the context",
    "opposing_case": "the genuine counterargument, not a strawman",
    "evidence": [{"source": "CONTEXT.md", "claim": "..."}]
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
  --request ./book/.clawock/work/request.json \
  --artifact decision=./book/.clawock/work/decision.json
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
