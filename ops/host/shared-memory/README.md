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
