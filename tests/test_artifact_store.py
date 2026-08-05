"""Where a generation goes, and what it must not disturb on the way (#314)."""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from clawock.publish import FilesystemStore, GitBranchStore  # noqa: E402


GENERATION = {
    "assets/data/dashboard.json": '{"totals": 1}',
    "assets/data/overview.json": '{"generation_id": "one"}',
}


def _git(root, *args, **kwargs):
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True, capture_output=True, text=True, **kwargs,
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    """A working checkout with a real remote, so pushes are exercised for real."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", "-b", "master", str(origin))
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-b", "master")
    _git(work, "config", "user.name", "test")
    _git(work, "config", "user.email", "test@example.invalid")
    _git(work, "remote", "add", "origin", str(origin))
    (work / "README.md").write_text("source\n", encoding="utf-8")
    _git(work, "add", "README.md")
    _git(work, "commit", "-m", "source")
    _git(work, "push", "-u", "origin", "master")
    return work


def _branch_tree(repo, branch):
    """path -> contents, as the data branch actually holds them."""
    names = _git(repo, "ls-tree", "-r", "--name-only", f"origin/{branch}").split()
    return {n: _git(repo, "show", f"origin/{branch}:{n}") for n in names}


def test_the_data_branch_is_a_snapshot_not_a_log(repo):
    """Force-updated and parentless: the branch holds the current generation and
    nothing else. If publishing appended, this branch would grow the same 72
    commits/day that put the outputs on `master` in the first place."""
    store = GitBranchStore(repo, "data-plane")

    store.publish(GENERATION, label="first")
    store.publish({**GENERATION, "assets/data/dashboard.json": '{"totals": 2}'},
                  label="second")
    _git(repo, "fetch", "origin", "data-plane")

    assert _git(repo, "rev-list", "--count", "origin/data-plane") == "1"
    assert _branch_tree(repo, "data-plane") == {
        "assets/data/dashboard.json": '{"totals": 2}',
        "assets/data/overview.json": '{"generation_id": "one"}',
    }, "the branch holds exactly the latest generation, at its published paths"


def test_publishing_leaves_the_caller_checkout_alone(repo):
    """The live publisher runs inside the workspace checkout while it is on
    `master` with other files in flight. A store that reached the branch by
    checking out, adding and committing would publish by disturbing the very tree
    it publishes from — so this asserts HEAD, the index and the worktree are
    exactly as they were."""
    (repo / "dirty.txt").write_text("uncommitted\n", encoding="utf-8")
    (repo / "staged.txt").write_text("mid-edit\n", encoding="utf-8")
    _git(repo, "add", "staged.txt")
    before_head = _git(repo, "rev-parse", "HEAD")
    before_branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    before_status = _git(repo, "status", "--porcelain")

    GitBranchStore(repo, "data-plane").publish(GENERATION, label="x")

    assert _git(repo, "rev-parse", "HEAD") == before_head
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD") == before_branch
    assert _git(repo, "status", "--porcelain") == before_status
    assert not (repo / "assets").exists(), (
        "the published paths must not appear in the caller's worktree")


def test_publishing_does_not_leave_the_caller_repository_shallow(repo):
    """Reading the branch fetches it, and `--depth=1` there writes a shallow
    boundary into the CALLER's repository — repository-wide state, not
    per-ref. A shallow repository has its pushes rejected ("shallow update not
    allowed"), so the next thing to break is not the data plane but the `master`
    publish this same script performs three lines later.

    Not hypothetical: it took a full publish, an unchanged republish and a lost
    branch to surface, which is why the unit tests missed it and an end-to-end
    run did not.
    """
    store = GitBranchStore(repo, "data-plane")
    store.publish(GENERATION, label="first")
    store.publish(GENERATION, label="unchanged")           # the read that fetches

    assert _git(repo, "rev-parse", "--is-shallow-repository") == "false"
    _git(repo, "push", "origin", "master")                  # the master publish


def test_a_published_generation_reads_back_byte_for_byte(repo, tmp_path):
    """Byte-equality between what was published and what is served is the
    acceptance criterion for the whole migration, and the easiest way to lose it
    is a trailing newline: `git` output is routinely stripped, and a JSON payload
    ends in one. Round-tripped through a real push and a real fetch."""
    generation = {
        "assets/data/dashboard.json": '{"totals": 1}\n',
        "assets/data/overview.json": '{"generation_id": "one"}\n',
    }
    store = GitBranchStore(repo, "data-plane")
    store.publish(generation, label="round trip")

    into = tmp_path / "checkout"
    written = store.fetch(into, names=list(generation))

    assert written == list(generation)
    for name, text in generation.items():
        assert (into / name).read_text(encoding="utf-8") == text


def test_a_materialised_generation_is_readable_by_whoever_serves_it(repo, tmp_path):
    """`mkstemp` creates 0600 and `os.replace` swaps the inode, so a published
    file inherits the staging permissions rather than its own.

    Invisible for as long as these went out through git — the index normalises
    the mode to 100644 — and load-bearing the moment a consumer reads them off
    disk instead. The Pages build was the first: `jekyll-build-pages` runs in a
    container as another user and could not read its own inputs
    (`PermissionError: … _site/assets/data/overview.json`).
    """
    store = GitBranchStore(repo, "data-plane")
    store.publish(GENERATION, label="x")

    into = tmp_path / "checkout"
    store.fetch(into, names=list(GENERATION))

    for name in GENERATION:
        mode = (into / name).stat().st_mode & 0o777
        assert mode == 0o644, f"{name} published as {oct(mode)}"


def test_a_generation_the_branch_does_not_carry_is_refused(repo, tmp_path):
    """Materialising three of four outputs would leave the fourth as whatever the
    checkout already had — one page serving two generations, with nothing in the
    logs. The reader asserts the whole set."""
    GitBranchStore(repo, "data-plane").publish(GENERATION, label="x")

    with pytest.raises(FileNotFoundError, match="decision_audit"):
        GitBranchStore(repo, "data-plane").fetch(
            tmp_path / "checkout",
            names=[*GENERATION, "assets/data/decision_audit.json"])
    assert not (tmp_path / "checkout").exists(), (
        "nothing is materialised when the generation is incomplete")


@pytest.mark.parametrize("branch", ["master", "main", "HEAD"])
def test_a_branch_that_is_built_on_is_refused(repo, branch):
    """Every publish discards the target's history. Pointed at `master` that is
    not a bad publish, it is the repository."""
    with pytest.raises(ValueError, match="force-update"):
        GitBranchStore(repo, branch).publish(GENERATION, label="x")


def test_the_default_branch_is_refused_under_any_name(repo, tmp_path):
    """`master`/`main` are a static guess; the remote's own default branch is the
    real answer, and it is asked OF THE REMOTE.

    `refs/remotes/origin/HEAD` is a local convenience that plenty of checkouts do
    not have — this one included until something creates it. Reading only that
    would leave a repository whose default is `trunk` protected by nothing but
    the static list, which is the case this exists for.
    """
    _git(repo, "push", "origin", "master:refs/heads/trunk")
    _git(tmp_path / "origin.git", "symbolic-ref", "HEAD", "refs/heads/trunk")
    assert "origin/HEAD" not in _git(repo, "branch", "-r"), (
        "the local remote-HEAD ref must be absent, or this proves nothing")

    with pytest.raises(ValueError, match="force-update"):
        GitBranchStore(repo, "trunk").publish(GENERATION, label="x")


@pytest.mark.parametrize("branch", ["refs/heads/master", ""])
def test_something_that_is_not_a_branch_name_is_refused(repo, branch):
    """A fully-qualified ref would be pushed to `refs/heads/refs/heads/master`,
    so the guard above would be inspecting a name nothing is published to — the
    caller asked for one branch and got a different one, silently."""
    with pytest.raises(ValueError, match="expected a branch name"):
        GitBranchStore(repo, branch).publish(GENERATION, label="x")


def test_republishing_the_same_generation_does_not_write(repo):
    """The store compares against the branch, so an unchanged generation is a
    no-op it reports rather than a second commit of the same bytes. Callers use
    `changed` to decide whether anything needs deploying."""
    store = GitBranchStore(repo, "data-plane")
    first = store.publish(GENERATION, label="first")

    again = store.publish(GENERATION, label="second")

    assert first.changed and not again.changed
    assert again.receipt == first.receipt, "the branch tip must not move"


def test_a_publish_that_never_arrived_is_retried_by_the_next_one(repo):
    """The self-healing property, and the reason the caller must NOT gate this on
    its own "did anything change locally".

    Generation N reaches `master` but not the branch. Nothing changes locally
    afterwards, so a caller gated on its own diff would never try again and the
    branch would sit a generation behind until the next genuine change — on a
    quiet day, indefinitely. Comparing against the branch instead makes the next
    tick repair it with no new information.
    """
    store = GitBranchStore(repo, "data-plane")
    store.publish(GENERATION, label="generation N")
    _git(repo, "push", "origin", "--delete", "data-plane")   # the publish is lost

    repaired = store.publish(GENERATION, label="generation N")

    assert repaired.changed, "an absent branch must be republished, not skipped"
    _git(repo, "fetch", "origin", "data-plane")
    assert _branch_tree(repo, "data-plane") == GENERATION


def test_the_filesystem_default_is_idempotent_too(tmp_path):
    """Same contract on both sides of the seam, so a caller reading `changed`
    behaves the same whichever store it was configured with."""
    store = FilesystemStore(tmp_path / "out")
    assert store.publish(GENERATION).changed
    assert not store.publish(GENERATION).changed


def test_an_empty_generation_is_refused_rather_than_treated_as_a_no_op(repo):
    """`GitBranchStore` replaces its whole state, so publishing zero files is not
    "nothing changed" — it is deleting the data plane. Refused in the shared
    check, so the filesystem default cannot drift away from it either."""
    with pytest.raises(ValueError, match="empty generation"):
        GitBranchStore(repo, "data-plane").publish({}, label="x")
    with pytest.raises(ValueError, match="empty generation"):
        FilesystemStore(repo / "out").publish({}, label="x")


def test_a_generation_member_cannot_escape_the_store(tmp_path):
    """Members are addressed by relative path in both stores; an absolute path or
    a `..` would write outside the store in the filesystem case and commit a path
    git would refuse in the other."""
    store = FilesystemStore(tmp_path / "out")
    with pytest.raises(ValueError, match="relative path"):
        store.publish({"../escape.json": "{}"})
    with pytest.raises(ValueError, match="relative path"):
        store.publish({str(tmp_path / "escape.json"): "{}"})


def test_the_filesystem_default_keeps_the_published_layout(tmp_path):
    """The layout is the contract shared with `DirectoryBaseline` and with the
    data branch: outputs keep their workspace-relative path rather than being
    flattened, so "what did we publish last time" resolves the same way wherever
    the generation was stored."""
    out = tmp_path / "out"

    result = FilesystemStore(out).publish(GENERATION, label="ignored")

    assert result.receipt == str(out) and result.changed
    assert (out / "assets/data/dashboard.json").read_text(encoding="utf-8") == '{"totals": 1}'
    assert (out / "assets/data/overview.json").read_text(encoding="utf-8") == '{"generation_id": "one"}'
