"""Reviewed dreaming candidates become public store topics and regenerate MEMORY.md."""
from datetime import date
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PROMOTE = ROOT / "ops/host/promote_dreaming.py"
PUBLISH = ROOT / "ops/host/shared-memory/scripts/publish.py"


def topic(slug, body, *, order=1, separator="false", publish="public"):
    return f"""---
name: {slug}
description: "{slug} hook"
metadata:
  type: feedback
  updated: 2026-11-07
  scope: memory
  salience: normal
  status: verified
  publish: {publish}
  agent: test
  order: {order}
  separator: {separator}
---

{body.rstrip()}
"""


def candidate(text, source="memory/2026-11-07.md", line=3):
    return (f"## Promoted From Short-Term Memory (2026-11-08)\n\n"
            f"<!-- openclaw-memory-promotion:memory:{source}:{line}:{line + 1} -->\n"
            f"- {text} [score=0.9 source={source}:{line}-{line + 1}]\n")


def key(source, line):
    return f"memory:{source}:{line}:{line + 1}"


def receipt(text, conclusion="Read the primary source before treating a summary as evidence."):
    import hashlib
    return {"sha256": hashlib.sha256(text.encode()).hexdigest(), "reviewer": "test reviewer",
            "rationale": "checked the source", "durable": True,
            "reviewed_on": date.today().isoformat(), "conclusion": conclusion}


def write_candidate(workspace, text, approval=True, conclusion=None):
    private = workspace / "memory/.dreams"
    private.mkdir(parents=True, exist_ok=True)
    (private / "promotion-candidates.md").write_text(candidate(text), encoding="utf-8")
    if approval:
        row = receipt(text, conclusion or receipt(text)["conclusion"])
        (private / "promotion-approvals.json").write_text(
            json.dumps({key("memory/2026-11-07.md", 3): row}), encoding="utf-8")


def memctl_stub(tmp_path):
    log = tmp_path / "memctl.log"
    script = tmp_path / "memctl"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "with open(os.environ['MEMCTL_LOG'], 'a', encoding='utf-8') as stream:\n"
        "    stream.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "raise SystemExit(0)\n", encoding="utf-8")
    script.chmod(0o755)
    return script, log


def make_store(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    (store / "MEMORY.md").write_text("# Shared memory index\n\n- `indexes/MEMORY-host.md` — host index\n", encoding="utf-8")
    (store / "indexes").mkdir()
    (store / "indexes/MEMORY-host.md").write_text(
        "# Host\n\n- `feedback-existing.md` — existing public section\n", encoding="utf-8")
    (store / "indexes/routes.tsv").write_text("*\tindexes/MEMORY-host.md\n", encoding="utf-8")
    (store / "feedback-existing.md").write_text(
        topic("feedback-existing", "## Existing\n\n- keep this section"), encoding="utf-8")
    return store


def make_workspace(tmp_path, store):
    workspace = tmp_path / "workspace"
    (workspace / "memory/.dreams").mkdir(parents=True)
    (workspace / "ops/host/shared-memory").mkdir(parents=True)
    subprocess.run([sys.executable, str(PUBLISH), "--write", "--repo", str(workspace),
                    "--store", str(store)], check=True, capture_output=True, text=True)
    return workspace


def run_promote(workspace, store, memctl, log, *extra, env_extra=None):
    env = {**os.environ, "SHARED_MEMORY_DIR": str(store),
           "SHARED_MEMORY_STATE": str(workspace.parent / "state"),
           "SHARED_MEMORY_MEMCTL": str(memctl), "MEMCTL_LOG": str(log)}
    env.update(env_extra or {})
    return subprocess.run([sys.executable, str(PROMOTE), "--workspace", str(workspace),
                           "--store", str(store), *extra],
                          capture_output=True, text=True, env=env)


def check_store(workspace, store):
    return subprocess.run([sys.executable, str(PUBLISH), "--check", "--repo", str(workspace),
                           "--store", str(store)], capture_output=True, text=True)


def calls(log):
    if not log.is_file():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line]


def test_promotion_writes_a_public_topic_and_regenerates_memory(tmp_path):
    store = make_store(tmp_path)
    workspace = make_workspace(tmp_path, store)
    memctl, log = memctl_stub(tmp_path)
    text = "Read the primary source before treating a summary as evidence."
    write_candidate(workspace, text)

    proc = run_promote(workspace, store, memctl, log)
    assert proc.returncode == 0, proc.stderr + proc.stdout

    path = store / "lessons-dreaming-2026-11-07-3-4.md"
    written = path.read_text(encoding="utf-8")
    assert "publish: public" in written
    assert "order: 2" in written
    assert "separator: true" in written
    assert "<!-- openclaw-memory-promotion:memory:memory/2026-11-07.md:3:4 -->" in written
    assert text in written
    assert "- Source: memory/2026-11-07.md:3-4 (reviewed " in written

    memory = (workspace / "MEMORY.md").read_text(encoding="utf-8")
    assert "## Existing" in memory
    assert "## Dreaming 晋升 2026-11-07（3-4）" in memory
    assert text in memory
    assert memory.count("## Existing") == 1

    checked = check_store(workspace, store)
    assert checked.returncode == 0, checked.stderr
    verbs = [row[0] for row in calls(log)]
    assert "snapshot" in verbs
    assert "verify" in verbs
    assert "doctor" in verbs


