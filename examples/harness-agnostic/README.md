# Harness-agnostic example

One decision workflow, five ways to run it. clawock's contract is files and a
CLI, so the harness around the model is yours to pick — and yours to change
without touching the workflow.

```
clawock run prepare ──► request.json ──► [your agent, any harness] ──► decision.json ──► clawock run publish ──► receipt
```

| harness | how the agent participates | file |
|---|---|---|
| None (pure CLI) | a literal stands in for the agent; proves the whole loop with no model and no pinned workflow | [`run.sh`](run.sh) |
| OpenClaw | a SKILL.md tells the agent to read `request.json` and write `decision.json` | [`openclaw.SKILL.md`](openclaw.SKILL.md) |
| Claude Code | a CLAUDE.md instruction block, loaded per workspace | [`claude-code.CLAUDE.md`](claude-code.CLAUDE.md) |
| Codex | an AGENTS.md instruction block, auto-loaded from the workspace root | [`codex.AGENTS.md`](codex.AGENTS.md) |
| DeepSeek Harness | agent calls the clawock CLI through its bash tool; the contract is unchanged | [`dsh.md`](dsh.md) |

The point is the middle column never changes: the harness only ever reads a
request, writes a decision, and lets Python validate. Swap OpenClaw for
Codex, or Codex for DeepSeek Harness, tomorrow and `decision.json` looks the
same.

## From zero to a published decision

Every harness file below assumes a prepared workspace already exists. One
time per workspace, create it with the workflow pinned — that flag is what
turns `decision.json` into the enforced contract (without it, publish checks
nothing workflow-specific):

```bash
python -m pip install clawock
clawock init book --workflow investment-decision
```

Then each run is three steps: `clawock run prepare --workspace book`, write
`decision.json` at the **workspace root** (artifact paths are resolved
against the workspace root, not the request directory — `decision.json=decision.json`
means `<workspace>/decision.json`; the shape is in any harness file below),
and

```bash
clawock run publish \
  --workspace book \
  --request book/.clawock/work/<run_id>/request.json \
  --artifact decision.json=book/decision.json
```

`run_id` is printed by `run prepare` (the `request_file` path). The default
gates are `min_supporting_evidence: 1`, `min_opposing_evidence: 1`,
`max_confidence_without_primary_source: 0.65`; introspect the exact artifact
shape any time with `clawock workflow schema investment-decision decision.json`.

**If publish rejects**, the receipt lists `validation_issues` with `code` and
`message` — repair only the named issue and retry against the **same**
prepared request; re-run `prepare` only if the context or workflow
certificate changed. The only artifact allowed when the workflow is pinned is
`decision.json`.

The full contract — including money/FX reconciliation and reported failure
repair — is described in the package's installed skill
(`clawock workflow install investment-decision --workspace book`, then read
`book/.agents/skills/investment-decision/references/decision-contract.md`)
and enforced by `clawock run publish` itself.

## Running the pure-CLI proof

```bash
bash examples/harness-agnostic/run.sh
```

Same isolation discipline as `minimal-run`: clean virtualenv, emptied
environment, no checkout, no Git, no model. The pure-CLI script intentionally
publishes a stand-in `answer` artifact without a pinned workflow — it proves
the loop, not the contract; the five harness files above prove the contract.
