# Shared memory for coding agents

One Markdown memory that Claude Code, Codex, dsh and OpenCode all read and write on one
machine, with a history of who changed what and a self-check that every agent is still wired
to it. This directory is the whole mechanism; it ships no memory. A fresh install starts with
an empty store and grows the user's own.

| File | Role |
|---|---|
| `SKILL.md`, `references/maintenance.md` | the skill each agent loads: when to recall, what to record, how to maintain |
| `scripts/memory.py` | format owner: read, search, add/update/archive, index routing, `doctor` (stdlib only) |
| `scripts/memctl` | history, audit and wiring checks around the store (stdlib only; PyYAML optional for the dsh profile check) |
| `scripts/recall.py` | private recall counter (`recall.jsonl`, `recall-stats.json`) shared by `memory.py` and the OpenClaw supplement |
| `scripts/retire.py` | nightly nomination report: stale, unused, superseded and duplicate topics; never edits the store |
| `scripts/replay.py` | nightly consolidation candidates (duplicates, contradictions, unused high-salience) under `memory/.replay/`; never edits the store |
| `hooks/claude-hook.sh` | Claude Code `PostToolUse` / `SessionStart` hook |
| `wiring.json` | where each agent looks, and which working directories share the store |
| `systemd/` | four timers: a 10-minute snapshot, a daily bundle + deep self-check, the 03:47 retirement nomination report, and the 04:02 replay candidate report |
| `openclaw/` | read-only corpus plugin that lets an OpenClaw assistant search the store (see below) |

## Layout of a store

```
~/.shared-memory -> ~/.claude/projects/<home project>/memory   (Claude Code's own auto-memory)
  MEMORY.md                 index: long-term conventions + routes to area indexes (≤ 8 KB)
  indexes/MEMORY-*.md       area indexes, one line per topic
  indexes/routes.tsv        <glob><TAB><index>: where `memory.py add` routes a new topic
  indexes/redirects.tsv     old<TAB>new names after a rename or merge
  feedback-*.md, decision-*.md, project-*.md, incident-*.md, reference-*.md, lessons-*.md
  archive/                  retired topics, search-only
```

Each topic is one file with Claude Code's auto-memory frontmatter (`name`, `description`,
`metadata.type`), so Claude keeps loading and writing it natively; the other agents read it
through the skill. A write also carries `metadata.scope`
(`investment|engineering|persona|memory`, extensible), `metadata.salience`
(`high|normal|low`), `metadata.status` (`verified|hypothesis|stale`), `metadata.publish`
(`public|private`) and `metadata.agent` (who wrote this revision), plus optional
comma-separated `metadata.tags`. `memory.py add|update` requires `scope` (no default) and fills
the other four (defaults: `normal`, `hypothesis`, `private`, the invoking agent);
`memory.py doctor` fails an active topic that is missing any of them. Nothing is injected
beyond the scoped view, and there is no vector store: recall is "open the one relevant topic".

## Where the store applies: working directory, not agent name

| Started in | Who | Memory |
|---|---|---|
| the home directory (`contexts.coding`) | the four coding agents, interactive or dispatched | this shared store |
| an OpenClaw workspace (`contexts.openclaw`) | the OpenClaw assistant | the workspace's own `MEMORY.md`, which OpenClaw's dreaming may publish |

The two are never merged. Claude Code's auto-memory is project-scoped, so a Claude session in
the workspace already resolves to a different directory; the SessionStart hook never injects
the shared index under `no_inject_under`, and `doctor` fails if the store sits inside the
workspace or anything there links into it. 

## Install

```bash
ops/host/install_shared_memory.sh            # skill → ~/.agents/skills/shared-memory
ops/host/install_shared_memory.sh --units    # + systemd timers (root)
~/.agents/skills/shared-memory/scripts/memctl init      # history for an existing store
~/.agents/skills/shared-memory/scripts/memctl doctor --deep
```

Then link each agent's user-level entry points to one guidance file and the skill
(`wiring.json` lists the paths `doctor` expects), and register the hook in
`~/.claude/settings.json`:

```json
{"hooks": {
  "PostToolUse": [{"matcher": "Write|Edit|MultiEdit|NotebookEdit|Bash",
                   "hooks": [{"type": "command", "command": "~/.agents/skills/shared-memory/hooks/claude-hook.sh post"}]}],
  "SessionStart": [{"hooks": [{"type": "command", "command": "~/.agents/skills/shared-memory/hooks/claude-hook.sh start"}]}]}}
```

## History and audit

