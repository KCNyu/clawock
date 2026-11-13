# Dispatch and dreaming memory intake

Status: implemented 2026-11-13. This page owns the path from a dispatch brief or a
finished task to the shared store, and the model review that closes the 03:20 gate.
It complements [`agent-memory-unified.md`](agent-memory-unified.md) (the store and
its views) and [`../operations/dreaming-review.md`](../operations/dreaming-review.md)
(the hash-bound review contract).

## The failure this replaces

Three separate breaks produced the same symptom: kcn repeated a durable instruction
that the system already had.

1. **Direct chat was not in the dreaming material.** On 2026-11-13 the session corpus
   had 20 lines and zero `User:` lines; the live WeChat direct session
   (`6f69c1f4-…`, 494 KB) was not in any corpus file. OpenClaw's sweep divides a
   240-message budget across 628 transcript files (12 messages per file on that count), sorts by
   session path, and resets a changed transcript's cursor to line 0. An active chat
   therefore re-read its first messages, de-duplicated them, and never advanced; a
   session whose UUID sorts late was never reached.
2. **The 03:20 gate had no reviewer.** `review_dreaming.py` is deterministic and
   hash-bound by design: it approves only an exact receipt in
   `memory/.dreams/promotion-approvals.json`. That file did not exist. The 2026-11-09
   batch reported 0 approved / 2 pending / 53 rejected, and the gate has not promoted
   anything since it went live. Dreaming was producing candidates, not memory.
3. **Dispatched coding work was not a source at all.** Dreaming reads OpenClaw session
   transcripts. The 11-11 (41 issues), 11-12 (20 issues) and 11-13 (19 issues) dsh
   rounds lived only in `/root/logs/agent-dispatch/<id>/`, and the workers were told
   to write code, not notes. Those results could never become memory.

The prompt text also exposed a review bug: `internal_metadata` rejected the word
`派发`, so the exact rule “派 agent 处理 issues 时不要信任描述” could never pass the
gate even with a reviewer. That token is gone; task/session ids and paths are still
rejected.

## Sources and stages

```
OpenClaw direct + cron sessions ──► session-corpus + short-term recalls ──► dreaming candidates
                                                    │
dispatch prompt / task result ──► private intake queue ──► model curator ──► deterministic screen ──► dedupe ──► topic
                                                    │                                              │
                                                    └──────────────► private ledger ◄──────────────┘
dreaming candidates ──► deterministic gate ──► model reviewer ──► hash-bound receipt ──► promote_dreaming.py
```

| Stage | Owner | What it decides | What it may write |
|---|---|---|---|
| 1. Capture | `intake.py capture` (dispatch, runner) | nothing; copies the owner's words and the task envelope | private queue only |
| 2. Curate | `intake.py run` + `llm_json.py` | durable vs task-specific, scope, salience, public vs private, duplicate vs new | one-line conclusion |
| 3. Screen | `intake.py` rules (mirror of `review_dreaming.py`) | reject dates, prices/positions, HTML, paths, task/session ids, commands | nothing on rejection |
| 4. De-dupe | token overlap + model's `existing_topic` | reuse an existing topic | an update is left to the reviewer |
| 5. Write | `memory.py add` | schema and history | one topic |
| 6. Project | `publish.py --write` | public topics only | `MEMORY.md` + manifest |
| 7. Dream review | `review_dreaming_llm.py` | which clean candidates carry a reusable conclusion | receipts only |

## 1. Capture is deterministic and cheap

`dispatch.sh` writes `prompt.md`, then calls `intake.py capture --stage dispatch`.
`run-agent.sh` calls it again after the final report as `--stage outcome`. The
capture layer never calls a model:

- it extracts only the `【kcn 的原话】` / `【追加指令】` sections, or the quoted
  `「…」` lines; the dispatcher's context and the standing contract are not captured;
- the outcome pass also reads the last `attempt*.prompt` and any remaining `inbox/*.md`,
  which is where an appended instruction such as “不要信任 issue 描述” actually lives;
- it includes `STATE` / `OUTCOME` / `NEEDS` and the final report, truncated;
- it scrubs credentials, writes one `0600` JSON item under
  `~/.local/state/shared-memory/intake/queue/`, and returns.

