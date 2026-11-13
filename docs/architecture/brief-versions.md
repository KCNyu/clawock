# Brief version chain

The daily deep brief is delivered as a static WeChat/Telegram card whose link
points at `memory/{date}-pre-open.html`. Before this chain, a re-run rewrote
`memory/{date}-pre-open.md` in place: the 08:32 card still showed the old
numbers, the 09:02 page showed the corrected ones, and the only trace was the
digest-based revision notice added in #3105. That notice says the page changed;
it does not preserve what the card showed.

The design borrows one idea from a message-tree chat client: a delivered
artifact is a node with an identity, and a separate pointer names the node a
reader should see. It deliberately stops short of a tree. A daily brief has one
linear lineage: a re-run either reproduces the current bytes (pure retry) or
appends a correction. There is no branch to switch to, so there is no branch
field, no parent tree, no archive UI, and no new delivery channel.

## Storage

One directory per brief date, written by postflight:

```text
memory/brief-versions/2026-11-13/
  index.json
  v1-3f2a9c1b.md
  v2-8d1e0f2a.md
```

`v{seq}-{sha8}.md` is the immutable report as rendered for delivery, including
Jekyll front matter and excluding the revision banner. The digest is
`brief_postflight.report_sha256`'s basis: SHA-256 of the report with the
`> 📝 **投递后修订**` notice removed. The name embeds its seq and the first
eight digest characters; the full digest is in the index.

`index.json` is the only mutable file:

```json
{
  "schema_version": 1,
  "date": "2026-11-13",
  "current": "v2-8d1e0f2a",
  "current_sha256": "8d1e0f2a…",
  "updated_at": "2026-11-13T09:02:11+08:00",
  "versions": [
    {
      "id": "v1-3f2a9c1b",
      "seq": 1,
      "sha256": "3f2a9c1b…",
      "bytes": 41234,
      "file": "v1-3f2a9c1b.md",
      "path": "memory/brief-versions/2026-11-13/v1-3f2a9c1b.md",
      "created_at": "2026-11-13T08:32:41+08:00",
      "generation_id": "…",
      "parent": null,
      "delivery": {
        "at": "2026-11-13T08:32:47+08:00",
        "channels": {"wechat": true, "telegram": true},
        "receipt": "brief-sent-2026-11-13.json"
      }
    }
  ]
}
```

- `current` is the version `memory/{date}-pre-open.md` must match. The page
  itself stays where it was; the version directory is the history, not a second
  live page.
- Versions are content-addressed. Rendering the same bytes again reuses the
  existing node and leaves the history alone; a correction appends a node and
  moves `current`. Reverting to older bytes moves `current` back without
  deleting or duplicating a node.
- `parent` records the `current` id at creation. It makes the lineage readable;
  nothing consumes it as a tree.
- The report file is written before the index that names it. `index.json` is
  written atomically, and the whole read/modify/write is serialized with
  `safe_io.temp_dir_lock`, so a host retry cannot race the off-host fallback.
  A malformed index raises instead of being replaced: overwriting it would
  forget which delivery was bound to which version.

## Who owns current

`index.json.current` owns "current". Postflight captures a version after the
report has been rendered, Jekyll front matter added and validation classified as
`pass` or `warn`, and before the card is composed. It is a fail-open step: a
version-store error is printed and returned in `brief_version_error`, and the
card still goes out without a version label. Traceability must not cost the
brief.

On a day with no version directory (older dates), nothing changes: the page is
the only artifact, exactly as before.

## Delivery binding

The delivery receipt (`memory/.tmp/brief-sent-{date}.json`) is the binding:

| field | meaning |
|---|---|
| `report_sha256` | Existing digest of the page the card linked to. Kept for older readers. |
| `brief_version` | `v1-3f2a9c1b` — the version whose card went out. |
| `brief_version_path` | Repository path of the archived report. |
| `brief_version_sha256` | Same digest as `report_sha256`, named for the archived node. |

They are written only when WeChat or Telegram returned success. A receipt that
records two failures describes an attempt, not a delivery, and gets no binding.
The version row carries the same fact as `delivery.at/channels/receipt`; the
receipt is the short-lived delivery evidence, the index row is the durable one.

