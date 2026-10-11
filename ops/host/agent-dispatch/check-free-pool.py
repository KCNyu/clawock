#!/usr/bin/env python3
"""2026-10-10: dispatch-time guard after refresh_live restored dead pool entries.
No network or timers. Catalog/zero-cost checks are part of pool-change review.
"""
import re
import sys
import syslog
from pathlib import Path


# Out of the catalog or answering nothing (exo, fledge), or dropped on what their finished rounds
# were worth (see the record in opencode-fallback-models). A restore has to edit this set too,
# which is the point: an old copy of the pool file cannot bring them back by itself.
RETIRED = {
    "opencode/exo-free", "opencode/fledge-alpha-free",
    "opencode/nemotron-3-ultra-free", "opencode/nemotron-3.5-lightning-free", "opencode/ling-3.1-flash-free",
}


def check(path):
    models = [word for line in Path(path).read_text().splitlines()
              for word in line.split("#", 1)[0].split()]
    errors = []
    if not models:
        errors.append("empty pool")
    if len(models) != len(set(models)):
        errors.append("duplicate models")
    for model in models:
        if not re.fullmatch(r"opencode/[a-z0-9.-]+-free", model):
            errors.append(f"non-free/provider-invalid entry: {model}")
        if model in RETIRED:
            errors.append(f"retired/unavailable entry restored: {model}")
    if errors:
        raise ValueError("; ".join(errors))
    return models


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) == 2 else "/root/tools/agent-dispatch/opencode-fallback-models"
    try:
        check(path)
    except (OSError, ValueError) as exc:
        message = f"FREE POOL INVALID: {exc}; review pool and host installer before dispatch"
        print(message, file=sys.stderr)
        syslog.openlog("agent-dispatch-free-pool")
        syslog.syslog(syslog.LOG_ERR, message)
        sys.exit(2)
