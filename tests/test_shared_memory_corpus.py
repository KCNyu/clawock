"""ops/host/shared-memory/openclaw: the read-only corpus plugin that lets the OpenClaw assistant
search the coding agents' shared memory — direct chats only, never writes, never fails a search."""
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
PLUGIN = ROOT / "ops/host/shared-memory/openclaw/index.ts"
MANIFEST = ROOT / "ops/host/shared-memory/openclaw/openclaw.plugin.json"
INSTALLER = ROOT / "ops/host/install_memory_corpus_plugin.sh"
MEMCTL = ROOT / "ops/host/shared-memory/scripts/memctl"

DIRECT = "agent:main:openclaw-weixin:direct:peer-1"
# One sample per credential pattern, built at runtime so the repository's own scan stays quiet.
SAMPLES = [
    "-----BEGIN RSA " + "PRIVATE KEY-----",
    "sk-" + "a" * 30,
    "ghp_" + "b" * 36,
    "github_pat_" + "c" * 36,
    "AKIA" + "D" * 16,
    "LTAI" + "e" * 16,
    "xoxb-" + "1" * 12,
    "123456789:AA" + "f" * 33,
    "ctxdb-" + "g" * 20,
    "AIza" + "h" * 35,
    "tvly-" + "i" * 24,
    "tp-" + "j" * 32,
    "nsec1" + "q" * 55,
    "api_key = " + "k" * 30,
]


def node(script):
    proc = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "--input-type=module", "-e",
                           f"import register, * as m from {json.dumps(PLUGIN.as_uri())};\n" + script],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "store"
    (root / "archive").mkdir(parents=True)
    (root / "indexes").mkdir()
    (root / "feedback-sandbox.md").write_text(
        "---\nname: feedback-sandbox\ndescription: \"Claude Code sandbox stays off\"\nmetadata:\n  type: feedback\n"
        "  updated: 2026-10-01\n---\n\nThe sandbox is off on purpose.\nkey: " + SAMPLES[11] + "\n")
    (root / "archive/incident-old.md").write_text("---\nname: incident-old\ndescription: \"old sandbox outage\"\n---\n\nsandbox history\n")
    (root / "indexes/MEMORY-host.md").write_text("- `feedback-sandbox.md` — sandbox\n")
    outside = tmp_path / "outside.md"
    outside.write_text("sandbox secret outside the store\n")
    (root / "linked.md").symlink_to(outside)
    return root


def corpus(store, call):
    return f"const c = m.createSharedMemoryCorpus({{root: {json.dumps(str(store))}}});\nconsole.log(JSON.stringify({call}));"


def test_direct_chat_finds_topics_and_archive_ranks_lower(store):
    hits = node(corpus(store, f"await c.search({{query: 'sandbox', agentSessionKey: '{DIRECT}', corpus: 'all'}})"))
    paths = [h["path"] for h in hits]
    assert paths[0] == "shared-memory/feedback-sandbox.md"
    assert "shared-memory/archive/incident-old.md" in paths
    assert "shared-memory/linked.md" not in paths            # symlink out of the store
    assert all(h["corpus"] == "shared-memory" and 0 < h["score"] <= 1 for h in hits)
    assert hits[0]["startLine"] == 9                         # the matching body line, frontmatter counted


@pytest.mark.parametrize("key", [None, "", "agent:main:openclaw-weixin:group:g-1", "agent:main:telegram:channel:c",
                                 "agent:main:cron:brief", "agent:main:explicit:abc", "agent:main:subagent:x"])
def test_groups_channels_cron_and_keyless_sessions_get_nothing(store, key):
    arg = "undefined" if key is None else json.dumps(key)
    hits = node(corpus(store, f"await c.search({{query: 'sandbox', agentSessionKey: {arg}, corpus: 'all'}})"))
    got = node(corpus(store, f"await c.get({{lookup: 'shared-memory/feedback-sandbox.md', agentSessionKey: {arg}}})"))
    assert hits == [] and got is None


def test_main_session_is_direct_and_only_corpus_all_is_answered(store):
    assert node(corpus(store, "await c.search({query: 'sandbox', agentSessionKey: 'agent:main:main'})"))
    assert node(corpus(store, f"await c.search({{query: 'sandbox', agentSessionKey: '{DIRECT}', corpus: 'wiki'}})")) == []


def test_get_reads_redacted_lines_and_refuses_escapes(store):
    got = node(corpus(store, f"await c.get({{lookup: 'shared-memory/feedback-sandbox.md', fromLine: 9, lineCount: 2, agentSessionKey: '{DIRECT}'}})"))
    assert got["content"].splitlines() == ["The sandbox is off on purpose.", "key: [REDACTED]"]
    assert (got["fromLine"], got["lineCount"], got["title"]) == (9, 2, "feedback-sandbox")
    for lookup in ("shared-memory/../outside.md", "shared-memory/linked.md", "shared-memory//etc/passwd",
                   "shared-memory/indexes/MEMORY-host.md", "feedback-sandbox.md", "shared-memory/feedback-sandbox.txt"):
        assert node(corpus(store, f"await c.get({{lookup: {json.dumps(lookup)}, agentSessionKey: '{DIRECT}'}})")) is None, lookup


