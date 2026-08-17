#!/usr/bin/env bash
# Publish the DSH skill package (clawock-dsh) to npm.
#
# One script for every path that publishes the npm side of a release:
#   - release.yml calls it on a v* tag (version synced to the release)
#   - a human can call it directly for a standalone bump (no GitHub Release,
#     no PyPI) — the version then comes from package.json
#
# Usage:
#   ops/publish/publish_dsh_plugin.sh [version]
#     version   optional semver; when given, dsh-plugin/package.json is bumped
#               to it before publishing (used by release.yml with the tag
#               version). Without it, the current package.json version is
#               published.
#
# Env:
#   NPM_TOKEN  required (or a userconfig with the registry auth token)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PKG_DIR="$ROOT/examples/dsh/packages/clawock-dsh"

version="${1:-}"

if [ -n "$version" ]; then
  # Idempotent bump: `npm version <same>` fails with "Version not changed"
  # (#617). Compare first so a tag whose version already matches package.json
  # (e.g. a re-run after a partial failure) proceeds to publish instead of
  # dying on the bump step.
  current="$(cd "$PKG_DIR" && node -p "require('./package.json').version")"
  if [ "$current" != "$version" ]; then
    (cd "$PKG_DIR" && npm version "$version" --no-git-tag-version)
  else
    echo "dsh-plugin already at $version — skipping bump"
  fi
fi

# Rebuild artifacts (src → lib + Typert generation) so the published package
# never ships stale committed output. `--include=dev` guards hosts whose npm
# config omits devDependencies by default.
# Which toolchain is doing the work. On 2026-08-17 the v0.1.6 npm job died
# twice at the same place with npm's own `Exit handler never called!` while the
# identical commands ran clean on the desk host (112 packages, 5s, exit 0) —
# and the log said nothing, because the install output went to /dev/null. Never
# again: a publish step that can fail silently is a publish step nobody can fix.
echo "node $(node --version) / npm $(npm --version) / registry $(npm config get registry)"

echo "--- npm install (dev) ---"
# 2026-08-17: the npm job died because the lockfile baked in mirror-registry
# URLs the GitHub runner cannot reach (each fetch stalled through npm's retry
# ladder, then npm's own `Exit handler never called!`). The lockfile is fixed;
# the retry below is a cheap second line of defense and the install is
# idempotent, so a transient fetch stall cannot fail the publish by itself.
#
# `$?` after an `if`-condition that fails with no branch run reports 0 by bash
# semantics, so the exit status is captured from a plain statement under
# `set +e` instead — masking a failed install as a success is how the first
# retry-loop version "passed" without publishing anything.
attempt=1
while [ "$attempt" -le 3 ]; do
  set +e
  (cd "$PKG_DIR" && npm install --include=dev --no-audit --no-fund)
  rc=$?
  set -e
  if [ "$rc" -eq 0 ]; then
    break
  fi
# Surface where npm actually hung: its debug log is the only place the
# stalled step is visible from the outside.
  logfile="$(find "$HOME/.npm/_logs" -maxdepth 1 -name '*-debug-0.log' -print 2>/dev/null | sort | tail -1 || true)"
  if [ -n "${logfile:-}" ] && [ -f "$logfile" ]; then
    echo "--- tail of $(basename "$logfile") ---" >&2
    tail -n 25 "$logfile" >&2
  fi
  if [ "$attempt" -ge 3 ]; then
    echo "npm install failed after 3 attempts (last rc=$rc)" >&2
    exit "$rc"
  fi
  echo "npm install attempt $attempt failed (rc=$rc) — retrying in 5s" >&2
  attempt=$((attempt + 1))
  sleep 5
done
echo "npm install ok"
echo "--- npm run build ---"
(cd "$PKG_DIR" && npm run build)

# Verify what will be shipped before touching the registry.
echo "--- npm pack --dry-run ---"
(cd "$PKG_DIR" && npm pack --dry-run)
test -f "$PKG_DIR/package.json"
test -f "$PKG_DIR/skills/investment-decision/SKILL.md"
test -f "$PKG_DIR/lib/typert.remote-client.js"

# The file list the registry copy will be compared against, captured from the
# same tree that is about to be published.
expected="$(cd "$PKG_DIR" && node -e '
const { execFileSync } = require("node:child_process");
const listed = JSON.parse(execFileSync("npm", ["pack", "--dry-run", "--json"], { encoding: "utf8" }));
process.stdout.write(JSON.stringify(listed[0].files.map((f) => f.path).sort()));
')"

(cd "$PKG_DIR" && npm publish --access public)

published="$(cd "$PKG_DIR" && node -p "require('./package.json').version")"

# Publishing "succeeded" is not evidence that the registry now holds this code.
# #712: npm's clawock-dsh@0.1.5 was a *different* build than the repo's 0.1.5 —
# same version number, two sets of files — and nobody noticed until a consumer
# installed a half-working plugin. So download what the registry actually
# serves and compare it to what was just packed.
echo "--- verifying the published tarball ---"
verify="$(mktemp -d)"
trap 'rm -rf "$verify"' EXIT
attempt=1
while :; do
  set +e
  # --ignore-scripts: this is untrusted-by-construction downloaded content.
  npm pack "clawock-dsh@$published" --pack-destination "$verify" --ignore-scripts --silent
  rc=$?
  set -e
  [ "$rc" -eq 0 ] && break
  if [ "$attempt" -ge 5 ]; then
    echo "could not download clawock-dsh@$published back from the registry (rc=$rc)" >&2
    exit "$rc"
  fi
  echo "registry does not serve $published yet — retrying in 10s" >&2
  attempt=$((attempt + 1))
  sleep 10
done
tar -xzf "$verify/clawock-dsh-$published.tgz" -C "$verify"
EXPECTED_FILES="$expected" node -e '
const { readFileSync, existsSync } = require("node:fs");
const { join } = require("node:path");
const root = join(process.argv[1], "package");
const expected = JSON.parse(process.env.EXPECTED_FILES);
const problems = [];
for (const file of expected) {
  if (!existsSync(join(root, file))) problems.push(`published tarball is missing ${file}`);
}
const manifest = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));
if (manifest.version !== process.argv[2]) problems.push(`published version is ${manifest.version}`);
// The #712 fingerprint: the pre-#708 layout had client.js at the tarball root
// and no ./remote export. Name it explicitly so the failure is legible.
if (existsSync(join(root, "client.js"))) problems.push("published tarball has a top-level client.js (pre-#708 layout)");
for (const subpath of ["./typert", "./remote", "./client"]) {
  if (manifest.exports?.[subpath] === undefined) problems.push(`published manifest lost the ${subpath} export`);
}
for (const dependency of Object.keys(JSON.parse(readFileSync(join(process.argv[3], "package.json"), "utf8")).dependencies ?? {})) {
  if (manifest.dependencies?.[dependency] === undefined) problems.push(`published manifest lost the ${dependency} dependency`);
}
if (problems.length > 0) {
  console.error("published tarball does not match what was packed:");
  for (const problem of problems) console.error("  - " + problem);
  process.exit(1);
}
console.log(`  ok: ${expected.length} files, version ${manifest.version}, exports and dependencies intact`);
' "$verify" "$published" "$PKG_DIR"

echo "clawock-dsh@$published published to https://www.npmjs.com/package/clawock-dsh"