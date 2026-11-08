# Agent memory: components and ownership

This host runs one Markdown memory store with a generated public projection. The OpenClaw
assistant keeps `DREAMS.md` as a separately reviewed diary; its `MEMORY.md` is generated from
the store's `publish: public` topics. The coding agents (Claude Code, Codex, dsh and OpenCode)
read and write the same store outside every repository. `ops/host/shared-memory/wiring.json`
still marks the OpenClaw workspace as a separate context: `memctl doctor` fails when the private
store is injected there or sits inside it, and the projection is a one-way generated file rather
than a second store.

This page maps the memory components used by an agent to the surface that owns each one
on this host, and records the boundary between the private store and its public projection. The vocabulary
follows Anthropic's [components of agent memory](https://www.anthropic.com/research/components-of-agent-memory)
research note: transcripts, memory notes, representations, injected context and dreaming.
Weights, in-context learning and compaction are explicitly **not** memory here: they do
not survive a session as readable context, and nothing in this page changes them.

## Components and owners

| Component | What it is on this host | Owner and entry point |
|---|---|---|
| Transcripts | OpenClaw session transcripts; Claude Code's own session files; the shared store's change history (not a transcript) | OpenClaw runtime; Claude Code; `memctl log/show` for the shared store |
| Memory notes | One Markdown topic per concept, with a one-line description and a body | `~/.shared-memory`; write through the `shared-memory` skill / `memory.py add|update` |
| Write-time judgement | `metadata.salience`, `metadata.status` and `metadata.tags`, written with the note | `memory.py add|update --salience|--status|--tag` |
| Representations | Area indexes, a routing table, redirects, and `[[topic]]` links between notes | `MEMORY.md`, `indexes/MEMORY-*.md`, `indexes/routes.tsv`, `indexes/redirects.tsv` |
| Retrieval | Literal, rarity-weighted topic search; exact tag/status filters; the assistant's semantic `memory_search` with a read-only supplement over the same store | `memory.py search`; `ops/host/shared-memory/openclaw/index.ts` |
| Injected context | OpenClaw `MEMORY.md` (generated public projection) in direct chats; the shared index for Claude Code sessions in the home directory; payload/skill only in isolated cron and subagent runs | OpenClaw bootstrap; `publish.py`; Claude Code auto-memory + SessionStart hook; dispatch payload |
| Dreaming | 03:00 HKT candidates in private `memory/.dreams/`, 03:20 HKT reviewed promotion into public store topics and a regenerated `MEMORY.md`, plus the separately gated `DREAMS.md` append (legacy diary entries reviewed and pruned 2026-11-08) | `ops/host/patch_dreaming_review.py`, `ops/host/review_dreaming.py`, `ops/host/promote_dreaming.py`, `ops/host/review_dreams.py`, `ops/host/commit_dreaming.sh`, `ops/host/shared-memory/scripts/publish.py`; see [`dreaming-review.md`](../operations/dreaming-review.md) |
| Evaluation | Held-out search rows; a three-layer benefit run (no memory / index only / notes) | `ops/host/shared-memory-eval/` |

## Notes are written once, with their future use attached

A note is a prediction that a future session will need it. The write path therefore records
the judgement while the author still has the context; nothing infers it afterwards.

| Field | Values | Meaning |
|---|---|---|
| `scope` | `investment`, `engineering`, `persona`, `memory` (extensible) | Which injection view may use the note. Required, no default. |
| `salience` | `high`, `normal`, `low` | `high` should change a future session's behaviour and is a replay/consolidation candidate; `normal` is useful context; `low` is niche and stays searchable only. Default `normal`. |
| `status` | `verified`, `hypothesis`, `stale` | `verified` has its check/test/commit in the body; `hypothesis` is a candidate rule awaiting one; `stale` is superseded but kept for history. Default `hypothesis`. |
| `tags` | comma-separated, lowercase, at most 16 | Exact facets such as `dispatch`, `dreaming` or `deploy`, written by the author. Optional. |
| `publish` | `public`, `private` | `public` may reach the repository projection; `private` never does. Default `private`. |
| `agent` | lowercase identifier | Who wrote this revision, stamped from the invoking environment. |

