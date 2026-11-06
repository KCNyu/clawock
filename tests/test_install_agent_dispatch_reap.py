"""The reap timer installer: atomic unit files, an enabled timer, drift and removal."""
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "ops/host/install_agent_dispatch_reap.sh"


def run(tmp_path, *args):
    systemctl = tmp_path / "systemctl"
    systemctl.write_text(f"""#!/bin/sh
echo "$*" >>"{tmp_path}/calls"
exit 0
""")
    systemctl.chmod(0o755)
    env = {**os.environ, "AGENT_DISPATCH_UNIT_DIR": str(tmp_path / "units"),
           "AGENT_DISPATCH_SYSTEMCTL": str(systemctl)}
    (tmp_path / "units").mkdir(exist_ok=True)
    return subprocess.run(["bash", str(INSTALL), *args], env=env, capture_output=True, text=True, timeout=60)


def test_install_check_drift_and_uninstall(tmp_path):
    r = run(tmp_path)
    assert r.returncode == 0, r.stderr
    for name in ("agent-dispatch-reap.service", "agent-dispatch-reap.timer"):
        assert (tmp_path / "units" / name).read_bytes() == (ROOT / "ops/host" / name).read_bytes()
    calls = (tmp_path / "calls").read_text()
    assert "daemon-reload" in calls and "enable --now agent-dispatch-reap.timer" in calls
    assert run(tmp_path, "--check").returncode == 0
    (tmp_path / "units" / "agent-dispatch-reap.timer").write_text("[Timer]\n")
    assert run(tmp_path, "--check").returncode == 1
    r = run(tmp_path, "--uninstall")
    assert r.returncode == 0, r.stderr
    assert not (tmp_path / "units" / "agent-dispatch-reap.timer").exists()
    assert not (tmp_path / "units" / "agent-dispatch-reap.service").exists()
