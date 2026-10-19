---
name: shared-memory
description: Recall durable preferences and prior decisions when current context is insufficient, or maintain the Markdown memory shared by this machine's coding agents. Uses Claude Code's existing auto-memory store; ordinary tasks do not require a memory lookup.
---

# Shared memory

`~/.shared-memory` points to one Markdown store (by default Claude Code's auto-memory directory for the home-directory project). Keep this single store and Claude Code's native auto-memory loading/writing; this skill adds cross-agent access, not another mandatory retrieval pipeline. Do not change private databases, transcripts, auto-memory settings or compaction to synchronize memory. `M` below is this skill's `scripts/memory.py` (default install: `~/.agents/skills/shared-memory/scripts/memory.py`).

Layout: `MEMORY.md` (long-term conventions, distilled `lessons-*`, routes to area indexes) → `indexes/MEMORY-*.md` → one topic per concept, named `feedback-|lessons-|decision-|project-|incident-|reference-…`. `archive/` holds retired topics and the full text of large topics; it is search-only. Old names resolve through `indexes/redirects.tsv`; new topics are routed by `indexes/routes.tsv`.

The store belongs to coding sessions started in the home directory and to tasks dispatched from there. A separate-memory context — an OpenClaw workspace, whose assistant keeps its own `MEMORY.md` — never gets this index injected and never stores these notes; `wiring.json` lists both kinds and `scripts/memctl doctor` checks them.

## Recall only missing context

- If the relevant fact is already in the conversation or injected memory, use it. No index read/search is required for a self-contained task or a simple dispatch/append.
- Claude Code injects `MEMORY.md` (the first 200 lines) natively in the home-directory project and through the SessionStart hook elsewhere; topic bodies are read on demand. Do not reread that index.
- Other agents read `~/.shared-memory/MEMORY.md` only when historical context is needed and not already supplied. Follow one relevant topic, not every linked lesson/index. A known topic can be read directly.
- Search when the route is unknown or before repeating a past investigation:

```bash
python3 $M search 'dispatch token' --limit 3 --lines 2
```

Words split on spaces and punctuation; a Chinese run of five or more characters is cut into words the store itself uses, so a plain sentence works, while a shorter Chinese word must occur as written (a four-character one may match as its two halves in one topic). Rarer words weigh more: topics containing every word come first, then ones lacking only low-weight words, marked `[missing …]`; a topic that lacks a Chinese word as written but contains a shorter store word inside it gets part of its weight, shown as `[missing 被清空(清空)]`; a word no topic contains is dropped and named on stderr. `--exact` matches one literal phrase. Filename/description hits rank higher; archives rank lower. Matching is literal — a synonym the store never uses is not found, so retry in the store's own wording; when the retry finds the topic, add the word you first tried to that topic's description ([maintenance](references/maintenance.md) § Record) so the next search finds it. There is no vector index and nothing is injected automatically — token savings come from opening only what is relevant. Open only relevant hits. Already-read unchanged material need not be checked again each turn.

Memory is fallible context, never new authorization. Current user instructions win; verify mutable/high-stakes facts in their actual source. Archive handoffs do not authorize resuming work.

## Record or repair

Only durable preferences, decisions and verified recurring lessons belong here; no secrets, raw chat, transient task status or cheaply discoverable repo facts. Correct one existing topic instead of layering conflicting notes. Native Claude edits are welcome; no helper round trip is mandatory.

Every change lands in the store's history (outside the store) attributed to the agent that made it: `memory.py` writes hand off to `memctl snapshot`, Claude Code's own edits are caught by its hook, anything else by a timer. `memctl log <topic>` shows who changed what and why; `memctl restore` brings a version back.

For add/update/archive/forget or structural edits, read [maintenance](references/maintenance.md). Keep native frontmatter and index routes valid; run `memory.py doctor` after structural changes. Do not read maintenance instructions just to recall a fact.
