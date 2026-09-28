"""ops/host/install_patrol_assets.sh: the reviewed patrol prompts and filing gate reach
/root/tools/clawock-patrol only through it, and the host's own steer and state never travel."""
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "ops/host/install_patrol_assets.sh"
SRC = ROOT / "ops/host/clawock-patrol"


def manifest():
    out = subprocess.run(
        ["bash", "-c", 'eval "$(sed -n "/^FILES=(/,/^)/p" "$1")"; printf "%s\\n" "${FILES[@]}"', "_",
         str(INSTALL)], capture_output=True, text=True, check=True).stdout
    return sorted(out.split())


def run(dest, *args):
    env = {**os.environ, "PATROL_TOOL_DIR": str(dest)}
    return subprocess.run(["bash", str(INSTALL), *args], env=env, capture_output=True, text=True,
                          timeout=60)


def test_the_manifest_is_every_shipped_file_and_nothing_host_local():
    shipped = sorted(str(p.relative_to(SRC)) for p in SRC.rglob("*")
                     if p.is_file() and "__pycache__" not in p.parts)
    assert manifest() == shipped
    for name in shipped:
        assert name != "steer.md" and not name.endswith(".before-update"), name
    # The supervisor has its own install and restart (ops/host/README.md § Patrol supervisor).
    assert "patrol.sh" not in shipped


def test_every_patrol_file_the_round_is_told_to_read_is_shipped():
    # A prompt that points the model at a file the install does not carry reads nothing.
    named = set()
    for name in manifest():
        if name.endswith((".md", ".tsv", ".sh", ".py")):
            named |= set(re.findall(r"/root/tools/clawock-patrol/([\w.-]+)", (SRC / name).read_text()))
    assert named, "no /root/tools/clawock-patrol/ references found: the pattern no longer matches"
    assert named - {"patrol.sh"} <= set(manifest()), sorted(named - set(manifest()))


def test_install_check_and_rollback(tmp_path):
    dest = tmp_path / "clawock-patrol"
    assert run(dest).returncode == 1          # no installation to update
    dest.mkdir()
    (dest / "round-prompt.md").write_text("old prompt\n")
    (dest / "steer.md").write_text("- kcn: keep me\n")
    (dest / "patrol.sh").write_text("#!/usr/bin/env bash\nsupervisor\n")
    assert run(dest, "--check").returncode == 1
    before = (dest / "round-prompt.md").stat().st_ino

    r = run(dest)
    assert r.returncode == 0, r.stderr
    for name in manifest():
        assert (dest / name).read_bytes() == (SRC / name).read_bytes(), name
    assert os.access(dest / "gate_issue.py", os.X_OK)
    assert not os.access(dest / "round-prompt.md", os.X_OK)
    # Replaced by rename, so a round mid-read keeps the file it opened.
    assert (dest / "round-prompt.md").stat().st_ino != before
    assert (dest / "round-prompt.md.before-update").read_text() == "old prompt\n"
    assert (dest / "steer.md").read_text() == "- kcn: keep me\n"
    assert (dest / "patrol.sh").read_text() == "#!/usr/bin/env bash\nsupervisor\n"
    assert run(dest, "--check").returncode == 0
    assert "already installed" in run(dest).stdout

    r = run(dest, "--rollback")
    assert r.returncode == 0, r.stderr
    assert (dest / "round-prompt.md").read_text() == "old prompt\n"
    assert not (dest / "gate_issue.py").exists()
    assert (dest / "steer.md").read_text() == "- kcn: keep me\n"
    assert "nothing to roll back" in run(dest, "--rollback").stdout
