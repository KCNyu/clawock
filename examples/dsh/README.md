# examples/dsh — DeepSeek Harness workspace

Two things live here:

- `instruction.md` — the harness-agnostic instruction sheet (how a DSH agent
  drives the clawock investment-decision workflow with no plugin installed);
- `packages/clawock-dsh/` — the published npm package (skill + Decision Mind
  conversation-view tab).

## Why this directory looks like a monorepo root

The three `tsconfig.*.json` files here are not decoration: the official
`@deepseek-ai/dsh-typert-generator` (rc.6) discovers packages by reading
`tsconfig.host.json` / `tsconfig.client.json` from a workspace root and
**only accepts project references that resolve under `<root>/packages/`**
(`WorkspaceAnalyzer.loadRegistrations`). A package outside that shape is
silently skipped — the build succeeds and emits no reflection at all.

So this directory *is* the generator's workspace root, and the package sits at
`packages/clawock-dsh`. That is the whole reason for the layout; it lets
`npm run build` inside the package run the official generator against the real
source tree instead of copying `src/` into a fabricated temporary workspace
(the shape this repo shipped until #731).
