# Examples

Runnable proofs that `clawock` works as an installed package rather than as
this checkout. Each one is executed by CI, so an example that stops working
fails a required check instead of quietly rotting into documentation.

One decision workflow, one files-and-CLI contract — the harness is
swappable, so the examples are **organized by harness**: each folder is one
harness's way in, and the contract never changes between them.

## The folders

| harness | how the agent participates | file | copy to |
|---|---|---|---|
| CLI (no model) | a literal stands in for the agent; proves the whole loop with no model and no pinned workflow | [`cli/run.sh`](cli/run.sh) | run as-is |
| CLI (isolated install) | clean virtualenv installs the wheel and finishes one complete run — `init` → `run prepare` → `run publish` — with no checkout, no Git, no OpenClaw and an emptied environment; exercised by `release.yml` | [`cli/minimal-run/run.sh`](cli/minimal-run/run.sh) | run as-is |
| OpenClaw | a SKILL.md tells the agent to read `request.json` and write `decision.json` | [`openclaw/SKILL.md`](openclaw/SKILL.md) | `<workspace>/skills/investment-decision/SKILL.md` |
| Claude Code | a CLAUDE.md instruction block, auto-loaded per workspace | [`claude-code/CLAUDE.md`](claude-code/CLAUDE.md) | `<workspace>/CLAUDE.md` |
| Codex | an AGENTS.md instruction block, auto-loaded from the workspace root | [`codex/AGENTS.md`](codex/AGENTS.md) | `<workspace>/AGENTS.md` |
| DeepSeek Harness | agent calls the clawock CLI through its bash tool; the contract is unchanged | [`dsh/instruction.md`](dsh/instruction.md) | workspace instruction / system prompt |
| DSH plugin | npm-distributable skill package (and future Decision Studio UI) | [`dsh/packages/clawock-dsh/`](dsh/packages/clawock-dsh/) | `dsh plugin --profile web add clawock-dsh` + `cp` the skill into `~/.dsh/skills/` (see its [README](dsh/packages/clawock-dsh/README.md)) |
| Profiles | a second desk selects markets, workflows, resources, policy, presentation and delivery declaratively — the harness *profile* surface (e.g. the `intraday` desk workflow), distinct from the per-workspace decision contract above | [`profiles/`](profiles/) | reference |

The point of the middle column is that it never changes: the harness only
ever reads a request, writes a decision, and lets Python validate. Swap
OpenClaw for Codex, or Codex for DeepSeek Harness, tomorrow and
`decision.json` looks the same.

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
against the workspace root, not the request directory —
`decision.json=decision.json` means `<workspace>/decision.json`; the shape is
in any harness file below), and

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

## Running the pure-CLI proofs

```bash
bash examples/cli/run.sh
bash examples/cli/minimal-run/run.sh        # or: examples/cli/minimal-run/run.sh dist/*.whl
```

Same isolation discipline for both: clean virtualenv, emptied environment,
no checkout, no Git, no model. The `cli/run.sh` script intentionally
publishes a stand-in `answer` artifact without a pinned workflow — it proves
the loop, not the contract; the five harness files above prove the contract.

## Why they are files and not workflow steps

The claim these support is that someone else can use the package. A check
that only exists inside `release.yml` cannot be run by that someone, so it
proves the package works for GitHub and nothing more. `release.yml` calls
`examples/cli/minimal-run/run.sh`; there is one copy, and it is the copy a
reader can execute.