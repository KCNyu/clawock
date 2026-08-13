# Operations

Repository and host wiring lives here; none of it ships in the portable
`clawock` wheel. Each child directory has one owner so `ops/` cannot become a
renamed `scripts/data` bucket:

- `host/` — this machine's cron, scheduler inspection, session maintenance and
  installed launcher wiring.
- `publish/` — the only git/data-plane publication path.
- `ci/` — coverage, scheduled-workflow health and the generated command catalog.
- `growth/` — IndexNow, Nostr and project broadcast delivery.
- `pages/` — read the published generation and stage the public Pages allowlist.
- `system_check.py` — audit the KCNyu live workspace before publication.

Dependency direction is one-way: operations may call the installed `clawock`
product with declarative profiles. Product code never imports `ops/`; the
package lifecycle may request publication but `ops/publish/` owns its repository
implementation. Workflow, strategy, schedule and harness behavior belong in
the root wheel; KCNyu supplies configuration and state.

Do not add `ops/data`, generic helpers, market logic, or generated state here.
Choose an existing owner or create a named product domain instead.
