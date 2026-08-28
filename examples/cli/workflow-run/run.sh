#!/usr/bin/env bash
# The README headline, executed: a stranger installs the package, installs the
# decision workflow into their OWN directory, and publishes a real
# `decision.json` — with this repository nowhere in the picture.
#
# `cli/minimal-run/run.sh` already proves the *base* loop from a wheel, but it
# runs `init` with no workflow pinned and publishes a literal `{"answer":"smoke"}`.
# That leaves the part the product is actually sold on unproven (#1111): that
# `clawock workflow install investment-decision` ships the pack, its example
# artifact and its validators inside the wheel, and that the contract gates fire
# in a foreign workspace rather than only in this checkout's test suite.
#
# So this script asserts both directions:
#   • a valid decision publishes             -> status: published
#   • a decision with its opposing case cut   -> status: rejected, non-zero exit,
#     naming `insufficient_opposing_evidence` and `unsupported_bear_case`
#
# The negative half is the one that matters. A gate that only exists in
# `tests/test_portable_workflow.py` is a promise about this repository; the same
# gate refusing a bad decision from an installed wheel, in `/tmp`, under `env -i`,
# is a promise about the package.
#
# `env -i` clears the environment for every clawock call (and redirects HOME), so
# a pass cannot come from a variable this machine happens to export — including a
# PYTHONPATH or CLAWOCK_WORKSPACE pointing back at a checkout.
#
# Usage:
#   examples/cli/workflow-run/run.sh                 # install clawock from PyPI
#   examples/cli/workflow-run/run.sh dist/*.whl      # install the artifact under test
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
python="$workdir/venv/bin/python"

iso() { env -i PATH=/usr/bin:/bin HOME="$workdir/home" "$@"; }
mkdir -p "$workdir/home" "$workdir/newuser"
cd "$workdir/newuser"

echo "==> the clawock under test is the installed one, not a source tree"
# Cheap, but it is the assumption every assertion below rests on: if the import
# resolved to a checkout (a stray .pth, a PYTHONPATH), this script would be
# testing the repository while claiming to test the package.
iso "$python" - "$workdir/venv" <<'PY'
import sys, clawock
venv = sys.argv[1]
assert clawock.__file__.startswith(venv), f"clawock imported from {clawock.__file__}, not {venv}"
print("   ", clawock.__file__)
PY

echo "==> clawock workflow install investment-decision"
# Installs into a directory that is not yet a workspace, exactly as README's
# "Run it on your own book" orders the two commands.
iso "$clawock" workflow install investment-decision --workspace book > install.json
"$python" - <<'PY'
import json, pathlib
report = json.load(open('install.json'))
assert report['workflow'] == 'investment-decision', report
skill = pathlib.Path(report['skill'])
assert skill.is_file(), skill
# The agent-facing example ships with the pack: without it a stranger has no
# shape to fill in, and "any harness works" would still require this repository.
example = skill.parent / 'assets' / 'decision.example.json'
assert example.is_file(), example
print('    pack installed at', skill.parent)
PY

echo "==> clawock init --workflow investment-decision"
iso "$clawock" init book --workflow investment-decision
cd book
mkdir -p .clawock/work

echo "==> clawock run prepare"
iso "$clawock" run prepare > .clawock/work/request.json

# The agent's answer. A real runtime writes model output here; the packaged
# example stands in, and it comes from the INSTALLED pack rather than from this
# repository — copying it out of the checkout would quietly reintroduce the
# dependency this script exists to rule out.
cp .agents/skills/investment-decision/assets/decision.example.json decision.json

echo "==> clawock run publish (valid decision)"
iso "$clawock" run publish \
  --request .clawock/work/request.json \
  --artifact decision.json=decision.json > receipt.json

"$python" - <<'PY'
import json
receipt = json.load(open('receipt.json'))
assert receipt['status'] == 'published', receipt
assert receipt['workflow']['id'] == 'investment-decision', receipt
names = {artifact['name'] for artifact in receipt['artifacts']}
assert {'decision.json', 'manifest.json'} <= names, names
print('    published', receipt['run_id'], 'workflow', receipt['workflow']['version'])
PY

echo "==> clawock run publish (opposing case removed) must be refused"
# A fresh run: a request is consumed by the publish it certified.
iso "$clawock" run prepare > .clawock/work/request2.json
"$python" - <<'PY'
import json
decision = json.load(open('decision.json'))
decision['evidence'] = [row for row in decision['evidence'] if row['stance'] != 'opposing']
decision['debate']['bear_case']['evidence_ids'] = ['filing-growth']
json.dump(decision, open('one-sided.json', 'w'))
PY

status=0
iso "$clawock" run publish \
  --request .clawock/work/request2.json \
  --artifact decision.json=one-sided.json > rejected.json || status=$?
[ "$status" -ne 0 ] || {
  echo "a one-sided decision published from an installed wheel — the contract gate is not in the package" >&2
  exit 1
}

"$python" - <<'PY'
import json
receipt = json.load(open('rejected.json'))
assert receipt['status'] == 'rejected', receipt
codes = {issue['code'] for issue in receipt['validation_issues']}
assert {'insufficient_opposing_evidence', 'unsupported_bear_case'} <= codes, codes
assert receipt['publish']['receipt'] is None and receipt['publish']['changed'] is False, receipt
print('    refused:', sorted(codes))
PY

echo "foreign-workspace workflow run OK"
