#!/usr/bin/env bash
# One complete clawock run, from an installed wheel, with nothing else present.
#
# This is the acceptance check for #379 and the last box of #420, and it is a
# file rather than a workflow step on purpose: the claim is "a stranger can
# install the package and finish a run without this repository", and a snippet
# buried in release.yml is not something a stranger can execute. `release.yml`
# invokes this script, so what CI proves and what a reader can run are the same
# thing rather than two copies that drift.
#
# `env -i` is the whole point. It clears the environment for every clawock call,
# so a pass cannot come from a variable this machine happens to export — the
# failure mode that makes "works on my box" survive all the way to a user.
#
# Usage:
#   examples/minimal-run/run.sh                 # install clawock from PyPI
#   examples/minimal-run/run.sh dist/*.whl      # install the artifact under test
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

# HOME is redirected too: a run must not read the caller's dotfiles, and this is
# also what lets the script work on a machine that has a real clawock workspace.
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

# Stands in for the agent's answer. A real runtime writes its model output here;
# the package's job is to certify and publish whatever it is handed, so a literal
# is enough to exercise every gate this example is about.
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
print('isolated run published', receipt['run_id'])
PY
