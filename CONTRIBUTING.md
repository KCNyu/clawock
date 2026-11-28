# Contributing to clawock

Contributions cover the portable Python package, workflow packs, skills, tests,
docs, the DSH package and its dispatch runner, and the release, Pages, and CI
entry points. Changes should work with the contributor's own deployment.
Use example profiles and test data for development. Keep instance settings and
generated holdings or reports out of a code PR.

## Open an issue for behavior changes

For changes beyond a typo, describe the observed behavior, the expected
result, and a way to verify the fix. Report security issues through the
[security policy](.github/SECURITY.md).

## Work in a separate checkout

```bash
git fetch origin master
git worktree add -b <your-branch> ../clawock-change origin/master
cd ../clawock-change
python -m pip install -e '.[test]'
python -m pytest -q tests/test_relevant_behavior.py
```

Choose the targeted tests for your change. Follow the surrounding Python or
JavaScript style and reuse the existing owner for policies and data contracts.
Update the caller, test, and documentation together when changing an interface.
Keep generated docs synchronized with their owning script. For diagram and
README numbers, use the evidence source checked by CI.

## Open a pull request

Push the topic branch and open a PR against `master`. Describe the user impact,
reproduction or replay, and validation. Required checks include `validate`,
lint, and CodeQL. CI runs the full suite and a Dashboard build on applicable
changes. Add a regression check when the existing tests miss your change.

The maintainer reviews and merges the PR after the required checks pass.
If the change affects a running instance, deployment follows that instance's
operations workflow.

By contributing, you agree to the repository's MIT license. See
[NOTICE](NOTICE) and [third-party licenses](THIRD_PARTY_LICENSES/) for other terms.