`memctl` keeps a git history of the store in a separate git directory
(`~/.local/state/shared-memory/history.git`, no remote) and an append-only `ledger.jsonl`:

- `memory.py add|update|archive|normalize` hands each finished write to `memctl snapshot`,
  which commits it with the calling agent as author (from `MEMCTL_AGENT`,
  `AGENT_DISPATCH_AGENT`, `CLAUDECODE`, `AI_AGENT` or the nearest agent process) and the
  dispatch task id as a trailer. `run-agent.sh` exports `MEMCTL_AGENT`/`AGENT_DISPATCH_AGENT`
  from the task's agent, so a dispatched task's legitimate write is attributed, not
  `unattributed`.
- Claude Code's own file edits are committed by the PostToolUse hook with the session id.
- Anything else is committed by the snapshot timer as `unattributed`.
- A file whose new lines look like a credential is never committed and is reported by
  `doctor`; a topic that disappears without moving is flagged `md_deleted`.

`memctl log <topic>`, `memctl show <commit>`, `memctl restore <topic> --at <commit>`;
`memctl verify` names each file changed without a matching `memory.py` receipt (an uncommitted
edit, or a topic committed by `memctl snapshot` even under a named agent), plus history/ledger
tampering (a ref reset, a rewritten ledger, a tree that disagrees with the recorded tree), and
exits non-zero when it finds one. An old `unattributed` entry can be corrected without editing
or deleting the ledger: `memctl reattribute --agent <id> [<topic>...]` appends a correction and
`verify` then treats the earlier entry as attributed; a hand-written file still reports
`UNRECEIPTED`. The daily timer writes a git bundle (14 kept).

A copied store must be paired with a copied state directory: `memctl` refuses to write when
`SHARED_MEMORY_DIR` is not the default and `SHARED_MEMORY_STATE` is unset or still the live
state, and when the history's configured worktree is not that store.

## Self-check

`memctl doctor` checks the static wiring (each agent's instruction file and skill link, the
store links, Codex's native memories off, the Claude hook), every context in `wiring.json`
(which index a Claude session there gets; for a separate-memory context, that the shared index
is not injected and the store is not inside it), the store's own `memory.py doctor`, history,
backups, timers and audit flags. The store check fails while an active topic lacks one of the
four write-time fields; archived topics are exempt.

`--deep` adds discovery through each agent's real entry point, without calling a model, from
every shared context and in two environments — the interactive one and the bare `HOME` + `PATH`
a dispatched task starts with: `codex debug prompt-input`, `opencode api skill.list` /
`debug paths`, dsh's own `discoverBaselineInstructionFiles` and default skill roots, and for
each configured dsh profile (`headless`, `web`) that `dsh --profile P --dump-config` mounts
instruction loading and filesystem skills without moving their roots.

## Vector staging view (`memctl index-view`)

OpenClaw's `memory_search` indexes only its own workspace plus configured `extraPaths`. This
version of OpenClaw skips symlinks at the extraPath root and inside its walker, so the view must be
a **real copy**, not a link farm:

```bash
memctl index-view                      # ~/.openclaw/state/shared-memory-vector
memctl index-view --check              # name every file whose hash moved
memctl index-view --limit 20           # measurement subset
memctl index-view --print-config       # print the extraPaths snippet; does not edit config
```

The view contains active top-level topics only (no store index, no `archive/`), copies them as real
files with a manifest of SHA256 hashes, and swaps the directory atomically. It never writes inside the
store or the repository. Pointing `agents.defaults.memorySearch.extraPaths` at it is a separate,
reviewed deployment step; install the plugin and verify its session middleware first, because
the built-in index does not pass through `sessionAllowed` on its own. The command does not change
OpenClaw config or restart the gateway.

## The OpenClaw corpus plugin (`openclaw/`)

`openclaw/index.ts` registers a memory corpus supplement through OpenClaw's plugin API
(`registerMemoryCorpusSupplement`), loaded from outside OpenClaw's own install so an upgrade
leaves it in place. The assistant's `memory_search` with `corpus=all` and `memory_get` on a
`shared-memory/<topic>.md` path then return the store's topics, read-only (the only write
is the private recall counter below):

- it only reads files under the configured root, `.md` only, no symlink escapes;
- it answers every configured session — direct, group, channel, cron and subagent — so a
  scheduled brief or subagent can check the owner's recorded preferences instead of guessing.
  Only a keyless call gets nothing, because the plugin cannot tell whether it is configured;
