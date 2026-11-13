"""The one-shot memory model call uses MiniMax and a thinking level it accepts.

MiniMax-M3.1-Flash rejects a disabled thinking level with HTTP 400, while the host's
OpenClaw default resolves to `off`; the command therefore always names the level.
"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "ops/host/shared-memory/scripts/llm_json.py"


def load(monkeypatch):
    spec = importlib.util.spec_from_file_location("llm_json_for_test", MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "_resolve_cli", lambda: "/usr/bin/openclaw")
    monkeypatch.delenv("MEMORY_LLM_CMD", raising=False)
    return module


def test_the_memory_jobs_default_to_minimax_with_adaptive_thinking(monkeypatch):
    module = load(monkeypatch)
    monkeypatch.delenv("MEMORY_LLM_MODEL", raising=False)
    assert module.model() == "minimax/MiniMax-M3.1-Flash"
    argv, _ = module._command("prompt", module.model())
    assert argv[argv.index("--model") + 1] == "minimax/MiniMax-M3.1-Flash"
    assert argv[argv.index("--thinking") + 1] == "adaptive"
    assert argv[argv.index("--prompt") + 1] == "prompt"


def test_the_minimax_retry_alias_also_gets_adaptive(monkeypatch):
    module = load(monkeypatch)
    assert module.thinking_level("minimax-2/MiniMax-M3.1-Flash") == "adaptive"


def test_a_non_minimax_override_keeps_the_old_pinned_off(monkeypatch):
    module = load(monkeypatch)
    monkeypatch.setenv("MEMORY_LLM_MODEL", "deepseek/deepseek-v4-pro")
    argv, _ = module._command("prompt", module.model())
    assert argv[argv.index("--model") + 1] == "deepseek/deepseek-v4-pro"
    assert argv[argv.index("--thinking") + 1] == "off"


def test_a_closing_fence_attached_to_the_json_is_ignored(monkeypatch):
    module = load(monkeypatch)
    assert module.extract_json('```json\n[{"key": "a"}]\n```') == [{"key": "a"}]
    assert module.extract_json('```json\n[{"key": "a"}]```') == [{"key": "a"}]
