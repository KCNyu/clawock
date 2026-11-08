"""A brief may quote a public topic or runtime data, never a private topic body."""
from pathlib import Path

from clawock.harness import brief_postflight as postflight

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = "The private desk line says this exact sentence is not for publication."


def store_with_private(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    (store / "project-private.md").write_text(
        "---\nname: project-private\ndescription: \"private evidence\"\nmetadata:\n"
        "  type: project\n  scope: investment\n  publish: private\n---\n\n" + PRIVATE + "\n")
    return store


def brief_holding(tmp_path, text):
    path = tmp_path / "memory" / "2026-11-08-pre-open.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_a_brief_that_transcribes_a_private_topic_is_critical(tmp_path, monkeypatch):
    store = store_with_private(tmp_path)
    path = brief_holding(tmp_path, f"# 盘前\n\n{PRIVATE}\n")
    monkeypatch.setenv("SHARED_MEMORY_DIR", str(store))
    monkeypatch.setattr(postflight, "WS", tmp_path)
    issues = postflight.validate_shared_memory_sources(path, "2026-11-08")
    assert any("引用了 private topic" in issue and "project-private" in issue for issue in issues)
    assert postflight.categorize(issues) == "fail"


def test_runtime_data_is_an_allowed_source_for_the_same_line(tmp_path, monkeypatch):
    store = store_with_private(tmp_path)
    path = brief_holding(tmp_path, f"# 盘前\n\n{PRIVATE}\n")
    (tmp_path / "portfolio.json").write_text('{"note": "' + PRIVATE + '"}')
    monkeypatch.setenv("SHARED_MEMORY_DIR", str(store))
    monkeypatch.setattr(postflight, "WS", tmp_path)
    assert postflight.validate_shared_memory_sources(path, "2026-11-08") == []


def test_an_absent_store_has_nothing_to_copy(tmp_path, monkeypatch):
    path = brief_holding(tmp_path, f"# 盘前\n\n{PRIVATE}\n")
    monkeypatch.setenv("SHARED_MEMORY_DIR", str(tmp_path / "missing"))
    monkeypatch.setattr(postflight, "WS", tmp_path)
    assert postflight.validate_shared_memory_sources(path, "2026-11-08") == []


def test_a_legacy_topic_without_frontmatter_is_private_by_default(tmp_path, monkeypatch):
    store = store_with_private(tmp_path)
    (store / 'project-private.md').write_text('# Legacy private note\n\n' + PRIVATE + '\n')
    path = brief_holding(tmp_path, f'# 盘前\n\n{PRIVATE}\n')
    monkeypatch.setenv('SHARED_MEMORY_DIR', str(store))
    monkeypatch.setattr(postflight, 'WS', tmp_path)
    issues = postflight.validate_shared_memory_sources(path, '2026-11-08')
    assert any('private topic' in issue and 'project-private' in issue for issue in issues)
