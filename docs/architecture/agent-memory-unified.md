# Unified agent memory: one store, three views

Decision (kcn, 2026-11-08): **every agent reads and writes the same memory store**. OpenClaw keeps
its own injection and publishing, but it no longer owns a separate memory file. Dreaming runs once,
over the unified store.

This page replaces the two-store boundary recorded in
[`memory-components.md`](memory-components.md). That page stays as the record of what the boundary
was and why it existed; this one is where the system is going.

## Why

The two-store design failed in practice, not in theory:

- The shared store has 157 topics. Its change history (`memctl log`) ends **2026-10-19 02:23**,
  written by `claude-code`. No other agent ever appears in it.
- The newest note (`project-dsh-deployment.md`, 2026-11-06 23:37) has **no `memctl` commit**: it was
  written by editing the file directly, so it has no author and no restorable history.
- The write-time schema landed 2026-11-08 01:38. Since then `salience` / `status` / `tags` are
  **0/157** — nothing has been written through `memory.py` at all.
- Recall is split. `memory_search corpus=all` reads the shared store only in direct chats, and the
  assistant's own `MEMORY.md` never reaches a coding agent.

A store that is not written through its own tool is not a memory system; it is a folder. Unifying
without closing the write path would only produce a larger version of the same problem.

## Target architecture

**One store.** `~/.shared-memory`: one Markdown topic per concept, `memctl` history outside the
store, `memory.py` as the only writer.

**Three views over that store.** Unification is about the store, not about showing every agent
everything:

| View | Who reads it | Selection | Why |
|---|---|---|---|
| Inject | OpenClaw direct chat; every worker at task start | `salience: high`, `status: verified`, `publish` respected | A future session needs the rules, not 157 topics of prose |
| Publish | Public repository `MEMORY.md` | `publish: public` only | The repo is public; private operational notes must not follow the merge |
| Search | Any agent, on demand | everything, ranked | Recall stays complete; only the injected subset is curated |

The public file becomes a **generated projection**, not a hand-written document. If a line is not
marked `publish: public`, it cannot reach the repository.

**Dreaming, once.** 03:00 HKT candidates and the 03:20 HKT hash-bound review gate run against the
unified store. Candidates carry the source agent and the transcript they came from. The gate writes
topics and, in the same run, regenerates the publish projection. There is no second dreaming job and
no second reviewer.

## Write schema

| Field | Values | Notes |
|---|---|---|
| `type` | `project`, `decision`, `incident`, `feedback`, `reference`, `rule` | existing |
| `salience` | `high`, `normal`, `low` | written at write time, never inferred later |
| `status` | `verified`, `hypothesis`, `stale` | a rule without a check stays `hypothesis` |
| `tags` | comma-separated, lowercase, ≤16 | exact facets |
| `publish` | `public`, `private` | **default `private`**; only `public` reaches the repo |
| `agent` | `rick`, `claude-code`, `codex`, `dsh`, `opencode` | who wrote it |
| `updated` | `YYYY-MM-DD` | existing |

`memory.py add|update` writes all of them. A note missing `salience`, `status` or `publish` fails
`memory.py doctor`.

## Closing the write path

Nothing above matters while `cat > topic.md` works. Enforcement is part of the first phase:

1. `memory.py` stamps `agent` from the invoking environment and refuses a write without `salience`
   and `publish`.
2. A store-side check (inotify watcher or a periodic `memctl verify`) flags any topic whose content
   changed without a matching `memctl` commit, and names the file.
3. The repository's pre-commit hook keeps refusing coding-agent notes under `memory/*.md`; that rule
   does not relax because the store moved.

## Migration

Read-only dry run first; nothing is written until the report is reviewed.

1. Inventory the 157 topics and every `MEMORY.md` section; produce a merge plan with the topics that
   would be created, merged, or archived.
2. Conflict rule: investment and position rules take the `MEMORY.md` wording; operations, deployment
   and dispatch facts take the shared-store wording. Both keep their dates and their evidence.
3. Classify `publish`: everything currently in the public `MEMORY.md` starts `public`; every
   coding-agent note starts `private`. Nothing else is inferred.
4. Backfill `salience` / `status` / `tags` as **proposals**, reviewed before they land. A wrong
   `high` puts noise into every agent's injected context, so it is not a bulk guess.
5. Only after the store is uniform does `MEMORY.md` stop being hand-written and start being generated.

## Phases

| Phase | Change | Acceptance |
|---|---|---|
| P0 | Write path closed: schema required, direct edits detected | `memory.py doctor` fails on a missing field; a direct edit is reported by name |
| P1 | Migration dry run: inventory, conflicts, `publish` classification | report only, zero writes, reviewed by kcn |
| P2 | Backfill + merge; `MEMORY.md` sections become topics | every current `MEMORY.md` line resolves to one topic or is listed as dropped with a reason |
| P3 | Injection: direct chat and workers read the unified store | a worker's brief can cite `search --salience high` output; no private note reaches the repo |
| P4 | Single dreaming engine; publish projection generated | 03:20 gate writes topics and regenerates `MEMORY.md`; the repo diff contains only `publish: public` |

## Risks

- **Noise.** Every agent writing one store means the store grows with every task. Mitigation:
  `salience` at write time, and injection is `high`-only.
- **Context bloat.** Injecting the wrong subset buries the rules. Mitigation: the inject view has a
  byte budget, and a note over it is split or demoted, not truncated silently.
- **Private leakage.** A unified store plus a public repository is the one irreversible failure.
  Mitigation: `publish` defaults to `private`, the projection only reads `public`, and CI fails on a
  non-public line appearing in the repository.
- **Gate overload.** One 03:20 review over every agent's transcripts is more candidates than one
  reviewer can hold. Mitigation: cap per-source candidates per night and keep the review hash-bound,
  so an unreviewed night promotes nothing.

## What does not change

- Weights, in-context learning and compaction are still not memory.
- No per-turn automatic extractor: notes are written when an agent records a durable conclusion.
- No vector service or graph database; literal search plus facets plus the assistant's semantic
  search is the retrieval layer.
