#!/usr/bin/env bash
# One complete clawock run with no harness at all: a literal stands in for the
# agent's answer. The harness-agnostic claim is that nothing in the loop below
# is owned by OpenClaw, Claude Code, Codex or any other runtime — the same
# script is the "agent side" of every harness example in this directory.
#
# Usage:
#   examples/harness-agnostic/run.sh              # install clawock from PyPI
#   examples/harness-agnostic/run.sh dist/*.whl   # install the artifact under test
set -euo pipefail

wheel="${1:-}"
workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

echo "==> installing into a clean virtualenv"
python3 -m venv "$workdir/venv"
if [ -n "$wheel" ]; then
  "$workdir/venv/bin/pip" install --quiet "$wheel"
else
  "$workdir/venv/bin/pip" install --quiet clawock
fi
clawock="$workdir/venv/bin/clawock"

iso() { env -i PATH=/usr/bin:/bin HOME="$workdir/home" "$@"; }
mkdir -p "$workdir/home" "$workdir/newuser"
cd "$workdir/newuser"

echo "==> clawock init"
iso "$clawock" init book
cd book
mkdir -p .clawock/work

echo "==> clawock run prepare"
# cwd is enough: clawock finds the workspace from the current directory.
# --workspace/CLAWOCK_WORKSPACE only matter when running from elsewhere.
iso "$clawock" run prepare > .clawock/work/request.json

# This is the entire harness surface. In the other examples in this directory,
# an OpenClaw skill, a Claude Code instruction or a DeepSeek Harness agent does
# exactly this one step: read request.json and write decision.json. Nothing
# else in the loop belongs to the harness.
#
# No workflow is pinned here (init without --workflow), so publish checks only
# the base loop and a literal "answer" artifact is enough. A pinned workflow
# (init --workflow investment-decision) instead refuses to publish a non-
# decision.json artifact — see the five harness files in this directory.
echo '{"answer":"smoke"}' > .clawock/work/answer.json

echo "==> clawock run publish"
iso "$clawock" run publish \
  --request .clawock/work/request.json \
  --artifact answer=.clawock/work/answer.json > receipt.json

echo "==> checking the receipt"
"$workdir/venv/bin/python" - <<'PY'
import json
receipt = json.load(open('receipt.json'))
assert receipt['status'] == 'published', receipt
assert len(receipt['generation_id']) == 32, receipt
names = {artifact['name'] for artifact in receipt['artifacts']}
assert {'answer', 'manifest.json'} <= names, names
print('harness-free run published', receipt['run_id'])
PY
