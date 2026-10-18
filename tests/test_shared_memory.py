"""ops/host/shared-memory: the coding agents' shared Markdown memory toolkit, against throwaway
stores and a throwaway HOME only (never the host's store)."""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "ops/host/shared-memory"
MEMCTL = KIT / "scripts/memctl"
MEMORY_PY = KIT / "scripts/memory.py"
HOOK = KIT / "hooks/claude-hook.sh"
INSTALL = ROOT / "ops/host/install_shared_memory.sh"

# Built at runtime so the repository's own secret scan does not flag this test.
FAKE_KEY = "tp-" + "abcdefghijklmnopqrstuvwxyz0123"

TOPIC = """---
name: {slug}
description: "{desc}"
metadata:
  type: feedback
  updated: 2026-10-01
---

{body}
"""


def load_memctl():
    loader = importlib.machinery.SourceFileLoader("memctl", str(MEMCTL))
    spec = importlib.util.spec_from_loader("memctl", loader)
    module = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode, before = True, sys.dont_write_bytecode  # no __pycache__ in the kit
    try:
        loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = before
    return module


@pytest.fixture
def kit(tmp_path):
    """A HOME with a store reached through ~/.shared-memory (Claude's home-project memory),
    a separate-memory workspace and a wiring file describing both."""
    home = tmp_path / "home"
    store = home / ".claude/projects" / re.sub(r"[^A-Za-z0-9]", "-", str(home)) / "memory"
    (store / "indexes").mkdir(parents=True)
    (store / "archive").mkdir()
    (store / "MEMORY.md").write_text("# Index\n\n- `indexes/MEMORY-host.md` — host\n")
    (store / "indexes/MEMORY-host.md").write_text("# Host\n\n- `feedback-alpha.md` — alpha rule\n")
    (store / "indexes/MEMORY-tools.md").write_text("# Tools\n")
    (store / "indexes/redirects.tsv").write_text("# old\tnew\n")
    (store / "indexes/routes.tsv").write_text("# glob\tindex\nreference-tool-*\tindexes/MEMORY-tools.md\n*\tindexes/MEMORY-host.md\n")
    (store / "feedback-alpha.md").write_text(TOPIC.format(slug="feedback-alpha", desc="alpha rule", body="alpha body"))
    for p in store.rglob("*.md"):
        p.chmod(0o644)
    (home / ".shared-memory").symlink_to(store)
    workspace = home / ".openclaw/workspace"
    workspace.mkdir(parents=True)
    wiring = tmp_path / "wiring.json"
    wiring.write_text(json.dumps({
        "guidance": "~/.agents/AGENTS.md",
        "store_links": ["~/.shared-memory"],
        "agents": {},
        "contexts": {"coding": {"cwd": "~", "shared": True},
                     "openclaw": {"cwd": "~/.openclaw/workspace", "shared": False}},
        "no_inject_under": ["~/.openclaw"],
    }))
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "AGENT_DISPATCH", "AI_AGENT"))}
    env.update(HOME=str(home), SHARED_MEMORY_DIR=str(home / ".shared-memory"),
               SHARED_MEMORY_STATE=str(tmp_path / "state"), SHARED_MEMORY_WIRING=str(wiring),
               MEMCTL_AGENT="test-agent")
    ns = type("Kit", (), {})()
    ns.home, ns.store, ns.workspace, ns.state, ns.env, ns.tmp = home, store, workspace, tmp_path / "state", env, tmp_path

    def run(*args, script=MEMCTL, env=None, stdin=None, cwd=None):
        return subprocess.run([sys.executable, str(script), *args], env=env or ns.env, text=True,
                              capture_output=True, input=stdin, cwd=cwd or tmp_path, timeout=60)

    def ok(*args, **kw):
        proc = run(*args, **kw)
        assert proc.returncode == 0, proc.stderr
        return proc

    def git(*args):
        return subprocess.run(["git", f"--git-dir={ns.state / 'history.git'}", *args], text=True,
                              capture_output=True).stdout

    def ledger():
        return [json.loads(line) for line in (ns.state / "ledger.jsonl").read_text().splitlines()]

    def body(text):
        f = tmp_path / f"body-{abs(hash(text))}.md"
        f.write_text(text)
        return str(f)

    ns.run, ns.ok, ns.git, ns.ledger, ns.body = run, ok, git, ledger, body
    ok("init")
    return ns


