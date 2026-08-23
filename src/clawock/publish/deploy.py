"""Asking for the site to be rebuilt — the third thing git was doing at once.

Storing a generation and making it visible are different jobs, and in this
repository they were the same act: a `dashboard:` commit on `master` matched the
Pages workflow's `paths:` filter, so pushing the data *was* the deploy trigger.
Take the data off `master` (#314) and the trigger silently goes with it — the
site keeps serving the last generation it happened to build, with no failure
anywhere.

So the trigger has to be asked for explicitly, and by something that is not the
store. Git is simultaneously audit log, concurrency protocol, state replication,
auth boundary and Pages trigger (#203); this is the seam that separates the last
of those from the rest.

An orphan branch cannot carry the trigger itself: a `push` event runs the
workflows *on the pushed ref*, and a data branch has none. `repository_dispatch`
is the one mechanism that works from every publisher this repository has —
GitHub documents it and `workflow_dispatch` as the two events that create a run
**even when sent with the automatic `GITHUB_TOKEN`**, so the Actions publishers
need no extra secret and the host needs no special case.
"""
from __future__ import annotations

import json
import subprocess
from typing import Protocol


class SiteDeployer(Protocol):
    """Makes the stored generation visible, or knows there is nothing to do."""

    name: str

    def request(self, reason: str = "") -> str:
        """Ask for the site to be rebuilt from what the store now holds.

        Returns a receipt for the caller to log. Raises if the request could not
        be made — a deploy that was never asked for must not read as success,
        because the failure it hides is a site frozen on an old generation while
        every other gate stays green.
        """


class NullDeployer:
    """No deploy step. The default, and correct for a filesystem store.

    Publishing into a directory that something else serves needs nothing asked
    of anyone. This exists so "no deployer configured" is a decision the code
    states rather than a branch every caller writes.
    """

    name = "null"

    def request(self, reason: str = "") -> str:
        return "no deploy step configured"


class GitHubDispatchDeployer:
    """`repository_dispatch`, sent through `gh`.

    `gh` rather than a hand-rolled HTTPS call because it already resolves an
    identity in both places this runs: the host's stored login, and
    `GITHUB_TOKEN`/`GH_TOKEN` on a runner. One transport, no token handling here,
    and nothing new to keep out of a log.

    Deliberately *not* the deploy itself. This asks; GitHub Actions builds and
    deploys. Doing the build here would put the Pages artifact's contents at the
    mercy of whichever machine happened to publish.
    """

    name = "github-dispatch"

    def __init__(self, repository: str, event_type: str = "data-plane-published") -> None:
        self.repository = repository
        self.event_type = event_type

    def request(self, reason: str = "") -> str:
        # The whole body as one JSON document on stdin, not `-f`/`--raw-field`
        # pairs. `client_payload` has to arrive as an OBJECT, and both of those
        # flags send their value as a string — GitHub answers 422 ("is not an
        # object") and the deploy is never requested. A fake `gh` that only
        # checks the command exits 0 cannot see this; the test below parses the
        # body it was handed.
        body = {"event_type": self.event_type}
        if reason:
            body["client_payload"] = {"reason": reason}
        subprocess.run(
            ["gh", "api", "--method", "POST",
             f"repos/{self.repository}/dispatches", "--input", "-"],
            input=json.dumps(body), check=True, capture_output=True, text=True,
            # A hung dispatch request must surface as a failed deploy, not an
            # endless wait (#848).
            timeout=120,
        )
        return f"{self.event_type} → {self.repository}"
