# Unified agent memory: one store, three views

Decision (kcn, 2026-11-08): **every agent reads and writes the same memory store**. OpenClaw keeps
its own injection and publishing, but it no longer owns a separate memory file. Dreaming runs once,
over the unified store.

This page replaces the two-store boundary recorded in
[`memory-components.md`](memory-components.md). That page stays as the record of what the boundary
was and why it existed; this one is where the system is going.

## Why

The two-store design failed in practice, not in theory:

- The shared store has **156 active topics** (157 `.md` files counting the index) and 149 archived
  topics. `memctl log` has five entries; the latest is **2026-11-06 23:37 by `dsh`**, a `memory.py
  update` of `project-dsh-deployment.md`. The earlier claim that this note had no history does not
  survive verification: the direct-edit risk is real, but this file is not evidence of it.
- The write-time schema landed 2026-11-08 01:38. All 156 active topics still have
  `salience` / `status` / `tags` empty, and `publish` / `agent` did not exist. The latest write did
  go through `memory.py`; it still wrote none of the new fields because `update` had no required
  schema. That is the gap P0 closes.
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
| Inject: direct | OpenClaw direct chat | `scope in (investment, persona)` **and** `salience: high` | The chat needs the rule that changes an answer, not engineering detail |
| Inject: worker | Coding workers at task start | `scope: engineering` **and** `status: verified` | A worker needs checked engineering rules, never the investment playbook |
| Inject: investment cron | Investment briefs/reports | `scope: investment` | A cron gets the investment domain only, never engineering procedure |
| Publish | Public repository `MEMORY.md` | `publish: public` only | The repo is public; private operational notes must not follow the merge |
| Search | Any agent, on demand | everything, ranked | Recall stays complete; only the injected subset is curated |

The public file becomes a **generated projection**, not a hand-written document. If a line is not
marked `publish: public`, it cannot reach the repository. The projection is still one `MEMORY.md`:
scope filters what is selected, it does not create one file per domain.

## Scope is the split between investment and engineering

One injected document was mixing two different jobs. `MEMORY.md` contains investment rules
(positions, data definitions, SPCH) next to coding/ops rules (cron, models, delivery, release), so a
direct chat and a coding worker receive each other's playbook. Scope makes the split explicit at the
topic, not at the file:

| Scope | Holds | Primary consumer |
|---|---|---|
| `investment` | Positions, data definitions, strategy, market rules | Direct chat (high only), investment crons |
| `engineering` | Repository, deployment, dispatch, CI, tooling | Workers (verified only) |
| `persona` | Voice, boundaries, how the assistant talks | Direct chat |
| `memory` | How the memory system itself works | Maintainers, on demand |

The set is extensible: `memory.py` accepts any lowercase scope and `doctor` warns on one it does not
know. The three injection policies above are the contract; `memory.py inject --audience direct|worker|investment-cron`
is their one implementation, and a topic over the byte budget is skipped by name, not truncated.

**Dreaming, once.** 03:00 HKT candidates and the 03:20 HKT hash-bound review gate run against the
unified store. Candidates carry the source agent and the transcript they came from. The gate writes
topics and, in the same run, regenerates the publish projection. There is no second dreaming job and
no second reviewer.

## Write schema

| Field | Values | Notes |
|---|---|---|
| `type` | `user`, `feedback`, `project`, `reference` | existing; `decision-`/`incident-`/`lessons-` prefixes map to `project` |
| `scope` | `investment`, `engineering`, `persona`, `memory` (extensible) | **required, no default**; selects the injection view |
| `salience` | `high`, `normal`, `low` | written at write time, never inferred later |
| `status` | `verified`, `hypothesis`, `stale` | a rule without a check stays `hypothesis` |
| `tags` | comma-separated, lowercase, ≤16 | exact facets |
| `publish` | `public`, `private` | **default `private`**; only `public` reaches the repo |
| `agent` | `claude-code`, `codex`, `opencode`, `dsh`, `rick`, `unattributed` (any lowercase identifier is accepted) | who wrote it |
| `updated` | `YYYY-MM-DD` | existing |

`memory.py add|update` writes all five required fields on every call: `scope` has no default (the
author must choose investment, engineering, persona or memory), `salience` defaults to `normal`,
`status` to `hypothesis`, `publish` to `private`, and `agent` is stamped from the invoking environment
(`MEMCTL_AGENT` overrides it). An active note missing any of them fails `memory.py doctor`; archived
topics are exempt because they are history, not a write target.

## Closing the write path

Nothing above matters while `cat > topic.md` works. Enforcement is part of the first phase:

1. `memory.py` stamps `agent` from the invoking environment and writes `scope` / `salience` /
   `status` / `publish` on every `add` and `update`, including a repair of an old topic.
