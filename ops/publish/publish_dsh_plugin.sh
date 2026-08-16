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
PKG_DIR="$ROOT/examples/dsh/plugin"

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
(cd "$PKG_DIR" && npm install --include=dev --no-audit --no-fund >/dev/null && npm run build)

# Verify what will be shipped before touching the registry.
(cd "$PKG_DIR" && npm pack --dry-run >/dev/null)
test -f "$PKG_DIR/package.json"
test -f "$PKG_DIR/skills/investment-decision/SKILL.md"
test -f "$PKG_DIR/lib/typert.remote-client.js"

(cd "$PKG_DIR" && npm publish --access public)

published="$(cd "$PKG_DIR" && node -p "require('./package.json').version")"
echo "clawock-dsh@$published published to https://www.npmjs.com/package/clawock-dsh"