# --- history -----------------------------------------------------------------

def test_baseline_then_direct_edit_is_an_attributed_snapshot(kit):
    assert "feedback-alpha.md" in kit.git("ls-files").split()
    (kit.store / "feedback-alpha.md").write_text(TOPIC.format(slug="feedback-alpha", desc="alpha", body="edited"))
    kit.ok("snapshot", "--reason", "native edit")
    last = kit.ledger()[-1]
    assert (last["agent"], last["files"]) == ("test-agent", ["feedback-alpha.md"])
    assert kit.ok("snapshot").stdout.strip() == "nothing to commit"


def test_lock_temp_and_backup_files_stay_out_of_history(kit):
    (kit.store / ".shared-memory.lock").write_text("")
    (kit.store / ".feedback-alpha.md.tmp123").write_text("x")
    (kit.store / "feedback-alpha.md.bak-20261017").write_text("x")
    assert kit.ok("snapshot").stdout.strip() == "nothing to commit"


def test_secret_is_held_out_of_history_and_reported_once(kit):
    (kit.store / "feedback-alpha.md").write_text(
        TOPIC.format(slug="feedback-alpha", desc="a", body='"apiKey": "' + FAKE_KEY + '"'))
    assert "NOT committed" in kit.ok("snapshot").stderr
    assert FAKE_KEY[:9] not in kit.git("log", "-p")
    n = len(kit.ledger())
    kit.ok("snapshot")
    assert len(kit.ledger()) == n
    assert "audit.secret_held" in json.loads(kit.run("doctor", "--json").stdout)["warn"]


def test_deleting_a_topic_is_flagged_and_restorable(kit):
    base = kit.git("rev-parse", "HEAD").strip()
    (kit.store / "feedback-alpha.md").unlink()
    kit.ok("snapshot")
    assert kit.ledger()[-1]["md_deleted"] == ["feedback-alpha.md"]
    kit.ok("restore", "feedback-alpha", "--at", base)
    assert "alpha body" in (kit.store / "feedback-alpha.md").read_text()


def test_bundle_is_a_valid_backup(kit):
    kit.ok("bundle")
    bundle = next((kit.state / "bundles").glob("history-*.bundle"))
    verify = subprocess.run(["git", f"--git-dir={kit.state / 'history.git'}", "bundle", "verify", str(bundle)],
                            capture_output=True, text=True)
    assert verify.returncode == 0, verify.stderr


# --- memory.py writes: one format owner, attributed history ---------------------

def test_memory_py_add_is_routed_and_committed_as_the_calling_agent(kit):
    env = {**kit.env, "MEMCTL_AGENT": "codex", "AGENT_DISPATCH_TASK_ID": "task-1"}
    kit.ok("add", "reference-tool-x", "--summary", "tool x", "--body-file", kit.body("x body"),
           script=MEMORY_PY, env=env)
    assert "reference-tool-x.md" in (kit.store / "indexes/MEMORY-tools.md").read_text()
    last = kit.ledger()[-1]
    assert (last["op"], last["agent"], last["dispatch"], last["via"]) == ("add", "codex", "task-1", "memory.py")
    assert "reference-tool-x.md" in last["files"]
    assert kit.git("log", "-1", "--format=%an").strip() == "codex"