Notes are written when an agent records a durable conclusion: at the end of a task or while
repairing a topic, not on every turn. Granularity is one topic per concept with dated
timeline sections; a topic that would exceed 16 KB keeps its conclusions and moves the full
text to `archive/`. That keeps recall cheap, but it also leaves in-session salience to the
author. There is no automatic per-turn extractor: the article's own results show that a
fixed "record this" rule can cost more than it saves, and an automatic writer would create a
second, unaudited store.

`memory.py add|update` requires `scope` and writes `salience`, `status`, `publish` and `agent`
(tags stay optional); an active topic missing any of them fails `memory.py doctor`. The 156 existing
topics predate that rule and are the P2 backfill debt; they are not retrofitted here. Every write
still lands in `memctl` history outside the store, so a bad tag or status can be restored.
`memctl verify` names a file changed without a matching write. Use `--tag` as an exact,
conjunctive filter:
`search --tag dispatch --tag review`. A tag also matches as ordinary text in both engines,
so it supplements literal and semantic retrieval rather than replacing either. The
OpenClaw supplement does not implement the CLI filters; it includes tags in its matchable
text and keeps returning results under the assistant's own `memory_search` ranking.

## Scoped injection

The write-time `scope` selects an injection view, not a separate store: direct chat gets
`scope in (investment, persona)` with `salience: high`; a worker gets `scope: engineering` with
`status: verified`; an investment cron gets `scope: investment`. `memory.py inject --audience`
implements the three policies, and a topic over its byte budget is skipped by name rather than
truncated. This is what keeps an engineering procedure out of a market brief and the investment
playbook out of a coding task; the repository's `MEMORY.md` remains one file and keeps its current
publish path.

## The learning loop

The incident/lesson format already existed; the new `status` field makes its state
machine visible and filterable:

1. **Failure** — write or update an `incident-*` topic with the evidence. Do not write a
   rule from the failure yet.
2. **Hypothesis** — put the proposed rule in the topic that owns the subject with
   `status: hypothesis` and say how it will be tested. If retrieval was the failure, add a
   question to the benefit evaluation; that row is the regression.
3. **Verification** — run the test or reproduce the fix. A rule without a check stays a
   hypothesis; a rejected theory becomes `stale` or is corrected, not deleted.
4. **Rule** — set `status: verified`, keep the evidence in the body, and fold the durable
   wording into the `lessons-*` topic that cites the incident.

`search --status hypothesis` lists open theories; `search --status verified` retrieves only
rules that carry evidence. The article's warning against a "record only failures" rule is
why failure topics and verified rules are separate objects: the failure is evidence, the
rule is what a future session should act on.

## One store, one public projection

| | Shared store | OpenClaw public projection |
|---|---|---|
| Path | `~/.shared-memory` | `~/.openclaw/workspace/MEMORY.md` |
| Written by | Claude Code, Codex, dsh and OpenCode through the shared-memory skill; the 03:20 dreaming gate for reviewed public topics | `ops/host/shared-memory/scripts/publish.py --write` only |
| Injected | Index only for home-directory Claude sessions; other agents read on demand | Direct chat |
| Readable by the other side | `memory.py search` and the read-only corpus supplement | Generated from `publish: public` topics only; a private topic never appears |

`wiring.json` and `memctl doctor` own the separation. The private store is not copied into the
workspace and the workspace is not a symlink target; the public file is generated from
`publish: public` topics, so a private note cannot reach it by being in the store. The plugin's
results are not recorded by OpenClaw's short-term recall. A note repeated verbatim in a direct
chat can still reach `DREAMS.md` through the assistant's own transcript.