`delivery` describes the send that first made the card canonical. A later
per-channel recovery (WeChat retried after Telegram already landed, or the
reverse) may rebuild the card from a newer page, but it keeps the first receipt's
`report_sha256` and `brief_version`: the page notice always compares the live
page with the card that first reached a reader, not with every retry.

A receipt from before this chain has only `report_sha256`. When that digest
still matches an archived version, postflight binds it on the next run, so the
rollout does not leave today's already-delivered card unnamed. A digest no
archived version matches is left alone; the notice falls back to digest wording
rather than inventing a version.

## The card

`brief_card.build_brief_card` appends one harness-owned line:

```text
本卡版本 v1-3f2a9c1b
```

It is appended after the model's card text and after the `完整报告` link, so it
cannot displace the URL or the compact layout, and a model-written card cannot
forget or invent it. The primary send passes the version it just captured. The
watchdog passes the receipt's delivered version only when the archive still
shows that version; a rebuilt card for a page that moved on carries no version
label.

This is an identity, not a second link. The card still links to the live page;
the page's revision notice links the archived delivered version.

## Readers

| Reader | What it reads | What it must not do |
|---|---|---|
| The page (`memory/{date}-pre-open.md`) | Always the current render. | Never serve a version file as the live page. |
| Revision notice (postflight) | Receipt's delivered version + index `current`. | Not claim a version when the receipt cannot identify one. |
| Dashboard/pinned latest-brief card | `brief_projection.as_of` → the live page. | Must not read the version directory; it shows current. |
| `brief_watchdog` | Receipt for delivery state and the delivered version; `wechat_body` for a failed WeChat replay. | Must not resend a version the archive no longer marks current under a version label. |
| Postflight commit | `memory/brief-versions/{today}/` in the day's scoped commit. | Must not stage another date's archive. |
| Off-host fallback | Runs the same postflight, so it captures and commits the same way. | — |

### Page notice

When the current digest differs from the delivered one, the page gets the
existing one-line notice under its title, now naming both versions:

```text
> 📝 **投递后修订**：今天的卡片 08:32 HKT 送达 v1-3f2a9c1b；本页于
> 09:02 HKT 更新为 v2-8d1e0f2a。送达版存档：<repository blob URL 或相对路径>。
> 卡片内容以送达版为准，本页始终展示当前版。
```

`config/pages-public.json` carries `repo_url` (and optionally `repo_branch`) so
the notice can link the committed archive. Without it the notice names the
relative path and keeps working. The notice is presentation; it is excluded
from the digest and from every snapshot.

## Failure modes

- **Index unreadable/corrupt**: capture raises, postflight prints
  `brief version not recorded`, the card still goes out with no version, and
  the revision notice uses digests. The corrupt index is not overwritten.
- **Report file missing but index row present**: `load_report` returns `None`;
  the notice still names the version but omits its archive link.
- **Delivery succeeded, commit/push failed**: the index and receipt are local
  truth; the archive link starts working when the commit reaches origin, the
  same as the page link.
- **Two writers**: the temp-dir lock serializes index updates. The send claim
  still serializes delivery; version capture itself is safe to repeat.
- **Disk full**: `safe_write_text`/`safe_write_json` raise, postflight fails
  open, and no partial version file is published.

## Why this scope

- **No tree/branch UI**: a day has one publishable lineage. A tree would need a
  "which branch is current" policy, a way to switch it, and a reader that
  understands it; none of that answers the delivered-card question.
- **No Pages history pages**: publishing every version would create duplicate
  pages and duplicate sitemap entries. The requirement is that history is
  queryable and does not interfere with current; a committed directory plus a
  blob link does both.
- **No new message on revision**: the existing 2026-07-09 rule stands — a
  corrected brief does not send a second card. The notice and the archive make
  the first card honest.
- **No card resend**: the receipt, watchdog and send-claim paths keep their
  current behavior. The watchdog only reuses the exact failed bytes that the
  receipt already recorded.
