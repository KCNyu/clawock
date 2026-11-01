# OpenClaw patch kit

The dist adaptations are a versioned unit under `ops/host/`, not instructions to
edit an installed package from untracked host scripts. The upgrade entry remains
`reapply_openclaw_patches.sh`; it invokes `manage_openclaw_patches.py` and then the
two existing host-extension installers. Gateway restart remains a separate step.

## Ownership

`openclaw-patches/manifest.json` owns ordered patch IDs, adapter paths, target
selectors and required postconditions. The eight shell adapters live beside it;
`patch_dreaming_fallbacks.py` and `patch_dreaming_review.py` are the two existing
Python adapters. A target selector must resolve to exactly one bundle. Shared
bundles are copied once, and adapters see earlier staged edits in manifest order.
Required markers are checked on each named target, including all three dreaming
race forwarding hops; a marker in an unrelated bundle is insufficient.

Historical `/root/tools/openclaw/current/patch-*.sh` files are recovery evidence,
not inputs to the upgrade path. No installer or second source copy is needed:
the wrapper executes the reviewed checkout's kit. Shell adapters require an
explicit staging directory and must not be called directly against live files.
Provider latency measurement is not part of patch application; no credentials,
model requests, cron edits or package downloads are needed for a plan.

## Plan, check, apply

```bash
bash ops/host/reapply_openclaw_patches.sh --plan
bash ops/host/reapply_openclaw_patches.sh --check-only
# After the upgrade runbook's no-in-flight check:
bash ops/host/reapply_openclaw_patches.sh
```

A plan resolves all targets, copies only those files into an isolated package,
runs all adapters there, and checks postconditions, JSON and JavaScript syntax.
Failure discards the stage and leaves installed bytes untouched. Check performs
the same rehearsal and exits 1 for any pending edit, 2 on an error. It does not
write installed files. The wrapper also checks the installed host extensions.

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
