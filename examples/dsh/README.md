# examples/dsh — DeepSeek Harness workspace

Two things live here:

- `instruction.md` — the harness-agnostic instruction sheet (how a DSH agent
  drives the clawock investment-decision workflow with no plugin installed);
- `packages/clawock-dsh/` — the published npm package (skill + Decision Mind
  global sidebar panel).

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

## Where Decision Mind mounts (host extension points)

Decision Mind reads workspace-wide data, so it should not live inside a
session. Surveyed against the installed runtime (`@deepseek-ai/dsh`
0.1.5-rc.2) and the npm history of the client UI packages:

- `@deepseek-ai/dsh-client-ui-sidebar` declares `sidebar.footer.action`
  (`lib/types/client/contract/slots.d.ts`: "Optional actions beside Settings
  at the sidebar foot", `kind: 'list'`, `scope: 'root'`, owner props `{ wide }`)
  and renders it in the foot above `sidebar.settings`. The host's own Cordis
  panel (`dsh-client-ui-cordis`) registers there. Present since at least
  0.1.2-rc.1.
- `@deepseek-ai/dsh-client-ui-layout` declares `main` as a keyed root slot:
  "Central panel selected by sidebar entry id. The reserved `conversation` key
  hosts the Conversation; other keys receive no Session binding", selected via
  `ctx.layout.selectPanel(id | null)`. ui-workspace calls `selectPanel(null)`
  whenever a session is opened. Both `main`-as-keyed and `selectPanel` first
  ship in 0.1.5-rc.1 (absent in 0.1.5-alpha.1 and earlier).
- `sidebar.panellist` (same release) is the alternative: rows under New
  Session at the top of the column, not the foot.

The plugin therefore registers a `sidebar.footer.action` button that toggles a
keyed `main` panel (`clawock-decision-mind`). When `ctx.layout.selectPanel` is
missing (DSH < 0.1.5-rc.1) it registers the old `conversation.view` tab
instead. The panel sits outside `ConversationRoot`, so
`--dsh-composer-height` / `--dsh-chat-content-width` are undefined there; the
panel wrapper pins the composer height to 0 and the column keeps its 748px
fallback.
