"""The one place that knows where the OpenClaw binary lives and how to call it.

Everything OpenClaw-specific belongs here so the rest of the tree can be counted
as runtime-agnostic — see `tests/test_runtime_coupling_ratchet.py`, which exempts
`clawock/providers/` precisely because that is what an adapter is for.

Moved out of `scripts/harness/_watchdog_common.py`, which held the binary path
and the cron CLI call and was therefore the largest single consumer that knew
which runtime it was on.
"""
from __future__ import annotations

import json
import subprocess

# pnpm's global bin. Kept as one constant rather than resolved through PATH: the
# cron environment is not a login shell, and PATH resolution has bitten this
# before.
OPENCLAW_BIN = "/root/.local/share/pnpm/openclaw"

# `cron list --json` round-trips through the gateway and has been observed at
# ~42s on a loaded host. A tight timeout trips TimeoutExpired, which callers
# read as "no data" and quietly fall back to a stale source.
CRON_TIMEOUT_SECONDS = 120


def cron_cli_json(cli_args, *, binary: str = OPENCLAW_BIN,
                  timeout: int = CRON_TIMEOUT_SECONDS, runner=None):
    """Run `openclaw cron <args> --json` and parse the object it prints.

    Returns the dict, or None on any failure — the caller decides what an
    unavailable runtime means, because for a watchdog it is not the same as an
    empty result.

    Leading `Config warnings:` noise is skipped: the CLI prints it before the
    JSON body and it is not an error.
    """
    run = runner or (lambda cmd: subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout))
    try:
        done = run([binary, "cron", *cli_args])
        # Deliberately NOT gated on returncode: the original helper parsed
        # stdout regardless, and a command that exits non-zero while still
        # printing a valid object was treated as data. Preserving that keeps
        # this a move rather than a behaviour change.
        text = done.stdout
        start = text.find("{")
        if start < 0:
            return None
        return json.loads(text[start:])
    except Exception:
        return None
