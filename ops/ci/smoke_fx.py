#!/usr/bin/env python3
"""FX fallback-chain smoke probe.

Replaces the inline `clawock fx --json` + python one-liner that lived in
ci.yml's smoke-data-fetch job. The probe is advisory by construction — its
job carries `continue-on-error` because data sources can be flaky — but a
probe that cannot fail loudly is worth nothing, so the assertions still exit
nonzero and surface as annotations.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_OPS = Path(__file__).resolve().parents[1]
if str(_OPS) not in sys.path:
    sys.path.insert(0, str(_OPS))
from system_check import clawock_argv  # noqa: E402


def check(runner=None) -> str:
    """Return the winning FX source, or raise on an unusable answer.

    Spawns through clawock_argv, never a bare `clawock`: the probe must also
    work from a bare cron PATH where the console script is not resolvable.
    """
    argv, env = clawock_argv("fx", "--json")
    run = (runner or subprocess.run)(
        argv, capture_output=True, text=True, check=True, env=env
    )
    data = json.loads(run.stdout)
    rate = data["rate"]
    assert 7 < rate < 9, f"FX rate out of range: {rate}"
    return data["source"]


def main() -> int:
    try:
        source = check()
    except (subprocess.CalledProcessError, KeyError, AssertionError, json.JSONDecodeError) as exc:
        print(f"FX smoke FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"FX OK: {source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
