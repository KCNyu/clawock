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


# Named so the runtime does NOT resurrect them. The docs are only truthful while
# these stay gone, so the check runs in the opposite direction.
CONTEXT_RETIRED = ("scripts",)


def _context_docs():
    manifest = load_manifest()
    names = dict.fromkeys(
        name
        for profile in manifest["profiles"].values()
        for name in profile.get("bootstrap", [])
    )
    return [(name, (ROOT / name).read_text(encoding="utf-8")) for name in names]


def _repo_paths(body):
    """Backticked tokens that claim to be a path in this repository.

    A token qualifies only when its first segment is a top-level entry that
    exists (or is one we assert is gone). Prose full of slashes — `加仓/减仓`,
    `America/New_York`, `action/date/shares/price` — is not a claim about the
    tree, and neither is a `YYYY-MM-DD` naming convention.
    """
    import re

    roots = {entry.name for entry in ROOT.iterdir()} | set(CONTEXT_RETIRED)
    for token in re.findall(r"`([^`\s]+/[^`\s]*)`", body):
        token = token.rstrip(".,;:)")
        if token.split("/", 1)[0] not in roots:
            continue
        if re.search(r"[A-Z]{2,}|[*{}<>]", token):
            continue
        yield token


def test_every_path_the_injected_context_names_still_exists():
    """A moved file silently makes the model's map wrong; nothing else catches it.

    These documents are the agent's only description of where things are. When a
    path in them dies, no job fails — the model follows a dead route and
    improvises, one run at a time.

    "Exists" means present in the checkout OR gitignored. The second half is not
    a loophole: `memory/.tmp/` and the dashboard payloads are runtime-generated
    on purpose, and requiring them to be committed would push generated state
    back into the repository. A path that is neither present nor generated is
    the dead one.
    """
    import subprocess

    candidates = {token for _, body in _context_docs() for token in _repo_paths(body)
                  if not any(token.startswith(dead) for dead in CONTEXT_RETIRED)}
    missing = sorted(token for token in candidates if not (ROOT / token).exists())
    if missing:
        ignored = subprocess.run(
            ["git", "check-ignore", "--stdin"], cwd=ROOT, input="\n".join(missing),
            capture_output=True, text=True).stdout.split()
        missing = [token for token in missing if token.rstrip("/") not in
                   {line.rstrip("/") for line in ignored}]
    assert not missing, (
        "injected context points at paths that are neither present nor generated:\n"
        + "\n".join(missing))

    for dead in CONTEXT_RETIRED:
        assert not (ROOT / dead).exists(), (
            f"{dead} is back, and the injected context tells the runtime it is gone")


def test_every_command_the_injected_context_names_exists():
    """Same failure mode as the paths, one layer up: a renamed subcommand.

    Checked against what the CLI actually accepts — the packaged-utility set it
    dispatches on, plus the subcommand choices its own `--help` advertises — so
    this cannot drift from the real interface the way a hand-kept list would.
    """
    import importlib.metadata
    import re
    import subprocess
    import sys

    from clawock.cli import PACKAGED_UTILITIES

    usage = subprocess.run([sys.executable, "-m", "clawock", "--help"], cwd=ROOT,
                           capture_output=True, text=True, timeout=60).stdout
    choices = re.search(r"\{([a-z0-9,-]+)\}", usage)
    accepted = set(PACKAGED_UTILITIES) | set(choices.group(1).split(",") if choices else [])
    assert "brief" in accepted and "dashboard-build" in accepted, usage[:400]

    installed = {ep.name for ep in importlib.metadata.entry_points(group="console_scripts")}
    unknown = []
    for name, body in _context_docs():
        for command in sorted(set(re.findall(r"`clawock ([a-z][a-z0-9-]+)", body))):
            if command not in accepted:
                unknown.append(f"{name}: clawock {command}")
        for command in sorted(set(re.findall(r"`(clawock-kcnyu-[a-z-]+)", body))):
            if command not in installed:
                unknown.append(f"{name}: {command}")
    assert not unknown, ("injected context names commands that do not exist:\n"
                         + "\n".join(unknown))
