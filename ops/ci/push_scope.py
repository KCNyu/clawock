#!/usr/bin/env python3
"""Classify a change range into the CI lanes — the single source of truth.

Three gates in ci.yml (the validate detector, the lint scope, the CodeQL
push gate) used to carry three inline copies of overlapping
diff-classification bash. Copies drift: #750 and the config-directory lesson
both came from exactly that. This script is now the only place that knows
what a changed path means for CI, and tests/test_push_scope.py drives it
with synthetic file lists so lane behaviour is asserted without git or
GitHub.

Lanes emitted (GITHUB_OUTPUT `key=value` lines, or --json):

  code       run the Python suite / schema checks
  ui         dashboard browser contract needed (implies code)
  dsplugin   Decision Studio plugin contracts needed
  workflows  a workflow file itself changed (drives the lint gate)
  analysable  at least one path CodeQL should analyse; False when every
              changed path is automation-written runtime data, and False on
              an empty diff. Undiffable ranges never reach here: the caller
              answers --everything before invoking this script, failing
              toward running.

Matching semantics deliberately mirror the shell they replaced: glob lanes
use fnmatchcase, where `*` crosses `/` exactly like a `case` pattern did;
the ui/dsplugin lanes use the same regexes the old grep lines carried,
byte-for-byte.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys

# Files whose change must run the suite. Keep in sync with the push trigger's
# positive path list in ci.yml — test_ci_trigger_paths.py holds both halves.
CODE_GLOBS = [
    "src/*",
    "ops/*",
    "tests/*",
    "pyproject.toml",
    "pytest.ini",
    "portfolio.json",
    "memory/*-plan.json",
    # The ledger itself (#1063). It is the sole input of three gates in the
    # validate job — plan-origin cross-check, per-row schema, settle
    # idempotence — and was in no lane, so a commit that touched ONLY
    # decisions.jsonl ran none of them. That is how a fabricated row reached
    # master on 2026-08-26 and how its removal had to be verified by a manual
    # workflow_dispatch. Named exactly, not `memory/*.jsonl`: the sibling
    # archive/history files are automation output nothing validates.
    "memory/decisions.jsonl",
    "memory/theses/*",
    "memory/earnings/*",
    "memory/entry-gates/*",
    "assets/data/overview.json",
    "assets/data/dashboard.json",
    "config/*",
    "docs/operations/cron-schedules.md",
    ".github/workflows/*",
    ".github/actions/*",
    "skills/tavily-search/*",
    "site/tools/*",
]

# Automation-written runtime data: no analysable code, so the CodeQL matrix
# skips a push that touches nothing outside this set. overview.json and
# dashboard.json are deliberate exceptions by specificity: they sit in
# CODE_GLOBS above (the suite validates the projections), while CodeQL still
# skips them because a payload-only change contains nothing analysable — the
# same split the pre-merge files enforced with two different mechanisms.
DATA_GLOBS = [
    "assets/data/*",
    "memory/*",
    "logs/*",
    "site/assets/data/*",
    "portfolio.json",
    "monitor_state.json",
    "openclaw-workspace-state.json",
]

# Started byte-identical to the grep -E patterns the inline detector carried.
# `site/_layouts/` and `site/decimap/` were added after the shared header
# shipped a two-row nav to every phone: `site/index.html` is `layout: null`, so
# the dashboard contract never renders the layout, and nothing in this pattern
# used to make a change to it run a browser at all.
UI_RE = (r"^(site/assets/(css|js)/|site/index\.html$|site/_layouts/|"
         r"site/decimap/|"
         r"tests/(dashboard_tab_runtime|site_layout_mobile)\.spec\.js$)")
DSPLUGIN_RE = r"^(examples/dsh/|tests/decision_studio_plugin\.spec\.js$|tests/dsh_plugin_package_contract\.mjs$)"

WORKFLOWS_PREFIX = ".github/workflows/"

ZERO_SHA = "0" * 40


def classify(files: list[str]) -> dict[str, bool]:
    ui_re = re.compile(UI_RE)
    ds_re = re.compile(DSPLUGIN_RE)
    code = ui = dsplugin = workflows = False
    # An empty diff analyses nothing; otherwise at least one path outside the
    # automation-data set makes the range worth analysing (mirrors the
    # ignore-list semantics the standalone codeql.yml trigger used to have).
    analysable = bool(files) and any(
        not any(fnmatch.fnmatchcase(f, g) for g in DATA_GLOBS) for f in files
    )
    for f in files:
        if not f:
            continue
        if any(fnmatch.fnmatchcase(f, g) for g in CODE_GLOBS):
            code = True
        if ui_re.search(f):
            ui = True
            code = True
        if ds_re.search(f):
            dsplugin = True
        if f.startswith(WORKFLOWS_PREFIX):
            workflows = True
    return {
        "code": code,
        "ui": ui,
        "dsplugin": dsplugin,
        "workflows": workflows,
        "analysable": analysable,
    }


EVERYTHING = {
    "code": True,
    "ui": True,
    "dsplugin": True,
    "workflows": True,
    "analysable": True,
}


def changed_files(base: str, head: str) -> list[str] | None:
    """Files changed in the range, or None when the base is unusable."""
    if not base or base == ZERO_SHA:
        return None
    probe = subprocess.run(
        ["git", "cat-file", "-e", f"{base}^{{commit}}"],
        capture_output=True,
    )
    if probe.returncode != 0:
        return None
    out = subprocess.run(
        ["git", "diff", "--name-only", "--no-renames", base, head],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in out.stdout.splitlines() if line]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="", help="range start (event.before)")
    parser.add_argument("--head", default="HEAD", help="range end")
    parser.add_argument(
        "--everything",
        action="store_true",
        help="skip diffing; report every lane as changed",
    )
    parser.add_argument(
        "--files-from",
        help="classify this newline-separated path list instead of running git ('-' = stdin)",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON")
    args = parser.parse_args(argv)

    if args.everything:
        lanes = dict(EVERYTHING)
    elif args.files_from:
        text = (
            sys.stdin.read()
            if args.files_from == "-"
            else open(args.files_from, encoding="utf-8").read()
        )
        lanes = classify(text.splitlines())
    else:
        files = changed_files(args.base, args.head)
        lanes = classify(files) if files is not None else dict(EVERYTHING)

    if args.json:
        print(json.dumps(lanes, sort_keys=True))
    else:
        for key in sorted(lanes):
            print(f"{key}={'true' if lanes[key] else 'false'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
