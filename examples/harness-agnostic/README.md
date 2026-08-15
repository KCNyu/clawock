# Harness-agnostic example

One decision workflow, four ways to run it. clawock's contract is files and a
CLI, so the harness around the model is yours to pick — and yours to change
without touching the workflow.

```
clawock run prepare ──► request.json ──► [your agent, any harness] ──► decision.json ──► clawock run publish ──► receipt
```

| harness | how the agent participates | file |
|---|---|---|
| None (pure CLI) | a literal stands in for the agent; proves the whole loop with no model | [`run.sh`](run.sh) |
| OpenClaw | a SKILL.md tells the agent to read `request.json` and write `decision.json` | [`openclaw.SKILL.md`](openclaw.SKILL.md) |
| Claude Code | a CLAUDE.md instruction block, loaded per workspace | [`claude-code.CLAUDE.md`](claude-code.CLAUDE.md) |
| DeepSeek Harness | agent calls the clawock CLI through its bash tool; the contract is unchanged | [`dsh.md`](dsh.md) |

The point is the middle column never changes: the harness only ever reads a
request, writes a decision, and lets Python validate. Swap OpenClaw for
DeepSeek Harness tomorrow and `decision.json` looks the same.

## Running the pure-CLI proof

```bash
bash examples/harness-agnostic/run.sh
```

Same isolation discipline as `minimal-run`: clean virtualenv, emptied
environment, no checkout, no Git, no model.
