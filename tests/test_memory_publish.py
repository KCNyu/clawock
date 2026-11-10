"""The public MEMORY.md projection: only `publish: public` topics, stable order, and a
committed manifest CI can verify without the private store."""
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
PUBLISH = ROOT / "ops/host/shared-memory/scripts/publish.py"
MANIFEST = ROOT / "ops/host/shared-memory/publish-manifest.json"


def load_publish():
    loader = importlib.machinery.SourceFileLoader("publish_projection", str(PUBLISH))
    spec = importlib.util.spec_from_loader("publish_projection", loader)
    module = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode, before = True, sys.dont_write_bytecode
    try:
        loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = before
    return module


def topic(slug, body, *, publish="public", order="1", separator="false"):
    return f"""---
name: {slug}
description: "{slug} hook"
metadata:
  type: feedback
  scope: engineering
  updated: 2026-11-08
  salience: normal
  status: verified
  publish: {publish}
  agent: test
  order: {order}
  separator: {separator}
---

{body.rstrip()}
"""


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "store"
    root.mkdir()
    (root / "feedback-one.md").write_text(topic("feedback-one", "## One\n\npublic rule"))
    (root / "feedback-two.md").write_text(topic("feedback-two", "## Two\n\nthe second public rule", order="2"))
    (root / "project-private.md").write_text(
        topic("project-private", "## Private\n\nnever leaves the machine", publish="private", order="3"))
    return root


def test_only_public_topics_reach_the_projection(store):
    publish = load_publish()
    topics = publish.load_public_topics(store)
    text = publish.render(topics)
    assert "public rule" in text and "the second public rule" in text
    assert "never leaves the machine" not in text
    assert [topic["slug"] for topic in topics] == ["feedback-one", "feedback-two"]
    assert "## Private" not in text


def test_projection_is_idempotent_and_byte_stable(store, tmp_path):
    publish = load_publish()
    text = publish.render(publish.load_public_topics(store))
    manifest = publish.build_manifest(text, publish.load_public_topics(store))
    assert publish.render(publish.load_public_topics(store)) == text
    assert publish.build_manifest(text, publish.load_public_topics(store)) == manifest
    assert publish.validate(text, manifest) == []
    assert publish.sha256(text) == publish.sha256(text)


def test_a_private_topic_cannot_be_published_by_omitting_its_order(store):
    publish = load_publish()
    (store / "feedback-private-no-order.md").write_text(
        topic("feedback-private-no-order", "## X\n\nbody", publish="private", order=""))
    # Private topics are simply not selected; a public one without an order is an error.
    assert "feedback-private-no-order" not in [t["slug"] for t in publish.load_public_topics(store)]
    (store / "feedback-public-no-order.md").write_text(
        topic("feedback-public-no-order", "## Y\n\nbody", order=""))
    with pytest.raises(publish.ProjectionError, match="metadata.order"):
        publish.load_public_topics(store)


def test_public_orders_must_be_contiguous(store):
    publish = load_publish()
    (store / "feedback-one.md").write_text(topic("feedback-one", "## One\n\npublic rule", order="1"))
    (store / "feedback-two.md").write_text(topic("feedback-two", "## Two\n\nsecond", order="3"))
    with pytest.raises(publish.ProjectionError, match="contiguous"):
        publish.load_public_topics(store)


def test_manifest_rejects_an_edited_private_or_extra_line(store):
    publish = load_publish()
    topics = publish.load_public_topics(store)
    text = publish.render(topics)
    manifest = publish.build_manifest(text, topics)
    assert publish.validate(text, manifest) == []
    assert publish.validate(text.replace("public rule", "changed rule"), manifest)
    assert publish.validate(text + "a private line\n", manifest)
    bad = json.loads(json.dumps(manifest))
    bad["sections"][0]["publish"] = "private"
    assert any("not publish: public" in error for error in publish.validate(text, bad))


def test_the_committed_projection_and_manifest_are_public_only():
    publish = load_publish()
    text = (ROOT / "MEMORY.md").read_text(encoding="utf-8")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert publish.validate(text, manifest) == []
    assert manifest["sections"], "the projection has no sections"
    assert all(section["publish"] == "public" for section in manifest["sections"])
    assert all(section["slug"] == section["slug"].lower() for section in manifest["sections"])
    assert "publish: private" not in text and "publish: public" not in text


def test_a_public_section_that_transcribes_a_private_body_is_rejected(store, tmp_path):
    publish = load_publish()
    private_line = "The private entry rule says never publish this sentence verbatim."
    (store / "project-private.md").write_text(
        topic("project-private", f"## Private\n\n{private_line}", publish="private"))
    (store / "feedback-one.md").write_text(
        topic("feedback-one", f"## One\n\n{private_line}"))
    with pytest.raises(publish.provenance.ProvenanceError, match="copies a private topic body"):
        publish.write(tmp_path, store, tmp_path / "manifest.json")
    assert not (tmp_path / "MEMORY.md").exists()