- the built-in index is held to the same predicate. The plugin registers an
  `agentToolResultMiddleware` for the `openclaw` runtime (`contracts.agentToolResultMiddleware`),
  which strips `shared-memory-vector/…` and `shared-memory/…` hits from the merged
  `memory_search` result and blocks `memory_get` on those paths for a keyless call. This is
  what makes `agents.defaults.memorySearch.extraPaths` safe; the reusable predicate is
  exported as `sessionAllowed` + `filterSharedMemoryRecall` for any future vector merge layer.
  `isolateBuiltinIndex: false` disables the gate, and `vectorRoot` overrides the staging
  directory (default `~/.openclaw/state/shared-memory-vector`);
- results are redacted with the same credential patterns `memctl` uses;
- any read error returns no results instead of failing the search;
- OpenClaw's short-term recall (the source of dreaming's promotions into `MEMORY.md`)
  records only its own memory index hits, not supplement results, so search results are not
  promoted into the assistant's public memory.
- What the plugin cannot stop: dreaming also reads the assistant's own chat transcripts, so a
  note the assistant *repeats* in a direct chat can reach `DREAMS.md` / `MEMORY.md`. The
  assistant is told to answer with conclusions, not quotes, and `memctl doctor` warns
  (`context.openclaw.no_shared_text`) when a line of the workspace's `public_files` repeats a
  line of the shared store.

Recall is not publication. `MEMORY.md`, `DREAMS.md` and the pre-open brief may still quote only
a `publish: public` topic or runtime data; `scripts/provenance.py` fails the generation path when
an artifact transcribes a private topic's line or paragraph (see § Publish projection).

Install with `ops/host/install_memory_corpus_plugin.sh`, add the directory to
`plugins.load.paths` and enable `plugins.entries.shared-memory-corpus`; a gateway restart loads it.
The middleware only runs when the plugin is explicitly enabled, so keep
`plugins.entries.shared-memory-corpus.enabled: true` in `~/.openclaw/openclaw.json`.

## Scoped injection

`memory.py inject --audience direct|worker|investment-cron` prints the one view that audience
receives. The policy is exclusive, so the two jobs never share a playbook:

| Audience | Selection | Reader |
|---|---|---|
| `direct` | `scope in (investment, persona)` and `salience: high` | OpenClaw direct chat |
| `worker` | `scope: engineering` and `status: verified` | coding workers at task start |
| `investment-cron` | `scope: investment` | brief/report/intraday runs |

The view has a byte budget (default 12 KB); a topic that would cross it is skipped and named on
stderr, never truncated silently. `memory.py search --scope SCOPE` applies the same facet to
recall. The live OpenClaw paths still read their existing files; switching them to this view is
P3 in `docs/architecture/agent-memory-unified.md`.

## Publish projection (`MEMORY.md`)

The repository's `MEMORY.md` is generated, not hand-written: it is the projection of the active
topics whose metadata says `publish: public`. A topic that is `private`, missing an order, or not
in the store cannot reach the file.

```bash
python3 ops/host/shared-memory/scripts/publish.py --check --store ~/.shared-memory
python3 ops/host/shared-memory/scripts/publish.py --write --store ~/.shared-memory
```

The generator sorts by `metadata.order` (contiguous `1..N`), writes `MEMORY.md`, and writes
`ops/host/shared-memory/publish-manifest.json` with the header, per-section line counts and
SHA-256 hashes. `--check` without `--store` validates the committed pair, so CI can run it from a
clean checkout; with `--store` it also proves the file is not stale. The manifest is what makes
a hand-added line, an edited paragraph, a deleted section or a `publish: private` section fail
rather than silently ship. On the write path (and on `--check --store`) `publish.py` also runs
`scripts/provenance.py`: a public topic that transcribes a private topic body is rejected, and
the same guard runs on the rendered brief and the new `DREAMS.md` entry before they are committed.

`MEMORY.md` stays the direct-chat injection source. The projection keeps the exact section text,
order and separators of the reviewed file, so switching it in does not change what the chat sees.
The 03:20 dreaming gate (`ops/host/promote_dreaming.py`) writes each reviewed conclusion as a
new `publish: public` topic with the next contiguous `order` and `separator: true`, then runs
`publish.py --write`; it never appends to the generated file. `tests/test_memory_publish.py`
holds the committed-pair check and the fake-store round trip, and
`tests/test_dreaming_promotion.py` covers the promotion, idempotency, unreviewed and rollback
paths.

## Recall counter and retirement

Recall is counted in one private append-only file, never in the store or the repository:

