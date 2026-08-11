# CI operations

Repository health tools run by GitHub Actions: coverage gating/badge generation,
scheduled-workflow health, and the generated command catalog in
`docs/reference/commands.md` (`python3 ops/ci/generate_tool_reference.py`,
`--check` to fail on drift). They report on product and instance behavior but
are not runtime APIs and do not belong in either wheel.
