#!/usr/bin/env bash
# Fix: every dreaming sweep writes "A memory trace surfaced, but details were
# unavailable in this run." into DREAMS.md for the REM and deep phases.
#
# Root cause (measured 2026-10-18, this host, 125 of 299 diary entries affected):
# one sweep runs the light / REM / deep narrative subagents CONCURRENTLY
# (DETACHED_NARRATIVE_CONCURRENCY = 3). The first phase to finish reaches its
# `finally` and calls scrubDreamingNarrativeArtifacts(), which sweeps every
# `dreaming-narrative-*` session entry. A sibling phase that is still running has
# an entry but has NOT written its transcript file yet, and
# lifecycleTranscriptIsReclaimable() answers `true` for "transcript path does not
# exist". So the live sibling's entry is deleted. The slower phase then reads
# itself back, gets no messages, and writes the fallback entry.
#
# Timeline from this host's own logs (2026-10-18), which shows the narrative was
# never missing — it was thrown away:
#   03:01:09.776  REM narrative session starts
#   03:01:14.379  light's finally -> cleanup scrub
#   03:01:16.778  REM transcript file created (751 chars of real narrative inside)
#   03:01:17.483  REM run finishes
#   03:01:19.742  fallback entry written
# Stats over 15 days: light 15/15 ok, REM 14/15 fallback, deep 8/10 fallback.
# It is a race, so it reads as "light succeeds, the others never do".
#
# Upstream fixed this by reading the reply out of `agent.wait` instead of the
# session store (openclaw/openclaw PR #127184, issue #123360, released in
# 2026.9.1). This host is on 2026.7.1-2, so it keeps the store read and is patched
# instead. We do NOT serialise the sweep (DETACHED_NARRATIVE_CONCURRENCY 3 -> 1):
# that would trade a 3x slower diary for a correct one, and it is thrown away on the
# next upgrade anyway.
#
# The fix is narrow on purpose. `protectInFlightSessions` is opt-in and defaults to
# off, so every other caller of cleanupSessionLifecycleArtifacts keeps byte-for-byte
# identical behaviour; only the dreaming scrub passes it. With it on, an entry whose
# transcript is missing is reclaimed only once it is older than
# `orphanTranscriptMinAgeMs` (dreaming already passes 5 min) measured from the
# entry's own `updatedAt`. A running phase writes a fresh `updatedAt`, so it is
# protected; a genuinely orphaned entry from a crashed run still ages out and is
# collected on a later sweep. That makes the patch self-healing instead of merely
# deferring the cleanup.
#
# v2 fixes v1, which patched the store bundle and the dreaming call site but missed the
# `session-store-runtime` wrapper in between: that wrapper rebuilds the parameter object
# field by field and had no entry for the new flag, so the guard received undefined and
# the fix was inert while still passing every marker and syntax check.
#
# Lives inside the .pnpm/openclaw@<ver> tree and is WIPED on every openclaw upgrade
# -> re-run this after each upgrade (idempotent). Registered in the repo's
# ops/host/openclaw-patches/manifest.json inventory and per-target postconditions.
set -euo pipefail

OCLAW_REAL="${CLAWOCK_PATCH_STAGE:?Use manage_openclaw_patches.py; adapters only edit a staging tree}"
DIST="$OCLAW_REAL/dist"

