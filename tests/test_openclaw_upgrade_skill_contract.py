"""Guard the upgrade path that preserves host-local OpenClaw dist fixes."""

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "openclaw-upgrade" / "SKILL.md"
WRAPPER = ROOT / "ops" / "host" / "reapply_openclaw_patches.sh"

def test_upgrade_skill_verifies_the_fork_before_restart():
    text = SKILL.read_text()
    update_at = text.index("## 2. Stage the fork artifact")
    patch_at = text.index("bash ops/host/reapply_openclaw_patches.sh")
    restart_at = text.index("openclaw gateway restart")

    assert update_at < patch_at < restart_at
    assert "runningAtMs != null" in text
    assert text.count("ops/host/reapply_openclaw_patches.sh") >= 3
    assert "ops/host/openclaw-patches/manifest.json" in text


def test_wrapper_only_verifies_fork_package_identity():
    text = WRAPPER.read_text()
    assert 'manage_openclaw_patches.py" verify-fork "$@"' in text
    assert 'install_skillhub_plugin.sh' not in text
    assert 'install_memory_corpus_plugin.sh' not in text
    assert 'gateway restart' not in text


def test_upgrade_contract_preserves_rich_agent_context():
    text = SKILL.read_text()

    for required in (
        "systemPromptReport",
        "truncatedFiles=0",
        "full skill catalog",
        "SKILL.md",
        "full tool set",
        "output budget",
        "thinking level",
        "whole-turn",
    ):
        assert required in text
    assert "Do not use `--light-context`" in text
    assert "a tool allowlist" in text
    assert "prompt trimming" in text


def test_patch_wrapper_has_valid_shell_syntax():
    subprocess.run(["bash", "-n", str(WRAPPER)], check=True)
