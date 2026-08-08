# External agent invocation protocol

`clawock` is an agent-native decision-workflow plugin kit, not an agent, model
client or agent launcher. Its deterministic CLI/tool surface is called by an
existing external agent runtime. OpenClaw, Hermes,
Claude Code, Codex, LangGraph or another runtime keeps its conversation, memory,
skills, routing, ReAct and tool loop.

In short: **built for agents, not an agent**. This follows the same agent-native
CLI principle as Lark CLI at a different layer: Lark exposes business operations
to an agent, while clawock packages decision workflows and certifies, validates,
reconciles and evaluates their outputs. A generation is one audit unit, not the
whole product.

## Prepare

Initialize a workspace once, then ask clawock to prepare a run:

```bash
clawock init ./my-workspace
clawock run prepare --workspace ./my-workspace
```

`prepare` prints JSON and stores the same request beneath `.clawock/work/`. It
contains a run ID, generation ID, task, context documents, per-document SHA-256
hashes and a hash of the assembled context. The external agent reads that input
using its normal conversation, skills and tools; clawock performs no inference.

## Validate and publish

After the external agent writes one or more text artifacts inside the workspace,
it calls:

```bash
clawock run publish \
  --workspace ./my-workspace \
  --request ./my-workspace/.clawock/work/<run-id>/request.json \
  --artifact response.md=./response.md
```

The request is rejected if the configured task or certified context changed
after preparation. Artifact names must be canonical relative paths inside one
generation; empty artifacts, traversal and the reserved `manifest.json` name are
rejected. Rejections are structured JSON for the external agent's own repair
loop. Nothing is published while validation fails.

On success the configured store receives one write set, including a
`manifest.json` that pins every artifact and context hash to one generation ID.
The JSON receipt reports the final location and whether anything changed.

Artifact source paths are restricted to the workspace. The external runtime
retains responsibility for its own credentials and permissions; clawock neither
starts it nor receives its provider stderr.