store_bundle="$(grep -rl 'function lifecycleTranscriptIsReclaimable' "$DIST" 2>/dev/null | head -1)"
dream_bundle="$(grep -rl 'const DETACHED_NARRATIVE_CONCURRENCY' "$DIST" 2>/dev/null | head -1)"
# The dreaming scrub does NOT call the store function directly. It imports a wrapper
# that rebuilds the parameter object field by field, so a flag added to the store
# function is dropped before it arrives. Patching only the store bundle leaves the
# fix silently inert: the marker and `node --check` both pass.
# No pipeline here: `| head -1` closes the pipe early, grep dies on SIGPIPE, and
# `set -o pipefail` turns that into a hard exit that prints nothing.
runtime_bundle=""
for candidate in "$DIST"/*.js; do
  if grep -q 'async function cleanupSessionLifecycleArtifacts' "$candidate" 2>/dev/null &&
     grep -q 'archiveRemovedEntryTranscripts: params.archiveRemovedEntryTranscripts' "$candidate" 2>/dev/null; then
    if [ -n "$runtime_bundle" ]; then
      echo "[patch] ERROR: more than one cleanup wrapper found:" >&2
      echo "[patch]   $runtime_bundle" >&2
      echo "[patch]   $candidate" >&2
      echo "[patch] Refusing to guess. Patch them by hand." >&2
      exit 1
    fi
    runtime_bundle="$candidate"
  fi
done

if [ -z "${store_bundle:-}" ] || [ ! -f "$store_bundle" ]; then
  echo "[patch] ERROR: lifecycleTranscriptIsReclaimable not found in $DIST (bundle renamed?)" >&2
  exit 1
fi
if [ -z "${dream_bundle:-}" ] || [ ! -f "$dream_bundle" ]; then
  echo "[patch] ERROR: DETACHED_NARRATIVE_CONCURRENCY not found in $DIST (bundle renamed?)" >&2
  exit 1
fi

if [ -z "${runtime_bundle:-}" ] || [ ! -f "$runtime_bundle" ]; then
  echo "[patch] ERROR: the session-store-runtime cleanup wrapper not found in $DIST." >&2
  echo "[patch] The dreaming scrub imports that wrapper, not the store function;" >&2
  echo "[patch] without it the flag never reaches the guard." >&2
  exit 1
fi

BACKUP_DIR="${CLAWOCK_PATCH_BACKUP_DIR:?staging backup directory required}"
mkdir -p "$BACKUP_DIR"
cp -p "$store_bundle" "$dream_bundle" "$runtime_bundle" "$BACKUP_DIR/"
echo "[patch] backups in $BACKUP_DIR"

python3 - "$store_bundle" "$dream_bundle" "$runtime_bundle" <<'PY'
import re, sys

store_path, dream_path, runtime_path = sys.argv[1], sys.argv[2], sys.argv[3]
MARKER = "clawock-dreaming-race-v2"

store = open(store_path, encoding="utf-8", errors="replace").read()
dream = open(dream_path, encoding="utf-8", errors="replace").read()
runtime = open(runtime_path, encoding="utf-8", errors="replace").read()

# A v1 patch is inert (the wrapper dropped the flag), so it must be re-done rather
# than treated as applied. Strip the v1 marker and its edits, then apply the full
# anchor set, so an already-v1 host converges instead of reporting "already applied".
if "clawock-dreaming-race-v1" in store or "clawock-dreaming-race-v1" in dream:
    # A v1 patch is inert (the wrapper dropped the flag), so it must be re-done rather
    # than reported as applied. These are literal strings copied from the shipped v1
    # text, not patterns: a pattern that fails to match would silently leave a
    # half-reverted bundle behind, which is the exact failure this branch exists to undo.
    print("[patch] v1 found (wrapper dropped the flag -> inert). reverting to pristine")
    V1_GUARD = (
        "\tif (!params.transcriptPath || !fs.existsSync(params.transcriptPath)) {\n"
        "\t\t/* clawock-dreaming-race-v1: a live sibling session has an entry but no\n"
        "\t\t   transcript file yet; reclaiming it deletes a running phase (see script\n"
        "\t\t   header). Wait for it to age out instead. Opt-in: without the flag this\n"
        "\t\t   returns true exactly as before. */\n"
        "\t\tconst grace = params.protectInFlightSessions === true\n"
        "\t\t\t? params.orphanTranscriptMinAgeMs\n"
        "\t\t\t: void 0;\n"
        "\t\tconst updatedAt = params.entryUpdatedAt;\n"
        "\t\tif (grace !== void 0 && typeof updatedAt === \"number\" && Number.isFinite(updatedAt) && updatedAt > 0) {\n"
        "\t\t\treturn params.nowMs - updatedAt >= grace;\n"
        "\t\t}\n"
        "\t\treturn true;\n"
        "\t}"
    )
    # Includes the trailing comma on orphanTranscriptMinAgeMs: removing v1's two
    # lines without it would leave `...,` and the pristine anchor below (which ends
    # the last property) would never match again.
    V1_CALL = (
        "\t\t\t\torphanTranscriptMinAgeMs: params.orphanTranscriptMinAgeMs,\n"
        "\t\t\t\tentryUpdatedAt: entry?.updatedAt,\n"
        "\t\t\t\tprotectInFlightSessions: params.protectInFlightSessions\n"
    )
    # Same trailing-comma detail as V1_CALL.
    V1_DREAM = (
        "\t\t\t\torphanTranscriptMinAgeMs: DREAMING_ORPHAN_MIN_AGE_MS,\n"
        "\t\t\t\t/* clawock-dreaming-race-v1 */\n"
        "\t\t\t\tprotectInFlightSessions: true\n"
    )
    for label, literal, target in (("guard", V1_GUARD, store), ("call site", V1_CALL, store),
                                   ("dreaming", V1_DREAM, dream)):
        if target.count(literal) != 1:
            raise SystemExit(f"[patch] ERROR: v1 {label} block matched {target.count(literal)}x, expected 1.\n"
                             "[patch] Restore the pristine bundles from backup-20261018-dream-race/ and rerun.")
    store = store.replace(V1_GUARD, "\tif (!params.transcriptPath || !fs.existsSync(params.transcriptPath)) return true;", 1)
    store = store.replace(V1_CALL,
        "\t\t\t\torphanTranscriptMinAgeMs: params.orphanTranscriptMinAgeMs\n", 1)
    dream = dream.replace(V1_DREAM,
        "\t\t\t\torphanTranscriptMinAgeMs: DREAMING_ORPHAN_MIN_AGE_MS\n", 1)
    if "clawock-dreaming-race-v1" in store or "clawock-dreaming-race-v1" in dream:
        raise SystemExit("[patch] ERROR: v1 marker still present after revert; restore from backup first")

