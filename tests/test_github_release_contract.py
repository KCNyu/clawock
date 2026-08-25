"""A PyPI version must leave a matching, honest first-party release page."""
from pathlib import Path
import re

import pytest
import json
from urllib.parse import urlsplit

from ops.publish.release_notes import changelog_section, release_notes


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


def test_release_notes_use_only_the_matching_public_changelog_section():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    notes = release_notes(text, "0.1.1")

    assert "https://pypi.org/project/clawock/0.1.1/" in notes
    assert "python -m pip install clawock==0.1.1" in notes
    assert "six broken images" in notes
    assert "https://github.com/KCNyu/clawock/pull/468" in notes
    assert "First release" not in notes
    assert "[Unreleased]" not in notes
    assert "compare/v0.1.1...HEAD" not in notes


@pytest.mark.parametrize("text", [
    "## [Unreleased]\nNothing yet.\n",
    "## [1.2.3]\none\n\n## [1.2.3]\ntwo\n",
    "## [1.2.3] — 2026-08-11\n\n## [1.2.2]\nolder\n",
])
def test_missing_ambiguous_or_empty_changelog_sections_fail(text):
    with pytest.raises(ValueError):
        changelog_section(text, "1.2.3")


def test_github_release_is_downstream_of_real_pypi_and_attaches_artifacts():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    release_job = workflow.split("\n  github-release:\n", 1)[1]

    # Both publishers must have accepted before the GitHub Release exists —
    # pinned exact, not `needs: publish`-or-anything (#607: it was relaxed once
    # and a regression to the PyPI-only dependency would not have failed).
    assert "needs: [publish, npm]" in release_job
    assert "if: startsWith(github.ref, 'refs/tags/v')" in release_job
    assert "contents: write" in release_job
    assert "ops/publish/release_notes.py" in release_job
    assert "actions/download-artifact" in release_job
    assert 'gh release create "$GITHUB_REF_NAME" dist/*' in release_job
    assert workflow.count("contents: write") == 1


