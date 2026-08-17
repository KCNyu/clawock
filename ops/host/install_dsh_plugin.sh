#!/usr/bin/env bash
# install_dsh_plugin.sh — install clawock-dsh into the live DSH profile through
# the official `dsh plugin add` path.
#
# Why this looks the way it does — two incidents, one lesson each:
#
#   2026-08-17 (#709): the live plugin was a source directory hand-copied into
#   ~/.dsh/plugins/clawock-dsh and wired into the profile as a `file:`
#   dependency. pnpm *links* a `file:` dependency instead of installing it, so
#   the plugin's own `dependencies` were never installed — the directory held
#   five hand-made @deepseek-ai symlinks. The moment #708 added `zod`, dsh
#   could no longer load the typert host reflection and crash-looped 83 times.
#   The first fix made the copy a real `npm install`; this one deletes the copy.
#
#   2026-08-17 (#731 follow-up): rsync + npm install + a hand-edited profile
#   manifest was still our own invention. `dsh plugin --profile <p> add <spec>`
#   is the official installer: it forwards to pnpm inside the profile directory
#   and reconciles `dsh.profile.bundles` itself. We hand it a **packed
#   tarball**, not a directory — a tarball installs like a registry package,
#   dependency tree and all, which is precisely what the `file:` link never did.
#
# Usage:
#   ops/host/install_dsh_plugin.sh              # from the repo checkout
#   ops/host/install_dsh_plugin.sh --restart    # and restart dsh afterwards
#
# Env:
#   DSH_PROFILE      profile to install into (default: web)
#   DSH_SKILLS_DIR   user skill root (default: ~/.dsh/skills)
#
# It is idempotent: run it after every change to examples/dsh/packages/clawock-dsh.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PKG="$ROOT/examples/dsh/packages/clawock-dsh"
PROFILE="${DSH_PROFILE:-web}"
PROFILE_DIR="$HOME/.dsh/profiles/$PROFILE"
SKILLS="${DSH_SKILLS_DIR:-$HOME/.dsh/skills}"
LEGACY_DIR="$HOME/.dsh/plugins/clawock-dsh"
# Where the installed tarballs live. The profile manifest keeps the spec
# (`file:<path>`), so it has to outlive this script — a temp-dir path leaves the
# profile referencing something that no longer exists the next time anything
# runs pnpm in it. The file name carries a content hash, because pnpm keys a
# `file:` tarball by path: re-packing the same version to the same name is
# *reused from the store*, and the desk then serves the previous build while
# every step here reports success (measured 2026-08-17, the probe that made this
# script content-addressed).
ARTIFACT_DIR="$HOME/.dsh/plugins"
restart=0
[ "${1:-}" = "--restart" ] && restart=1

test -f "$PKG/package.json" || { echo "no plugin at $PKG" >&2; exit 1; }
command -v dsh >/dev/null || { echo "dsh CLI not on PATH" >&2; exit 1; }

# The generated lib/ artifacts are committed, so a checkout is installable as
# is. Verify rather than assume: shipping a stale or partial lib/ is exactly
# how the last two live incidents started.
for f in lib/index.js lib/client.js lib/typert.host.js lib/typert.remote-client.js; do
  test -f "$PKG/$f" || { echo "missing build artifact $f — run 'npm run build' in $PKG" >&2; exit 1; }
done

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

version="$(cd "$PKG" && node -p "require('./package.json').version")"
# Hash the published file set itself, not the tarball: npm pack stamps mtimes,
# so two packs of identical content differ byte for byte.
content="$(cd "$PKG" && node -e '
const { execFileSync } = require("node:child_process");
const { createHash } = require("node:crypto");
const { readFileSync } = require("node:fs");
const listed = JSON.parse(execFileSync("npm", ["pack", "--dry-run", "--json"], { encoding: "utf8" }));
const files = listed[0].files.map((f) => f.path).sort();
const hash = createHash("sha256");
for (const file of files) { hash.update(file); hash.update(readFileSync(file)); }
process.stdout.write(hash.digest("hex").slice(0, 12));
')"
ARTIFACT="$ARTIFACT_DIR/clawock-dsh-$version-$content.tgz"
echo "packing clawock-dsh@$version ($content)"
packed="$work/$(cd "$PKG" && npm pack --pack-destination "$work" --silent | tail -n 1)"
test -f "$packed" || { echo "npm pack produced nothing" >&2; exit 1; }
mkdir -p "$ARTIFACT_DIR"
mv "$packed" "$ARTIFACT"

