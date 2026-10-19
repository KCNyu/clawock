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
| `hooks/claude-hook.sh` | Claude Code `PostToolUse` / `SessionStart` hook |
| `wiring.json` | where each agent looks, and which working directories share the store |
| `systemd/` | two timers: a 10-minute snapshot and a daily bundle + deep self-check |
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
through the skill. Nothing is injected beyond the index, and there is no vector store:
recall is "open the one relevant topic".

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
  which commits it with the calling agent as author (from `CLAUDECODE`, `AI_AGENT` or the
  nearest agent process) and the dispatch task id as a trailer.
- Claude Code's own file edits are committed by the PostToolUse hook with the session id.
- Anything else is committed by the snapshot timer as `unattributed`.
- A file whose new lines look like a credential is never committed and is reported by
  `doctor`; a topic that disappears without moving is flagged `md_deleted`.

`memctl log <topic>`, `memctl show <commit>`, `memctl restore <topic> --at <commit>`; the daily
timer writes a git bundle (14 kept).

## Self-check

`memctl doctor` checks the static wiring (each agent's instruction file and skill link, the
store links, Codex's native memories off, the Claude hook), every context in `wiring.json`
(which index a Claude session there gets; for a separate-memory context, that the shared index
is not injected and the store is not inside it), the store's own `memory.py doctor`, history,
backups, timers and audit flags.

`--deep` adds discovery through each agent's real entry point, without calling a model, from
every shared context and in two environments — the interactive one and the bare `HOME` + `PATH`
a dispatched task starts with: `codex debug prompt-input`, `opencode debug skill` /
`debug paths`, dsh's own `discoverBaselineInstructionFiles` and default skill roots, and for
each configured dsh profile (`headless`, `web`) that `dsh --profile P --dump-config` mounts
instruction loading and filesystem skills without moving their roots.

## The OpenClaw corpus plugin (`openclaw/`)

`openclaw/index.ts` registers a memory corpus supplement through OpenClaw's plugin API
(`registerMemoryCorpusSupplement`), loaded from outside OpenClaw's own install so an upgrade
leaves it in place. The assistant's `memory_search` with `corpus=all` and `memory_get` on a
`shared-memory/<topic>.md` path then return the store's topics, read-only:

- it only reads files under the configured root, `.md` only, no symlink escapes;
- it answers direct (one-to-one) sessions only — group, channel, cron and keyless sessions get
  nothing, so private notes do not surface in a group or in a published brief;
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

The plugin matches queries by the same rules as `memory.py search` (§ Search matching); only
the score it reports differs, because OpenClaw ranks it next to its own corpora.

Install with `ops/host/install_memory_corpus_plugin.sh`, add the directory to
`plugins.load.paths` and enable `plugins.entries.shared-memory-corpus`; a gateway restart loads it.

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

What each tool adds on top: `memory.py` searches every `.md` under the root (indexes included),
lists topics containing every word first, scores filename, description and line hits, and lifts
an active digest above its archived full text. The plugin searches top-level and `archive/`
topics, reads at most 256 query characters and 16 words, and reports a score in 0–1.