def test_the_source_guard_accepts_paraphrase_and_runtime_data_but_not_a_copy(store):
    publish = load_publish()
    private_line = "The private entry rule says never publish this sentence verbatim."
    (store / "project-private.md").write_text(
        topic("project-private", f"## Private\n\n{private_line}", publish="private"))
    publish.provenance.assert_public_sources(
        "brief", "The private entry rule says this sentence is not for publication.", store)
    publish.provenance.assert_public_sources(
        "brief", private_line, store, allowed_texts=["portfolio: " + private_line])
    with pytest.raises(publish.provenance.ProvenanceError, match="project-private"):
        publish.provenance.assert_public_sources("brief", f"prefix\n{private_line}\n", store)


@pytest.mark.parametrize('damage', ['missing-scope', 'invalid-status', 'stale'])
def test_public_projection_refuses_invalid_source_schema(store, tmp_path, damage):
    path = store / 'feedback-one.md'
    text = path.read_text()
    if damage == 'missing-scope':
        text = text.replace('  scope: engineering\n', '')
    else:
        text = text.replace('status: verified', 'status: ' + ('stale' if damage == 'stale' else 'typo'))
    path.write_text(text)
    publish = load_publish()
    target = tmp_path / 'projection'
    target.mkdir()
    (target / 'MEMORY.md').write_text('previous projection')
    with pytest.raises(publish.ProjectionError):
        publish.write(target, store, target / 'manifest.json')
    assert (target / 'MEMORY.md').read_text() == 'previous projection'
    assert not (target / 'manifest.json').exists()


@pytest.mark.parametrize('failure', ['manifest-replace', 'post-check', 'locked'])
def test_projection_failure_preserves_the_previous_pair(store, tmp_path, monkeypatch, failure):
    import fcntl

    publish = load_publish()
    repo = tmp_path / 'repo'
    repo.mkdir()
    manifest = repo / 'manifest.json'
    memory = repo / 'MEMORY.md'
    memory.write_bytes(b'previous memory\n')
    manifest.write_bytes(b'previous manifest\n')
    before = (memory.read_bytes(), manifest.read_bytes())
    real_replace = publish.os.replace
    if failure == 'manifest-replace':
        failed = False

        def fail_once(src, dst):
            nonlocal failed
            if Path(dst) == manifest and not failed:
                failed = True
                raise OSError('simulated manifest replacement failure')
            return real_replace(src, dst)

        monkeypatch.setattr(publish.os, 'replace', fail_once)
    elif failure == 'post-check':
        monkeypatch.setattr(publish, 'check', lambda *args: 1)
    lock_dir = repo / 'memory/.dreams'
    lock_dir.mkdir(parents=True)
    with (lock_dir / 'projection.lock').open('a') as lock:
        if failure == 'locked':
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            result = publish.write(repo, store, manifest)
        except (publish.ProjectionError, OSError):
            result = 1
        assert result != 0, 'generation failure or concurrent publisher must fail closed'
        assert (memory.read_bytes(), manifest.read_bytes()) == before


@pytest.mark.parametrize("separator", [
    "|---|---|---|---|---|---|",  # 25 chars: the original false positive
    "| :--- | ---: | :---: | " + "-" * 60 + " |",
    ":--- | ---: | :---: | " + "-" * 60,
    "|" + "-" * 60 + "|",
])
def test_table_delimiters_are_not_private_body_units(store, separator):
    guard = load_publish().provenance
    (store / "project-private.md").write_text(
        topic("project-private", separator + "\n" + separator, publish="private"))
    assert guard.find_copies(separator + "\n" + separator, store) == []


@pytest.mark.parametrize("private", [
    "| Internal heading with private meaning | Other column |",
    "| Private account instructions must stay on this machine | withheld |",
    "|---|---|---|secret|---|---|",
    "|---|---|---|---|---|---| trailing private explanation",
    "Sensitive internal instructions kept in a private engineering note.",
    "------------------------------",  # not a table delimiter
    "a" * 24,  # retain the exact line-length boundary
    "| short private header |\n|---|---|---|---|---|---|\n| short private cell |",
    "short private words\nmore private words\nadditional private words",
])
def test_table_delimiter_filter_keeps_real_private_units_blocked(store, private):
    guard = load_publish().provenance
    separator = "|---|---|---|---|---|---|"
    (store / "project-private.md").write_text(topic(
        "project-private", separator + "\n" + private, publish="private"))
    # Copy the content without its delimiter as well as with it: neither may pass.
    for artifact in (private, separator + "\n" + private):
        with pytest.raises(guard.ProvenanceError, match="project-private"):
            guard.assert_public_sources("brief", artifact, store)
