# Memory benefit evaluation

`run_benefit.py` asks the same fixed questions of three memory layers:

| Mode | What the agent can read | What it answers |
|---|---|---|
| `none` | nothing | the stateless floor |
| `index` | only `MEMORY.md`, the layer a session receives without searching | can the injected index answer alone? |
| `search` | the note layer through `memory.py search` (top 3 by default) | do the notes carry the answer? |

A positive case is a **hit** only when the expected topic is retrieved *and* the
expected fact is present in that topic. A negative case is a **false positive**
when the search returns any topic. This is deliberately not a model benchmark:
it measures whether the memory surface exposes an answer-bearing note, which is
the part a change to memory can regress.

## Fixtures and live runs

`cases.tsv` and `fixtures/` are synthetic, so the committed result is repeatable
and contains no private memory. The fixture result is:

```
mode     positive  hits   hit% avg rank negative false+   fp%
none            8     0   0.00        -        2      0  0.00
index           8     0   0.00        -        2      0  0.00
search          8     8   1.00     1.00        2      0  0.00
```

`index` is the important baseline: it reads the same store's `MEMORY.md` but not
the topics, so a fact that only lives in a note cannot leak into it.

For a real-store check, pass a private cases file and the live store. Keep the
cases outside the repository: they quote private memory. Only aggregate numbers
belong in a PR or report.

```bash
python3 ops/host/shared-memory-eval/benefit/run_benefit.py
python3 ops/host/shared-memory-eval/benefit/run_benefit.py --json after.json
python3 ops/host/shared-memory-eval/benefit/run_benefit.py \
  --store ~/.shared-memory --cases /path/to/private-cases.tsv
```

## Case format

`id  question  topic  fact  kind`, tab-separated. `kind` is `positive` or
`negative`; a negative row uses `-` for topic and fact.

Add a row when a retrieval failure becomes a rule: the question is the failure,
the topic is where the rule now lives, and the fact is the sentence that must be
retrieved. Do not weaken a row to make a change pass; fix the case in its own
commit with the reason ([search evaluation](../README.md) has the same rule).