```
~/.local/state/shared-memory/recall.jsonl   0600
{"ts":"...","source":"openclaw-supplement","topics":["feedback-x"]}
```

Sources are the OpenClaw supplement (`search` and `get`), `memory.py search`,
`memory.py read`, and the cron/brief injection view (`inject --audience investment-cron`
records `cron-brief`). Only topic slugs are written: no query, no snippet, no session
key. The supplement appends best-effort and still answers when the counter is
unavailable. `scripts/recall.py stats --write` derives `recall-stats.json`
(`count`, `last_recalled`, per-source counts).

`scripts/retire.py` runs nightly at 03:47 from a separate timer and writes
`retirement-candidates.json` / `.md` in the state directory. It **nominates only** and
never edits, archives or deletes a topic. Rules: `status: stale` older than 90 days, an
optional zero-recall rule (30 days, ships **off** until the counter has at least 30 days
of coverage), `superseded_by`, and exact duplicate bodies. A topic is never a candidate
when it is `verified`, `publish: public`, `scope: persona|memory`, linked/cited by
another topic or an index, or missing a write-time field.

`memory.py forget <slug> --confirm` is manual only. It refuses a referenced topic,
takes a snapshot first, removes the file and its single index route, records `op=forget`,
and prints `memctl restore <slug> --at <commit>`. `archive` remains the recommended
action for reviewed stale content.

## Replay candidates (`memory/.replay/`)

`scripts/replay.py` runs from its own 04:02 timer and reads the store, `memctl`'s ledger
and recent task/session text. It writes `candidates.json` and `report.md` under the
workspace's `memory/.replay/` — a gitignored sibling of `memory/.dreams/`. It never
edits the store, `MEMORY.md`, `DREAMS.md` or any public file, and `commit_dreaming.sh`
does not call it.

Kinds: duplicate merge (same or ≥0.85 Jaccard body), contradiction (overlapping bodies
with a stale/superseded pair or opposite policy markers), and unused high-salience
(zero recalls in 30 days and no recent task/session mention). The report is a review
queue; `manual_only` marks public, verified and persona/memory topics.

## Search matching

`scripts/memory.py search` and `openclaw/index.ts` implement one set of matching rules, each in
its own language with no shared build step; `tests/test_shared_memory_corpus.py` runs both on
the same queries and requires the same words, credits and kept topics. Change both together, and
judge a change on the repository's held-out queries (`ops/host/shared-memory-eval/`, not installed).

1. **Words.** The lowercased query splits on whitespace and CJK / full-width punctuation;
   `MEMORY.md`, `T+0` and `check-clawock-guide` stay whole, and Han and non-Han runs separate
   (`T+0回放` is `t+0` + `回放`). Quotes and brackets are trimmed from non-Han words.
2. **Han words.** A Han run of up to four characters must occur in the store as written; a
   four-character run the store never writes may match as its two halves, both in one topic
   (`单日跌幅` is `单日` + `跌幅`); otherwise it is reported missing. A run of five or more is cut
   into the fewest store words of two to four characters, preferring common ones on a tie
   (`通知没送到` is `通知` + `没送到`); characters no store word covers drop out.
3. **Weights.** Each word weighs its BM25 idf, `log(1 + (N - df + 0.5) / (df + 0.5))`, over the
   topics searched; a word no topic contains drops out.
4. **Credit.** A topic containing a word as written gets its whole weight. A topic lacking a
   Han word of three or more characters gets the share of its characters that the longest of
   the store's shorter words inside it covers (`被清空` → `清空`, 2/3; `磁盘空间` → `磁盘` or
   `空间`, 1/2); pieces found apart never add up to the word. Only a topic that contains at least
   one word as written is listed.
5. **Kept topics.** Coverage is a topic's credited weight over the query's total; a topic is kept
   when its coverage is at least 0.6 × the best topic's.

Tags and status are written with the note, not inferred later. `memory.py search --tag TAG`
(repeatable, all must match), `--salience` and `--status` filter the candidate set before
matching; with no query they list the selected topics instead. Both engines also match tags as
ordinary text (Python over the whole file, the plugin next to the description), so tags add an
exact facet to literal/semantic recall rather than replacing it. The plugin does not implement
the CLI filters.

What each tool adds on top: `memory.py` searches every `.md` under the root (indexes included),
lists topics containing every word first, scores filename, description and line hits, lifts an
active digest above its archived full text, and can filter by tag/salience/status. The plugin
searches top-level and `archive/` topics, reads at most 256 query characters and 16 words, and
reports a score in 0–1.

