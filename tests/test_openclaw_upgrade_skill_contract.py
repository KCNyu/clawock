"""Guard the upgrade path that preserves host-local OpenClaw dist fixes."""

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "openclaw-upgrade" / "SKILL.md"
WRAPPER = ROOT / "ops" / "host" / "reapply_openclaw_patches.sh"

def test_upgrade_skill_patches_after_update_and_before_restart():
    text = SKILL.read_text()
    update_at = text.index("openclaw update --tag <version> --no-restart --yes")
    patch_at = text.index("bash ops/host/reapply_openclaw_patches.sh")
    restart_at = text.index("openclaw gateway restart")

    assert update_at < patch_at < restart_at
    assert "runningAtMs != null" in text
    assert text.count("ops/host/reapply_openclaw_patches.sh") >= 3
    assert "ops/host/openclaw-patches/manifest.json" in text


def test_wrapper_routes_all_dist_work_through_the_versioned_kit():
    text = WRAPPER.read_text()
    assert 'manage_openclaw_patches.py" apply' in text
    assert 'manage_openclaw_patches.py" check' in text
    assert 'manage_openclaw_patches.py" plan' in text
    assert '/root/tools/openclaw/current' not in text
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
