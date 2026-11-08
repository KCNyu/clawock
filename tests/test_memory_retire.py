"""Nightly retirement candidates: report only, guarded, and the usage rule is off."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
RETIRE = ROOT / "ops/host/shared-memory/scripts/retire.py"
NOW = "2026-11-08T12:00:00+08:00"


def topic(store, slug, *, status="hypothesis", publish="private", scope="engineering",
          updated="2026-01-01", body=None):
    body = body or f"# {slug}\n\n{slug} body."
    (store / f"{slug}.md").write_text(f"""---
name: {slug}
description: "{slug}"
metadata:
  type: project
  scope: {scope}
  updated: {updated}
  salience: normal
  status: {status}
  publish: {publish}
  agent: test
---

{body}
""")


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "store"
    (root / "indexes").mkdir(parents=True)
    (root / "archive").mkdir()
    (root / "MEMORY.md").write_text("# Index\n\n- `indexes/MEMORY-host.md` — host\n")
    slugs = ["stale-topic", "verified-topic", "public-topic", "persona-topic",
             "referenced-topic", "linker", "dup-a", "dup-b", "unused-topic", "used-topic"]
    (root / "indexes/MEMORY-host.md").write_text(
        "# Host\n" + "".join(f"- `{slug}.md` — {slug}\n" for slug in slugs))
    topic(root, "stale-topic", status="stale")
    topic(root, "verified-topic", status="verified")
    topic(root, "public-topic", publish="public")
    topic(root, "persona-topic", scope="persona")
    topic(root, "referenced-topic")
    topic(root, "linker", body="# linker\n\nSee [[referenced-topic]].")
    same = "# Same\n\nA durable rule repeated in two topics. " * 3
    topic(root, "dup-a", body=same)
    topic(root, "dup-b", body=same)
    topic(root, "unused-topic")
    topic(root, "used-topic")
    state = tmp_path / "state"
    state.mkdir()
    (state / "recall.jsonl").write_text("\n".join([
        json.dumps({"ts": "2026-09-01T00:00:00+08:00", "source": "python-search", "topics": ["used-topic"]}),
        json.dumps({"ts": "2026-11-01T00:00:00+08:00", "source": "python-search", "topics": ["used-topic"]}),
    ]) + "\n")
    env = {**os.environ, "SHARED_MEMORY_DIR": str(root), "SHARED_MEMORY_STATE": str(state)}
    return root, state, env


def run(store, *args):
    root, state, env = store
    out = state / "retirement-candidates.json"
    proc = subprocess.run([sys.executable, str(RETIRE), "--store", str(root), "--output", str(out),
                           "--now", NOW, *args], env=env, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(out.read_text())


def store_hash(root):
    return hashlib.sha256(b"".join(
        p.relative_to(root).as_posix().encode() + b"\0" + p.read_bytes()
        for p in sorted(root.rglob("*.md")))).hexdigest()


def test_candidates_are_guarded_and_report_only(store):
    before = store_hash(store[0])
    report = run(store)
    assert store_hash(store[0]) == before
    reasons = [item["reason"] for item in report["candidates"]]
    assert reasons.count("stale") == 1
    assert "unused" not in reasons                 # rule ships off
    assert [item["reason"] for item in report["candidates"]].count("duplicate") == 1
    guarded = {item["slug"]: item["evidence"] for item in report["guarded"]}
    assert "status=verified" in guarded["verified-topic"]
    assert "publish=public" in guarded["public-topic"]
    assert "scope=persona" in guarded["persona-topic"]
    assert "referenced-topic" in guarded and "[[referenced-topic]]" in guarded["referenced-topic"]
    assert report["rules"]["action"].startswith("nominate only")
    assert report["rules"]["usage_rule_enabled"] is False


def test_usage_rule_requires_coverage_and_skips_seen_topics(store):
    report = run(store, "--enable-usage-rule")
    assert report["rules"]["usage_rule_enabled"] is True
    assert report["rules"]["coverage_days"] >= 30
    unused = {item["slug"] for item in report["candidates"] if item["reason"] == "unused"}
    assert "unused-topic" in unused
    assert "used-topic" not in unused
    assert not unused & {"verified-topic", "public-topic", "persona-topic", "referenced-topic"}


def test_report_is_private_and_has_a_markdown_view(store):
    root, state, env = store
    out = state / "retirement-candidates.json"
    report = run(store)
    assert out.is_file() and out.with_suffix(".md").is_file()
    assert (state / "recall-stats.json").is_file()
    assert oct(out.stat().st_mode & 0o777) == "0o600"
    markdown = out.with_suffix(".md").read_text()
    assert "stale-topic" in markdown and "nomination only" in markdown.lower()
    assert report["total_candidates"] == len(report["candidates"])
