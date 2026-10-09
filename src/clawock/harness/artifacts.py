"""Only consume an artifact after this invocation successfully rewrites it."""
import json
import subprocess
import sys


def clawock_argv(command, *args):
    """argv for one package command, run through *this* interpreter (#918).

    Spawning the bare console script makes every one of these steps depend on
    whatever is on PATH — and the failure mode is quiet: under the user
    crontab's ``PATH=/usr/bin:/bin`` the entry point is simply not there,
    ``FileNotFoundError`` gets swallowed by the callers' broad excepts, and the
    step reports that it did nothing wrong. ``sys.executable -m clawock`` runs
    the package that is actually imported here, so there is no second install
    to keep in sync and no PATH to get wrong.
    """
    return [sys.executable, '-m', 'clawock', command, *args]


def refresh_json(command, path, *, timeout, cwd):
    """Keep recovery files on disk; a successful no-op is not a fresh result."""
    before = path.stat() if path.exists() else None
    subprocess.run(clawock_argv(command), cwd=cwd, capture_output=True,
                   text=True, timeout=timeout, check=True)
    after = path.stat()
    if before is not None and (before.st_ino, before.st_mtime_ns, before.st_size) == (
            after.st_ino, after.st_mtime_ns, after.st_size):
        raise ValueError(f'{command} did not refresh {path.name}')
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f'{path.name} is not an object')
    return data
