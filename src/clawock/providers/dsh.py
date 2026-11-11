"""The dsh runtime's private credential seam.

The portable package needs DeepSeek's key when it runs inside dsh, but the dsh
home layout is host-private. Keeping the path and the `refs:` reader here means
`market_data.deepseek_search` asks a capability instead of naming another
runtime's home (#3353); the coupling ratchet scans portable modules outside this
package and must stay at zero.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

DEFAULT_CREDENTIALS = Path.home() / '.dsh' / '.credentials.yaml'
DEFAULT_GATE_DIR = Path.home() / '.cache' / 'clawock' / 'deepseek-search'


def profiles_dir() -> Path:
    return Path.home() / '.dsh' / 'profiles'


def credentials_path() -> Path:
    return Path(os.environ.get('CLAWOCK_DSH_CREDENTIALS', DEFAULT_CREDENTIALS))


def gate_dir() -> Path:
    return Path(os.environ.get('CLAWOCK_DEEPSEEK_GATE_DIR', DEFAULT_GATE_DIR))


def ref(name: str, path: Path | None = None) -> str | None:
    """`name` from the credentials seam's top-level `refs:` mapping."""
    try:
        lines = (path or credentials_path()).read_text(encoding='utf-8').splitlines()
    except OSError:
        return None
    in_refs = False
    for line in lines:
        if re.match(r'^refs:\s*$', line):
            in_refs = True
            continue
        if not in_refs:
            continue
        if re.match(r'^\S', line):
            break
        match = re.match(r'^\s+([A-Z][A-Z0-9_]*):\s*(.*?)\s*$', line)
        if match and match.group(1) == name:
            value = re.sub(r'^([\'"])(.*)\1$', r'\2', match.group(2))
            return value or None
    return None
