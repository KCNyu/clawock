"""A configured `openai/gpt-6-*` hop is only real if the codex runtime serves it.

On 2026-09-23 the Codex runtime under OpenClaw's codex plugin was re-pinned
from 0.144.3 to 0.155.1 by swapping the platform layout's files in place — the
plugin release that pins 0.155.1 needs a newer core. The npm metadata beside it
still says 0.144.3, and a plugin update or reinstall brings 0.144.3 back. The
cron fallback hop and the direct-chat fallback would then fail as `Unknown
model`, and only when they are needed. This check says it beforehand.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def system_check():
    for path in (ROOT, ROOT / "src"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    spec = importlib.util.spec_from_file_location(
        "kcnyu_system_check_codex_runtime", ROOT / "ops" / "system_check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _host(tmp_path, *, runtime, npm_says="0.144.3", cron_fallback="openai/gpt-6-luna",
          chat_fallback="openai/gpt-6-sol"):
    ws = tmp_path / "ws"
    (ws / "config").mkdir(parents=True)
    (ws / "config" / "cron-schedules.json").write_text(json.dumps({"payload_profiles": {
        "report": {"model": "minimax/MiniMax-M3",
                   "fallbacks": ["minimax-2/MiniMax-M3", cron_fallback]},
        "memory": {"model": "minimax/MiniMax-M3"},
    }}))
    config = tmp_path / "openclaw.json"
    config.write_text(json.dumps({"agents": {"defaults": {"model": {
        "primary": "anthropic/claude-sonnet-5",
        "fallbacks": [chat_fallback, "minimax/MiniMax-M3"]}}}}))
    projects = tmp_path / "npm" / "projects"
    if runtime is not None:
        pkg = (projects / "openclaw-codex-8902d781d4__openclaw-generation__g-1"
               / "node_modules" / "@openclaw" / "codex" / "node_modules" / "@openai")
        layout = pkg / "codex-linux-x64" / "vendor" / "x86_64-unknown-linux-musl"
        layout.mkdir(parents=True)
        (layout / "codex-package.json").write_text(json.dumps({"version": runtime}))
        (pkg / "codex-linux-x64" / "package.json").write_text(
            json.dumps({"version": f"{npm_says}-linux-x64"}))
    return ws, config, projects


def _rows(system_check, monkeypatch, host):
    ws, config, projects = host
    monkeypatch.setattr(system_check, "WS", ws)
    monkeypatch.setattr(system_check, "OPENCLAW_CONFIG", config)
    monkeypatch.setattr(system_check, "CODEX_PLUGIN_PROJECTS", projects)
    r = system_check.Result()
    system_check.check_codex_runtime(r)
    return [row for row in r.checks if row[0] == "codex runtime"]


def test_a_reverted_runtime_is_a_warning_naming_the_dead_hops(system_check, monkeypatch, tmp_path):
    rows = _rows(system_check, monkeypatch, _host(tmp_path, runtime="0.144.3"))

    assert len(rows) == 1
    _, severity, message = rows[0]
    assert severity == system_check.WARNING
    assert "openai/gpt-6-luna" in message and "openai/gpt-6-sol" in message
    assert "0.144.3" in message and "0.155.1" in message


def test_the_layout_manifest_wins_over_the_stale_npm_metadata(system_check, monkeypatch, tmp_path):
    """A re-pin swaps the layout's files and leaves package.json on 0.144.3."""
    rows = _rows(system_check, monkeypatch,
                 _host(tmp_path, runtime="0.155.1", npm_says="0.144.3"))

    assert [row[1] for row in rows] == [system_check.OK]


def test_a_newer_runtime_than_the_minimum_is_fine(system_check, monkeypatch, tmp_path):
    rows = _rows(system_check, monkeypatch, _host(tmp_path, runtime="0.160.0"))

    assert [row[1] for row in rows] == [system_check.OK]


def test_an_unreadable_manifest_is_not_taken_on_trust(system_check, monkeypatch, tmp_path):
    host = _host(tmp_path, runtime="0.155.1")
    next(host[2].rglob("codex-package.json")).write_text("{")

    rows = _rows(system_check, monkeypatch, host)

    assert [row[1] for row in rows] == [system_check.WARNING]
    assert "unreadable" in rows[0][2]


def test_one_gpt6_hop_is_enough_to_need_the_runtime(system_check, monkeypatch, tmp_path):
    rows = _rows(system_check, monkeypatch, _host(
        tmp_path, runtime="0.144.3",
        cron_fallback="openai/gpt-5.6-luna", chat_fallback="openai/gpt-6-sol"))

    assert [row[1] for row in rows] == [system_check.WARNING]
    assert "openai/gpt-6-sol" in rows[0][2] and "gpt-6-luna" not in rows[0][2]


def test_no_gpt6_hop_needs_nothing(system_check, monkeypatch, tmp_path):
    rows = _rows(system_check, monkeypatch, _host(
        tmp_path, runtime="0.144.3",
        cron_fallback="openai/gpt-5.6-luna", chat_fallback="openai/gpt-5.6-sol"))

    assert rows == []


def test_off_the_live_box_it_stays_silent(system_check, monkeypatch, tmp_path):
    rows = _rows(system_check, monkeypatch, _host(tmp_path, runtime=None))

    assert rows == []


def test_it_reads_without_spawning(system_check, monkeypatch, tmp_path):
    """It runs in the pre-push hook: no `codex --version`."""
    def denied(*args, **kwargs):
        raise AssertionError(f"spawned {args!r}")

    monkeypatch.setattr(subprocess, "run", denied)
    monkeypatch.setattr(subprocess, "Popen", denied)
    rows = _rows(system_check, monkeypatch, _host(tmp_path, runtime="0.144.3"))

    assert [row[1] for row in rows] == [system_check.WARNING]
