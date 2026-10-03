"""Code identity shared by run cards and scorecard provenance.

Consumers supply their workspace; this module neither resolves a book nor
imports a decision or evidence layer. Wire formats retain the original
short git hash and sha256 prefix.
"""
from pathlib import Path
import hashlib
import subprocess


def file_digest(path) -> str | None:
    path = Path(path)
    if not path.exists():
        return None
    return f'sha256:{hashlib.sha256(path.read_bytes()).hexdigest()[:16]}'


def git_commit(workspace) -> str | None:
    try:
        out = subprocess.run(
            ['git', 'rev-parse', '--short', 'HEAD'], cwd=workspace,
            capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None if out.returncode == 0 else None
