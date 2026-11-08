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
