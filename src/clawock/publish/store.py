"""Artifact stores: a generation of files, put somewhere, as one write set.

Two implementations, and the difference between them is the whole point of the
seam:

* `FilesystemStore` — the default, and the only thing a third party gets without
  configuring anything. Writing the files where they were built is a store, not
  the absence of one; a clawock that defaults to pushing somewhere would be
  wrong.
* `GitBranchStore` — one instance configuration. An orphan, force-updated ref in
  a repository, built entirely with plumbing so it never touches the caller's
  index or worktree. That constraint is not stylistic: the live publisher runs
  inside the workspace checkout, which must stay on `master` and keeps a dirty
  tree of other in-flight files while it publishes.

Neither store deploys anything, and neither decides *what* a generation is.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol


# Published artifacts are read by a web server, a Jekyll container and anyone
# who checks the repository out. Explicit rather than umask-derived so a
# publisher's environment cannot decide whether the site's data is readable.
PUBLISHED_MODE = 0o644


def write_generation(writes: Mapping[str, str]) -> list[str]:
    """Publish files as ONE write set: stage every file, then swap.

    `writes` maps path -> already-serialized text. `os.replace` is atomic per
    file, so no single output can be torn — but four sequential writes are not
    atomic ACROSS files: a failure on the third leaves two files from the new
    generation beside two from the old, and every consumer of a dashboard
    generation (the browser, the semantic diff, the publication pathspec) treats
    them as one thing.

    Staging every file first shrinks the window from "serialize + write + fsync,
    four times" down to the `os.replace` calls themselves, and converts the
    common failures — a full disk, a read-only mount, an unwritable directory —
    from "publish a mixed generation" into "publish nothing and raise".

    Targets are checked before anything is staged, because a target that cannot
    be replaced at all (one that is a directory) would otherwise fail in the swap
    loop, i.e. after earlier files had already been published — the exact outcome
    this exists to prevent.

    What remains is genuinely irreducible: the swap loop itself. If the directory
    is removed between staging and replacing, some files can land and others not.
    Files cannot be swapped atomically as a group without a transactional
    filesystem; this narrows the window to consecutive `os.replace` calls rather
    than closing it, and the payloads carry generation IDs so a reader can still
    tell.

    Returns the paths written, in the order given.
    """
    for path in map(Path, writes):
        if path.is_dir():
            raise IsADirectoryError(
                f"{path} is a directory; the write set cannot be swapped in")
    staged: list[tuple[str, Path]] = []
    try:
        for raw, text in writes.items():
            path = Path(raw)
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".staged-")
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            # `mkstemp` creates 0600, and `os.replace` swaps the inode — so the
            # published file inherits the temp file's permissions, not the ones
            # it had. These are artifacts a web server serves; 0600 is an
            # artifact of how they were staged, not a decision. It stayed
            # invisible for as long as they went out through git, which
            # normalises the mode to 100644 in the index, and surfaced the first
            # time a consumer read them off disk instead: the Pages build,
            # whose Jekyll container could not read its own inputs.
            os.chmod(tmp, PUBLISHED_MODE)
            staged.append((tmp, path))
    except BaseException:
        for tmp, _ in staged:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
        raise
    # Every byte is on disk; only the swaps remain.
    for tmp, path in staged:
        os.replace(tmp, path)
    return [str(path) for _, path in staged]


def _check_names(files: Mapping[str, str]) -> None:
    """Reject a write set that cannot be stored as a self-contained generation.

    An empty mapping is refused rather than treated as "nothing to do": for a
    store that replaces its whole state — `GitBranchStore` does — publishing
    zero files means publishing an empty generation over a good one.
    """
    if not files:
        raise ValueError("refusing to publish an empty generation")
    for name in files:
        path = Path(name)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(
                f"generation member must be a relative path inside the store: {name!r}")


@dataclass(frozen=True)
class PublishResult:
    """What the store holds now, and whether this call is what put it there.

    `changed` is not decoration. A publisher has to answer "did anything move?"
    to decide whether to ask for a deploy, and a store that always claimed yes
    would make every tick request one. It is also the honest answer to the
    reverse question: a store already holding this exact generation was not
    written to.
    """

    receipt: str
    changed: bool


class ArtifactStore(Protocol):
    """Somewhere a generation can be put, addressed by relative path."""

    name: str

    def publish(self, files: Mapping[str, str], *, label: str = "") -> PublishResult:
        """Store `files` (relative path -> text) as one generation.

        Idempotent: storing a generation the store already holds is a no-op that
        reports `changed=False`, not a second write of the same bytes. `label` is
        a human description of the generation; a store with nowhere to put one is
        free to ignore it.
        """


class FilesystemStore:
    """A directory. The default, and what publishing means with no remote.

    `label` is dropped: a directory has nowhere to record why a generation was
    written. The payloads carry their own generation IDs, so nothing is lost that
    a reader needs.
    """

    name = "filesystem"

    def __init__(self, directory: Path | str) -> None:
        self.directory = Path(directory)

    def _current(self, name: str) -> str | None:
        try:
            return (self.directory / name).read_text(encoding="utf-8")
        except OSError:
            return None

    def publish(self, files: Mapping[str, str], *, label: str = "") -> PublishResult:
        _check_names(files)
        if all(self._current(name) == text for name, text in files.items()):
            return PublishResult(str(self.directory), changed=False)
        write_generation(
            {str(self.directory / name): text for name, text in files.items()})
        return PublishResult(str(self.directory), changed=True)


class GitBranchStore:
    """An orphan, force-updated branch: the generation, and nothing else.

    Force-updated because this branch is state, not history. Each publish is a
    parentless commit whose tree is exactly the generation, so the branch never
    accumulates the 72 commits/day that put the outputs on `master` in the first
    place. Nothing rebases onto it and nothing merges it, which is what makes
    discarding its history safe — and what makes pointing it at a branch someone
    *does* build on catastrophic, hence `_reject_protected`.

    Everything is built with plumbing (`hash-object`, `update-index` against a
    throwaway index file, `write-tree`, `commit-tree`), so the caller's index,
    worktree, HEAD and stash are untouched. The live publisher calls this from
    inside the workspace checkout while that checkout is on `master` with a dirty
    tree; a `checkout`/`add`/`commit` implementation would be publishing by
    disturbing the thing it publishes from.
    """

    name = "git-branch"

    # Never force-update a branch other refs are built on. `HEAD` is here
    # because it is accepted where a branch name is expected and would resolve
    # to whatever the repository is currently on.
    ALWAYS_PROTECTED = frozenset({"master", "main", "HEAD"})

    def __init__(
        self,
        repo: Path | str,
        branch: str,
        *,
        remote: str = "origin",
        author_name: str | None = None,
        author_email: str | None = None,
    ) -> None:
        self.repo = Path(repo)
        self.branch = branch
        self.remote = remote
        self.author_name = author_name
        self.author_email = author_email

    # ── git plumbing ────────────────────────────────────────────────────────
    def _argv(self, *args: str) -> list[str]:
        identity: list[str] = []
        if self.author_name:
            identity += ["-c", f"user.name={self.author_name}"]
        if self.author_email:
            identity += ["-c", f"user.email={self.author_email}"]
        return ["git", "-C", str(self.repo), *identity, *args]

    def _git(self, *args: str, env: dict | None = None, stdin: str | None = None) -> str:
        result = subprocess.run(
            self._argv(*args),
            input=stdin, capture_output=True, text=True, env=env, check=True,
            # A hung git remote must fail the publish, not park the process
            # forever (#848).
            timeout=120,
        )
        return result.stdout.strip()

    def _git_blob(self, ref: str, name: str) -> str:
        """Read a stored file back with its bytes intact.

        Separate from `_git` because that one strips — right for a sha or a ref
        name, wrong for content. A trailing newline silently removed here would
        make a fetched generation differ from the published one by exactly the
        byte no diff prints, and byte-equality is the acceptance criterion for
        the whole migration.
        """
        result = subprocess.run(
            self._argv("cat-file", "blob", f"{ref}:{name}"),
            capture_output=True, check=True,
            timeout=120,
        )
        return result.stdout.decode("utf-8")

    def _default_branch(self) -> str | None:
        """The remote's own default branch, asked of the remote.

        `refs/remotes/<remote>/HEAD` is a local convenience that plenty of
        checkouts do not have — a bare local remote, `clone --no-tags`, a remote
        added by hand, or `remote` given as a bare URL. Falling back to the
        static `master`/`main` list there would leave a repository whose default
        is `trunk` unprotected, which is the whole point of asking. `ls-remote`
        answers over ssh and https alike; the local ref is the fallback, not the
        source.
        """
        try:
            listing = self._git("ls-remote", "--symref", self.remote, "HEAD")
        except subprocess.CalledProcessError:
            listing = ""
        for line in listing.splitlines():
            if line.startswith("ref:"):
                ref = line.split()[1]
                return ref.removeprefix("refs/heads/")
        try:
            ref = self._git(
                "symbolic-ref", "--short", f"refs/remotes/{self.remote}/HEAD")
        except subprocess.CalledProcessError:
            return None
        return ref.split("/", 1)[1] if "/" in ref else ref

    def _reject_protected(self) -> None:
        if not self.branch or self.branch.startswith("refs/"):
            # A fully-qualified ref would be pushed to `refs/heads/refs/heads/…`
            # rather than the branch the caller meant, so the guard below would
            # be inspecting a name nothing is published to.
            raise ValueError(
                f"expected a branch name, got {self.branch!r}")
        protected = set(self.ALWAYS_PROTECTED)
        default = self._default_branch()
        if default:
            protected.add(default)
        if self.branch in protected:
            raise ValueError(
                f"refusing to force-update {self.branch!r}: this store replaces "
                f"the branch's entire history on every publish")

    def _stored_tree(self) -> str | None:
        """The tree the branch holds right now, or None if it holds nothing.

        Fetched at full depth, which for a parentless branch is one commit — the
        same cost `--depth=1` would have. `--depth=1` is not merely redundant
        here, it is harmful: it writes a shallow boundary into the CALLER's
        repository, and a shallow repository has its pushes rejected ("shallow
        update not allowed"). The caller is the live workspace checkout, and the
        push it would break is the one that publishes `master`.
        """
        try:
            self._git("fetch", self.remote, self.branch)
        except subprocess.CalledProcessError:
            return None                      # branch does not exist yet
        try:
            return self._git("rev-parse", "FETCH_HEAD^{tree}")
        except subprocess.CalledProcessError:
            return None

    # ── ArtifactStore ───────────────────────────────────────────────────────
    def publish(self, files: Mapping[str, str], *, label: str = "",
                attempts: int = 3) -> PublishResult:
        _check_names(files)
        self._reject_protected()

        with tempfile.TemporaryDirectory() as tmp:
            # A scratch index, so `update-index` cannot touch the real one. It
            # also builds subdirectory trees for us, which hand-rolled `mktree`
            # would not.
            env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp) / "index")}
            for name, text in sorted(files.items()):
                blob = self._git("hash-object", "-w", "--stdin", stdin=text)
                self._git("update-index", "--add",
                          "--cacheinfo", f"100644,{blob},{name}", env=env)
            tree = self._git("write-tree", env=env)

        # Compare against what the BRANCH holds, not against what the caller
        # thinks changed. Those are different questions, and the difference is
        # the only thing that makes a failed publish self-healing: a caller that
        # skipped this tick because "nothing changed locally" would never notice
        # that last tick's generation never arrived, and the branch would sit
        # stale until the next genuine change — indefinitely, on a quiet day.
        # It also covers the first publish, where there is no branch at all.
        if self._stored_tree() == tree:
            return PublishResult(self._git("rev-parse", "FETCH_HEAD"), changed=False)

        # No `-p`: parentless, so the branch is a snapshot and not a log.
        commit = self._git("commit-tree", tree, "-m", label or "generation")
        # Retried like every other publish here. There is nothing to rebase onto
        # a force-updated orphan ref, so `safe_push.sh`'s rebase machinery has
        # nothing to do — but its retry answers the transient failure that would
        # otherwise leave the branch a generation behind.
        for attempt in range(1, attempts + 1):
            try:
                self._git("push", "--force", self.remote,
                          f"{commit}:refs/heads/{self.branch}")
                break
            except subprocess.CalledProcessError:
                if attempt == attempts:
                    raise
                time.sleep(attempt * 3)
        return PublishResult(commit, changed=True)

    def fetch(self, into: Path | str, *, names=None) -> list[str]:
        """Materialise the stored generation into a directory.

        The read side of the same seam. Two callers need it and neither wants a
        checkout: the Pages build has to put the payloads where Jekyll will pick
        them up, and the semantic diff has to answer "what did we publish last
        time" once that is no longer a question about this repository's history.

        Written through `write_generation`, so a fetch is the same all-or-nothing
        write set a build is — a half-materialised generation would be published
        by the very next step.

        `names` asserts what the caller expects to be there. A member the branch
        does not carry raises rather than being skipped: silently materialising
        three of four files is how a page ends up serving one payload from this
        generation and another from whatever was on disk.
        """
        # Full depth for the same reason `_stored_tree` uses it: `--depth=1`
        # writes a shallow boundary into the repository doing the fetch, and a
        # shallow repository has its pushes rejected. A parentless branch is one
        # commit either way.
        self._git("fetch", self.remote, self.branch)
        listed = self._git("ls-tree", "-r", "--name-only", "FETCH_HEAD").split("\n")
        listed = [name for name in listed if name]
        wanted = list(names) if names is not None else listed
        missing = [name for name in wanted if name not in listed]
        if missing:
            raise FileNotFoundError(
                f"{self.remote}/{self.branch} does not carry {missing}")
        into = Path(into)
        write_generation({
            str(into / name): self._git_blob("FETCH_HEAD", name) for name in wanted
        })
        return wanted
