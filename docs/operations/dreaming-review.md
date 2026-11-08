# Dreaming promotion review

Automatic scores nominate candidates; they do not verify durable facts. This gate governs the
OpenClaw workspace's generated `MEMORY.md` and the appended diary in `DREAMS.md`. The coding
agents' shared store (`~/.shared-memory`) is the source of the public projection: the 03:20 gate
writes each reviewed conclusion as a `publish: public` topic and then regenerates `MEMORY.md`
with the projection generator ([memory components](../architecture/memory-components.md)).

The host uses one promotion engine with two independent outputs:

- `ops/host/patch_dreaming_review.py` redirects only the promotion writer into ignored
  `memory/.dreams/promotion-candidates.md`. Pending candidates are not evicted by the upstream
  MEMORY character budget. The patch validates exact anchors, is idempotent, saves a pre-patch
  backup, and supports `--check`. `reapply_openclaw_patches.sh` reapplies it after upgrades. An
  idle gateway must be restarted after installation; checking files alone does not prove
  activation.
- `ops/host/promote_dreaming.py` applies `review_dreaming.py`'s hash-bound decisions. It writes
  only approved conclusions as new public store topics, snapshots the store first, requires
  `memctl verify` and `memctl doctor` to pass, then calls
  `ops/host/shared-memory/scripts/publish.py --write` to regenerate `MEMORY.md` and
  `publish-manifest.json`. If generation or its post-check fails, it restores the previous pair
  and returns non-zero.
- `ops/host/commit_dreaming.sh` runs the promotion and `review_dreams.py` independently, then
  commits the projection pair and `DREAMS.md` in separate commits. A MEMORY failure still lets a
  reviewed DREAMS append commit, and a DREAMS failure does not block a reviewed projection.
  Neither failed side is published.
- `ops/host/review_dreams.py` reviews the DREAMS diary append against a private baseline. Existing
  entries are grandfathered once; a new entry must be clean under the same deterministic rules and
  carry an exact hash-bound receipt, or it is removed from DREAMS and preserved in ignored
  `dreams-quarantine.jsonl`.

A host-only filter would leave unreviewed content in MEMORY between the dreaming run and the
commit job. A plugin-only filter cannot provide durable review receipts and legacy cleanup. The
combination closes both gaps without changing scores, selection, narrative generation, model
routing, or message behavior.

## Review contract

### MEMORY.md promotions

The deterministic filter rejects front matter, HTML, dated facts, numeric prices and position
actions, dispatch/session metadata, internal paths, and command-like package identifiers. It is
deliberately conservative: a decimal in a reusable lesson is also held out. This is a screening
rule, not semantic verification. Rejection takes precedence over any approval receipt. Same-file
candidates are reported as dependent evidence. Only one reviewed conclusion per source file can
enter permanent memory, including across later batches; combine a source's lessons in that single
reviewed conclusion.

All remaining candidates stay pending until a reviewer checks the source and writes a receipt in
ignored `memory/.dreams/promotion-approvals.json`, keyed by the exact promotion key. Fields are:

```json
{
  "memory:memory/example.md:1:1": {
    "sha256": "SHA256 of the candidate text without score metadata",
    "reviewer": "reviewer identity",
    "reviewed_on": "YYYY-MM-DD",
    "rationale": "What was checked in the source, and why this is reusable",
    "durable": true,
    "conclusion": "One self-contained, cross-date lesson without transient details."
  }
}
```

Receipts expire after 30 days until applied and bind the exact candidate hash. They are
operator-controlled input, never generated from score or model DONE status. This flow does not
schedule a new model reviewer. Pending work needs a reviewer; absence of a reviewer keeps it
private.

An approved conclusion becomes one new topic:

- slug `lessons-dreaming-<source-stem>-<start>-<end>`;
- `publish: public`, the next contiguous integer `order`, and `separator: true`;
- default write-time fields `scope: memory`, `salience: normal` and `status: verified`, because
  the receipt does not classify a domain and the public projection is the intended consumer;
- body start with a heading, then the reviewed marker, the conclusion, and the exact
  `- Source: <file>:<start>-<end> (reviewed <date>; SHA256 <hash>)` line.

The 14 sections already in `MEMORY.md` correspond to existing public topics and are never
recreated. Promotion only handles new candidates. The marker is the idempotency key: a repeated
run sees it in the committed projection or in the store, writes no second topic, and regenerates
nothing when the projection already contains it. A candidate whose content changes after
promotion is refused rather than rewritten. Legacy dated promotion sections, if an old runtime
left one, are copied to the private legacy candidate file before the projection drops them.

`promote_dreaming.py --check` performs the same review and prints the approved/pending/rejected
decisions and the slugs it would write, without touching the store or the repository.

### Failure behavior

- **Review not approved:** no store write and no projection. Pending and rejected candidates stay
  private.
- **Store write fails:** the snapshot or `memory.py add` step is named on stderr; no projection is
  written, so the injected `MEMORY.md` remains the last usable version.
- **Store audit fails:** `memctl verify` or `memctl doctor` is named on stderr; no projection is
  written. The topic remains for a retry after the underlying store issue is fixed.
- **Source guard fails:** a candidate, brief or `DREAMS.md` entry transcribes a topic whose
  metadata is not `publish: public`; the guard names the topic and the artifact is not published.
  A private line duplicated into a public topic fails too: the public topic is what needs fixing.
