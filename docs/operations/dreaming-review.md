# Dreaming promotion review

Automatic scores nominate candidates; they do not verify durable facts. The host
uses two boundaries:

- `ops/host/patch_dreaming_review.py` redirects only the promotion writer into
  ignored `memory/.dreams/promotion-candidates.md`. Pending candidates are not
  evicted by the upstream MEMORY character budget. The patch validates exact
  anchors, is idempotent, saves a pre-patch backup, and supports `--check`.
  `reapply_openclaw_patches.sh` reapplies it after upgrades. An idle gateway must
  be restarted after installation; checking files alone does not prove activation.
- `ops/host/commit_dreaming.sh` runs `review_dreaming.py` before staging. Unknown
  structures or invalid receipts fail the commit. Legacy dated promotion sections
  are quarantined first, then removed through the same review logic. Unrelated
  MEMORY sections and DREAMS markers are untouched.

A host-only filter would leave unreviewed content in MEMORY between the dreaming
run and the commit job. A plugin-only filter cannot provide durable review
receipts and legacy cleanup. The combination closes both gaps without changing
scores, selection, narrative generation, model routing, or message behavior.

## Review contract

The deterministic filter rejects front matter, HTML, dated facts, numeric prices
and position actions, dispatch/session metadata, internal paths, and command-like
package identifiers. It is deliberately conservative: a decimal in a reusable
lesson is also held out. This is a screening rule, not semantic verification.
Rejection takes precedence over any approval receipt. Same-file candidates are
reported as dependent evidence. Only one reviewed conclusion per source file can
enter permanent memory, including across later batches; combine a source's
lessons in that single reviewed conclusion.

All remaining candidates stay pending until a reviewer checks the source and
writes a receipt in ignored `memory/.dreams/promotion-approvals.json`, keyed by
the exact promotion key. Fields are:

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

Receipts expire after 30 days until applied and bind the exact candidate hash.
They are operator-controlled input, never generated from score or model DONE
status. This flow does not schedule a new model reviewer. Pending work needs a
reviewer; absence of a reviewer keeps it private.

Approved conclusions go into `## Reviewed Dreaming Memory`, outside the dated
promotion sections, with source file/line range, review date and SHA256. Rejected
candidates retain their original promotion marker as a content-free receipt.
Original bytes and per-candidate decisions remain in ignored `review-<hash>.json`;
legacy pending inputs remain in `legacy-promotion-candidates.md`. Reruns preserve
accepted/rejected markers and do not duplicate permanent conclusions. Never
publish these private archives or approval files. Pending storage and permanent
receipts grow over time; archival pruning requires separate review.

## Verification and recovery

After an upgrade, run the patch with `--check`. After the 03:00 HKT dreaming run,
confirm new candidates went to the private candidate file and no dated promotion
section appeared in MEMORY. After 03:20, check the dreaming commit log for review
decision counts and run:

```bash
python3 ops/host/patch_dreaming_review.py --check
python3 ops/host/review_dreaming.py --workspace /root/.openclaw/workspace --check
```

Inspect the private review ledger for the matching candidate hashes and verify
that approved text is in the permanent section. An empty batch is not evidence
of a successful live promotion; verify the next nonempty batch as well. Tests
support `DREAMING_AUDIT_MEMORY=/path/to/copy/MEMORY.md` for private before/after
checks without committing raw session metadata as fixtures.

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

When the private candidate file or reviewed-memory section is present, the old
brief-age promotion metric is skipped: explicit review may intentionally leave all
recent briefs unpromoted. Its informational result is not proof that the patch is
active or that pending candidates have been reviewed. Inspect the private review
receipts as described above; narrative health and promotion approval are separate.