def test_default_route_and_archive_is_recorded_as_a_move(kit):
    kit.ok("add", "feedback-beta", "--summary", "beta", "--body-file", kit.body("beta"), script=MEMORY_PY)
    assert "feedback-beta.md" in (kit.store / "indexes/MEMORY-host.md").read_text()
    kit.ok("archive", "--drop-hooks", "feedback-beta", script=MEMORY_PY)
    last = kit.ledger()[-1]
    assert last["op"] == "archive" and "md_deleted" not in last
    assert (kit.store / "archive/feedback-beta.md").exists()


def test_store_without_a_routing_table_routes_from_the_main_index(kit):
    (kit.store / "indexes/routes.tsv").unlink()
    kit.ok("add", "feedback-gamma", "--summary", "gamma", "--body-file", kit.body("g"), script=MEMORY_PY)
    assert "feedback-gamma.md" in (kit.store / "MEMORY.md").read_text()


def test_writes_work_without_history(kit):
    env = {**kit.env, "SHARED_MEMORY_STATE": str(kit.tmp / "no-history")}
    kit.ok("add", "feedback-delta", "--summary", "d", "--body-file", kit.body("d"), script=MEMORY_PY, env=env)
    assert (kit.store / "feedback-delta.md").exists()


def test_attribution_names_the_nearest_agent_process():
    memctl = load_memctl()
    assert memctl.agent_of("node /home/u/.nvm/versions/node/v22/bin/dsh --profile headless --json -") == "dsh"
    assert memctl.agent_of("/usr/local/bin/codex exec --json -c model=x") == "codex"
    assert memctl.agent_of("opencode run --format json") == "opencode"
    assert memctl.agent_of("claude -p --output-format json") == "claude-code"
    assert memctl.agent_of("bash -c python3 memory.py add x") is None


# --- working-directory contexts ------------------------------------------------

def hook_start(kit, cwd, **extra):
    return kit.ok("hook", "claude-start", stdin=json.dumps({"cwd": str(cwd)}), env={**kit.env, **extra}).stdout


def test_start_hook_injects_only_where_claude_does_not_and_never_in_the_workspace(kit):
    other = kit.tmp / "elsewhere"
    other.mkdir()
    assert hook_start(kit, kit.home) == ""                      # native auto-memory already injects it
    assert hook_start(kit, kit.workspace) == ""                 # OpenClaw keeps its own memory
    assert hook_start(kit, kit.workspace / "memory") == ""
    assert "indexes/MEMORY-host.md" in hook_start(kit, other)
    assert hook_start(kit, other, SHARED_MEMORY_INJECT="0") == ""


def test_start_hook_surfaces_a_failed_self_check(kit):
    kit.state.mkdir(exist_ok=True)
    (kit.state / "doctor.json").write_text(json.dumps({"status": "FAIL", "ts": "t", "fail": ["wiring.x"]}))
    assert "wiring.x" in hook_start(kit, kit.home)
    assert hook_start(kit, kit.workspace) == ""


def doctor(kit):
    return {c["id"]: c for c in json.loads(kit.run("doctor", "--json").stdout)["checks"]}


def test_doctor_tells_the_two_contexts_apart(kit):
    checks = doctor(kit)
    assert checks["context.coding.claude.index"]["status"] == "OK"
    assert "native auto-memory" in checks["context.coding.claude.index"]["detail"]
    assert checks["context.openclaw.claude.index"]["status"] == "OK"
    assert checks["context.openclaw.store_separate"]["status"] == "OK"


def test_doctor_fails_when_the_workspace_links_into_the_store(kit):
    (kit.workspace / "memory").mkdir()
    (kit.workspace / "memory/coding-notes").symlink_to(kit.store)
    assert doctor(kit)["context.openclaw.store_separate"]["status"] == "FAIL"


