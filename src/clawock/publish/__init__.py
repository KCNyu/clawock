"""Where a generation of build outputs is stored — separately from how it is built.

`clawock dashboard-build` writes four files that are one logical generation (#308).
Where that generation *went* was never a decision: it went into the worktree it
was built in, and got committed, which is why 71% of the commits on `master`
are `dashboard:` publishes (#314).

This package is the missing seam. A store answers "put this generation
somewhere"; it does not build it, render it, or deploy a site. Git is
simultaneously audit log, concurrency protocol, state replication, auth boundary
and Pages trigger (#203) — a store that also triggered a deploy would fuse two of
those into one thing that can only be replaced as a unit.
"""
from __future__ import annotations

from clawock.publish.deploy import (  # noqa: F401
    GitHubDispatchDeployer,
    NullDeployer,
    SiteDeployer,
)
from clawock.publish.store import (  # noqa: F401
    ArtifactStore,
    FilesystemStore,
    GitBranchStore,
    PublishResult,
    write_generation,
)

__all__ = [
    "ArtifactStore", "FilesystemStore", "GitBranchStore", "PublishResult",
    "write_generation",
    "GitHubDispatchDeployer", "NullDeployer", "SiteDeployer",
]
