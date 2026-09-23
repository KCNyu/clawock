"""Run every `Detect code changes` step, including a crashing classifier.

Each step pipes ops/ci/push_scope.py into `tee -a "$GITHUB_OUTPUT"`, and a dozen
`steps.changes.outputs.* == 'true'` gates read what it wrote. Under the default
`bash -e` shell a crashing producer used to exit 0 through `tee`, write no lanes
at all, and skip every gated suite while the job stayed green (#1774).
"""
import os
from pathlib import Path
import subprocess

import pytest

from workflow_contract_helpers import steps, strip_hash_comments


ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / ".github/workflows/ci.yml"
BOGUS_SHA = "0" * 39 + "1"


def _detector_runs():
    lines = CI.read_text().splitlines()
    runs = []
    for start, name in steps(CI):
        if name != "Detect code changes":
            continue
        indent = len(lines[start]) - len(lines[start].lstrip())
        body = []
        in_run = False
        for line in lines[start + 1:]:
            if line.startswith(" " * indent + "- "):
                break
            if line.strip() == "run: |":
                in_run = True
                continue
            if in_run:
                if line.strip() and not line.startswith(" " * (indent + 4)):
                    break
                body.append(line)
        runs.append((start + 1, strip_hash_comments("\n".join(body))))
    return runs


def test_there_are_detectors_to_check():
    assert len(_detector_runs()) == 3


@pytest.mark.parametrize(("line", "script"), [
    pytest.param(line, script, id=f"ci.yml:{line}") for line, script in _detector_runs()
])
@pytest.mark.parametrize("head", ["HEAD", BOGUS_SHA])
def test_detector_fails_when_the_classifier_crashes(tmp_path, line, script, head):
    output = tmp_path / "github_output"
    output.touch()
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True, check=True).stdout.strip()
    # Unspecified Linux Actions shell is bash -e (without implicit pipefail).
    result = subprocess.run(
        ["bash", "-e", "-c", "cd \"$0\" && " + script, str(ROOT)],
        env=dict(os.environ, BASE_SHA=base, HEAD_SHA=head, GITHUB_OUTPUT=str(output)),
        capture_output=True, text=True,
    )
    if head == BOGUS_SHA:
        assert result.returncode != 0, f"ci.yml:{line} swallowed a crash\n{result.stderr}"
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert "code=" in output.read_text()
