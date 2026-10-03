"""Guard the upgrade path that preserves host-local OpenClaw dist fixes."""

from pathlib import Path
import os
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "openclaw-upgrade" / "SKILL.md"
WRAPPER = ROOT / "ops" / "host" / "reapply_openclaw_patches.sh"

PATCH_SCRIPTS = (
    "/root/tools/openclaw/current/patch-embedding-threads1.sh",
    "/root/tools/openclaw/current/patch-memory-search-timeout.sh",
    "/root/tools/openclaw/current/patch-minimax-m3-priority.sh",
    "/root/tools/openclaw/current/patch-minimax-response-header-timeout.sh",
    "/root/tools/openclaw/current/patch-minimax-m3x-adaptive-thinking.sh",
)
PATCH_BASENAMES = tuple(Path(script).name for script in PATCH_SCRIPTS)
PATCH_MARKERS = (
    "threads: 1, batchSize: 512",
    "const MEMORY_SEARCH_TOOL_TIMEOUT_MS = 60000;",
    "clawock-minimax-m3-priority",
    "clawock-minimax-response-header-timeout-v3",
    "MiniMax response-header timeout after 60000ms",
    "clawock-minimax-m3x-adaptive-thinking",
)


def test_upgrade_skill_patches_after_update_and_before_restart():
    text = SKILL.read_text()
    update_at = text.index("openclaw update --tag <version> --no-restart --yes")
    patch_at = text.index("bash ops/host/reapply_openclaw_patches.sh")
    restart_at = text.index("openclaw gateway restart")

    assert update_at < patch_at < restart_at
    assert "runningAtMs != null" in text
    assert text.count("ops/host/reapply_openclaw_patches.sh") >= 3
    for patch_script in PATCH_SCRIPTS:
        assert patch_script in text


def test_wrapper_owns_all_current_patches_in_stable_order():
    text = WRAPPER.read_text()
    positions = [text.index(script) for script in PATCH_BASENAMES]

    assert positions == sorted(positions)
    for marker in PATCH_MARKERS:
        assert marker in text
    assert "node --check" in text
    assert "python3 -m py_compile" in text
    assert "gateway restart" not in text


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


@pytest.mark.parametrize("adaptive_present", [False, True])
def test_check_only_requires_adaptive_thinking_in_installed_bundle(tmp_path, adaptive_present):
    """An upgrade that wiped only the M3.x fix must fail the operator's gate."""
    install = tmp_path / "openclaw"
    dist = install / "dist"
    dist.mkdir(parents=True)
    markers = PATCH_MARKERS if adaptive_present else PATCH_MARKERS[:-1]
    (dist / "bundle.js").write_text("\n".join(f"// {marker}" for marker in markers))
    shims = tmp_path / "bin"
    shims.mkdir()
    for name, body in {
        "realpath": 'printf "%s\\n" "$TEST_OPENCLAW_INSTALL"',
        # Keep this fixture away from host maintenance files and their pycache.
        "python3": "exit 0",
    }.items():
        shim = shims / name
        shim.write_text(f"#!/bin/sh\n{body}\n")
        shim.chmod(0o755)
    result = subprocess.run(
        ["bash", str(WRAPPER), "--check-only"],
        env={**os.environ, "PATH": f"{shims}:{os.environ['PATH']}",
             "TEST_OPENCLAW_INSTALL": str(install)},
        capture_output=True, text=True,
    )
    if adaptive_present:
        assert result.returncode == 0, result.stderr
        assert "all 5 patches" in result.stdout
    else:
        assert result.returncode != 0
        assert "marker missing for MiniMax-M3.x always-adaptive thinking" in result.stderr
