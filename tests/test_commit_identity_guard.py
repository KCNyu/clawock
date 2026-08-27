"""Commit-identity guard: bare `username@users.noreply.github.com` must fail.

2026-08-27: one commit authored as `kcn@users.noreply.github.com` (bare
username noreply, no numeric ID prefix) was attributed by GitHub to a
stranger's account of the same name. The pre-commit and pre-push hooks now
refuse every identity outside the whitelist: KCNyu's two addresses, or any
ID-prefixed users.noreply.github.com address (github-actions[bot],
dependabot[bot], ...).
"""
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

GOOD_EMAILS = (
    "shengyu.li.evgeny@gmail.com",
    "45508369+KCNyu@users.noreply.github.com",
    "41898282+github-actions[bot]@users.noreply.github.com",
    "49699333+dependabot[bot]@users.noreply.github.com",
)
BAD_EMAILS = (
    "kcn@users.noreply.github.com",        # bare username noreply — the 08-27 bug
    "root@localhost.localdomain",          # the 08-27 openinference identity leak
    "someone@example.com",
)


def _git(repo, *args, check=True, env=None, input=None):
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=check,
        capture_output=True, text=True, env=env, input=input)


def _repo(tmp_path):
    _git(tmp_path, "init", "-q")
    hooks = tmp_path / "hooks"
    hooks.mkdir(exist_ok=True)
    # absolute path: git resolves a relative core.hooksPath against the cwd
    # of the invoking process, which in pytest is not the repo
    _git(tmp_path, "config", "core.hooksPath", str(hooks))
    (hooks / "pre-commit").write_text((ROOT / ".githooks" / "pre-commit").read_text())
    (hooks / "pre-push").write_text((ROOT / ".githooks" / "pre-push").read_text())
    (hooks / "_identity_check.sh").write_text(
        (ROOT / ".githooks" / "_identity_check.sh").read_text())
    for name in ("pre-commit", "pre-push", "_identity_check.sh"):
        (hooks / name).chmod(0o755)
    (tmp_path / "file.txt").write_text("x\n")
    _git(tmp_path, "add", "file.txt")
    return tmp_path


def _commit(repo, email, name="Tester", no_verify=False):
    env = {**os.environ,
           "GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email,
           "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email}
    args = ["commit", "-qm", "test"]
    if no_verify:
        args.insert(1, "--no-verify")
    return _git(repo, *args, env=env, check=False)


def test_bare_noreply_email_is_rejected(tmp_path):
    repo = _repo(tmp_path)
    result = _commit(repo, "kcn@users.noreply.github.com")
    assert result.returncode != 0
    assert "unrecognized commit identity" in (result.stdout + result.stderr)


def test_foreign_and_localhost_emails_are_rejected(tmp_path):
    for email in ("someone@example.com", "root@localhost.localdomain"):
        repo = _repo(tmp_path)
        result = _commit(repo, email)
        assert result.returncode != 0, email
        assert "unrecognized commit identity" in (result.stdout + result.stderr)


def test_whitelisted_identities_are_allowed(tmp_path):
    for i, email in enumerate(GOOD_EMAILS):
        repo = _repo(tmp_path)
        (repo / f"f{i}.txt").write_text("y\n")
        _git(repo, "add", f"f{i}.txt")
        result = _commit(repo, email)
        assert result.returncode == 0, (email, result.stdout + result.stderr)


def test_pre_push_rejects_bad_identity_in_the_pushed_range(tmp_path):
    """The phantom commit reached master by push; pre-push must scan the range.

    The hook is invoked directly like the other contract tests, with the
    update line Git would feed it: master updated from seed to a commit whose
    author email is the bare noreply form.
    """
    repo = _repo(tmp_path)
    _commit(repo, "shengyu.li.evgeny@gmail.com")  # seed commit (good identity)
    seed = _git(repo, "rev-parse", "HEAD").stdout.strip()
    # create the bad commit bypassing pre-commit (which already refuses it)
    (repo / "bad.txt").write_text("z\n")
    _git(repo, "add", "bad.txt")
    _commit(repo, "kcn@users.noreply.github.com", no_verify=True)
    bad = _git(repo, "rev-parse", "HEAD").stdout.strip()
    assert bad != seed
    hook = repo / "hooks" / "pre-push"
    result = subprocess.run(
        ["bash", str(hook)], cwd=repo, capture_output=True, text=True,
        input=f"refs/heads/master {bad} refs/heads/master {seed}\n")
    assert result.returncode != 0
    assert "unrecognized identity" in result.stdout


def test_pre_push_allows_good_identity_range(tmp_path):
    repo = _repo(tmp_path)
    _commit(repo, "shengyu.li.evgeny@gmail.com")  # seed commit (good identity)
    seed = _git(repo, "rev-parse", "HEAD").stdout.strip()
    (repo / "more.txt").write_text("y\n")
    _git(repo, "add", "more.txt")
    _commit(repo, "shengyu.li.evgeny@gmail.com")
    good = _git(repo, "rev-parse", "HEAD").stdout.strip()
    assert good != seed
    hook = repo / "hooks" / "pre-push"
    result = subprocess.run(
        ["bash", str(hook)], cwd=repo, capture_output=True, text=True,
        input=f"refs/heads/master {good} refs/heads/master {seed}\n")
    # no checker + no portfolio.json in the fixture → the rest of the hook
    # takes the permissive path; the identity gate must not block it
    assert result.returncode == 0, result.stdout + result.stderr