if MARKER in store and MARKER in dream:
    print("[patch] already applied (marker present); nothing to do")
    raise SystemExit(0)

# 1. An in-flight session is one whose entry was written recently but whose
#    transcript file has not landed yet. Reclaim it only after it has aged out.
old = "\tif (!params.transcriptPath || !fs.existsSync(params.transcriptPath)) return true;"
new = (
    "\tif (!params.transcriptPath || !fs.existsSync(params.transcriptPath)) {\n"
    "\t\t/* clawock-dreaming-race-v2: a live sibling session has an entry but no\n"
    "\t\t   transcript file yet; reclaiming it deletes a running phase (see script\n"
    "\t\t   header). Wait for it to age out instead. Opt-in: without the flag this\n"
    "\t\t   returns true exactly as before. */\n"
    "\t\tconst grace = params.protectInFlightSessions === true\n"
    "\t\t\t? params.orphanTranscriptMinAgeMs\n"
    "\t\t\t: void 0;\n"
    "\t\tconst updatedAt = params.entryUpdatedAt;\n"
    "\t\tif (grace !== void 0 && typeof updatedAt === \"number\" && Number.isFinite(updatedAt) && updatedAt > 0) {\n"
    "\t\t\treturn params.nowMs - updatedAt >= grace;\n"
    "\t\t}\n"
    "\t\treturn true;\n"
    "\t}"
)
if store.count(old) != 1:
    raise SystemExit(f"[patch] ERROR: reclaimable guard anchor found {store.count(old)}x, expected exactly 1")
store = store.replace(old, new, 1)

# 2. Hand the caller the data the new guard needs.
old = (
    "\t\t\tif (sessionKeySegmentStartsWith(sessionKey, sessionKeySegmentPrefix) && lifecycleTranscriptIsReclaimable({\n"
    "\t\t\t\ttranscriptPath,\n"
    "\t\t\t\tnowMs,\n"
    "\t\t\t\torphanTranscriptMinAgeMs: params.orphanTranscriptMinAgeMs\n"
    "\t\t\t})) {"
)
new = (
    "\t\t\tif (sessionKeySegmentStartsWith(sessionKey, sessionKeySegmentPrefix) && lifecycleTranscriptIsReclaimable({\n"
    "\t\t\t\ttranscriptPath,\n"
    "\t\t\t\tnowMs,\n"
    "\t\t\t\torphanTranscriptMinAgeMs: params.orphanTranscriptMinAgeMs,\n"
    "\t\t\t\tentryUpdatedAt: entry?.updatedAt,\n"
    "\t\t\t\tprotectInFlightSessions: params.protectInFlightSessions\n"
    "\t\t\t})) {"
)
if store.count(old) != 1:
    raise SystemExit(f"[patch] ERROR: call-site anchor found {store.count(old)}x, expected exactly 1")
