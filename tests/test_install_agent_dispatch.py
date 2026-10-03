"""ops/host/install_agent_dispatch.sh: the versioned runner reaches /root/tools/agent-dispatch
only through it, and what stays on the host never travels with it."""
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "ops/host/install_agent_dispatch.sh"
SRC = ROOT / "ops/host/agent-dispatch"
LIMITS = ("MAX_RUNNING_CLAUDE=1\nMAX_RUNNING_CODEX=1\nMAX_RUNNING_OPENCODE=1\n"
          "PATROL_MIN_AVAILABLE_KB=1\nPATROL_MAX_MEMORY_FULL_AVG60=10\nQUEUE_FAIR_WAIT_SEC=14400\n")


def manifest():
    out = subprocess.run(
        ["bash", "-c", 'eval "$(sed -n "/^FILES=(/,/^)/p" "$1")"; printf "%s\\n" "${FILES[@]}"', "_",
         str(INSTALL)], capture_output=True, text=True, check=True).stdout
    return sorted(out.split())


def run(dest, *args):
    env = {**os.environ, "AGENT_DISPATCH_DIR": str(dest)}
    return subprocess.run(["bash", str(INSTALL), *args], env=env, capture_output=True, text=True,
                          timeout=60)


def test_the_manifest_is_every_shipped_file_and_nothing_host_local():
    shipped = sorted(str(p.relative_to(SRC)) for p in SRC.rglob("*")
                     if p.is_file() and "__pycache__" not in p.parts)
    assert manifest() == shipped
    for name in shipped:
        assert name not in ("notify.env", "limits.env") and not name.endswith(".before-update"), name
    # The ops entry has its own installer and stays where it is.
    assert "task_queue_ops.py" not in shipped and "model_prices.json" not in shipped


def test_install_check_and_rollback(tmp_path):
    dest = tmp_path / "agent-dispatch"
    dest.mkdir()
    # No host policy yet: nothing is installed.
    r = run(dest)
    assert r.returncode == 1 and "limits.env" in r.stderr
    assert not (dest / "run-agent.sh").exists()

    (dest / "limits.env").write_text(LIMITS)
    (dest / "run-agent.sh").write_text("#!/usr/bin/env bash\nold\n")
    (dest / "dispatch.sh.before-update").write_text("from an older hand edit\n")
    (dest / "notify.env").write_text("NOTIFY_TARGET=keep-me\n")
    assert run(dest, "--check").returncode == 1
    before = (dest / "run-agent.sh").stat().st_ino

    r = run(dest)
    assert r.returncode == 0, r.stderr
    for name in manifest():
        assert (dest / name).read_bytes() == (SRC / name).read_bytes(), name
    assert os.access(dest / "run-agent.sh", os.X_OK)
    assert not os.access(dest / "templates/review.md", os.X_OK)
    # Replaced by rename, so a running runner keeps reading the file it opened.
    assert (dest / "run-agent.sh").stat().st_ino != before
    assert (dest / "run-agent.sh.before-update").read_text() == "#!/usr/bin/env bash\nold\n"
    assert (dest / "limits.env").read_text() == LIMITS
    assert (dest / "notify.env").read_text() == "NOTIFY_TARGET=keep-me\n"
    assert run(dest, "--check").returncode == 0
    assert "already installed" in run(dest).stdout

    # Rollback undoes that install only: the replaced runner comes back, the files it created go,
    # and an unrelated older .before-update is not resurrected.
    r = run(dest, "--rollback")
    assert r.returncode == 0, r.stderr
    assert (dest / "run-agent.sh").read_text() == "#!/usr/bin/env bash\nold\n"
    assert not (dest / "dispatch.sh").exists()
    assert (dest / "limits.env").read_text() == LIMITS
    assert "nothing to roll back" in run(dest, "--rollback").stdout


def test_check_names_a_limits_key_the_host_lacks(tmp_path):
    dest = tmp_path / "agent-dispatch"
    dest.mkdir()
    (dest / "limits.env").write_text(LIMITS)
    assert run(dest).returncode == 0
    (dest / "limits.env").write_text(LIMITS.replace("QUEUE_FAIR_WAIT_SEC=14400\n", ""))
    r = run(dest, "--check")
    assert r.returncode == 3 and "QUEUE_FAIR_WAIT_SEC" in r.stderr
    assert run(dest, "--check-files").returncode == 0
