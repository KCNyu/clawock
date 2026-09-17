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

## Where the provider balance mounts (host extension points)

Account status is app chrome, not session content. Surveyed against the
installed runtime (`@deepseek-ai/dsh` 0.1.5-rc.2) and the npm history of the
client UI packages:

- `@deepseek-ai/dsh-client-ui-sidebar` declares `sidebar.footer.action`
  (`lib/types/client/contract/slots.d.ts`: "Optional actions beside Settings
  at the sidebar foot", `kind: 'list'`, `scope: 'root'`, owner props `{ wide }`)
  and renders it in the foot above `sidebar.settings`; the host's own Cordis
  panel registers there. Present in every release checked from 0.1.0-rc.6.
- `@deepseek-ai/dsh-client-ui-layout` declares `main` as a keyed root slot:
  "Central panel selected by sidebar entry id. The reserved `conversation` key
  hosts the Conversation; other keys receive no Session binding", selected via
  `ctx.layout.selectPanel(id | null)`; ui-workspace calls `selectPanel(null)`
  when a session is opened. Keyed `main` and `selectPanel` first ship in
  0.1.5-rc.1.

On hosts with `ctx.layout.selectPanel` the balance reading is a
`sidebar.footer.action` row that toggles a trigger-owned popover, copying the
host's own occupant of that seat (ui-cordis `CordisPanel`: `position:fixed`
anchored above the row, dismissed by an outside pointerdown or Escape). The
first version selected a keyed `main` panel instead; that replaced the whole
conversation column with a near-empty page on every click, which read as being
navigated away, so `main` is not used for a surface this small (community
plugins that do use it, such as `@syncended/dsh-automations`, host a full
editor workspace there). Without `selectPanel` (DSH < 0.1.5-rc.1) the plugin keeps the
`conversation.session.header.utilities` chip. Decision Mind is unaffected and
stays a `conversation.view` tab.
