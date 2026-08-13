"""The instance harness must spawn our own tooling in a way that still resolves.

Three separate incidents in two days shared one shape — a call that reads
correctly in the source and cannot run in production:

- #443 / #438: `clawock` spawned by bare name, unresolvable under cron's
  `PATH=/usr/bin:/bin` because the launcher lives in `~/.local/bin`.
- #445: `python3` given a heredoc importing `clawock`, dead once #392 moved the
  package behind `src/`.
- #447 (this one): `report_preflight` and `intraday_preflight` shelling out to
  `WS/'scripts'/'data'/analyze_{market}_stocks.py`, deleted in #429 and moved
  into the package by #421 — which added `clawock analyze-hk` / `analyze-us` and
  updated no callers. Both preflights failed on every run *and still exited 0*,
  so the report agent saw no error and spent the run searching site-packages for
  a file that no longer exists.

`test_harness_cli_contract` already proves every `PACKAGED_UTILITIES` target
imports and has a `main()`. It could not catch #447 because the harness did not
go through `PACKAGED_UTILITIES` at all — it named a filesystem path. So the gap
is not "are the commands healthy" but "does the harness use them".
"""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / 'src' / 'clawock' / 'harness'

def _harness_modules():
    return sorted(p for p in HARNESS.glob("*.py") if p.name != "__init__.py")


# Deliberately NOT asserted here: that nothing spawns `clawock` by bare name.
# `brief_preflight` does so in fifteen places and ran successfully this morning,
# because OpenClaw's environment carries `~/.local/bin`. #438 was the *user
# crontab*, a different launcher with `PATH=/usr/bin:/bin`, and it was fixed at
# its own site. A guard that reddened those fifteen working call sites would be
# a false alarm, and the rule it enforced would not be true.


def test_no_harness_module_spawns_a_script_out_of_the_workspace():
    """`WS / 'scripts' / ...` is a data directory that no longer holds code.

    This is the #447 shape specifically: the workspace can be pointed elsewhere
    with CLAWOCK_WORKSPACE, and `scripts/` was deleted outright, so a spawn built
    from it is either dead or runs a stranger's file.
    """
    pattern = re.compile(r"WS\s*/\s*['\"]scripts['\"]")
    offenders = [
        f"{path.name}:{lineno}"
        for path in _harness_modules()
        for lineno, line in enumerate(path.read_text().splitlines(), 1)
        if pattern.search(line)
    ]
    assert not offenders, (
        "these build a path into the workspace's deleted scripts/ tree; the "
        f"analysis lives in the package and is named by PACKAGED_UTILITIES: {offenders}")


def test_the_analysis_the_preflights_run_is_the_one_the_cli_ships():
    """The preflights and `clawock analyze-*` must not be able to diverge.

    Both preflights previously hardcoded a filename. Resolving through the CLI's
    own map is what makes a future move of the module update them too — and the
    map's targets are already proven importable with a `main()` by
    test_harness_cli_contract, so this reuses that guarantee rather than
    restating it.
    """
    from clawock.cli import PACKAGED_UTILITIES

    for market in ("hk", "us"):
        assert f"analyze-{market}" in PACKAGED_UTILITIES

    for name in ("report_preflight.py", "intraday_preflight.py"):
        source = (HARNESS / name).read_text()
        assert "PACKAGED_UTILITIES[f'analyze-{market}']" in source, (
            f"{name} no longer resolves its analysis through the CLI command map, "
            "so it can drift from the shipped command again (#447)")