Isolated cron and subagent runs do not receive `MEMORY.md`. That is deliberate: a rule such
a run must obey belongs in the job payload, the skill mode or a postflight gate. Durable
procedure belongs in `AGENTS.md` or the relevant skill; task-specific facts belong in the
dispatch brief. A dispatcher can use `search --salience high` to see which durable rules
exist, but the brief still has to carry the rules the run needs.

## Dreaming, representations and promotion

OpenClaw's dreaming pipeline is the only automatic memory writer. It reads transcripts,
proposes candidates into ignored `memory/.dreams/`, and the 03:20 gate promotes only
explicitly reviewed, hash-bound conclusions. An approved conclusion becomes a public store
topic; `publish.py --write` then regenerates `MEMORY.md`. There is no second dreaming job and
no second reviewer. High-salience notes written by coding agents are not candidates for that
gate.

The store is small, curated at write time, and every change is attributable and restorable
through `memctl`; the dreaming gate adds one reviewed public write path, not a general
background rewriter. The area indexes and `[[links]]` are the representation layer, and
`memory.py doctor` checks that links resolve and every active topic has one route. A generated
wiki is not warranted at this size; the article's 350,000-file corpus is a different regime.

## Evaluation

`ops/host/shared-memory-eval/` has two layers:

- `run_eval.py` / `queries.tsv` — held-out real queries scored against a change to literal
  search; rows are fixed, and a wrong row is fixed in its own commit.
- `benefit/run_benefit.py` — a fixed question set under three memory layers: no memory, the
  injected `MEMORY.md` only, and the notes reached by search. A hit needs the expected topic
  and the expected fact; a negative question that returns a topic is a false positive. The
  committed fixture is synthetic, so it runs in CI without private memory; a live run takes
  a private cases file and reports only aggregate numbers.

This is a memory-surface evaluation, not a model benchmark: it measures whether a change
exposes an answer-bearing note, which is the part a memory change can regress.

## What we do not adopt

| Suggestion | Decision | Why |
|---|---|---|
| Update model weights from experience | Not adopted | Out of scope for this harness; weights are not readable session memory. |
| Treat in-context learning or compaction as memory | Not adopted | Both are session-local; the article excludes them too. |
| Per-session automatic note extraction | Not adopted | The write-time judgement is the point; an auto-writer would create noise and a second audit path. |
| Auto-promote high-salience notes into `MEMORY.md` | Not adopted | The 03:20 review gate stays; salience is input to a reviewer, not an approval. |
| Inject the assistant's `MEMORY.md` into isolated runs | Not adopted | It would put public assistant prose into every coding task. |
| A generated wiki over the coding store | Not adopted now | The store is small; indexes and links are the representation. Revisit if cross-topic questions outgrow them. |
| A second transcript index | Not adopted | Native transcripts already exist; a new store would duplicate them and add a service. |
| Record only failures | Not adopted | The article measures a large loss of the memory benefit; failures are evidence, verified rules are the reusable part. |
| A vector service or graph database | Not adopted | The existing literal search plus tags covers the retrieval need; no new resident service. |

## Where to change what

| Change | Path |
|---|---|
| Topic schema, write validation, tag/status filters | `ops/host/shared-memory/scripts/memory.py` |
| Install the skill and its files | `ops/host/install_shared_memory.sh` |
| History, audit, wiring checks | `ops/host/shared-memory/scripts/memctl` |
| Read-only assistant supplement | `ops/host/shared-memory/openclaw/index.ts` |
| Retrieval and benefit evaluations | `ops/host/shared-memory-eval/` |
| Dreaming review gate | `ops/host/review_dreaming.py`, `ops/host/promote_dreaming.py`, `ops/host/review_dreams.py`, `ops/host/commit_dreaming.sh` |
| Public projection | `ops/host/shared-memory/scripts/publish.py`, `ops/host/shared-memory/publish-manifest.json` |
| Workspace/store separation | `ops/host/shared-memory/wiring.json` |
