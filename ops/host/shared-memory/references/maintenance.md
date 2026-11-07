# Shared memory maintenance

Set `M` to the skill's `scripts/memory.py` (default install: `~/.agents/skills/shared-memory/scripts/memory.py`) for the commands below; `memctl` is the script next to it.

## Topic format

Every topic is one Markdown file with frontmatter compatible with Claude Code auto-memory:

```markdown
---
name: <slug, same as the filename>
description: "<one-line hook used for recall>"
metadata:
  type: user | feedback | project | reference
  updated: YYYY-MM-DD
  salience: high | normal | low
  status: verified | hypothesis | stale
  tags: "dispatch, review"
---

<body>
```

Other `metadata` keys written by Claude Code (`originSessionId`, `node_type`, `modified`) are kept. Index lines use a backticked route (`` - `slug.md` — hook ``); a Claude-style `- [Title](slug.md) — hook` line is also recognised.

## Record

Record only durable, reusable information: explicit user preferences, stable decisions, verified recurring fixes, and project conventions. Do not store secrets, credentials, transient status, guesses, raw conversation logs, or facts already discoverable cheaply from the repository.

Write the `description` in the words people search with: what the topic is about plus the other names users and agents use for it (`微信掉投/投递失败/通知没送到：…`). Search is literal and ranks description hits above body hits; a word written only deep in one body is found late, and a word written nowhere is never found. When a search missed because you tried another word, add that word to the description of the topic you eventually found.

Write the future-use judgement at the same time, while you still know why the note matters:

| Field | Values | Meaning |
|---|---|---|
| `salience` | `high`, `normal`, `low` | `high` should change a future session's behaviour and is a replay/consolidation candidate; `normal` is useful context; `low` is niche or one-off and stays searchable only. `add` defaults to `normal`. |
| `status` | `verified`, `hypothesis`, `stale` | `verified` has the check/test/commit in the body; `hypothesis` is a candidate rule awaiting that check; `stale` is superseded but kept for its history. |
| `tags` | comma-separated, lowercase, ≤16 | Exact retrieval facets (`dispatch`, `dreaming`, `deploy`) written by the author, never inferred after the fact. |

Tags are facets, not a replacement for search words: put the words people will type in the `description` as before. A tag is also matched as text; `--tag` is the exact, conjunctive filter.

Prefer one topic per concept and search before adding; when a concept gains a new episode, append a dated section to its topic (timeline form) instead of creating `<concept>-<date>.md`. Routes in every index are relative to the shared-memory root.

Names are lowercase and hyphenated and start with a type prefix (`add` refuses others; `doctor` warns):

| Prefix | Holds |
|---|---|
| `feedback-` | the user's standing preferences and rules |
| `lessons-` | lessons distilled across incidents, each citing its evidence topics |
| `decision-` | product/strategy decisions and boundaries |
| `project-` | how a system works now, with its timeline |
| `incident-` | one failure analysis (date suffix only for a one-off event) |
| `reference-` | how-to, checklists, environment facts |

```bash
python3 $M add <slug> --summary '<compact hook>' --body-file <markdown-file> [--type feedback] \
  [--salience high] [--status verified] [--tag dispatch] [--tag review]
python3 $M update <slug> [--summary '<hook>'] [--body-file <file>] [--type <type>] \
  [--salience low] [--status stale] [--tag deploy]
python3 $M search '<terms>' [--tag dispatch] [--salience high] [--status verified]
python3 $M search --tag dispatch            # list the tagged topics, no query
```

