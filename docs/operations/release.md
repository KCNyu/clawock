# Releasing `clawock` to PyPI

Only the `clawock` distribution is published. It owns lifecycle, strategies,
scheduling, watchdogs and provider integrations. Declarative profiles and live
workspace data are inputs to that distribution, never packages of their own.

## Running the latest code on this host / 本机跑最新代码

**A release is for people who are not this host. Merging is what makes a fix
live here.** 本机不需要为每个修复发一次 release：合并即上线，发版只面向外部用户。

The desk installs the distribution **editable**
(`ops/host/install_clawock_launcher.sh`), so `/root/.openclaw/workspace` is the
implementation rather than a copy of it, and a fast-forward changes behaviour
with no reinstall (`tests/test_clawock_launcher.py` holds that property). One
command applies a merge to the whole host:

```bash
ops/host/refresh_live.sh           # fast-forward, then reinstall only what moved
ops/host/refresh_live.sh --check   # what is pending; writes nothing, exit 1 if behind
```

What it decides, and why the two exceptions exist:

| what moved in the merge | what the desk needs | why |
|---|---|---|
| anything under `src/clawock/` | nothing beyond the fast-forward | the install is editable |
| `pyproject.toml` | `ops/host/install_clawock_launcher.sh` | pip recorded the dependency set and the `[project.scripts]` entry points at install time; a new console script does not exist until it is re-run |
| `examples/dsh/packages/clawock-dsh/**` | `ops/host/install_dsh_plugin.sh --restart` | pnpm installed a packed copy, not a link (#709) — no npm publish involved |

Do not read `clawock --version` as the answer to "what is running here". On an
editable install that number is the one pip recorded, and it says so itself once
the checkout moves past it:

```
clawock 0.1.5 (editable install of /root/.openclaw/workspace, which now declares
0.1.8 — the code that runs is the checkout's; re-run
ops/host/install_clawock_launcher.sh to refresh this metadata)
```

That drift is cosmetic and expected; it was still read as a missing feature once
([#745](https://github.com/KCNyu/clawock/issues/745)), which is why the string
now names the checkout. `git -C /root/.openclaw/workspace log --oneline -1` is
the real answer for the Python half, and for the plugin half it is
`curl -s http://127.0.0.1:3081/plugins/clawock-dsh/client.js | cmp -
examples/dsh/packages/clawock-dsh/lib/client.js` — `refresh_live.sh` runs both
checks itself after it installs anything.

Cut a release when the outside world needs the change — a PyPI/npm user, a
documented install line, a version a skill contract names — and batch fixes into
it. The rest of this page is that path.

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
# Publish whatever version examples/dsh/packages/clawock-dsh/package.json declares
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

On a `v*` tag the workflow's `npm` job calls the same script with the version
read from `pyproject.toml` (the tag–version gate in the `build` job has already
refused a mismatch, so tag refs and branch dispatch refs agree), publishing PyPI
and npm together; the GitHub Release is created only after both publishers
accepted (`needs: [publish, npm]`). PR pushes and TestPyPI dispatches never
touch npm.

### Re-run the npm side alone (no PyPI, no GitHub Release)

A version whose PyPI upload already succeeded while its npm job died (v0.1.6:
the runner's npm crashed with `Exit handler never called!`) is half-published —
superseding it would burn a whole version number. The workflow has a dispatch
mode that publishes just `clawock-dsh` and cannot create a GitHub Release:

```bash
# version is read from pyproject.toml; run from master or the v* tag
gh workflow run release.yml --ref master -f repository=pypi -f npm_only=true
```

`npm_only` skips the PyPI publish job (the index already holds that version,
and re-uploading it is a hard failure), and `github-release` still requires a
`v*` tag — so the dispatch ends with the npm side fixed and no release behind
it.

### The lockfile must not bake in a mirror registry

npm installs from the lockfile's `resolved` URLs, not from the configured
registry. Regenerating `examples/dsh/packages/clawock-dsh/package-lock.json` on a machine
whose npm points at a mirror writes mirror URLs into it — on 2026-08-17 that
made the v0.1.6 npm job die: the GitHub runner cannot reach
`mirrors.tencentyun.com`, every tarball fetch stalled through npm's retry
ladder, and npm exited with `Exit handler never called!`.

Keep the lockfile on `registry.npmjs.org` URLs (`npm install --package-lock-only
--registry=https://registry.npmjs.org` regenerates it), and the release
workflow additionally sets `npm_config_replace_registry_host=always`, so any
future mirror-poisoned lockfile is rehosted to the configured registry instead
of failing the run. Using a mirror locally is fine (`~/.npmrc` with
`replace-registry-host=always` makes local installs rehost to it) — the repo
lockfile itself stays canonical.

## One version, three places

A release version is declared in `pyproject.toml`, and two other places must
not disagree with it:

- `pyproject.toml` — what PyPI publishes; the workflow refuses a tag that
  disagrees with it
- `examples/dsh/packages/clawock-dsh/package.json` — what npm publishes; the publish script
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