The queue write has no model call and no global lock, so dispatch latency is
unchanged and a model outage loses nothing. A transient systemd unit
(`agent-dispatch-memory-<task>`) runs the curator immediately; the 03:20 dreaming
job drains anything still queued as a retry path.

Direct chat is captured separately from a dispatch. At 03:20 `intake.py capture-chat`
reads the previous and current day's private `session-corpus` and queues one item per
transcript's `User:` lines (probe prompts, heartbeats and dispatch events are dropped).
This exists because the short-term score needs repeated recalls and ranked 0 candidates
on a one-day conversation: the corpus was fixed, but the score threshold still starved
a new instruction. The raw lines stay private; the same model and screen decide.

## 2. A model, not the worker, decides what is memory

`intake.py run` sends the item plus the descriptions of existing topics to a
one-shot model (`openclaw infer model run`, default `deepseek/deepseek-v4-pro`).
The prompt asks one question: is this a durable rule/preference/definition/lesson,
or a task-specific request? It returns strict JSON:

```json
{"store": true, "kind": "preference|rule|definition|lessons",
 "summary": "one line", "conclusion": "one self-contained line",
 "slug": "feedback-…", "scope": "engineering", "salience": "high",
 "publish": "private", "tags": ["…"], "confidence": 0.9,
 "reason": "why this survives the task", "existing_topic": null}
```

`store: false` is a normal, successful answer. A malformed reply, an unknown kind or
a missing field is a failure: the raw item stays private and is retried up to three
times. This is deliberately *not* “store the owner's words”: the raw words never
reach a topic.

`review_dreaming_llm.py` uses the same model surface for the 03:00 candidates. It is
a batch call: one JSON array, one conclusion per clean candidate. It never sees a
candidate the deterministic gate already rejected, and it writes receipts, not
topics. The prompt asks for `covered_by` first: if a public topic already covers the
rule, even in different words, the candidate is rejected and no receipt is written.
Only public topic descriptions leave the host; the intake de-dupe still compares
against private topics locally. `review_dreaming.py` still owns the decision and
re-checks the SHA256.

## 3. The hard screen is not the model

Both intakes run the same fixed rules before a write. They reject:

| Class | Examples | Why |
|---|---|---|
| `html` | `<div class="brief-card">` | brief shells are not knowledge |
| `dated_fact` | `2026-11-13`, `今天`, `收在` | a date is not a reusable rule |
| `price_or_position` | `12.34`, `40 股`, `减仓` | prices and position actions are transient |
| `internal_metadata` | `/root/...`, task/session ids, `DONE` | private operational details |
| `front_matter` | `layout:`, `title:` | leaked page front matter |
| `command_like` | `` `clawock …` `` | a command is not a conclusion |

A model saying “durable” cannot override this screen. A model conclusion that trips
it is dropped and the candidate stays pending. The same rules screen the dreaming
candidate text and the model's one-line conclusion; the promotion step also checks
that a public body does not copy a private topic (`provenance.py`).

## 4. De-duplication is deliberate

An existing topic wins in three ways:

1. the model names `existing_topic`;
2. the proposed slug already exists;
3. token overlap between the conclusion and an existing description is at least 0.65
   (Latin words and Han 2/3-grams), which catches a rephrasing even when the model
   misses it.

A “covered” decision is recorded in the private ledger and the queue item is
retired; no topic is written. This is the answer to “why does kcn have to repeat
himself”: the repeat becomes a ledger hit, not a second topic.

## 5. Public is earned, capped and reversible

Auto-capture is allowed to publish only when the model says `public`, the item is an
explicit preference/rule, confidence is at least 0.8, and the daily public cap
(3) is not exhausted. Otherwise the topic is private. A private topic is still
searchable and still reaches the worker view when its scope/status match; it just
does not enter `MEMORY.md`.

A public write immediately calls `publish.py --write` under the projection lock. If
generation or its post-check fails, the previous `MEMORY.md` and manifest are
restored and the new topic is downgraded to `publish: private`; the topic survives,
the projection does not. This is the only automatic path that changes the public
file, and it is bounded by the same generator and manifest checks as the 03:20 gate.

## 6. What the morning gate now does

At 03:20 `commit_dreaming.sh` runs, in order:

