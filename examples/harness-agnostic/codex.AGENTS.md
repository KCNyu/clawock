# AGENTS.md — clawock decision runs (Codex)

You are the model side of a clawock decision run. Codex owns conversation,
memory and tools; clawock owns the decision contract. Your job is one file
in, one file out. Codex reads this file automatically from the workspace
root.

## When to engage

When a clawock request file is present (normally `.clawock/work/request.json`
produced by `clawock run prepare`), or when the user asks to run the
investment-decision workflow.

## The loop

1. **Read the request.** `request.json` contains the certified `context`
   (with per-file sha256 fingerprints), the `task`, and `workflow.parameters`
   (evidence and opposing-case minimums, confidence cap without a primary
   source).
2. **Write `decision.json`** next to the request. Minimal shape:

   ```json
   {
     "decision": {
       "action": "hold",
       "strategy": "core_position",
       "confidence": 0.4,
       "reasoning": "claim with cited evidence",
       "opposing_case": "genuine counterargument",
       "evidence": [{"source": "...", "claim": "..."}]
     }
   }
   ```

3. **Run `clawock run publish`** with the request and your artifact:

   ```bash
   clawock run publish \
     --request .clawock/work/request.json \
     --artifact decision=.clawock/work/decision.json
   ```

4. **Report the receipt** — `status` and `run_id` — and stop. Do not edit the
   receipt, do not re-grade the decision, do not "improve" the artifact after
   publish; Python settles.

## Non-negotiables

- Every claim in `reasoning` cites an item in `evidence`.
- `opposing_case` must be a real counterargument; publish fails without one.
- Order amounts must reconcile; never invent prices, FX or sizes.
- Confidence above the workflow cap requires a primary source in `evidence`.

## Why this file exists

clawock's contract is files and a CLI, so the harness is swappable. This file
is the Codex side of the same contract shown for a pure CLI, an OpenClaw
skill, a Claude Code instruction and a DeepSeek Harness agent in
`examples/harness-agnostic/` — swap harnesses, `decision.json` looks the same.
