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
  carry generation IDs and are validated as one set before publication.
- The static Pages artifact remains the cold-start fallback, so a raw-content
  outage degrades to an older but internally complete screen instead of blanking
  the application.

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
`evidence/intraday_status.py`: both postflight and dashboard publication use its
160-character banner and 120-character mover limits, trimming valid text rather
than rejecting the whole sidecar for length. Postflight owns the generation timestamp;
the publisher additionally filters mover identities against the current book.

Overview carries only first-paint evidence; detail metrics and degradation prose stay in the
full payload. The leverage dial's top-level `as_of` remains HSTECH's date. Each US
name and reentry radar row carries its own source-bar `as_of`; missing dates are
shown as unverified and are never borrowed from HK or the separate proxy history.
