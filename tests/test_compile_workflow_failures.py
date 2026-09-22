"""Run the actual compile steps, including a failing pipeline producer."""
from pathlib import Path
import subprocess

import pytest

from workflow_contract_helpers import step_run


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(("workflow", "step", "directories"), [
    ("ci.yml", "Import-check all scripts", ("src", "ops", "site/tools")),
    ("weekly-health.yml", "Compile all scripts", ("src", "ops")),
])
@pytest.mark.parametrize("failure", [None, "missing-directory", "invalid-python"])
def test_compile_step_propagates_failures(tmp_path, workflow, step, directories, failure):
    for directory in directories:
        (tmp_path / directory).mkdir(parents=True)
    source = tmp_path / "src" / "example.py"
    source.write_text("value = 1\n" if failure != "invalid-python" else "def broken(\n")
    if failure == "missing-directory":
        (tmp_path / "ops").rmdir()

    # Unspecified Linux Actions shell is bash -e (without implicit pipefail).
    result = subprocess.run(
        ["bash", "-e", "-c", step_run(ROOT / ".github/workflows" / workflow, step)],
        cwd=tmp_path, capture_output=True, text=True,
    )
    if failure:
        assert result.returncode != 0, result.stdout + result.stderr
        assert ("find:" if failure == "missing-directory" else "SyntaxError") in result.stderr
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert list((source.parent / "__pycache__").glob("example.*.pyc"))
