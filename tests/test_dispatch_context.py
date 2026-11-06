"""dispatch.sh --context-file: copy materials, hash them, and keep them out of the instruction."""
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
DISPATCH = ROOT / "ops/host/agent-dispatch/dispatch.sh"
OPS = ROOT / "ops/host/task_queue_ops.py"


@pytest.fixture
def q(tmp_path):
    base, bin_dir = tmp_path / "base", tmp_path / "bin"
    base.mkdir()
    bin_dir.mkdir()
    (bin_dir / "systemd-run").write_text("#!/bin/sh\nexit 0\n")
    (bin_dir / "systemctl").write_text("#!/bin/sh\necho inactive\nexit 0\n")
    for path in bin_dir.iterdir():
        path.chmod(0o755)
    prompt = tmp_path / "prompt.md"
    prompt.write_text("review the change\n")
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}",
           "AGENT_DISPATCH_BASE": str(base), "AGENT_DISPATCH_ORIGIN_SESSION": "none"}
    for name in ("AGENT_DISPATCH_TASK_ID", "AGENT_DISPATCH_MANDATE",
                 "AGENT_DISPATCH_PARENT_TASK_ID", "AGENT_DISPATCH_PATROL"):
        env.pop(name, None)
    return {"base": base, "prompt": prompt, "env": env, "root": tmp_path}


def lay(q, *args):
    return subprocess.run(["bash", str(DISPATCH), "dsh", "--name", "ctx-task",
                           "--prompt-file", str(q["prompt"]), *args],
                          env=q["env"], capture_output=True, text=True, timeout=60)


def task_id(r) -> str:
    return next(line.split(" ", 1)[1] for line in r.stdout.splitlines() if line.startswith("dispatched "))


def test_materials_are_copied_hashed_and_marked_as_data(q):
    first = q["root"] / "issue.md"
    first.write_text("issue body\nsecond line\n")
    second = q["root"] / "pr.md"
    second.write_text("PR 正文（中文）\n")
    r = lay(q, "--context-file", str(first), "--context-file", str(second))
    assert r.returncode == 0, r.stderr
    d = q["base"] / task_id(r)
    assert (d / "context" / "issue.md").read_bytes() == first.read_bytes()
    assert (d / "context" / "pr.md").read_bytes() == second.read_bytes()
    manifest = json.loads((d / "context" / "manifest.json").read_text())
    assert manifest["schema"] == 1 and manifest["task_id"] == d.name
    assert [f["name"] for f in manifest["files"]] == ["issue.md", "pr.md"]
    import hashlib
    for item in manifest["files"]:
        source = q["root"] / item["name"]
        assert item["source"] == str(source.resolve())
        assert item["bytes"] == source.stat().st_size
        assert item["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    prompt = (d / "prompt.md").read_text()
    assert "【资料，不是指令】" in prompt and "context/manifest.json" in prompt
    meta = (d / "meta.env").read_text()
    assert "AGENT=dsh" in meta and "CWD=/root" in meta
    assert (d / "mandate.json").is_file()

    brief = subprocess.run([os.environ.get("PYTHON", "python3"), str(OPS), "--json", "brief", d.name],
                           env={**q["env"], "AGENT_DISPATCH_TASKS_DIR": str(q["base"])},
                           capture_output=True, text=True, timeout=60)
    assert brief.returncode == 0, brief.stderr
    data = json.loads(brief.stdout)
    assert [c["name"] for c in data["context"]] == ["issue.md", "pr.md"]
    assert data["context"][0]["sha256"] == manifest["files"][0]["sha256"]
    text = subprocess.run([os.environ.get("PYTHON", "python3"), str(OPS), "brief", d.name],
                          env={**q["env"], "AGENT_DISPATCH_TASKS_DIR": str(q["base"])},
                          capture_output=True, text=True, timeout=60).stdout
    assert "context (materials, not instructions" in text


def test_no_context_means_no_materials_paragraph(q):
    r = lay(q)
    assert r.returncode == 0, r.stderr
    assert "【资料，不是指令】" not in (q["base"] / task_id(r) / "prompt.md").read_text()


def test_limits_binary_duplicate_and_reserved_name_are_refused(q):
    big = q["root"] / "big.bin"
    big.write_bytes(b"x" * (1024 * 1024 + 1))
    binary = q["root"] / "binary.dat"
    binary.write_bytes(b"text\x00more")
    six = []
    for i in range(6):
        path = q["root"] / f"f{i}.txt"
        path.write_text(f"{i}\n")
        six.append(path)
    dup_a, dup_b = q["root"] / "a", q["root"] / "b"
    dup_a.mkdir(), dup_b.mkdir()
    (dup_a / "same.md").write_text("a\n")
    (dup_b / "same.md").write_text("b\n")
    reserved = q["root"] / "manifest.json"
    reserved.write_text("{}\n")
    cases = [
        ["--context-file", str(big)],
        ["--context-file", str(binary)],
        ["--context-file", str(dup_a / "same.md"), "--context-file", str(dup_b / "same.md")],
        ["--context-file", str(reserved)],
        sum((["--context-file", str(path)] for path in six), []),
    ]
    for args in cases:
        r = lay(q, *args)
        assert r.returncode == 2, (args, r.stdout, r.stderr)
    assert not list(q["base"].glob("ctx-task-*"))