def test_a_missing_or_broken_store_returns_nothing_instead_of_failing(tmp_path, store):
    (store / "feedback-binary.md").write_bytes(b"\xff\xfe\x00 sandbox")
    script = (f"const warnings = []; const gone = m.createSharedMemoryCorpus({{root: {json.dumps(str(tmp_path / 'nope'))}, warn: (w) => warnings.push(w)}});\n"
              f"const ok = m.createSharedMemoryCorpus({{root: {json.dumps(str(store))}}});\n"
              f"const a = await gone.search({{query: 'sandbox', agentSessionKey: '{DIRECT}'}});\n"
              f"const b = await gone.search({{query: 'sandbox', agentSessionKey: '{DIRECT}'}});\n"
              f"const g = await gone.get({{lookup: 'shared-memory/x.md', agentSessionKey: '{DIRECT}'}});\n"
              f"const h = await ok.search({{query: 'sandbox', agentSessionKey: '{DIRECT}'}});\n"
              "console.log(JSON.stringify({a, b, g, warnings: warnings.length, h: h.length}));")
    out = node(script)
    assert (out["a"], out["b"], out["g"], out["warnings"]) == ([], [], None, 1)
    assert out["h"] >= 1


def test_it_never_writes(store):
    before = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in store.rglob("*") if p.is_file()}
    node(corpus(store, f"[await c.search({{query: 'sandbox', agentSessionKey: '{DIRECT}'}}), "
                       f"await c.get({{lookup: 'shared-memory/feedback-sandbox.md', agentSessionKey: '{DIRECT}'}})]"))
    after = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in store.rglob("*") if p.is_file()}
    assert before == after
    source = PLUGIN.read_text()
    imported = re.search(r'import \{([^}]*)\} from "node:fs/promises"', source).group(1)
    assert {name.strip() for name in imported.split(",")} == {"readdir", "readFile", "realpath", "stat"}
    assert not re.search(r"writeFile|appendFile|createWriteStream|unlink|rename|mkdir|rmSync|copyFile|require\(|\bfs\.", source)


def test_redaction_matches_memctl_pattern_for_pattern():
    loader = importlib.machinery.SourceFileLoader("memctl", str(MEMCTL))
    spec = importlib.util.spec_from_loader("memctl", loader)
    memctl = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode, before = True, sys.dont_write_bytecode
    try:
        loader.exec_module(memctl)
    finally:
        sys.dont_write_bytecode = before
    out = node(f"console.log(JSON.stringify({{n: m.SECRET_PATTERNS.length, r: {json.dumps(SAMPLES)}.map(m.redact)}}))")
    assert out["n"] == len(memctl.SECRET_PATTERNS) == len(SAMPLES)
    for sample, redacted in zip(SAMPLES, out["r"]):
        assert memctl.secret_hits(sample), sample
        assert "[REDACTED]" in redacted and sample not in redacted, sample


def test_register_adds_one_corpus_supplement_from_config(store):
    out = node(f"""
const calls = [];
register({{pluginConfig: {{root: {json.dumps(str(store))}}}, logger: {{warn() {{}}}},
          registerMemoryCorpusSupplement: (s) => calls.push(s)}});
const hits = await calls[0].search({{query: 'sandbox', agentSessionKey: '{DIRECT}', corpus: 'all'}});
console.log(JSON.stringify({{n: calls.length, keys: Object.keys(calls[0]).sort(), first: hits[0].path}}));""")
    assert out == {"n": 1, "keys": ["get", "search"], "first": "shared-memory/feedback-sandbox.md"}


def test_manifest_loads_at_startup_and_ships_no_host_paths():
    manifest = json.loads(MANIFEST.read_text())
    assert manifest["id"] == "shared-memory-corpus" and manifest["activation"]["onStartup"] is True
    assert set(manifest["configSchema"]["properties"]) == {"root", "includeArchive"}
    for path in (PLUGIN, MANIFEST):
        assert not re.search(r"/root\b|/home/\w+|kcn", path.read_text()), path


def test_install_check_and_rollback(tmp_path):
    target = tmp_path / "extensions/shared-memory-corpus"
    target.mkdir(parents=True)
    for name in ("index.ts", "openclaw.plugin.json"):
        (target / name).write_text(f"previous {name}")
    env = {**os.environ, "MEMORY_CORPUS_PLUGIN_DIR": str(target)}

    def run(*args):
        return subprocess.run(["bash", str(INSTALLER), *args], env=env, capture_output=True, text=True)

    assert run("--check").returncode != 0
    assert run().returncode == 0
    assert run("--check").returncode == 0
    assert (target / "index.ts").read_text() == PLUGIN.read_text()
    assert run("--rollback").returncode == 0
    assert (target / "index.ts").read_text() == "previous index.ts"


def test_words_no_topic_contains_do_not_dilute_the_score(store):
    plain = node(corpus(store, f"await c.search({{query: 'sandbox', agentSessionKey: '{DIRECT}'}})"))
    noisy = node(corpus(store, f"await c.search({{query: 'sandbox zzqxv 鸡鸭鹅狗', agentSessionKey: '{DIRECT}'}})"))
    assert [h["path"] for h in noisy] == [h["path"] for h in plain]
    assert noisy[0]["score"] == pytest.approx(plain[0]["score"])
