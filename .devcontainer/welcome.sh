#!/usr/bin/env bash
# Printed when a Codespace attaches. The distance between "read the README" and
# "watched it settle one decision" is the expensive part of this project's
# funnel (#788); this is the shortest path across it.
cat <<'TXT'

  clawock — ready.

  One complete run, from a clean virtualenv, no credentials, no broker:

      examples/cli/minimal-run/run.sh

  This is the same script release.yml executes against every published wheel,
  so what CI proves and what you just ran are one file, not two copies.

  The same contract with no harness at all:

      examples/cli/run.sh

  Tests:               pytest -q tests/
  Live public instance: https://kcnyu.github.io/clawock/
  Wins and losses:      https://kcnyu.github.io/clawock/evidence.html

  Nothing here reaches a market or needs an API key. The parts that do — price
  feeds, disclosure pulls, delivery — are the instance's, not the package's.

TXT
