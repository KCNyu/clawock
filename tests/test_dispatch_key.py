"""dispatch.sh --key: one task per stable key, --force, TTL and the 30-day cleanup."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
DISPATCH = ROOT / "ops/host/agent-dispatch/dispatch.sh"


@pytest.fixture
def q(tmp_path):
    base, bin_dir = tmp_path / "base", tmp_path / "bin"
    base.mkdir()
    bin_dir.mkdir()
    (bin_dir / "systemd-run").write_text('#!/bin/sh\necho "$*" >>"${FAKE_DIR}/systemd-run.calls"\nexit 0\n')
    (bin_dir / "systemctl").write_text(
        '#!/bin/sh\ncase "$1" in is-active) grep -qx "$2" "${FAKE_DIR}/active" 2>/dev/null '
        '&& echo active || echo inactive ;; esac\nexit 0\n')
    for path in bin_dir.iterdir():
        path.chmod(0o755)
    (tmp_path / "active").write_text("")
    prompt = tmp_path / "prompt.md"
    prompt.write_text("do the thing\n")
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}",
           "FAKE_DIR": str(tmp_path), "AGENT_DISPATCH_BASE": str(base),
           "AGENT_DISPATCH_ORIGIN_SESSION": "none"}
    for name in ("AGENT_DISPATCH_TASK_ID", "AGENT_DISPATCH_MANDATE",
                 "AGENT_DISPATCH_PARENT_TASK_ID", "AGENT_DISPATCH_PATROL"):
        env.pop(name, None)
    return {"base": base, "prompt": prompt, "env": env, "root": tmp_path}


def lay(q, *args):
    return subprocess.run(["bash", str(DISPATCH), "dsh", "--name", "key-task",
                           "--prompt-file", str(q["prompt"]), *args],
                          env=q["env"], capture_output=True, text=True, timeout=60)


def dispatched(r) -> str:
    return next(line.split(" ", 1)[1] for line in r.stdout.splitlines() if line.startswith("dispatched "))


def key_file(q, key: str) -> Path:
    return q["base"] / ".keys" / (hashlib.sha256(key.encode()).hexdigest() + ".json")


def task_dirs(q):
    return sorted(p.name for p in q["base"].iterdir() if p.is_dir() and p.name != ".keys")


def test_one_task_per_key_and_force_dispatches_again(q):
    r = lay(q, "--key", "cron-slot-1")
    assert r.returncode == 0, r.stderr
    first = dispatched(r)
    data = json.loads(key_file(q, "cron-slot-1").read_text())
    assert set(data) == {"hash", "task_id", "created", "created_epoch"}
    assert data["task_id"] == first
    assert "cron-slot-1" not in key_file(q, "cron-slot-1").read_text()

    r = lay(q, "--key", "cron-slot-1")
    assert r.returncode == 3
    assert first in r.stdout
    assert task_dirs(q) == [first]

    time.sleep(1.1)
    r = lay(q, "--key", "cron-slot-1", "--force")
    assert r.returncode == 0, r.stderr
    second = dispatched(r)
    assert second != first and len(task_dirs(q)) == 2
    assert json.loads(key_file(q, "cron-slot-1").read_text())["task_id"] == second


def test_two_concurrent_callers_only_one_dispatches(q):
    procs = [subprocess.Popen(["bash", str(DISPATCH), "dsh", "--name", "key-task",
                               "--prompt-file", str(q["prompt"]), "--key", "race"],
                              env=q["env"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
             for _ in range(2)]
    results = [(p.wait(timeout=60), p.stdout.read()) for p in procs]
    assert sorted(rc for rc, _ in results) == [0, 3], results
    assert len(task_dirs(q)) == 1


def test_a_live_task_blocks_but_a_dead_or_old_one_does_not(q):
    r = lay(q, "--key", "k1")
    first = dispatched(r)
    (q["base"] / first / "result.env").write_text("STATE=running\nUPDATED='2026-01-01 00:00:00'\n")
    (q["root"] / "active").write_text(f"agent-dispatch-{first}.service\n")
    assert lay(q, "--key", "k1").returncode == 3

    # The unit is gone: the same state is not "alive"; a new dispatch is allowed.
    (q["root"] / "active").write_text("")
    time.sleep(1.1)
    r = lay(q, "--key", "k1")
    assert r.returncode == 0, r.stderr
    assert len(task_dirs(q)) == 2

    # A success within the TTL blocks; an old success does not.
    second = dispatched(r)
    (q["base"] / second / "result.env").write_text("STATE=ok\n")
    assert lay(q, "--key", "k1").returncode == 3
    data = json.loads(key_file(q, "k1").read_text())
    data["created_epoch"] = int(time.time()) - 90000
    key_file(q, "k1").write_text(json.dumps(data))
    time.sleep(1.1)
    assert lay(q, "--key", "k1").returncode == 0


def test_failed_task_can_be_redispatched_and_force_needs_a_key(q):
    r = lay(q, "--key", "k2")
    first = dispatched(r)
    (q["base"] / first / "result.env").write_text("STATE=failed\n")
    time.sleep(1.1)
    r = lay(q, "--key", "k2")
    assert r.returncode == 0, r.stderr
    assert len(task_dirs(q)) == 2
    assert lay(q, "--force").returncode == 2


def test_keys_older_than_30_days_are_cleaned_up(q):
    old = key_file(q, "old-key")
    old.parent.mkdir(parents=True)
    old.write_text('{"hash": "x", "task_id": "gone", "created": "old", "created_epoch": 1}\n')
    stamp = time.time() - 40 * 86400
    os.utime(old, (stamp, stamp))
    r = lay(q, "--key", "fresh-key")
    assert r.returncode == 0, r.stderr
    assert not old.exists()
    assert key_file(q, "fresh-key").exists()


def freeze_id_clock(q):
    date = q["root"] / "bin" / "date"
    date.write_text('#!/bin/sh\nif [ "$1" = +%Y%m%d-%H%M%S ]; then echo 20261106-120000; '
                    'else exec /usr/bin/date "$@"; fi\n')
    date.chmod(0o755)


def test_force_in_same_second_preserves_the_previous_task(q):
    freeze_id_clock(q)
    first = dispatched(lay(q, "--key", "same-second"))
    before = (q["base"] / first / "prompt.md").read_bytes()
    q["prompt"].write_text("a different task\n")
    r = lay(q, "--key", "same-second", "--force")
    assert r.returncode == 0, r.stderr
    assert dispatched(r) != first
    assert (q["base"] / first / "prompt.md").read_bytes() == before
    assert len(task_dirs(q)) == 2


def test_failed_old_claim_cannot_remove_forced_replacement(q):
    freeze_id_clock(q)
    # Hold the first caller at stdin, after its claim but before prompt validation.
    first = subprocess.Popen(["bash", str(DISPATCH), "dsh", "--name", "key-task", "--key", "race"],
                             env=q["env"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
    try:
        end = time.monotonic() + 5
        while not key_file(q, "race").exists() and time.monotonic() < end:
            time.sleep(0.01)
        assert key_file(q, "race").exists()
        r = lay(q, "--key", "race", "--force")
        assert r.returncode == 0, r.stderr
        second = dispatched(r)
        first.communicate("", timeout=5)
        assert first.returncode == 2
        assert json.loads(key_file(q, "race").read_text())["task_id"] == second
        assert lay(q, "--key", "race").returncode == 3
        assert (q["base"] / second / "meta.env").exists()
    finally:
        if first.poll() is None:
            first.kill()
            first.wait()


def test_launch_failure_releases_key_immediately(q):
    launch = q["root"] / "bin" / "systemd-run"
    launch.write_text("#!/bin/sh\nexit 1\n")
    r = lay(q, "--key", "launch-failure")
    assert r.returncode == 1
    assert not key_file(q, "launch-failure").exists()
    launch.write_text("#!/bin/sh\nexit 0\n")
    assert lay(q, "--key", "launch-failure").returncode == 0