- **Projection generation fails:** `publish.py --write` or its `--check --store` post-check is
  named on stderr; `MEMORY.md` and `publish-manifest.json` are restored byte-for-byte from their
  before-image. The reviewed topic stays in the store, so the next run retries the projection
  without another review. The restored file is the previous injectable version, not an empty or
  partially generated one.
- **One side fails in `commit_dreaming.sh`:** each side is reviewed and committed separately; the
  other side still commits and pushes. The failing side is named in the cron log.

No gateway restart is needed for a change to this host-side Python or shell gate. Never publish
private archives, approval files, or candidate text. Private storage pruning requires separate
review.

### DREAMS.md diary append

`DREAMS.md` is tracked and published, so its raw narrative is a public memory path.
`review_dreams.py` parses the entries inside the dreaming diary markers:

- On the first run it writes `memory/.dreams/dreams-review.json` with every current
  entry marked `grandfathered` and does not rewrite the file. This is a one-time
  migration; legacy prose is not silently classified as reviewed.
- The 229 dated blocks (217 unique; 12 duplicate placeholder copies) were read and
  classified on 2026-11-08. 193 blocks were deleted: 148 as rhetoric, duplicates or
  material already covered by `MEMORY.md` / `lessons-*` / `incident-*`, then the 45
  held for confirmation on kcn's explicit instruction. The remaining 36 entries
  carry a reusable conclusion, decision basis or incident context. The private
  baseline keeps the removed hashes; the remaining entries were not rewritten.
- A later entry whose hash is not in the baseline is kept only when the
  deterministic contamination rules pass **and** `memory/.dreams/dreams-approvals.json`
  has a receipt for its exact normalized SHA256 (reviewer, rationale, reviewed_on
  within 30 days, durable). Otherwise it is removed from `DREAMS.md` and appended
  to ignored `memory/.dreams/dreams-quarantine.jsonl` with the reason.
- `review_dreams.py --list` prints quarantined hashes. An operator can inspect the
  text and run `review_dreams.py --approve <sha256> --reviewer ... --rationale ...`;
  the next review records it as approved. A contaminated entry cannot be approved.
- `--check` fails if the baseline is missing, if DREAMS contains an unreviewed
  entry, or if a quarantined entry is present. No path, marker or site input moves.

## Verification and recovery

After an upgrade, run the patch with `--check`. After the 03:00 HKT dreaming run,
confirm new candidates went to the private candidate file and no dated promotion
section appeared in MEMORY. After 03:20, check the dreaming commit log for review
decision counts and run:

```bash
python3 ops/host/patch_dreaming_review.py --check
python3 ops/host/review_dreaming.py --workspace /root/.openclaw/workspace --check
python3 ops/host/review_dreams.py --workspace /root/.openclaw/workspace --check --store ~/.shared-memory
python3 ops/host/promote_dreaming.py --workspace /root/.openclaw/workspace --check
python3 ops/host/shared-memory/scripts/publish.py --check --store ~/.shared-memory
python3 ~/.agents/skills/shared-memory/scripts/memctl verify --quiet
python3 ~/.agents/skills/shared-memory/scripts/memctl doctor --quiet
```

Inspect the private review ledger for the matching candidate hashes, then verify the approved
conclusion is in its new public topic and in `MEMORY.md`. An empty batch is not evidence of a
successful live promotion; verify the next nonempty batch as well. Tests support
`DREAMING_AUDIT_MEMORY=/path/to/copy/MEMORY.md` for private before/after checks without committing
raw session metadata as fixtures.

For a failed projection, the error names the failing step and the restored hash. Confirm
`MEMORY.md` still matches its manifest:

```bash
python3 ops/host/shared-memory/scripts/publish.py --check
```

The store topic may already exist; fix the named cause and run the promotion again. It will skip
the topic write and retry only the projection.

For DREAMS, confirm the first run bootstrapped `dreams-review.json`, then verify a
new diary entry went to `dreams-quarantine.jsonl` and disappeared from
`DREAMS.md`; `--list` names it. After an approval, `--check` must pass and the
entry must reappear only through the explicit `--approve` path.

For an incident, preserve the private ledger and stop the dreaming commit job
before investigating. Restore the changed bundle from its
`.before-dreaming-review` backup only if its other patch versions still match;
otherwise reinstall the matching package and reapply the other required patches.
Restart only an idle gateway. Revert the gate commit through a PR and CI, then run
`refresh_live.sh`. Do not restore an old MEMORY wholesale over human changes;
recover reviewed entries individually from the private before-image. Removing
both boundaries restores the original unsafe behavior, so keep automatic
promotion/publication paused until a corrected gate is active.

## Artifact health

`ops/system_check.py` checks the latest dated batch inside DREAMS' diary markers,
independently of the cron result. Empty entries or the upstream fallback sentence,
a stale date, a future date, and unreadable/unknown diary formats produce a warning.
The daily 03:00 HKT run has until 04:00 before today's artifact is expected. Old
placeholders do not keep warning once a newer batch has recovered. A non-placeholder
entry is only evidence of output, not semantic quality or successful promotion.
This check does not rewrite the diary, change cron status, retry models, or send
another notification; it participates in the existing system health report.

When the private candidate file or a reviewed promotion topic is present, the old
brief-age promotion metric is skipped: explicit review may intentionally leave all
recent briefs unpromoted. Its informational result is not proof that the patch is
active or that pending candidates have been reviewed. Inspect the private review
receipts as described above; narrative health and promotion approval are separate.