store = store.replace(old, new, 1)

# 3. Only the dreaming scrub opts in. The 5 min it already passes to
#    orphanTranscriptMinAgeMs becomes the in-flight grace too.
old = (
    "\t\t\t\ttranscriptContentMarker: DREAMING_TRANSCRIPT_RUN_MARKER,\n"
    "\t\t\t\torphanTranscriptMinAgeMs: DREAMING_ORPHAN_MIN_AGE_MS\n"
    "\t\t\t});"
)
new = (
    "\t\t\t\ttranscriptContentMarker: DREAMING_TRANSCRIPT_RUN_MARKER,\n"
    "\t\t\t\torphanTranscriptMinAgeMs: DREAMING_ORPHAN_MIN_AGE_MS,\n"
    "\t\t\t\t/* clawock-dreaming-race-v2 */\n"
    "\t\t\t\tprotectInFlightSessions: true\n"
    "\t\t\t});"
)
if dream.count(old) != 1:
    raise SystemExit(f"[patch] ERROR: dreaming scrub anchor found {dream.count(old)}x, expected exactly 1")
dream = dream.replace(old, new, 1)

# 4. The wrapper is what the dreaming scrub actually calls. It rebuilds the
#    parameter object field by field, so the flag has to be listed here or it is
#    dropped on the floor (this is what made the v1 patch inert).
old = "\t\tarchiveRemovedEntryTranscripts: params.archiveRemovedEntryTranscripts,\n"
new = ("\t\tarchiveRemovedEntryTranscripts: params.archiveRemovedEntryTranscripts,\n"
       "\t\t/* clawock-dreaming-race-v2 */\n"
       "\t\tprotectInFlightSessions: params.protectInFlightSessions,\n")
if runtime.count(old) != 1:
    raise SystemExit(f"[patch] ERROR: runtime wrapper anchor found {runtime.count(old)}x, expected exactly 1")
runtime = runtime.replace(old, new, 1)

open(store_path, "w", encoding="utf-8").write(store)
open(dream_path, "w", encoding="utf-8").write(dream)
open(runtime_path, "w", encoding="utf-8").write(runtime)
print(f"[patch] dreaming race guard applied ({MARKER}); wrapper now forwards the flag")
PY

# `node --check` is the only real proof these bundles still parse. Every anchor above
# is asserted at patch time, but a syntax error here is the failure that would stop
# the gateway from booting at all.
node --check "$store_bundle"
node --check "$dream_bundle"
node --check "$runtime_bundle"

MARKER_NAME="clawock-dreaming-race-v2"
for bundle in "$store_bundle" "$dream_bundle" "$runtime_bundle"; do
  if ! grep -q "$MARKER_NAME" "$bundle"; then
    echo "[patch] ERROR: marker missing from $bundle after patching" >&2
    exit 1
  fi
done

echo "[patch] done. The scrub reads its constants at process start:"
echo "[patch] Do NOT restart while a cron run is in flight (it orphans the run):"
echo "[patch]   openclaw cron list   # confirm nothing is 'running', then"
echo "[patch] On a host without a login session, plain 'openclaw gateway restart' fails"
echo "[patch] with 'systemctl is-enabled unavailable: No medium found'. Use:"
echo "[patch]   XDG_RUNTIME_DIR=/run/user/0 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/0/bus \\"
echo "[patch]     openclaw gateway restart"
echo "[patch] Verify after 03:00 HKT: grep -c 'A memory trace surfaced' DREAMS.md"
echo "[patch] should stop growing, and the log should show 'narrative generation"
echo "[patch] produced no text' for no phase (upstream fix PR #127184 does the same"
echo "[patch] by reading agent.wait's terminalReply instead of the session store)."