1. `intake.py capture-chat` for yesterday and today — queue direct-chat `User:` lines
   from the private corpus;
2. `intake.py run --limit 20` — drain dispatch, outcome and chat items (fail-soft);
3. `review_dreaming_llm.py` — batch-review clean candidates and write hash-bound
   receipts (`scope`/`salience` from the review now reach the topic);
4. `promote_dreaming.py` — the existing fail-closed write + projection;
5. the two commit halves, unchanged.

The script exports the host's pnpm and node directories on `PATH`; a bare crontab
`/usr/bin:/bin` cannot find the CLI even when the gateway is healthy. `llm_json.py`
also resolves the CLI from `~/.local/share/pnpm` and adds node's directory to the
child process, so the model call works from either cron or a transient unit.

An unreachable model leaves candidates pending and raw items queued. A malformed
reply writes nothing. The deterministic gate keeps rejecting contamination even
when a receipt exists. No new timer or second dreaming job was added.

## 7. Session ingestion patch

`ops/host/openclaw-patches/patch-dreaming-session-ingestion.py` is a versioned dist
patch in the existing kit. It changes selection only:

- sweep cap 240 → 4000, per-file cap 80 → 400, and each changed session gets the
  per-file cap instead of a 1–2 message share;
- a transcript that grew resumes at `lastContentLine` instead of restarting at 0;
- `:direct:` and `:main` sessions sort before cron sessions, so the owner's own
  words cannot be starved by briefs.

It does not change scores, prompts, candidate selection, review rules or narrative
generation. It is pinned to OpenClaw `2026.7.1-2`: reapply it after an upgrade
(`reapply_openclaw_patches.sh`) and restart an idle gateway, because the old process
keeps the bytes it loaded. `system_check.py` and the patch receipt name a missing
half; the adapter refuses incomplete anchors rather than guessing.

## Verification

Local, against throwaway stores and `--llm-response` fixtures:

- capture keeps the owner's quote and drops the standing contract;
- a repeat of the issue SOP is skipped as `feedback-issue-handling-sop`, with no
  second topic;
- a new rule writes only the conclusion, never the raw quote;
- a price/date conclusion is rejected and the item stays queued for retry;
- a public rule is projected immediately and downgraded to private when the
  projection target fails;
- outcome capture includes an appended instruction from `attempt*.prompt`;
- the model reviewer binds the exact candidate SHA, refuses a different SHA, and
  never sends a contaminated candidate;
- the session patch is idempotent, leaves valid JavaScript, and its manifest
  postconditions are present.

Production verification after the restart: a manual dreaming run on 2026-11-13 grew
`memory/.dreams/session-corpus/2026-11-13.txt` from 20 lines / 0 `User:` lines to
166 lines / 11 `User:` lines, with 74 lines from the live direct session
`main/sessions/main/6f69c1f4-…`. The same run ranked 0 candidates, which is why the
direct-chat capture exists. A live `review_dreaming_llm.py --check` on the current
batch approved one new engineering rule and rejected two (one was a wording variant
of `feedback-delegation-brief`). A candidate batch followed by
`review_dreaming_llm.py --check` and `promote_dreaming.py --check` is the full
promotion check. An empty batch is not evidence.

## Remaining limits

- The dist patch is tied to the reviewed OpenClaw version. A new bundle layout fails
  the patch plan closed; it is not silently skipped.
- The model call is an external provider request. Raw queue items are private, but
  the curator sees the owner's words and the final report; the dreaming reviewer
  sees public-source brief text. Do not capture a task whose prompt contains a
  secret that must not leave the host.
- The 0.65 overlap threshold is conservative: it may retire a genuinely new rule
  that shares most of its wording with an old one. The ledger keeps the decision and
  the raw item until processed; a later review can reopen it.
- The model reviewer is semantic, not infallible. `covered_by` blocked the observed
  wording variant, but a model that names no covering topic can still create a
  duplicate; the public projection is reviewed at 03:20 and a bad topic can be
  corrected through `memory.py update` and a regeneration.
- Auto-public is capped, but it is still an automatic public write. The deterministic
  screen and the projection check are the safety boundary; there is no human preview
  for a new public topic.
- This page describes the mechanism, not a promise that a given night's candidates
  are good. The morning gate can legitimately approve nothing.
