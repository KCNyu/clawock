# Releasing `clawock` to PyPI

Only the runtime-neutral `clawock` distribution is ever published.
`clawock-kcnyu` is this repository's live-instance adapter: it may be installed
locally and in CI, but it must never reach an index, be pulled in by the public
package, or appear in a quickstart an ordinary user follows.

## One-time setup (kcn, on the PyPI side)

Trusted publishing is used instead of an API token, so nothing long-lived sits
in repository secrets. Configure the publisher at
<https://pypi.org/manage/account/publishing/> with:

| field | value |
|---|---|
| PyPI project name | `clawock` |
| Owner | `KCNyu` |
| Repository name | `clawock` |
| Workflow name | `release.yml` |
| Environment name | `pypi` |

Repeat on <https://test.pypi.org/manage/account/publishing/> with environment
name `testpypi` to be able to rehearse.

Then create the two GitHub environments (`Settings → Environments`): `pypi` and
`testpypi`. Adding yourself as a required reviewer on `pypi` is worth it — the
release job then waits for an explicit approval, and a version number, once
published, cannot be reused even after a yank.

## Rehearse on TestPyPI

`Actions → Release → Run workflow`, leaving `repository` at `testpypi`. This runs
the same build and the same isolated-install check without touching the real
index.

## Release

```bash
# version lives in exactly one place
sed -i 's/^version = .*/version = "0.2.0"/' pyproject.toml
# then write the CHANGELOG.md entry for that version, in the same PR
# ...open a PR, merge it, then tag the merge commit
git tag v0.2.0 && git push origin v0.2.0
```

The workflow refuses a tag that disagrees with `pyproject.toml`, because a
mismatch publishes a version nobody asked for under a name the changelog already
uses for something else.

After real PyPI publication succeeds, the same workflow creates the matching
GitHub Release, attaches the verified sdist/wheel and renders only that version's
`CHANGELOG.md` section plus its versioned PyPI link. TestPyPI dispatches do not
create a public GitHub Release, and a failed PyPI upload cannot leave one behind.

`tests/test_versions_agree.py` refuses a bump whose `CHANGELOG.md` entry is
missing, which is why the entry belongs in the same PR as the bump. Writing it
afterwards means the artifact is already on PyPI describing itself as something
nobody wrote down, and a published version cannot be replaced — only superseded,
which is what 0.1.1 cost.

## What the release job proves before it publishes

- `twine check` on both the sdist and the wheel.
- The tag matches the packaged version.
- The matching changelog section exists exactly once and becomes the GitHub
  Release notes; the built sdist/wheel are attached only after PyPI succeeds.
- A clean virtualenv installs the wheel and completes one real run —
  `clawock init` → `clawock run prepare` → `clawock run publish` — under
  `env -i`, with no checkout, no OpenClaw, no KCNyu workspace and no inherited
  environment, then asserts the receipt carries a 32-character `generation_id`
  and both the supplied artifact and its manifest.

That last step is the acceptance criterion of #379, executed against the exact
artifact about to ship rather than against the source tree.
