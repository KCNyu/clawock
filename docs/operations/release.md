# Releasing `clawock` to PyPI

Only the `clawock` distribution is published. It owns lifecycle, strategies,
scheduling, watchdogs and provider integrations. Declarative profiles and live
workspace data are inputs to that distribution, never packages of their own.

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

## The npm side: `clawock-dsh` (DSH skill package)

The DSH skill package rides the same version train as the Python package.
`ops/publish/publish_dsh_plugin.sh` is the single entry point for every npm
publication path — release.yml and a human both go through it:

```bash
# Publish whatever version examples/dsh/plugin/package.json declares
NPM_TOKEN=... ops/publish/publish_dsh_plugin.sh

# Standalone npm bump (no GitHub Release, no PyPI): the version is explicit
NPM_TOKEN=... ops/publish/publish_dsh_plugin.sh 0.2.1
```

`NPM_TOKEN` is the npm registry auth token and the only environment input the
script needs (a userconfig with registry auth works too). Before touching the
registry it rebuilds the plugin artifacts (`npm install --include=dev &&
npm run build` — src → lib + Typert generation, so the published package never
ships stale committed output) and runs `npm pack --dry-run` to verify the
package, its `skills/investment-decision/SKILL.md`, and the generated
`lib/typert.remote-client.js` all exist.

On a `v*` tag the workflow's `npm` job calls the same script with the tag
version (`"${GITHUB_REF_NAME#v}"`), so PyPI and npm publish together; the GitHub
Release is created only after both publishers accepted (`needs: [publish, npm]`).
PR pushes and TestPyPI dispatches never touch npm.

## One version, three places

A release version is declared in `pyproject.toml`, and two other places must
not disagree with it:

- `pyproject.toml` — what PyPI publishes; the workflow refuses a tag that
  disagrees with it
- `examples/dsh/plugin/package.json` — what npm publishes; the publish script
  bumps it to the version it is given
- `CHANGELOG.md` top entry — what the version claims to contain

`tests/test_versions_agree.py` enforces the contract in CI: the newest changelog
entry must be the `pyproject.toml` version, entries must be unique and
newest-first, and the changelog must be reachable from the package metadata. A
bump that updates `pyproject.toml` alone meets a red `validate` before any tag
can be cut.

## The bump is idempotent

`npm version <same>` exits non-zero (#617), so both publish paths compare
first: when `package.json` already sits at the target version — a re-run after
a partial failure, for instance — the bump is skipped with no error and the
flow proceeds straight to publish. Running the standalone command twice is
safe.

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
