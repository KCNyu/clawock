#!/usr/bin/env python3
"""One tolerant reader for dispatch control files.

The runner, the receipt parser and the queue ops all read mandate, question,
answer, wake and free-pool JSON the same way: unreadable, malformed or a
non-object document is ``{}`` and the caller takes its own missing-data path.
Keeping that contract in one place is what stops a future distinction between
"file absent" and "file corrupt" from landing in two of the three readers
(#3483).
"""
from __future__ import annotations

import json
from pathlib import Path


def read_json_object(path: Path | str) -> dict:
    """Read one JSON object; anything unreadable or non-object is ``{}``."""
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}
