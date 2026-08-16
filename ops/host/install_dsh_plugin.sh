#!/usr/bin/env bash
# install_dsh_plugin.sh — install clawock-dsh into the live DSH web profile,
# with its runtime dependencies, reproducibly.
#
# Why this exists (2026-08-17 outage): the live plugin used to be a source
# directory hand-copied into ~/.dsh/plugins/clawock-dsh, wired into the profile
# through a `file:` dependency. pnpm *links* a `file:` dependency instead of
# installing it, so the plugin's own `dependencies` were never installed — the
# directory only held five hand-made @deepseek-ai symlinks. The moment #708
# added `zod` as a runtime dependency, dsh could no longer load the typert host
# reflection and crash-looped 83 times (~3s of CPU every 5s on a 1.9Gi box)
# until someone noticed. Nothing in CI or on the host could see it coming.
#
# The fix is not "remember to symlink the next dependency too" — it is to make
# the install a real install. This script is that install.
#
# Usage:
#   ops/host/install_dsh_plugin.sh              # from the repo checkout
#   ops/host/install_dsh_plugin.sh --restart    # and restart dsh afterwards
#
# It is idempotent: run it after every change to examples/dsh/plugin.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC="$ROOT/examples/dsh/plugin"
DEST="${DSH_PLUGIN_DIR:-$HOME/.dsh/plugins/clawock-dsh}"
SKILLS="${DSH_SKILLS_DIR:-$HOME/.dsh/skills}"
restart=0
[ "${1:-}" = "--restart" ] && restart=1

test -f "$SRC/package.json" || { echo "no plugin at $SRC" >&2; exit 1; }

# The generated lib/ artifacts are committed, so a checkout is installable as
# is. Verify rather than assume: shipping a stale or partial lib/ is exactly
# how the last two live incidents started.
for f in lib/index.js lib/client.js lib/typert.host.js lib/typert.remote-client.js; do
  test -f "$SRC/$f" || { echo "missing build artifact $f — run 'npm run build' in $SRC" >&2; exit 1; }
done

echo "installing clawock-dsh -> $DEST"
mkdir -p "$DEST"
# Mirror the package's declared `files` set, deleting anything the package no
# longer ships. node_modules is excluded from the delete so the dependency
# install below is incremental rather than a full refetch every time.
rsync -a --delete --exclude node_modules --exclude '*.bak-*' \
  --include 'skills/***' \
  --include 'lib/***' \
  --include 'cordis.patch.yml' \
  --include 'package.json' \
  --include 'README.md' \
  --exclude '*' \
  "$SRC/" "$DEST/"

# The whole point: install the plugin's own runtime dependencies where Node
# will actually resolve them — inside the plugin directory, because Node walks
# up from the realpath of lib/*.js and never sees the profile's node_modules.
( cd "$DEST" && npm install --omit=dev --no-audit --no-fund --silent )

# rc.6 skill discovery does not scan node_modules; skills are picked up from
# ~/.dsh/skills only (see the dsh-plugin-skill-discovery note).
if [ -d "$SRC/skills" ]; then
  mkdir -p "$SKILLS"
  cp -r "$SRC/skills/." "$SKILLS/"
fi

# Prove the install can actually be loaded before handing it to dsh. Every
# export entry gets imported, so a missing runtime dependency fails here —
# loudly, in a script someone is watching — instead of in a restart loop.
echo "verifying export entries resolve"
( cd "$DEST" && node -e '
const { pathToFileURL } = require("node:url");
const path = require("node:path");
const pkg = require("./package.json");
// Import the file each export entry actually maps to. A bare path import
// would bypass the exports map and prove nothing; these are the same modules
// dsh loads through "./typert" and friends.
// `./client` is the browser bundle — a window.__ModuleLoader__ closure, not
// an ES module. Importing it here would throw "window is not defined" and say
// nothing about the install; its registration is covered by
// tests/decision_studio_plugin.spec.js.
const targets = Object.entries(pkg.exports || {})
  .filter(([name, spec]) => name !== "./package.json" && name !== "./client" && spec && spec.default)
  .map(([name, spec]) => [name, path.resolve(spec.default)]);
Promise.all(targets.map(([, file]) => import(pathToFileURL(file).href)))
  .then(() => console.log("  ok: " + targets.map(([n]) => n).join(", ")))
  .catch((err) => { console.error("  FAILED: " + err.message); process.exit(1); });
' )

if [ "$restart" = 1 ]; then
  systemctl restart dsh
  sleep 8
  systemctl is-active --quiet dsh || { echo "dsh did not come back up" >&2; journalctl -u dsh -n 30 --no-pager >&2; exit 1; }
  echo "dsh restarted and active"
fi
echo "done"
