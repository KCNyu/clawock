"""The master pre-push hook requires a completed system-check verdict."""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "rc,blocks",
    [(0, False), (2, False), (1, True), (127, True), (137, True)],
    ids=["ok", "warnings", "critical", "interpreter-missing", "killed"],
)
def test_pre_push_hook_blocks_unless_the_checker_gave_a_verdict(tmp_path, rc, blocks):
    """RC=0/2 are verdicts (clean / warnings only). Anything else means the check
    never ran; treating that as a pass is the fail-open this suite exists for."""
    import os
    repo = tmp_path / "r"
    (repo / "scripts" / "data").mkdir(parents=True)
    (repo / "ops").mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "ops" / "system_check.py").write_text("")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # first invocation (system_check) exits rc; the integrity call after it exits 0
    stub = bin_dir / "python3"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        'case "$1" in *system_check.py) exit %d;; *) exit 0;; esac\n' % rc
    )
    stub.chmod(0o755)
    clawock = bin_dir / "clawock"
    clawock.write_text("#!/usr/bin/env bash\nexit 0\n")
    clawock.chmod(0o755)
    p = subprocess.run(
        ["bash", str(ROOT / ".githooks" / "pre-push")],
        cwd=repo, capture_output=True, text=True,
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert (p.returncode != 0) is blocks, p.stdout + p.stderr
