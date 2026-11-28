# Dashboard data plane

The public dashboard has two delivery surfaces with different jobs:

- GitHub Pages serves the static HTML, CSS, JavaScript, and the cold-start copy
  of the JSON payloads. Its workflow follows GitHub's supported Pages model:
  build a site, upload a Pages artifact, then deploy it with `deploy-pages`.
- The browser's later polls read the current seven required generation files from the
  `data-plane` branch through `raw.githubusercontent.com`. The branch is an
  orphan snapshot: it is replaced rather than appended, because it is state and
  not an audit log. An eighth file, `evidence.json`, is published when available
  on its own cadence.

## Status: a GitHub-only compatibility layer

The orphan branch is **not a GitHub Pages recommended data-plane pattern**.
GitHub documents two Pages publishing sources: a source branch for simple sites,
or a custom Actions workflow using a Pages artifact and `deploy-pages` when a
build is required. GitHub does not document `raw.githubusercontent.com` as a
low-latency application-data service or give it a freshness SLA.

This repository uses it as a bounded workaround for an observed platform
constraint: a successful Pages deployment can take roughly fourteen minutes to
become visible, and a newer deployment created during that interval may never be
served. A five-minute raw-content cache is materially better for the dashboard's
60-second poll, while keeping the whole deployment on GitHub.

Treat that as an operational trade, not product architecture:

- `FilesystemStore` remains clawock's default artifact store. A foreign install
  never pushes to this repository.
- `GitBranchStore` and the raw URL are instance adapters owned by KCNyu/clawock.
- A data-plane push is independent of `master`'s ledger gate. The seven required payloads
  are read as one set and scanned for credentials before the branch is replaced.
  Where present, generation IDs let the Pages and browser readers detect
  mismatched dashboard documents.
- The static Pages artifact remains the cold-start fallback, so a raw-content
  outage degrades to an older but internally complete screen instead of blanking
  the application.
- The browser bounds raw-content reads at eight seconds. A live read failure
  on the Overview or full-document path disables that origin for the rest of
  the visit. Subsequent Overview and full-document reads use Pages and check
  that the two belong to one generation.
- On a failed live sidecar read the browser tries the Pages copy once, also
  with an eight-second deadline. The live origin stays available for the next
  sidecar refresh.
- The first paint is the Pages copy, so the first detail tab can meet a full
  document on the branch that is a generation newer. That is the normal state
  during a session, not an error: the page keeps the document, reads the
  branch's Overview once, and paints both.
- Every changed generation goes to the branch; only some ask for a Pages
  deploy and an artifact-gate run. Build clocks and the provenance commit
  pointers whose content digests did not move are not a change at all
  (`config/dashboard-outputs.json` `*_clock_fields`, `locator_fields`). A
  generation that differs from the one it replaced only in the automation's
  status (`status_fields`, `cron-heartbeats.json`, `workflow-outcomes.json`) is
  published without a dispatch: the polls read it from the branch, the gate
  validates none of it, and each intraday slot used to cost two deploys — one
  when its postflight published, one when the next tick saw the job finish.

## Long-term target

If the dashboard needs a freshness guarantee tighter than GitHub's caches and
Pages propagation, move the seven required JSON objects and optional evidence file to an object store/static data
service with atomic generation promotion, explicit cache headers, CORS, and
health telemetry. Keep Pages for the static shell. GitHub Actions artifacts are
build/deployment inputs with retention, not a public runtime API, so replacing
the branch with an Actions artifact would not create a browser-readable data
plane.

Selection criteria for a replacement are deliberately provider-neutral:

1. publish all seven required objects, then atomically move one manifest/current pointer;
2. reject an older generation overwriting a newer one;
3. set and observe cache TTL rather than inherit an undocumented raw-content
   cache;
4. expose a receipt the watchdog can verify independently of the writer;
5. require no OpenClaw path, Git checkout, or repository hook.


Intraday status sidecar text normalization is owned by
`intraday_status.py`: both postflight and dashboard publication use its
160-character banner and 120-character mover limits, trimming valid text rather
than rejecting the whole sidecar for length. Postflight owns the generation timestamp;
the publisher additionally filters mover identities against the current book.

Overview carries only first-paint evidence; detail metrics and degradation prose stay in the
full payload. The leverage dial's top-level `as_of` remains HSTECH's date. Each US
name and reentry radar row carries its own source-bar `as_of`; missing dates are
shown as unverified and are never borrowed from HK or the separate proxy history.

## Brief archive migration

The data plane can carry daily briefs and weekly reviews at their existing
`memory/` paths. The archive index binds the list and every published body
with SHA-256. The reader checks those hashes on the same pinned ref as the
Dashboard files before writing any staging input.

Seed the archive from a committed revision using
`ops/publish/publish_brief_archive.py --seed-ref <commit>`. A validated
daily or weekly publication can update its own entry with `--brief <path>`.
Each update preserves the other publisher's paths and fast-forwards from
the current branch tip. A competing update retries against the new tip.

Use `fetch_data_plane.py --expect-brief-archive` in the Pages build at cutover.
Before enabling it, verify the complete seeded index and route both scheduled
writers to the archive publisher. Retain existing URLs and remove the old
source-branch write path in the same cutover.
