# OpenClaw maintenance package verification

The KCN maintenance workflow applies its version-pinned adapters before it
packs the fork artifact. The build receipt in `dist/kcn-patches.json` records
the version, complete build commit, ordered patch IDs and adapted files'
SHA-256 values. Installation and verification are separate operations.

```bash
bash ops/host/reapply_openclaw_patches.sh --install "$CANDIDATE" --commit "$EXPECTED_COMMIT"
bash ops/host/reapply_openclaw_patches.sh --check-only
```

The candidate and the resolved active install are named
`.openclaw-kcn-<commit>`. The check verifies the directory and build identities,
supported version, adaptation set and bundle hashes. `--plan` checks the same
candidate identity. Install the two host extensions through
`install_skillhub_plugin.sh` and `install_memory_corpus_plugin.sh` before
the idle-gateway restart. Keep the prior package selection for rollback.

## Legacy transaction recovery

Use this section to recover an older host-applied package and existing
transaction receipts. The fork upgrade path uses the verifier above.

## Ownership

`openclaw-patches/manifest.json` owns ordered patch IDs, adapter paths, target
selectors and required postconditions. The eleven shell adapters live beside it;
`patch_dreaming_fallbacks.py`, `patch_dreaming_review.py`,
`patch-dreaming-session-ingestion.py` and `patch-memory-local-warmup.py` are the four
Python adapters. The session-ingestion adapter changes only which transcript messages
dreaming sees (budget, append-only cursor, direct-chat priority), not scoring or the
review rules; it is version-pinned and must be replayed after an upgrade.
`patch-vector-knn-oversample.sh` is the memory-recall KNN fix; its measured
rationale and the 8 → 1 argument are in the adapter's header.
`patch-memory-local-warmup.py` probes the local embedding provider 5s after
gateway start, so the first recall after a restart takes the warm path instead
of paying the 300MB GGUF load (measured 27s cold vs 0.5-5.5s warm on this box).
A target selector must resolve to exactly one bundle. Shared
bundles are copied once, and adapters see earlier staged edits in manifest order.
Required markers are checked on each named target, including all three dreaming
race forwarding hops; a marker in an unrelated bundle is insufficient.

Historical `/root/tools/openclaw/current/patch-*.sh` files are recovery evidence,
not inputs to the upgrade path. No installer or second source copy is needed:
the wrapper executes the reviewed checkout's kit. Shell adapters require an
explicit staging directory and must not be called directly against live files.
Provider latency measurement is not part of patch application; no credentials,
model requests, cron edits or package downloads are needed for a plan.

Run the legacy manager explicitly when inspecting an older installation:

```bash
python3 ops/host/manage_openclaw_patches.py plan --install "$LEGACY_INSTALL"
python3 ops/host/manage_openclaw_patches.py check --install "$LEGACY_INSTALL"
```

The JSON report includes package version, manifest and adapter SHA256s, ordered
patch IDs and per-file before/after hashes. `validated_versions` records the
reviewed package versions; an unfamiliar version still needs upgrade review and
behavioral regression checks even when its anchors pass. Native upstream fixes
are accepted only by explicit manifest postconditions (currently the native-hook
exec prefix). Syntax/marker checks cannot establish every runtime behavior.

Apply verifies the live files still match the plan, saves pre-run copies and a
`prepared` receipt under `~/logs/openclaw-patches/<transaction>/`, then replaces
files by rename. It records `applied` only after the last replacement. Every
attempt gets its own recovery set; a later reapply never destroys an earlier
backup. The before-image is the actual pre-run state, including other patches,
not an arbitrarily old `.bak` beside the bundle.

All commands serialize per installation using a lock in
`~/scratch/openclaw-patches/`; use the same scratch path for cooperating callers.
External package managers do not take that lock. Live hashes are rechecked before
writes, but an operator must still serialize package upgrades and patching.

## Recovery and limits

```bash
python3 ops/host/manage_openclaw_patches.py rollback \
  --receipt /path/to/transaction/receipt.json
```

A caught write failure restores the pre-run files. A process kill may leave a
`prepared` receipt: inspect it and run rollback before retrying. Rollback first
checks **all** current hashes and backup hashes. It refuses if any file is neither
that transaction's old nor new version, preserving later operator work. Keep the
receipt and resolve the conflicting file explicitly instead of forcing recovery.

Multi-file publication is not globally atomic. Apply/rollback require an idle
gateway, and restart is allowed only after the whole wrapper succeeds. Extension
installation is outside the dist transaction; if an extension installer fails,
repair it before restart. Neither the kit nor a successful receipt proves that a
running process loaded the patched bytes. The upgrade skill owns that regression
and restart gate.

`--install`, `--scratch`, `--state`, and `--manifest` support isolated verification.
Tests run real adapters against synthetic JavaScript and exercise late adapter
failure, syntax failure, ambiguous selection, partial markers, native fixes,
concurrent live edits, mid-install failure, replay, and guarded rollback. Full
OpenClaw/provider behavioral acceptance remains the upgrade runbook's job.
