#!/usr/bin/env python3
"""Prove every registered harness phase still has a free `--help`.

Two workflows want this probe: `ci.yml` on every code push and
`weekly-health.yml` as the Monday-morning backstop. They used to each carry
their own hand-written list of CLIs, and the lists disagreed — `ci.yml` grew
`brief render` in #1312 while `weekly-health.yml` stayed on the four it was
born with (#1317). A copy of a registry ages; the registry does not. This
script reads `harness.runner.PHASE_MODULES` directly, so a phase added there
is probed by both workflows the day it lands, with nothing to remember.

`timeout` is the point of the probe as much as the exit code. The two brief
scripts were once wrapped in `|| true`, which reads like the case was handled:
it is not, because what actually happened was a HANG. `brief_preflight` took no
arguments at all, so `--help` ran the whole preflight — live fetches, EDGAR,
Tavily — and ate the job's entire 10-minute budget, failing an unrelated PR. A
probe must cost nothing, and if it ever stops being free this fails in seconds
instead of taking the job down with it.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys


def probe(command: str, timeout: float, env: dict[str, str]) -> tuple[bool, str]:
    """Run `clawock <workflow> <phase> --help`. Returns (ok, reason)."""
    workflow, phase = command.split(" ", 1)
    try:
        done = subprocess.run(
            ["clawock", workflow, phase, "--help"],
            capture_output=True, text=True, timeout=timeout, env=env,
        )
    except subprocess.TimeoutExpired:
        return False, f"--help did not return within {timeout:g}s (it is doing real work)"
    except OSError as exc:
        return False, f"could not run the clawock entry point: {exc}"
    if done.returncode != 0:
        tail = (done.stderr or done.stdout or "").strip().splitlines()
        return False, f"--help exited {done.returncode}: {tail[-1] if tail else 'no output'}"
    return True, ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--timeout", type=float, default=30.0,
                        help="seconds one --help may take before it counts as a hang")
    args = parser.parse_args(argv)

    from clawock.harness.runner import PHASE_MODULES

    env = dict(os.environ)
    env.setdefault("CLAWOCK_PROFILE", "kcnyu")

    failures = []
    for workflow, phase in sorted(PHASE_MODULES):
        ok, reason = probe(f"{workflow} {phase}", args.timeout, env)
        if ok:
            print(f"  ok: clawock {workflow} {phase} --help")
        else:
            print(f"::error::clawock {workflow} {phase} --help {reason}")
            failures.append(f"{workflow} {phase}")

    if failures:
        print(f"FAIL: {len(failures)} of {len(PHASE_MODULES)} parsers unloadable: "
              f"{', '.join(failures)}")
        return 1
    print(f"OK: all {len(PHASE_MODULES)} argparse parsers loadable")
    return 0


if __name__ == "__main__":
    sys.exit(main())