def test_the_same_candidate_twice_is_idempotent(tmp_path):
    store = make_store(tmp_path)
    workspace = make_workspace(tmp_path, store)
    memctl, log = memctl_stub(tmp_path)
    write_candidate(workspace, "Read the primary source before trusting a summary.")

    first = run_promote(workspace, store, memctl, log)
    assert first.returncode == 0, first.stderr + first.stdout
    topic_path = store / "lessons-dreaming-2026-11-07-3-4.md"
    before = ((workspace / "MEMORY.md").read_bytes(),
              (workspace / "ops/host/shared-memory/publish-manifest.json").read_bytes(),
              topic_path.read_bytes(),
              sorted(path.name for path in store.glob("*.md")))

    second = run_promote(workspace, store, memctl, log)
    assert second.returncode == 0, second.stderr + second.stdout
    after = ((workspace / "MEMORY.md").read_bytes(),
             (workspace / "ops/host/shared-memory/publish-manifest.json").read_bytes(),
             topic_path.read_bytes(),
             sorted(path.name for path in store.glob("*.md")))
    assert after == before
    assert "no approved candidates" in second.stdout


def test_unreviewed_candidate_writes_nothing_and_generates_nothing(tmp_path):
    store = make_store(tmp_path)
    workspace = make_workspace(tmp_path, store)
    memctl, log = memctl_stub(tmp_path)
    write_candidate(workspace, "Read the primary source before trusting a summary.", approval=False)
    before = ((workspace / "MEMORY.md").read_bytes(),
              sorted(path.name for path in store.glob("*.md")),
              len(calls(log)))

    proc = run_promote(workspace, store, memctl, log)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "no approved candidates" in proc.stdout
    after = ((workspace / "MEMORY.md").read_bytes(),
             sorted(path.name for path in store.glob("*.md")),
             len(calls(log)))
    assert after == before
    assert not (store / "lessons-dreaming-2026-11-07-3-4.md").exists()


def test_generation_failure_restores_the_previous_projection(tmp_path):
    store = make_store(tmp_path)
    workspace = make_workspace(tmp_path, store)
    memctl, log = memctl_stub(tmp_path)
    write_candidate(workspace, "Read the primary source before trusting a summary.")
    before_memory = (workspace / "MEMORY.md").read_bytes()
    manifest = workspace / "ops/host/shared-memory/publish-manifest.json"
    before_manifest = manifest.read_bytes()

    broken = tmp_path / "broken_publish.py"
    broken.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib, sys\n"
        "repo = pathlib.Path(sys.argv[sys.argv.index('--repo') + 1])\n"
        "(repo / 'MEMORY.md').write_text('# broken projection\\n')\n"
        "print('publish: simulated write failure', file=sys.stderr)\n"
        "raise SystemExit(1)\n", encoding="utf-8")

    failed = run_promote(workspace, store, memctl, log, "--publish-script", str(broken))
    assert failed.returncode == 1
    assert "publish.py --write failed" in failed.stderr
    assert "restored MEMORY.md" in failed.stderr
    assert (workspace / "MEMORY.md").read_bytes() == before_memory
    assert manifest.read_bytes() == before_manifest
    topic_path = store / "lessons-dreaming-2026-11-07-3-4.md"
    assert topic_path.exists(), "the reviewed store write remains for a retry"

    retried = run_promote(workspace, store, memctl, log)
    assert retried.returncode == 0, retried.stderr + retried.stdout
    assert (workspace / "MEMORY.md").read_text(encoding="utf-8").count("## Existing") == 1
    assert "Read the primary source" in (workspace / "MEMORY.md").read_text(encoding="utf-8")
    checked = check_store(workspace, store)
    assert checked.returncode == 0, checked.stderr


def test_multiple_candidates_take_contiguous_orders(tmp_path):
    store = make_store(tmp_path)
    workspace = make_workspace(tmp_path, store)
    memctl, log = memctl_stub(tmp_path)
    private = workspace / "memory/.dreams"
    first = ("Verify the source before repeating a summary.", "memory/2026-11-07.md", 3)
    second = ("Keep the rollback copy until the new projection passes its check.", "memory/2026-11-06.md", 7)
    (private / "promotion-candidates.md").write_text(
        candidate(first[0], first[1], first[2]) + "\n" + candidate(second[0], second[1], second[2]),
        encoding="utf-8")
    approvals = {
        key(first[1], first[2]): receipt(first[0]),
        key(second[1], second[2]): receipt(second[0]),
    }
    (private / "promotion-approvals.json").write_text(json.dumps(approvals), encoding="utf-8")

    proc = run_promote(workspace, store, memctl, log)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    first_path = store / "lessons-dreaming-2026-11-07-3-4.md"
    second_path = store / "lessons-dreaming-2026-11-06-7-8.md"
    orders = []
    for path in (first_path, second_path):
        match = next(line for line in path.read_text(encoding="utf-8").splitlines()
                     if line.strip().startswith("order:"))
        orders.append(int(match.split(":", 1)[1]))
    assert sorted(orders) == [2, 3]
    checked = check_store(workspace, store)
    assert checked.returncode == 0, checked.stderr