# `dsh plugin add` forwards to pnpm, which re-resolves EVERY dependency spec
# already in the profile manifest — including this package's previous one. A
# spec pointing at something that no longer exists (the pre-#731 directory
# link, or a tarball from a temp dir) therefore fails the whole install with an
# ENOENT that has nothing to do with what is being installed. Repoint a stale
# spec at the durable artifact first; a healthy profile is left untouched.
if [ -f "$PROFILE_DIR/package.json" ]; then
  node -e '
const fs = require("node:fs");
const [manifestPath, artifact] = process.argv.slice(1);
const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
const spec = manifest.dependencies?.["clawock-dsh"];
if (spec === undefined) process.exit(0);
const target = spec.startsWith("file:") ? spec.slice("file:".length) : null;
if (target === null || fs.existsSync(target)) process.exit(0);
manifest.dependencies["clawock-dsh"] = "file:" + artifact;
fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2) + "\n");
console.log("  repointed a stale profile spec (" + spec + ") at the current artifact");
' "$PROFILE_DIR/package.json" "$ARTIFACT"
fi

echo "installing into the $PROFILE profile (dsh plugin add)"
dsh plugin --profile "$PROFILE" add "$ARTIFACT"

installed="$PROFILE_DIR/node_modules/clawock-dsh"
test -d "$installed" || { echo "dsh plugin add did not install into $installed" >&2; exit 1; }
# The profile layer only activates when dsh recorded the bundle row; a package
# whose dsh.bundle.patch went missing installs as a plain dependency and the
# tab silently never appears.
node -e '
const fs = require("node:fs");
const manifest = JSON.parse(fs.readFileSync(process.argv[1] + "/package.json", "utf8"));
const bundles = manifest.dsh?.profile?.bundles ?? [];
if (!bundles.includes("clawock-dsh")) {
  console.error("  FAILED: clawock-dsh is not a profile bundle row: " + JSON.stringify(bundles));
  process.exit(1);
}
console.log("  profile bundles: " + bundles.join(", "));
' "$PROFILE_DIR"

# The gate the content hash exists for: what the profile serves must be the
# build in this checkout, byte for byte. Anything else means pnpm answered from
# its store and the desk is running a previous version of the plugin.
for f in lib/client.js lib/index.js lib/typert.host.js; do
  cmp -s "$PKG/$f" "$installed/$f" || {
    echo "  FAILED: installed $f differs from the checkout build — the profile is serving a stale plugin" >&2
    exit 1
  }
done
echo "  installed artifacts match the checkout build"

# rc.6 skill discovery does not scan node_modules; skills are picked up from
# ~/.dsh/skills only (see the dsh-plugin-skill-discovery note).
if [ -d "$PKG/skills" ]; then
  mkdir -p "$SKILLS"
  cp -r "$PKG/skills/." "$SKILLS/"
fi

# Prove the install can actually be loaded before handing it to dsh. Every
# export entry gets imported from the *installed* copy, so a missing runtime
# dependency fails here — loudly, in a script someone is watching — instead of
# in a restart loop.
echo "verifying export entries resolve"
( cd "$installed" && node -e '
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

# The pre-#731 layout: a hand-copied source directory the profile pointed at
# with `file:`. Now that the profile installs a tarball, that directory is dead
# weight — and a second copy of the plugin is exactly the kind of ambiguity
# that made the last incident hard to read. It is regenerable from the repo.
if [ -d "$LEGACY_DIR" ]; then
  echo "removing the legacy hand-copied install at $LEGACY_DIR"
  rm -rf "$LEGACY_DIR"
fi

# Keep only the artifact the profile currently points at.
find "$ARTIFACT_DIR" -maxdepth 1 -name 'clawock-dsh-*.tgz' ! -name "$(basename "$ARTIFACT")" -delete
rm -f "$ARTIFACT_DIR/clawock-dsh.tgz"

if [ "$restart" = 1 ]; then
  systemctl restart dsh
  sleep 8
  systemctl is-active --quiet dsh || { echo "dsh did not come back up" >&2; journalctl -u dsh -n 30 --no-pager >&2; exit 1; }
  echo "dsh restarted and active"
fi
echo "done"
