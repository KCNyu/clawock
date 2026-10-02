"""The generation force-pushed to the public data branch is credential-scanned.

It never passes `safe_push.sh` or CI, and the pre-push hook used to exit before
its scan for any ref other than master, so this was the one push in the
repository that nothing looked at (#2335).
"""
import importlib.util
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Assembled at runtime: a literal would trip the scan this file is about.
TOKEN = "tvly-" + "A1b2C3d4E5f6G7h8I9j0K1l2"


def _publisher():
    spec = importlib.util.spec_from_file_location(
        "publish_data_branch_scan", ROOT / "ops/publish/publish_data_branch.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_publisher_names_the_file_and_kind_but_not_the_value():
    publisher = _publisher()
    assert publisher.credential_findings({"assets/data/a.json": '{"ok": 1}'}) == []
    findings = publisher.credential_findings({
        "assets/data/a.json": '{"ok": 1}',
        "assets/data/workflow-outcomes.json": '{"detail": "%s"}' % TOKEN,
    })
    assert len(findings) == 1
    assert findings[0].startswith("assets/data/workflow-outcomes.json: ")
    assert TOKEN not in findings[0]


def _git(repo, *args, input=None):
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True, input=input).stdout.strip()


def _generation(repo, text):
    """A parentless commit holding one payload, as the data-plane store makes."""
    blob = _git(repo, "hash-object", "-w", "--stdin", input=text)
    tree = _git(repo, "mktree", input=f"100644 blob {blob}\tdashboard.json\n")
    return _git(repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                "commit-tree", tree, "-m", "generation")


def _push(repo, commit, ref="refs/heads/data-plane"):
    return subprocess.run(
        ["bash", str(ROOT / ".githooks" / "pre-push")], cwd=repo,
        capture_output=True, text=True,
        input=f"refs/heads/x {commit} {ref} {'0' * 40}\n")


def test_the_hook_scans_a_data_plane_generation(tmp_path):
    _git(tmp_path, "init", "-q")
    scanner = tmp_path / "ops" / "ci" / "commit_secret_scan.py"
    scanner.parent.mkdir(parents=True)
    scanner.write_text((ROOT / "ops/ci/commit_secret_scan.py").read_text())

    clean = _push(tmp_path, _generation(tmp_path, '{"ok": 1}\n'))
    assert clean.returncode == 0, clean.stdout + clean.stderr

    leaked = _push(tmp_path, _generation(tmp_path, '{"detail": "%s"}\n' % TOKEN))
    assert leaked.returncode == 1
    assert "refs/heads/data-plane update failed credential scan" in leaked.stdout
    assert TOKEN not in leaked.stdout + leaked.stderr
