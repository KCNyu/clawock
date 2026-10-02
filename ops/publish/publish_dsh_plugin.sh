#!/usr/bin/env bash
# Publish the DSH skill package (clawock-dsh) to npm.
#
# One script for every path that publishes the npm side of a release:
#   - release.yml calls it on a v* tag (version synced to the release)
#   - a human can call it directly for a standalone bump (no GitHub Release,
#     no PyPI) — the version then comes from package.json
#
# Usage:
#   ops/publish/publish_dsh_plugin.sh [--no-verify | --verify-only] [version]
#     version        optional semver; when given, dsh-plugin/package.json is
#                    bumped to it before publishing (used by release.yml with
#                    the tag version). Without it, the current package.json
#                    version is published.
#     --no-verify    publish, but leave the registry readback to a separate
#                    run (release.yml's npm-readback job).
#     --verify-only  publish nothing; only compare what the registry serves for
#                    this version against a fresh build of this tree.
#   With neither flag (a human at a terminal) it publishes, then verifies.
#
# Env:
#   NPM_TOKEN                required to publish (or a userconfig with the
#                            registry auth token); not needed for --verify-only
#   DSH_READBACK_TIMEOUT_S   how long the readback waits for the registry to
#                            serve the version (default 900)
#   DSH_READBACK_INTERVAL_S  pause between readback attempts (default 20)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PKG_DIR="$ROOT/examples/dsh/packages/clawock-dsh"

mode=all
case "${1:-}" in
  --no-verify) mode=publish; shift ;;
  --verify-only) mode=verify; shift ;;
esac
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
// Path AND content hash: a tarball with every name present and a different
// build behind one of them used to read back as ok (#2304).
const { createHash } = require("node:crypto");
const { readFileSync } = require("node:fs");
const digest = (path) => createHash("sha256").update(readFileSync(path)).digest("hex");
process.stdout.write(JSON.stringify(listed[0].files.map((f) => f.path).sort()
  .map((path) => ({ path, sha256: digest(path) }))));
')"

# npm provenance: a signed, publicly verifiable statement of which repository,
# workflow and commit produced this tarball, rendered as a "Built and signed on
# GitHub Actions" block on the package page. It is the npm-side equivalent of
# the trusted publishing the PyPI half already uses, and the package page is
# this project's highest-traffic landing surface.
#
# npm only accepts it from a supported CI with an OIDC token, and hard-fails
# when asked for it anywhere else — so a human running this script directly
# (a documented path, see the header) must not pass the flag.
provenance_args=()
if [ "$mode" = verify ]; then
  : # nothing is published, so there is nothing to sign
elif [ "${GITHUB_ACTIONS:-}" = "true" ] && [ -n "${ACTIONS_ID_TOKEN_REQUEST_URL:-}" ]; then
  echo "provenance: OIDC token available — publishing with --provenance"
  provenance_args+=(--provenance)
else
  echo "provenance: no Actions OIDC token — publishing without provenance"
fi

published="$(cd "$PKG_DIR" && node -p "require('./package.json').version")"

if [ "$mode" != verify ]; then
  # A re-run of a job whose publish already went through (the readback, or
  # anything after it, failed) must not die on npm's "cannot publish over the
  # previously published version": the version is burned either way, and the
  # readback — not this step — is what proves the registry copy is this build.
  on_registry="$(cd "$PKG_DIR" && { npm view "clawock-dsh@$published" version --prefer-online 2>/dev/null || true; })"
  if [ "$on_registry" = "$published" ]; then
    echo "clawock-dsh@$published is already on the registry — skipping npm publish (a re-run); the readback compares it to this build"
  else
    (cd "$PKG_DIR" && npm publish --access public "${provenance_args[@]}")
  fi
fi

if [ "$mode" = publish ]; then
  echo "clawock-dsh@$published published; the registry readback runs separately (--verify-only)"
  exit 0
fi

# Publishing "succeeded" is not evidence that the registry now holds this code.
# #712: npm's clawock-dsh@0.1.5 was a *different* build than the repo's 0.1.5 —
# same version number, two sets of files — and nobody noticed until a consumer
# installed a half-working plugin. So download what the registry actually
# serves and compare it to what was just packed.
#
# How long to wait, and how to ask. 0.3.0 (2026-09-29) is why both changed:
#   - the registry now accepts a publish before it serves it ("Your package is
#     being processed and may take a few minutes to become available"): the
#     PUT returned at 01:08:21Z, the packument's time for 0.3.0 is 01:10:59Z.
#     0.1.9 and 0.2.0 were served within a second. The old budget (5 x 10s)
#     gave up at 01:09:03 and turned a good publish red.
#   - a plain `npm pack <spec>` never asked again anyway: the first miss stores
#     the packument in npm's HTTP cache (`cache-control: max-age=300`), pacote
#     does not revalidate on ETARGET, so attempts 2..5 read the same stale copy
#     without touching the network. --prefer-online makes every attempt a
#     registry request.
#   - --silent hid npm's own reason (ETARGET) from the log; it is printed now.
echo "--- verifying the published tarball ---"
verify="$(mktemp -d)"
trap 'rm -rf "$verify"' EXIT
timeout_s="${DSH_READBACK_TIMEOUT_S:-900}"
interval_s="${DSH_READBACK_INTERVAL_S:-20}"
started=$SECONDS
attempt=1
while :; do
  set +e
  # --ignore-scripts: this is untrusted-by-construction downloaded content.
  out="$(npm pack "clawock-dsh@$published" --pack-destination "$verify" --ignore-scripts --prefer-online --loglevel=error 2>&1)"
  rc=$?
  set -e
  [ "$rc" -eq 0 ] && break
  reason="$(printf '%s\n' "$out" | grep '^npm error' | head -n 2 | tr '\n' ' ' || true)"
  waited=$((SECONDS - started))
  if [ "$waited" -ge "$timeout_s" ]; then
    printf '%s\n' "$out" >&2
    echo "::error::the registry still does not serve clawock-dsh@$published after ${waited}s and $attempt attempts (rc=$rc): ${reason:-no npm error line}"
    exit "$rc"
  fi
  echo "attempt $attempt (${waited}s): registry does not serve $published yet — ${reason:-rc=$rc}; retrying in ${interval_s}s" >&2
  attempt=$((attempt + 1))
  sleep "$interval_s"
done
echo "  registry serves $published (attempt $attempt, $((SECONDS - started))s after the readback started)"
tar -xzf "$verify/clawock-dsh-$published.tgz" -C "$verify"
EXPECTED_FILES="$expected" node -e '
const { readFileSync, existsSync } = require("node:fs");
const { createHash } = require("node:crypto");
const { join } = require("node:path");
const root = join(process.argv[1], "package");
const expected = JSON.parse(process.env.EXPECTED_FILES);
const problems = [];
for (const { path: file, sha256 } of expected) {
  if (!existsSync(join(root, file))) { problems.push(`published tarball is missing ${file}`); continue; }
  // package.json is compared field by field below (the registry may rewrite it).
  if (file === "package.json") continue;
  const served = createHash("sha256").update(readFileSync(join(root, file))).digest("hex");
  if (served !== sha256) problems.push(`published tarball has a different ${file}`);
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