2. `memctl verify` names every file changed without a matching write: an uncommitted edit, a
   commit whose files carry no `memory.py` receipt hash, or history/ledger tampering (a ref reset,
   a rewritten ledger, a commit tree that disagrees with the recorded tree). It does not trust the
   `agent` field, so a hand-written topic committed by a named `memctl snapshot` is still reported.
   It exits non-zero when it finds one.
3. `memory.py doctor` fails an active topic missing any of the five fields. The 156 legacy topics are
   expected to fail until P2 backfills them; that failure is the migration debt, not a reason to
   weaken the schema.
4. The repository's pre-commit hook keeps refusing coding-agent notes under `memory/*.md`; that rule
   does not relax because the store moved.

## Migration

Read-only dry run first; nothing is written until the report is reviewed.

1. Inventory the 156 active topics (plus the index and archive) and every `MEMORY.md` section;
   produce a merge plan with the topics that would be created, merged, or archived.
2. Classify every `MEMORY.md` section by scope (`investment`, `engineering`, `persona`, `memory`) and
   name the sections that mix domains in one paragraph. The dry run is read-only and does not move,
   delete or rewrite any site input (`MEMORY.md`, `DREAMS.md`, `memory/*.md`, `assets/data/`).
3. Conflict rule: investment and position rules take the `MEMORY.md` wording; operations, deployment
   and dispatch facts take the shared-store wording. Both keep their dates and their evidence.
4. Classify `publish`: everything currently in the public `MEMORY.md` starts `public`; every
   coding-agent note starts `private`. Nothing else is inferred.
5. Backfill `scope` / `salience` / `status` / `tags` as **proposals**, reviewed before they land. A
   wrong `high` puts noise into every agent's injected context, so it is not a bulk guess.
6. Only after the store is uniform does `MEMORY.md` stop being hand-written and start being generated.
   No path moves are part of that step; the site keeps reading the same files.

## Recall counting and retirement

Every reader appends a private event (`~/.local/state/shared-memory/recall.jsonl`, 0600) with
the topic slugs, source and time: the OpenClaw supplement's `search` and `get`, `memory.py
search`, `memory.py read`, and the cron/brief injection view. Queries, snippets and session
keys are not stored. The supplement still answers if the append fails.

`retire.py` runs on its own 03:47 timer and writes a private candidate report; it never edits
the store. The only enabled rules are stale age, an optional zero-recall rule (30 days, off
until the counter covers at least 30 days), `superseded_by`, and exact duplicate bodies.
`verified`, `publish: public`, `scope: persona|memory`, linked/cited topics and topics
missing a write-time field are excluded from candidates. `forget` stays manual: `--confirm`,
a pre-delete snapshot, and a printed `memctl restore` command; `archive` is the default
recommendation.

## Phases

| Phase | Change | Acceptance |
|---|---|---|
| P0 | Write path closed: schema required, direct edits detected | `memory.py doctor` fails on a missing field; `memctl verify` reports a direct edit by name |
| P1 | Migration dry run: inventory, conflicts, per-section `scope` and `publish` classification | report only, zero writes, no file moves, reviewed by kcn |
| P2 | Backfill + merge; `MEMORY.md` sections become topics | every current `MEMORY.md` line resolves to one topic or is listed as dropped with a reason |
| P3 | Injection: direct chat, workers and investment crons read their scoped view | `inject --audience` matches the policy; no investment note reaches a worker brief and no engineering note reaches a report |
| P4 | Single dreaming engine; publish projection generated | 03:20 gate writes topics and regenerates `MEMORY.md`; the repo diff contains only `publish: public` |

## Risks

- **Noise.** Every agent writing one store means the store grows with every task. Mitigation:
  `salience` at write time, and each injection view has its own scope and status filter.
- **Cross-domain leakage.** A missing `scope` puts an investment rule into a worker brief or an
  engineering procedure into a report. Mitigation: `scope` is required with no default, and the three
  injection filters are exclusive.
- **Context bloat.** Injecting the wrong subset buries the rules. Mitigation: the inject view has a
  byte budget, and a note over it is split or demoted, not truncated silently.
- **Private leakage.** A unified store plus a public repository is the one irreversible failure.
  Mitigation: `publish` defaults to `private` and the projection only reads `public`. The generated
  `MEMORY.md` and its hash manifest are checked by `tests/test_memory_publish.py`; a hand-added or
  non-public section fails CI.
- **Gate overload.** One 03:20 review over every agent's transcripts is more candidates than one
  reviewer can hold. Mitigation: cap per-source candidates per night and keep the review hash-bound,
  so an unreviewed night promotes nothing.

## What does not change

- Weights, in-context learning and compaction are still not memory.
- No per-turn automatic extractor: notes are written when an agent records a durable conclusion.
- No vector service or graph database; literal search plus facets plus the assistant's semantic
  search is the retrieval layer.
- No split `MEMORY.md` per domain and no moved site inputs. The repository's `MEMORY.md`, `DREAMS.md`,
  `memory/*.md` and `assets/data/` keep their current paths and readers; scope changes selection, not
  the publication path.
