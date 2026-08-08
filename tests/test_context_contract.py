"""Pin OpenClaw's silent bootstrap rule and the portable equivalent (#366)."""
from pathlib import Path

import pytest

from clawock.context import assemble, audit, load_manifest


ROOT = Path(__file__).resolve().parents[1]
INJECTED = ["AGENTS.md", "TOOLS.md", "SOUL.md", "IDENTITY.md", "USER.md"]
EXCLUDED = ["MEMORY.md", "HEARTBEAT.md", "BOOTSTRAP.md"]


def test_live_openclaw_allowlist_is_exact_and_nonempty():
    manifest = load_manifest()
    assert manifest["bootstrap"] == INJECTED
    assert manifest["excluded"] == EXCLUDED
    result = audit(ROOT)
    assert result["ok"], result


def test_portable_assembler_is_exact_and_skills_are_lazy(tmp_path):
    for name in INJECTED + EXCLUDED:
        (tmp_path / name).write_text(f"body:{name}", encoding="utf-8")
    skill = tmp_path / "skills" / "demo" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("skill body", encoding="utf-8")

    plain = assemble(tmp_path)
    assert [doc.name for doc in plain.documents] == INJECTED
    assert all(name not in plain.text for name in EXCLUDED)
    assert "skill body" not in plain.text

    selected = assemble(tmp_path, skills=["demo"])
    assert "skill body" in selected.text


def test_missing_bootstrap_is_a_named_failure(tmp_path):
    with pytest.raises(ValueError, match="AGENTS.md"):
        assemble(tmp_path)
