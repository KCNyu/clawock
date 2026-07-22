"""Guards for the pre-push secret scan in scripts/system_check.py.

The scan runs in two tiers on purpose:

* LOOSE  — key-ish shapes (`sk-`, `tp-`, `<VENDOR>_API_KEY=…`) that can collide
  with ordinary slugs. On 2026-07-15 the string "risk-on-with-trend-conflict" in
  a plan.json matched `sk-` + 21 legal chars and blocked every push, so this tier
  skips `*.md`.
* STRICT — structurally unambiguous credential markers (PEM headers, vendor keys
  with fixed prefix + fixed length). These cannot occur in prose, so they must
  also scan `*.md` — that is where the memory-promotion cron writes, and it is a
  live path from a credential pasted into a session into the public repo.

Most tests drive the scan against a throwaway git repo rather than mocking the
internals, so a refactor that preserves behaviour stays green while any of the
three defects this suite was written for turns it red.

Credential literals are assembled from fragments so this file does not itself
contain a matching string — the scan would otherwise flag its own fixtures.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = str(ROOT / "scripts")


@pytest.fixture(scope="module")
def sc():
    if SCRIPTS not in sys.path:
        sys.path.insert(0, SCRIPTS)
    return pytest.importorskip("system_check")


# --------------------------------------------------------------------------
# credential fixtures, built so the literal never appears in this file
# --------------------------------------------------------------------------
def _pem() -> str:
    return "-----BEGIN" + " PRIVATE KEY" + "-----"


def _sa_json() -> str:
    return '{"type"' + ': ' + '"service_account", "project_id": "x"}'


def _google_key() -> str:
    return "AIza" + "b" * 35


def _telegram() -> str:
    return "8832401234" + ":AA" + "c" * 33


def _github_pat() -> str:
    return "gh" + "p_" + "d" * 36


def _aws() -> str:
    return "AKIA" + "E" * 16


def _slack() -> str:
    return "xox" + "b-" + "1234567890-abcdef"


def _tavily() -> str:
    return "tvly" + "-" + "f" * 24


def _nsec() -> str:
    # bech32 payload: 58 chars from the charset (no b/i/o/1)
    return "nsec" + "1" + ("qwertyu23456789acdefghjklmnpqrs" * 2)[:58]


def _sk_key() -> str:
    return "sk-" + "a" * 24


STRICT_POSITIVES = [
    pytest.param(_pem, id="pem-private-key"),
    pytest.param(_sa_json, id="gcp-service-account-json"),
    pytest.param(_google_key, id="google-api-key"),
    pytest.param(_telegram, id="telegram-bot-token"),
    pytest.param(_github_pat, id="github-pat"),
    pytest.param(_aws, id="aws-access-key-id"),
    pytest.param(_slack, id="slack-token"),
    pytest.param(_tavily, id="tavily-key"),
    pytest.param(_nsec, id="nostr-nsec"),
]


# --------------------------------------------------------------------------
# helpers: run the real check against a throwaway repo
# --------------------------------------------------------------------------
class _Rec:
    def __init__(self):
        self.entries = []

    def add(self, name, level, msg):
        self.entries.append((level, str(msg)))

    @property
    def level(self):
        return self.entries[0][0]

    @property
    def msg(self):
        return self.entries[0][1]


def _make_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    for name, body in files.items():
        p = repo / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    return repo


def _scan(sc, monkeypatch, repo: Path) -> _Rec:
    monkeypatch.setattr(sc, "WS", repo)
    rec = _Rec()
    sc.check_no_leaked_secrets(rec)
    return rec


# --------------------------------------------------------------------------
# behaviour: what the scan does to a repo
# --------------------------------------------------------------------------
def test_credential_in_markdown_is_caught(sc, monkeypatch, tmp_path):
    """memory/*.md is the public-repo leak path — markdown must be covered."""
    repo = _make_repo(tmp_path, {"memory/2026-07-22.md": f"note\nkey: {_pem()}\n"})
    rec = _scan(sc, monkeypatch, repo)
    assert rec.level == sc.CRITICAL
    assert "memory/2026-07-22.md" in rec.msg, "report must name the offending file"


def test_prose_slug_in_markdown_does_not_trip_the_scan(sc, monkeypatch, tmp_path):
    """The 2026-07-15 false positive: an sk--shaped slug blocked every push."""
    repo = _make_repo(
        tmp_path,
        {"memory/note.md": "driven_by: risk-on-with-trend-conflict\n港股开盘报告掉链\n"},
    )
    assert _scan(sc, monkeypatch, repo).level == sc.OK


def test_loose_tier_still_covers_non_markdown(sc, monkeypatch, tmp_path):
    """Skipping *.md must not have quietly disarmed the sk-/tp- tier elsewhere."""
    repo = _make_repo(tmp_path, {"config/keys.json": f'{{"k": "{_sk_key()}"}}\n'})
    rec = _scan(sc, monkeypatch, repo)
    assert rec.level == sc.CRITICAL
    assert "config/keys.json" in rec.msg


def test_clean_repo_reports_ok(sc, monkeypatch, tmp_path):
    repo = _make_repo(tmp_path, {"README.md": "# hello\n", "a.py": "x = 1\n"})
    assert _scan(sc, monkeypatch, repo).level == sc.OK


def test_this_repo_is_clean(sc):
    """The live tree must stay clean, and the scan must actually run on it."""
    lines, failure = sc._grep_tracked(sc.SECRET_PATTERNS_STRICT)
    assert failure is None, f"strict scan failed to run: {failure}"
    assert lines == []
    lines, failure = sc._grep_tracked(sc.SECRET_PATTERNS_LOOSE,
                                      extra_excludes=(":!*.md",))
    assert failure is None, f"loose scan failed to run: {failure}"
    assert lines == []


# --------------------------------------------------------------------------
# behaviour: fail closed when the scan cannot run
# --------------------------------------------------------------------------
def test_non_git_directory_reports_critical_not_ok(sc, monkeypatch, tmp_path):
    """A real rc>1 path: git grep outside a repository. Must not read as clean."""
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    rec = _scan(sc, monkeypatch, plain)
    assert rec.level == sc.CRITICAL
    assert "cannot certify" in rec.msg


@pytest.mark.parametrize(
    "exc",
    [
        subprocess.TimeoutExpired(cmd="git", timeout=10),
        FileNotFoundError("git"),
    ],
    ids=["timeout", "git-missing"],
)
def test_subprocess_failures_report_critical(sc, monkeypatch, exc):
    def boom(*a, **k):
        raise exc

    monkeypatch.setattr(sc.subprocess, "run", boom)
    rec = _Rec()
    sc.check_no_leaked_secrets(rec)
    assert rec.level == sc.CRITICAL
    assert "cannot certify" in rec.msg


def test_grep_passes_pattern_after_dash_e(sc, monkeypatch, tmp_path):
    """The PEM pattern starts with '-'; without -e git reads it as a flag (rc=129).

    Asserted through behaviour: a PEM in a fresh repo must be found. If the flag
    were dropped, git would error out instead of matching.
    """
    repo = _make_repo(tmp_path, {"k.md": _pem() + "\n"})
    assert _scan(sc, monkeypatch, repo).level == sc.CRITICAL


# --------------------------------------------------------------------------
# pattern-level unit checks (cheap, precise)
# --------------------------------------------------------------------------
@pytest.mark.parametrize("make", STRICT_POSITIVES)
def test_strict_patterns_catch_real_credential_shapes(sc, make):
    assert re.search(sc.SECRET_PATTERNS_STRICT, make()), (
        "strict tier must flag this credential shape"
    )


@pytest.mark.parametrize(
    "prose",
    [
        "the plan is risk-on-with-trend-conflict for hstech",
        "we rotated the service account yesterday",
        "BEGIN PRIVATE KEY is discussed in the runbook",
        "港股开盘报告掉链到 codex 之后 bash 炸了",
        "AIzaSy is a prefix people mention in blog posts",
        "set TAVILY_API_KEY in the environment before running",  # name, no value
        "workflow passes TAVILY_API_KEY: ${{ secrets.TAVILY }}",  # ':' not '='
    ],
)
def test_patterns_do_not_fire_on_prose_or_references(sc, prose):
    assert not re.search(sc.SECRET_PATTERNS_STRICT, prose)
    assert not re.search(sc.SECRET_PATTERNS_LOOSE, prose)


@pytest.mark.parametrize(
    "assignment",
    [
        "ALPHA_VANTAGE_API_KEY=" + "Z" * 16,
        "MISTRAL_API_KEY = " + "2xLUzf" + "q" * 26,
        "NOSTR_PRIVATE_KEY=" + "a1b2c3d4" * 8,
    ],
    ids=["alpha-vantage", "mistral", "nostr-hex"],
)
def test_prefixless_vendor_keys_are_caught_by_variable_name(sc, assignment):
    """These vendors' keys have no distinguishing prefix — only the name binds them."""
    assert re.search(sc.SECRET_PATTERNS_LOOSE, assignment)


def test_bare_64_hex_alone_is_not_flagged(sc):
    """sha256 sums and lockfile hashes are 64-hex; only the Nostr variable counts."""
    assert not re.search(sc.SECRET_PATTERNS_LOOSE, "sha256: " + "a1b2c3d4" * 8)


def test_config_and_self_are_always_excluded(sc):
    """openclaw.json holds live keys; this scanner holds the patterns themselves."""
    excludes = set(sc._SCAN_EXCLUDES)
    assert ":!openclaw.json*" in excludes
    assert ":!scripts/system_check.py" in excludes
