#!/usr/bin/env bash
# Fix: the built-in memory search asked sqlite-vec for 8x more neighbours than
# it needed, then filtered the extras away.
#
# `searchVector` already widens the KNN query to MAX_VECTOR_KNN_K when the
# model filter leaves fewer than `limit` rows, so the 8x oversample is only
# useful as a fast path. On this host the index has one embedding model and
# 8,697 chunks; k=320 instead of k=40 cost ~200-350ms per recall on the 2-core
# VM, while the returned top-k is identical (the KNN is exact; the extra rows
# were never used). One is exact for a single-model index and still safe for a
# multi-model one because of the existing underfill widening.
#
# This patch lives inside the .pnpm/openclaw@<ver> tree and is WIPED on every
# openclaw upgrade -> re-run this after each upgrade (idempotent).
set -euo pipefail
OCLAW_REAL="${CLAWOCK_PATCH_STAGE:?Use manage_openclaw_patches.py; adapters only edit a staging tree}"
TARGET=$(grep -rl "const VECTOR_KNN_OVERSAMPLE_FACTOR = 8;" "$OCLAW_REAL/dist/" 2>/dev/null | head -1)
if [ -z "${TARGET:-}" ]; then
  if grep -rq "clawock-vector-knn-oversample-v1" "$OCLAW_REAL/dist/" 2>/dev/null; then
    echo "[patch] already applied"
    exit 0
  fi
  echo "[patch] ERROR: VECTOR_KNN_OVERSAMPLE_FACTOR anchor not found (bundle changed?)" >&2
  exit 1
fi
python3 - "$TARGET" <<'PY'
import sys
path = sys.argv[1]
source = open(path, encoding="utf-8").read()
anchor = "const VECTOR_KNN_OVERSAMPLE_FACTOR = 8;"
replacement = (
    "const VECTOR_KNN_OVERSAMPLE_FACTOR = 1; "
    "/* clawock-vector-knn-oversample-v1: searchVector widens on model-filter "
    "underfill, so 8x only multiplied exact KNN work */"
)
assert source.count(anchor) == 1, "anchor is not unique"
open(path, "w", encoding="utf-8").write(source.replace(anchor, replacement))
print("[patch] applied 8 -> 1:", path)
PY
