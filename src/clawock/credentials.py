"""Reading `.api_keys`, in one place.

Five modules parsed this file with four hand-written loops — `hk_analysis` and
`us_quotes` byte-identical, `risk` the same with a different name, `filings` and
`peer_discovery` the same format read two other ways. The format is trivial;
that is exactly why it kept being rewritten instead of shared, and why the
copies drifted into disagreeing about blank lines, `#` comments and whitespace.

The parser lives here. Path resolution deliberately does NOT: each caller keeps
its own `API_KEYS_PATH`, because they derive it from workspace roots computed
differently and collapsing that here would be a behaviour change smuggled into a
deduplication. `clawock.workspace` is the place to fix that, separately.

Nothing in this module imports anything from clawock, so it can be read from any
layer (see `tests/test_import_layering.py`).
"""
from __future__ import annotations

from pathlib import Path


def parse_api_keys(text: str) -> dict[str, str]:
    """`KEY=value` per line. Blank lines and `#` comments ignored, values
    stripped, first `=` wins so a value may contain one."""
    keys: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        keys[name.strip()] = value.strip()
    return keys


def load_api_keys(path: str | Path) -> dict[str, str]:
    """The credentials at `path`, or `{}` when it is absent.

    Absent is not an error: a checkout without `.api_keys` is the normal case
    for anyone who is not the live host, and every caller here already treated
    `FileNotFoundError` as "no keys configured".
    """
    try:
        return parse_api_keys(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, NotADirectoryError, IsADirectoryError):
        return {}
