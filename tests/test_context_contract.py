"""Pin OpenClaw's distinct context profiles and lazy capabilities (#380)."""
from pathlib import Path

import pytest

from clawock.context.assembly import (
    assemble,
    audit,
    compare_prompt_reports,
    load_manifest,
    profile_names,
)


ROOT = Path(__file__).resolve().parents[1]
CRON = ["AGENTS.md", "SOUL.md", "TOOLS.md", "IDENTITY.md", "USER.md"]
INTERACTIVE = [*CRON, "HEARTBEAT.md", "MEMORY.md"]
EXCLUDED = ["MEMORY.md", "HEARTBEAT.md", "BOOTSTRAP.md"]


def test_live_openclaw_profiles_distinguish_chat_cron_and_heartbeat():
    manifest = load_manifest()
    assert manifest["profiles"]["isolated-cron"]["bootstrap"] == CRON
    assert manifest["profiles"]["isolated-cron"]["excluded"] == EXCLUDED
    assert manifest["profiles"]["interactive"]["bootstrap"] == INTERACTIVE
    assert manifest["profiles"]["heartbeat-light"]["bootstrap"] == ["HEARTBEAT.md"]
    assert set(profile_names()) == {
        "interactive", "isolated-cron", "heartbeat-full", "heartbeat-light",
        "bootstrap-pending", "subagent",
    }
    for profile in ("interactive", "isolated-cron", "heartbeat-full", "subagent"):
        result = audit(ROOT, profile=profile)
        assert result["ok"], result


def test_portable_assembler_is_exact_and_skills_are_lazy(tmp_path):
    for name in dict.fromkeys(INTERACTIVE + EXCLUDED):
        (tmp_path / name).write_text(f"body:{name}", encoding="utf-8")
    (tmp_path / "memory").mkdir()
    skill = tmp_path / "skills" / "demo" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("skill body", encoding="utf-8")

    plain = assemble(tmp_path)
    assert [doc.name for doc in plain.documents] == CRON
    assert all(name not in plain.text for name in EXCLUDED)
    assert "skill body" not in plain.text

    selected = assemble(tmp_path, skills=["demo"])
    assert "skill body" in selected.text

    chat = assemble(tmp_path, profile="interactive")
    assert [doc.name for doc in chat.documents] == INTERACTIVE
    heartbeat = assemble(tmp_path, profile="heartbeat-light")
    assert [doc.name for doc in heartbeat.documents] == ["HEARTBEAT.md"]


def test_missing_bootstrap_is_a_named_failure(tmp_path):
    with pytest.raises(ValueError, match="AGENTS.md"):
        assemble(tmp_path)


def test_audit_fails_when_lazy_memory_or_skill_capability_would_be_lost(tmp_path):
    for name in CRON:
        (tmp_path / name).write_text(f"body:{name}")
    result = audit(tmp_path, profile="isolated-cron")

    assert not result["ok"]
    assert result["missing_capabilities"] == ["skills", "MEMORY.md", "memory"]


def test_prompt_report_comparison_catches_tool_capability_loss():
    report = {
        "injectedWorkspaceFiles": [
            {"name": name, "missing": False, "rawChars": 10,
             "injectedChars": 10, "truncated": False}
            for name in CRON
        ],
        "skills": {"hash": "skill-hash", "entries": [{"name": "trading"}]},
        "tools": {"entries": [
            {"name": "read", "summaryHash": "r", "schemaHash": "r1"},
            {"name": "memory_search", "summaryHash": "m", "schemaHash": "m1"},
        ]},
    }
    assert compare_prompt_reports(
        report, report, profile="isolated-cron"
    )["ok"]

    narrowed = {**report, "tools": {"entries": report["tools"]["entries"][:1]}}
    result = compare_prompt_reports(report, narrowed, profile="isolated-cron")
    assert not result["ok"]
    assert not result["checks"]["tool_contracts"]
