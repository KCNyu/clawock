# Operations

Repository and host wiring lives here; none of it ships in the portable
`clawock` wheel. Each child directory has one owner so `ops/` cannot become a
renamed `scripts/data` bucket:

- `host/` — this machine's cron, scheduler inspection, session maintenance and
  installed launcher wiring.
- `publish/` — the only git/data-plane publication path.
- `ci/` — coverage and scheduled-workflow health used by GitHub Actions.
- `growth/` — IndexNow, Nostr and project broadcast delivery.
- `pages/` — read the published generation and stage the public Pages allowlist.
- `system_check.py` — audit the KCNyu live workspace before publication.

Dependency direction is one-way: operations may call the installed `clawock`
product and `clawock-kcnyu` instance adapter. Product code never imports
`ops/`; instance code delegates publication to `ops/publish/` but does not own
its implementation. Portable workflow semantics belong in `src/clawock/`, and
KCNyu schedule/harness behavior belongs in `instances/kcnyu/`.

Do not add `ops/data`, generic helpers, market logic, or generated state here.
Choose an existing owner or create a named product/instance domain instead.
