"""Artifact stores: a generation of files, put somewhere, as one write set.

Two implementations, and the difference between them is the whole point of the
seam:

* `FilesystemStore` — the default, and the only thing a third party gets without
  configuring anything. Writing the files where they were built is a store, not
  the absence of one; a clawock that defaults to pushing somewhere would be
  wrong.
* `GitBranchStore` — an instance deployment. A fast-forwarded ref built
  entirely with plumbing so it never touches the caller's
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
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol
from uuid import uuid4



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
        if path.is_absolute() or ".." in path.parts or "\0" in name:
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
    # The receipt this call replaced, when the store can name one. The deploy
    # decision compares against exactly that generation (publish_data_branch).
    previous: str | None = None


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


# ── publish budget ────────────────────────────────────────────────────────
# Named, and exported, because two layers have to agree on them and until
# 2026-09-07 they only agreed by coincidence: `_harness_common._publish_generation`
# wrapped the whole publish script in a hardcoded `timeout=120` — the SAME number
# as one git call below. An outer budget equal to a single inner step cannot
# accommodate even two of them, so a publish whose first network call hung was
# killed before its second could start, and the push retry ladder below was
# unreachable by construction.
#
# The numbers are not renegotiated here (a hung remote must still fail the
# publish rather than park the process, #848). What changes is that the outer
# budget is now DERIVED from them.
from clawock.run_budgets import (  # noqa: E402,F401
    GIT_CALL_TIMEOUT_SECONDS, PUSH_ATTEMPTS, PUSH_RETRY_BACKOFF_STEP_SECONDS,
    PUBLISH_NETWORK_CALLS, PUBLISH_BUDGET_SECONDS, DEPLOY_REQUEST_TIMEOUT_SECONDS,
    PUBLISH_LOOKUP_TIMEOUT_SECONDS,
)


class GitBranchStore:
    """Publish a repository generation without changing the caller's checkout.

    The store uses a private index and fast-forwards from the fetched commit.
    Overlay callers manage only their issued paths so independent publishers
    can share a branch with one retry contract.
    """

    name = "git-branch"

    # Do not publish artifact trees to a branch other refs are built on. `HEAD` is here
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

    def _git(self, *args: str, env: dict | None = None, stdin: str | None = None,
             timeout=GIT_CALL_TIMEOUT_SECONDS) -> str:
        result = subprocess.run(
            self._argv(*args),
            input=stdin, capture_output=True, text=True, env=env, check=True,
            # A hung git remote must fail the publish, not park the process
            # forever (#848).
            timeout=timeout,
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
            timeout=GIT_CALL_TIMEOUT_SECONDS,
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
            listing = self._git("ls-remote", "--symref", self.remote, "HEAD",
                                timeout=PUBLISH_LOOKUP_TIMEOUT_SECONDS)
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
                f"refusing to publish artifacts to protected branch {self.branch!r}")

    @contextmanager
    def _fetched_commit(self, *, timeout=GIT_CALL_TIMEOUT_SECONDS):
        """Pin one remote generation without touching the caller's FETCH_HEAD.

        A fetch by another process can change FETCH_HEAD between any two git
        calls. A private ref also keeps the commit reachable until
        every blob has been read. Full depth avoids making the caller shallow.
        """
        ref = f"refs/clawock/fetch/{uuid4().hex}"
        try:
            self._git("fetch", "--no-write-fetch-head", self.remote,
                      f"+refs/heads/{self.branch}:{ref}", timeout=timeout)
            yield self._git("rev-parse", f"{ref}^{{commit}}")
        finally:
            self._git("update-ref", "-d", ref)

    def _stored_generation(self) -> tuple[str, str] | None:
        """(commit, tree) for one fetched generation, or None on a missing read."""
        try:
            with self._fetched_commit(timeout=PUBLISH_LOOKUP_TIMEOUT_SECONDS) as commit:
                return commit, self._git("rev-parse", f"{commit}^{{tree}}")
        except subprocess.CalledProcessError:
            return None

    def publish(self, files: Mapping[str, str], *, label: str = "", overlay=False,
                remove=(), expand=None, attempts: int = PUSH_ATTEMPTS) -> PublishResult:
        """Fast-forward one branch, merging with the latest tree on each retry.

        Overlay writers own the paths they update or explicitly drop. A caller
        supplying `expand` can update a manifest from this exact parent.
        """
        self._reject_protected()
        for attempt in range(1, attempts + 1):
            stored = self._stored_generation()
            previous = stored[0] if stored else None
            writes = {**files, **(expand(previous) if expand else {})}
            _check_names(writes)
            removals = {name: "" for name in remove if name not in writes}
            if removals:
                _check_names(removals)
            with tempfile.TemporaryDirectory() as tmp:
                env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp) / "index")}
                self._git("read-tree", previous if overlay and previous else "--empty", env=env)
                for name in removals:
                    self._git("update-index", "--force-remove", "--", name, env=env)
                entries = []
                for name, body in sorted(writes.items()):
                    blob = self._git("hash-object", "-w", "--stdin", stdin=body)
                    entries.append(f"100644 {blob}\t{name}\0")
                self._git("update-index", "-z", "--index-info", env=env, stdin="".join(entries))
                tree = self._git("write-tree", env=env)
            if stored and tree == stored[1]:
                return PublishResult(previous, changed=False)
            parent = ("-p", previous) if previous else ()
            commit = self._git("commit-tree", tree, *parent, "-m", label or "generation")
            try:
                self._git("push", self.remote, f"{commit}:refs/heads/{self.branch}")
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                if attempt == attempts:
                    raise
                time.sleep(attempt * PUSH_RETRY_BACKOFF_STEP_SECONDS)
            else:
                return PublishResult(commit, changed=True, previous=previous)
        raise ValueError("publication requires a positive attempt count")

    def read(self, receipt: str, name: str) -> str | None:
        """One file of a stored generation by receipt, or None when it is absent."""
        try:
            return self._git_blob(receipt, name)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return None

    def fetch(self, into: Path | str, *, names=None, allow_missing=None, validate=None) -> list[str]:
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
        an incomplete set is how a page ends up serving one payload from this
        generation and another from whatever was on disk.

        `allow_missing` may excuse a known pre-split member after checking its
        parent against this same pinned commit. All other missing members fail.
        """
        with self._fetched_commit() as commit:
            listed = self._git("ls-tree", "-r", "--name-only", commit).split("\n")
            listed = [name for name in listed if name]
            selected = names(commit, listed) if callable(names) else names
            wanted = list(selected) if selected is not None else listed
            missing = [name for name in wanted if name not in listed]
            if missing:
                excused = allow_missing(commit, missing) if allow_missing else []
                if set(excused) != set(missing):
                    raise FileNotFoundError(
                        f"{self.remote}/{self.branch} does not carry {missing}")
                wanted = [name for name in wanted if name not in missing]
            files = {name: self._git_blob(commit, name) for name in wanted}
            if validate is not None:
                validate(files)
            into = Path(into)
            write_generation({str(into / name): body for name, body in files.items()})
        return wanted