def test_post_hook_commits_store_edits_with_the_session(kit):
    (kit.store / "feedback-alpha.md").write_text(TOPIC.format(slug="feedback-alpha", desc="alpha rule", body="hooked"))
    env = {k: v for k, v in kit.env.items() if k != "MEMCTL_AGENT"}
    payload = {"session_id": "s-1", "tool_name": "Edit", "tool_input": {"file_path": str(kit.store / "feedback-alpha.md")}}
    kit.ok("hook", "claude-post", stdin=json.dumps(payload), env=env)
    last = kit.ledger()[-1]
    assert (last["agent"], last["session"], last["via"]) == ("claude-code", "s-1", "PostToolUse")


def test_bash_filter_skips_unrelated_tool_calls(kit):
    proc = subprocess.run([str(HOOK), "post"], input='{"tool_name":"Bash","tool_input":{"command":"ls"}}',
                          text=True, capture_output=True, env=kit.env)
    assert (proc.returncode, proc.stdout) == (0, "")


# --- what ships ------------------------------------------------------------------

def installer_list(name):
    out = subprocess.run(
        ["bash", "-c", f'eval "$(sed -n "/^{name}=(/,/^)/p" "$1")"; printf "%s\\n" "${{{name}[@]}}"', "_",
         str(INSTALL)], capture_output=True, text=True, check=True).stdout
    return sorted(out.split())


def test_the_manifest_is_every_shipped_file():
    shipped = sorted(str(p.relative_to(KIT)) for p in KIT.rglob("*")
                     if p.is_file() and "__pycache__" not in p.parts and p.parts[len(KIT.parts)] not in ("systemd", "openclaw"))
    assert installer_list("FILES") == shipped
    assert installer_list("UNITS") == sorted(p.name for p in (KIT / "systemd").iterdir())


def test_no_host_paths_or_personal_memory_ship():
    for path in KIT.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts:
            text = path.read_text(encoding="utf-8")
            assert not re.search(r"/root\b|/home/\w+|kcn", text), path
    assert not list(KIT.rglob("*.bak*")) and not (KIT / "MEMORY.md").exists()


def test_install_check_units_and_rollback(tmp_path):
    dest = tmp_path / "skill"
    units = tmp_path / "units"
    units.mkdir()
    (dest / "scripts").mkdir(parents=True)
    (dest / "SKILL.md").write_text("old skill")
    (dest / "scripts/test_memory_format.py").write_text("old test")
    env = {**os.environ, "SHARED_MEMORY_SKILL_DIR": str(dest), "SHARED_MEMORY_UNIT_DIR": str(units)}

    def run(*args):
        return subprocess.run(["bash", str(INSTALL), *args], env=env, capture_output=True, text=True, timeout=60)

    assert run("--check").returncode == 1
    proc = run("--units")
    assert proc.returncode == 0, proc.stderr
    assert run("--check").returncode == 0
    assert not (dest / "scripts/test_memory_format.py").exists()
    for unit in installer_list("UNITS"):
        text = (units / unit).read_text()
        assert "@" not in text.replace("@agents", ""), unit
    assert f"{dest}/scripts/memctl" in (units / "shared-memory-daily.service").read_text()
    assert "already installed" in run().stdout
    assert run("--rollback").returncode == 0
    assert (dest / "SKILL.md").read_text() == "old skill"
    assert (dest / "scripts/test_memory_format.py").read_text() == "old test"
    assert not (dest / "scripts/memctl").exists()


def test_rerendering_units_keeps_cli_directories_the_installed_unit_had(tmp_path):
    units = tmp_path / "units"
    units.mkdir()
    (units / "shared-memory-daily.service").write_text("Environment=PATH=/opt/agents/bin:/usr/bin\n")
    env = {**os.environ, "PATH": "/usr/bin:/bin", "SHARED_MEMORY_SKILL_DIR": str(tmp_path / "skill"),
           "SHARED_MEMORY_UNIT_DIR": str(units)}
    proc = subprocess.run(["bash", str(INSTALL), "--units"], env=env, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    path = re.search(r"^Environment=PATH=(.+)$", (units / "shared-memory-daily.service").read_text(), re.M).group(1)
    assert "/opt/agents/bin" in path.split(":")
