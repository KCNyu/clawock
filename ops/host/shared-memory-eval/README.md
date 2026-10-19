# Held-out evaluation for shared-memory search

`queries.tsv` is a fixed set of real searches with the answer a reader needs. It exists to judge a
change to `shared-memory/scripts/memory.py search` (and the plugin that ports its rules), not to
tune one: **do not change the search to make a row pass, and do not change a row to make a search
pass.** A row that is wrong (the expected topic was renamed, or the judgement was mistaken) is fixed
in its own commit that says which row changed and why.

The answers name topics in one user's store, so the set is only meaningful on the machine that
holds that store; it is not a CI test. No topic text is copied here, only file names.

## Rows

`id  kind  query  expect  source  why`, tab-separated.

- **query** is verbatim from real use. `source` says where: `agent` (a coding agent's
  `memory.py search` call), `assistant` (the OpenClaw assistant's `memory_search` call), `chat`
  (the user's own question to the assistant), `brief` (a question the task brief quoted as real).
  Queries that earlier search changes were measured on are excluded.
- **expect** lists the topics that answer the query (any one of them counts), or `-` when the store
  holds no answer and the right result is nothing.
- **kind**: `zh-sentence`, `zh-phrase`, `en-words`, `id-symbol`, `colloquial` (a spoken question),
  `synonym` (the store says it in other words), `absent` (expect `-`).

## Running

```bash
python3 ops/host/shared-memory-eval/run_eval.py                         # this checkout's memory.py
python3 ops/host/shared-memory-eval/run_eval.py --memory-py ~/.agents/skills/shared-memory/scripts/memory.py
python3 ops/host/shared-memory-eval/run_eval.py --json after.json --compare before.json
python3 ops/host/shared-memory-eval/run_eval.py --hits ranked.json       # score another engine's lists
```

A row passes when an expected topic is in the first three results, or, for `-`, when the search
lists nothing. `baseline.tsv` is the score of `memory.py` before this directory existed.
