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
PKG_DIR="$ROOT/examples/harness-agnostic/dsh-plugin"

version="${1:-}"

if [ -n "$version" ]; then
  (cd "$PKG_DIR" && npm version "$version" --no-git-tag-version)
fi

# Verify what will be shipped before touching the registry.
(cd "$PKG_DIR" && npm pack --dry-run >/dev/null)
test -f "$PKG_DIR/package.json"
test -f "$PKG_DIR/skills/investment-decision/SKILL.md"

(cd "$PKG_DIR" && npm publish --access public)

published="$(cd "$PKG_DIR" && node -p "require('./package.json').version")"
echo "clawock-dsh@$published published to https://www.npmjs.com/package/clawock-dsh"