- `add` writes the frontmatter and routes a new topic from the first line of `indexes/routes.tsv` whose glob matches the slug (`<glob><TAB><index>`, for example `incident-clawock-*	indexes/MEMORY-clawock-incidents.md`, with a final `*` line as the default; without that file new topics are routed from `MEMORY.md`; `--index` overrides). Use `--pin` only for durable conventions that belong in `MEMORY.md` (≤8KB); `--replace` only after reading the existing topic.
- `update` keeps whatever you do not pass (body, summary, type, other metadata) and rewrites the topic's single-route index line.
- Writes are atomic per file under a shared lock (not a multi-file transaction). A hook that groups several topics is left alone; adjust its text by hand.
- After a write, `memory.py` asks `memctl snapshot` to commit it to the store's history, attributed to the calling agent (and to the dispatch task when `AGENT_DISPATCH_TASK_ID` is set). Do not turn this off: the history is how the next agent learns who changed what.
- Direct edits (for example with Claude Code's Write/Edit tools) are fine if they keep the frontmatter above and update the matching index line in the same change.

When a rule is superseded, correct conflicting entrypoints and older rule text instead of appending another contradictory note.

## Learning loop

Memory is a prediction about the next session. Keep the four steps on the record:

1. **Failure.** Add or update an `incident-*` topic with what failed and the evidence (test, log, commit). Do not write a rule from the failure yet.
2. **Hypothesis.** Put the proposed rule in the topic that owns the subject with `status: hypothesis`, and say how it will be tested. If retrieval was the failure, add a case to the benefit evaluation (`ops/host/shared-memory-eval/benefit/`).
3. **Verification.** Run the test or reproduce the fix. A rule with no check stays a hypothesis; a rejected theory is corrected or marked `stale`, not deleted.
4. **Rule.** On success, set `status: verified`, keep the evidence in the body, and fold the durable wording into the `lessons-*` topic that cites the incident.

`search --status hypothesis` (with no query) lists open theories; `search --status verified` retrieves only rules that carry evidence. `memctl log` still shows who changed the status and why, and `restore` can bring back a superseded version.

## Rename, merge, split

- Rename or merge by hand, then add `old<TAB>new` lines to `indexes/redirects.tsv` and rewrite `[[old]]` / `` `old.md` `` references in active topics, indexes and the agents' shared guidance; `memory.py read <old>` follows the redirect, and `doctor` flags redirect targets that do not exist and links that resolve nowhere.
- A topic that would exceed 16KB keeps its conclusions and a dated list of episodes; move the full text to `archive/<slug>.md` and point to it from the list.

## Distill, archive, forget

- When incidents repeat a lesson, add or extend a `lessons-*` topic that states the lesson once and cites the incident topics, then move the incident records out of the active set:

```bash
python3 $M archive --dry-run <slug>...      # preview
python3 $M archive --drop-hooks <slug>...   # move to archive/, drop index lines that only routed them
```

  Archiving never deletes. `archive/` is search-only and needs no index route. Label archived handoffs non-operative.
- When the user asks to forget something, remove the topic and its index entry. When correcting, keep only the corrected version and note supersession only if it prevents a likely future mistake. Search references before moving or deleting. Do not claim product-private history or service-side data was deleted; this skill controls only the shared Markdown store.

## Validate

```bash
python3 $M doctor              # errors: dead routes, duplicate routes, unrouted active topics, bad redirects
python3 $M doctor --verbose    # warnings: size budgets, frontmatter, permissions, dead topic links, names without a type prefix
python3 $M normalize           # dry run of frontmatter repairs; --apply to write
```

Budgets: `MEMORY.md` ≤8KB (Claude Code injects only its first 200 lines), each `indexes/MEMORY-*.md` ≤16KB, each active topic ≤16KB. Route every active topic from exactly one index line (`doctor` warns on a topic routed from several indexes); pinned conventions live in `MEMORY.md` only. Run `doctor` after structural changes. Warnings do not block, but do not add new ones.

## History and rollback

The history lives outside the store (`~/.local/state/shared-memory/history.git`, no remote) with one ledger line per change. Nothing here is needed to recall a fact.

```bash
memctl log [<topic>] [-n 20]          # who/when/why/which files
memctl show <commit>                  # one change in full
memctl restore <topic> --at <commit>  # bring content back as a new commit (never deletes)
memctl doctor [--deep]                # wiring per agent and working directory, store, history
```

A file whose new lines look like a credential is never committed; `doctor` reports it until the credential is removed. A Markdown file that disappears without moving is flagged `md_deleted`; `restore` brings it back.
