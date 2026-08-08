"""Guards for the pre-push secret scan in scripts/system_check.py.

The scan runs in two tiers on purpose:

* LOOSE  — key-ish shapes (`sk-`, `tp-`, `<VENDOR>_API_KEY=…`) that can collide
  with ordinary slugs. On 2026-07-15 the string "risk-on-with-trend-conflict" in
  a plan.json matched `sk-` + 21 legal chars and blocked every push; the fix is a
  prefix anchor, not a file exemption.
* STRICT — structurally unambiguous credential markers (PEM headers, vendor keys
  with fixed prefix + fixed length).

Both tiers cover `*.md` — that is where the memory-promotion cron writes, and it
is a live path from a credential pasted into a session into the public repo. Both
also run against HEAD as well as the working tree, because a push carries commits,
not the checkout.

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
    # keyed on private_key_id (40 hex), the field only a real key file carries
    return '{"private_key_id"' + ': ' + '"' + "9f" * 20 + '"}'


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


def test_loose_tier_covers_non_markdown(sc, monkeypatch, tmp_path):
    """The sk-/tp- tier must stay armed outside markdown too."""
    repo = _make_repo(tmp_path, {"config/keys.json": f'{{"k": "{_sk_key()}"}}\n'})
    rec = _scan(sc, monkeypatch, repo)
    assert rec.level == sc.CRITICAL
    assert "config/keys.json" in rec.msg


def test_clean_repo_reports_ok(sc, monkeypatch, tmp_path):
    repo = _make_repo(tmp_path, {"README.md": "# hello\n", "a.py": "x = 1\n"})
    assert _scan(sc, monkeypatch, repo).level == sc.OK


def test_full_repo_scan_is_not_registered_in_system_check(sc):
    """GitHub push protection owns full-history scanning; the hook must stay fast."""
    source = Path(sc.__file__).read_text(encoding="utf-8")
    checks = source.split("\n    checks = [", 1)[1].split("]", 1)[0]
    assert "check_no_leaked_secrets" not in checks


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
        # a news URL slug: "-sk-" opens no token, and *.md is full of these
        "see https://x.com/news/update-5-sk-hynix-plunges-after-nasdaq-debut-today",
        # plain GCP metadata any setup doc may quote; not a credential by itself
        'the fixture is {"type": "service_account", "project_id": "demo"}',
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


def test_scanner_does_not_exempt_itself_into_uselessness(sc, monkeypatch, tmp_path):
    """openclaw.json is untracked in practice, so excluding it only ever takes
    effect on the day it is committed by accident — exactly when it must fire."""
    repo = _make_repo(tmp_path, {"openclaw.json": f'{{"apiKey": "{_sk_key()}"}}\n'})
    rec = _scan(sc, monkeypatch, repo)
    assert rec.level == sc.CRITICAL
    assert "openclaw.json" in rec.msg


# --------------------------------------------------------------------------
# behaviour: markdown, quoting, and what is actually being pushed
# --------------------------------------------------------------------------
def _commit(repo: Path) -> None:
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=repo, check=True,
                   env={**__import__("os").environ, **env})


def test_prefixed_key_in_markdown_is_caught(sc, monkeypatch, tmp_path):
    """The loose tier used to skip *.md wholesale, so a pasted sk- key in the
    dreaming-write path reached the public repo with the scan reporting clean."""
    repo = _make_repo(tmp_path, {"memory/2026-07-22.md": f"note\nkey: {_sk_key()}\n"})
    rec = _scan(sc, monkeypatch, repo)
    assert rec.level == sc.CRITICAL
    assert "memory/2026-07-22.md" in rec.msg


def test_url_slug_in_markdown_stays_clean(sc, monkeypatch, tmp_path):
    """Real content from memory/2026-07-15-pre-open.md: a news URL containing
    '-sk-hynix-plunges-after-…'. Scanning *.md is only viable if this stays OK."""
    repo = _make_repo(tmp_path, {"memory/n.md": (
        "SK Hynix 弱利润预估（[Reuters](https://wealthinsights.metrobank.com.ph/"
        "news/update-5-sk-hynix-plunges-after-nasdaq-debut-as-memory-cools)）\n")})
    assert _scan(sc, monkeypatch, repo).level == sc.OK


def test_quoted_assignment_is_caught(sc, monkeypatch, tmp_path):
    """`KEY="value"` is the ordinary shape in .env/JS/YAML; binding the value
    straight to '=' meant the quote ended the match before it began."""
    repo = _make_repo(tmp_path, {".env.example": 'FINNHUB_API_KEY="' + "d1" * 12 + '"\n'})
    assert _scan(sc, monkeypatch, repo).level == sc.CRITICAL


def test_secret_committed_but_removed_from_worktree_is_caught(sc, monkeypatch, tmp_path):
    """`git grep` without a revision reads the checkout, but a push carries the
    commits. Editing the key out locally must not launder the commit that has it."""
    repo = _make_repo(tmp_path, {"c.py": f'KEY = "{_sk_key()}"\n'})
    _commit(repo)
    (repo / "c.py").write_text('KEY = os.environ["K"]\n', encoding="utf-8")
    rec = _scan(sc, monkeypatch, repo)
    assert rec.level == sc.CRITICAL, "HEAD still carries the credential"
    assert "HEAD" in rec.msg


def test_clean_committed_repo_reports_ok(sc, monkeypatch, tmp_path):
    """Scanning HEAD as well must not turn every ordinary repo red."""
    repo = _make_repo(tmp_path, {"README.md": "# hello\n", "a.py": "x = 1\n"})
    _commit(repo)
    assert _scan(sc, monkeypatch, repo).level == sc.OK


# --------------------------------------------------------------------------
# behaviour: the hook that consumes the scan
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "rc,blocks",
    [(0, False), (2, False), (1, True), (127, True), (137, True)],
    ids=["ok", "warnings", "critical", "interpreter-missing", "killed"],
)
def test_pre_push_hook_blocks_unless_the_checker_gave_a_verdict(tmp_path, rc, blocks):
    """RC=0/2 are verdicts (clean / warnings only). Anything else means the check
    never ran; treating that as a pass is the fail-open this suite exists for."""
    import os
    repo = tmp_path / "r"
    (repo / "scripts" / "data").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "scripts" / "system_check.py").write_text("")
    (repo / "scripts" / "data" / "preflight_integrity.py").write_text("")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # first invocation (system_check) exits rc; the integrity call after it exits 0
    stub = bin_dir / "python3"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        'case "$1" in *system_check.py) exit %d;; *) exit 0;; esac\n' % rc
    )
    stub.chmod(0o755)
    p = subprocess.run(
        ["bash", str(ROOT / ".githooks" / "pre-push")],
        cwd=repo, capture_output=True, text=True,
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert (p.returncode != 0) is blocks, p.stdout + p.stderr