def test_npm_version_bump_is_idempotent_in_both_publish_paths():
    """#617: `npm version <same>` exits non-zero; once package.json syncs to
    the tag version, the next release would fail both the npm job and the
    github-release pack step. Both paths must skip the bump when versions
    already match."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "already at" in workflow, workflow
    assert '"$current" != "$target"' in workflow

    script = (ROOT / "ops" / "publish" / "publish_dsh_plugin.sh").read_text(encoding="utf-8")
    assert '"$current" != "$version"' in script
    assert "skipping bump" in script


def test_the_npm_publish_cannot_fail_silently():
    """A publish step that swallows its own output is unfixable.

    On 2026-08-17 the v0.1.6 npm job died twice with npm's own
    `Exit handler never called!`. The script ran the install as
    `npm install ... >/dev/null`, so the log held nothing between "skipping
    bump" and the crash — the failing command had to be identified by
    reproducing it on the desk host instead. PyPI had already accepted 0.1.6 by
    then, so the release sat half-published while the log said nothing useful.
    """
    script = (ROOT / "ops" / "publish" / "publish_dsh_plugin.sh").read_text()

    assert "npm install --include=dev --no-audit --no-fund >/dev/null" not in script, (
        "the dev install must not send its output to /dev/null"
    )
    assert "npm --version" in script, "the publish has to record which npm did the work"
    assert "npm config get registry" in script, (
        "and which registry — a mirror in ~/.npmrc silently retargets a publish"
    )


def test_the_release_pins_the_npm_that_publishes():
    """setup-node ships whatever npm rides with the Node release.

    Letting a runner image decide which npm performs the publish is what turned
    v0.1.6 into a half-released version: PyPI accepted 0.1.6, npm never got it.
    The same install is clean on the pinned version.
    """
    workflow = WORKFLOW.read_text()
    assert "npm install -g npm@" in workflow, (
        "the npm job must pin the npm it publishes with"
    )
    pin_at = workflow.index("npm install -g npm@")
    publish_at = workflow.index("publish_dsh_plugin.sh")
    assert pin_at < publish_at, "the pin has to come before the publish, not after"

def test_the_release_tgz_is_rebuilt_from_source_and_refuses_a_stale_tree():
    """The release asset and the npm tarball carry the same version number, so
    they must be the same build.

    #712 was "one version number, two sets of files", found by hand months
    later. The npm half always rebuilds before publishing
    (publish_dsh_plugin.sh); the GitHub Release half used to pack whatever
    lib/ was committed at the tag — equal only when the tag happened to sit on
    a commit whose lane-gated rebuild-is-no-op check ran (#998). A tag can
    point at a commit no CI run ever gated, so the release job has to enforce
    it itself: build, then hard-fail on a dirty lib/ instead of attaching a
    divergent tgz to an immutable release page.
    """
    workflow = WORKFLOW.read_text(encoding="utf-8")
    release_job = workflow.split("\n  github-release:\n", 1)[1]

    bump_at = release_job.index('npm version "$target" --no-git-tag-version')
    install_at = release_job.index("npm install --include=dev")
    build_at = release_job.index("npm run build")
    guard_at = release_job.index("git diff --exit-code -- lib")
    pack_at = release_job.index("\n          npm pack")
    assert bump_at < install_at < build_at < guard_at < pack_at, (
        "the pack must come after a from-source rebuild and its stale-tree guard"
    )
    assert "diverge from the published npm tarball" in release_job, (
        "the failure message must name what a stale tree actually breaks"
    )


def test_npm_only_dispatch_runs_only_npm_and_never_a_github_release():
    """Repairing the npm side of a half-published version must not need a tag
    and must not create a GitHub Release.

    v0.1.6's PyPI upload succeeded while its npm job died (runner npm crashed
    with `Exit handler never called!`), leaving the version half-published.
    The repair path is a workflow_dispatch from a branch ref: `npm_only` runs
    the npm job alone — no PyPI re-upload, and github-release stays tag-only,
    so no dispatch can leave a release behind.
    """
    workflow = WORKFLOW.read_text()
    dispatch = workflow.split("workflow_dispatch:", 1)[1].split("permissions:")[0]
    assert "npm_only" in dispatch, "the dispatch must expose the npm-only mode"

    publish_job = workflow.split("\n  publish:\n", 1)[1].split("\n  npm:\n", 1)[0]
    assert "inputs.npm_only != 'true' && inputs.npm_only != true" in publish_job, (
        "npm-only dispatch must never re-upload an already-published PyPI version"
    )

    npm_job = workflow.split("\n  npm:\n", 1)[1].split("\n  github-release:\n", 1)[0]
    assert "inputs.npm_only == 'true' || inputs.npm_only == true" in npm_job, (
        "npm-only dispatch has to enable the npm job from a branch ref"
    )
    assert "tomllib.load(open('pyproject.toml'" in npm_job, (
        "the publish version must come from pyproject.toml, not from the ref "
        "name — a branch dispatch has no tag version to strip off"
    )
    assert "${GITHUB_REF_NAME#v}" not in npm_job, (
        "a branch ref would publish the branch name as the version"
    )

    release_job = workflow.split("\n  github-release:\n", 1)[1]
    assert "needs: [publish, npm]" in release_job
    assert "if: startsWith(github.ref, 'refs/tags/v')" in release_job


def test_the_npm_install_can_survive_a_stalled_runner_fetch():
    """The v0.1.6 npm job died in its first cold-cache `npm install`, not in
    publish: the runner's registry fetch stalled ~70s per request (npm's retry
    ladder, then npm's own `Exit handler never called!`) while the same install
    is instant on every other network tried. The publish must retry the
    install, and the job must force IPv4 DNS ordering — the classic
    runner-side stall cause — instead of hoping the fetch is fast this time.
    """
    workflow = WORKFLOW.read_text()
    assert "--dns-result-order=ipv4first" in workflow, (
        "the npm job must force IPv4 DNS ordering on the runner"
    )
    assert "NO_UPDATE_NOTIFIER" in workflow, (
        "npm must not ping the registry for updates on top of the stalled fetch"
    )
    assert "npm_config_replace_registry_host: 'always'" in workflow, (
        "the npm job must rehost any lockfile URL to the configured registry"
    )

    script = (ROOT / "ops" / "publish" / "publish_dsh_plugin.sh").read_text()
    assert "npm install attempt " in script, (
        "the install must retry instead of failing the publish"
    )
    assert "set +e" in script, (
        "the install must capture the real exit status, not the if-masked 0"
    )
    assert "*-debug-0.log" in script, (
        "a stalled install must surface npm's own debug log"
    )


def test_the_plugin_lockfile_does_not_bake_in_a_mirror_registry():
    """npm installs from the lockfile's `resolved` URLs, not from the
    configured registry. On 2026-08-17 the 0.1.6 lockfile had been regenerated
    on the desk under a mirror registry, so every resolved URL pointed at
    mirrors.tencentyun.com — unreachable from the GitHub runner — and the npm
    job died after each fetch stalled through npm's retry ladder. The lockfile
    must stay on registry.npmjs.org URLs (or carry no resolved overrides at
    all).
    """
    lock = json.loads((ROOT / "examples" / "dsh" / "packages" / "clawock-dsh" / "package-lock.json").read_text())
    urls = [
        p.get("resolved")
        for p in lock.get("packages", {}).values()
        if isinstance(p, dict) and p.get("resolved")
    ]
    assert urls, "the lockfile pins tarball URLs — they must be checked"
    # Compare the parsed host, not a substring: `mirrors.example.com/registry.npmjs.org/...`
    # would satisfy a substring check while still pointing at the mirror.
    hosts = {urlsplit(u).hostname for u in urls}
    assert hosts == {"registry.npmjs.org"}, (
        f"the lockfile must not bake in a mirror registry unreachable from CI: {sorted(hosts)}"
    )


def test_the_publish_verifies_what_the_registry_actually_serves():
    """`npm publish` exiting 0 is not evidence that the registry holds this code.

    #712: npm's clawock-dsh@0.1.5 was a different build than the repo's 0.1.5 —
    one version number, two sets of files — and it was found by hand, months
    later, by unpacking the tarball. #732 asked for that hand check to become an
    automatic post-publish assertion. Verified against the real 0.1.5 tarball
    while writing it: the check names the missing lib/, the top-level client.js,
    the lost ./typert and ./remote exports and the missing zod dependency.
    """
    script = (ROOT / "ops" / "publish" / "publish_dsh_plugin.sh").read_text(encoding="utf-8")
    publish_at = script.index("npm publish --access public")
    verify_at = script.index("verifying the published tarball")
    assert publish_at < verify_at, "the verification has to read the registry copy, after publishing"

    tail = script[verify_at:]
    assert 'npm pack "clawock-dsh@$published"' in tail, (
        "the check must download what the registry serves, not re-read the local tree"
    )
    assert "pre-#708 layout" in tail, "the #712 fingerprint (top-level client.js) must be named"
    assert "lost the ${dependency} dependency" in tail, (
        "a published manifest that dropped a runtime dependency is the #708 failure again"
    )
    assert "published tarball is missing" in tail, (
        "every file the pack listed must exist in the registry copy"
    )


def test_the_npm_publish_carries_provenance():
    """The two halves of the release train must carry equivalent credentials.

    The PyPI half publishes through trusted publishing: PyPI verifies the
    workflow's OIDC identity and no long-lived token exists to leak. The npm
    half had none of that (#785) — it published with a plain `NPM_TOKEN` and no
    `--provenance`, so the package page, which is this project's
    highest-traffic landing surface, carried no verifiable statement of what
    built the tarball.

    Two things have to hold together or the flag degrades to a no-op:
    the job must be granted the OIDC token, and the script must ask for it.
    """
    workflow = WORKFLOW.read_text(encoding="utf-8")
    npm_job = workflow.split("\n  npm:\n", 1)[1].split("\n  github-release:", 1)[0]
    assert "id-token: write" in npm_job, (
        "the npm job needs the OIDC token npm exchanges for a provenance attestation"
    )

    script = (ROOT / "ops" / "publish" / "publish_dsh_plugin.sh").read_text(encoding="utf-8")
    assert "--provenance" in script, "the publish has to ask for provenance"
    # A human running the script directly is a documented path, and npm hard-fails
    # when asked for provenance outside a supported CI — so the flag has to be
    # conditional, never unconditional.
    assert "ACTIONS_ID_TOKEN_REQUEST_URL" in script, (
        "provenance must be gated on an actually-present OIDC token, so a local "
        "publish degrades instead of failing"
    )


def test_the_pypi_publisher_is_pinned_to_a_commit():
    """A moving ref decides, from outside this repository, what code performs an
    irreversible publish.

    This is not hypothetical here. v0.1.6 half-published — PyPI accepted it,
    npm died — because the runner image's bundled npm crashed, and the fix was
    to pin npm. The PyPI half was still on `@release/v1`, whose contents change
    without anything in this repository moving (#808).
    """
    workflow = WORKFLOW.read_text(encoding="utf-8")
    publish = workflow.split("\n      - name: Publish\n", 1)[1].split("\n  npm:", 1)[0]
    ref = next(line.split("@", 1)[1].split()[0]
               for line in publish.splitlines()
               if "gh-action-pypi-publish@" in line)
    assert re.fullmatch(r"[0-9a-f]{40}", ref), (
        f"the PyPI publisher must be pinned to a 40-character commit sha, got {ref!r}"
    )
    assert "# v" in publish, "the pin needs a human-readable version comment beside it"


def test_the_environment_comment_does_not_claim_controls_that_do_not_exist():
    """#810: the comment claimed the pypi environment carried a required
    reviewer while `protection_rules` was empty. A comment describing a control
    nobody configured is worse than none — the next reader assumes somebody is
    watching that door.

    The claim is now a branch policy, which is what is actually configured, and
    the comment records the two runs that measured it in both directions.
    """
    workflow = WORKFLOW.read_text(encoding="utf-8")
    publish_job = workflow.split("\n  publish:\n", 1)[1].split("\n  npm:", 1)[0]
    assert "required reviewer as well" not in publish_job, (
        "the environment carries no required reviewer; do not say it does"
    )
    assert "deployment branch policy" in publish_job


def test_the_runbook_explains_that_a_pushed_version_tag_is_frozen():
    """#809 made `v*` tags immutable, which changes what a mistyped tag costs.

    A rule that silently makes the normal recovery impossible is how somebody
    concludes the repository is broken at 2am. The runbook has to carry both the
    escape hatch and the reason not to reach for it.
    """
    runbook = (ROOT / "docs" / "operations" / "release.md").read_text(encoding="utf-8")
    assert "cannot be moved or deleted once pushed" in runbook
    assert "enforcement=disabled" in runbook, "the recovery path must be written down"
    assert "enforcement=active" in runbook, "and so must putting the rule back"
    assert "non_fast_forward" in runbook and "update" in runbook, (
        "the trap that cost a real tag — a forward move passes non_fast_forward — "
        "has to be recorded, or the next person configures the same weak rule"
    )
