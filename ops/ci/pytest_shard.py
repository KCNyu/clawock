"""Partition collected node IDs deterministically; xdist workers agree exactly.

Every test belongs to one shard, including tests added after the last CI run.
Normal local pytest is unchanged unless both shard environment variables are set.
"""
import hashlib
import os

import pytest


def shard_for(nodeid: str, total: int) -> int:
    return int.from_bytes(hashlib.sha256(nodeid.encode()).digest()[:8], 'big') % total


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    index = os.environ.get('CI_SHARD_INDEX')
    total = os.environ.get('CI_SHARD_TOTAL')
    if index is None and total is None:
        return
    try:
        index, total = int(index), int(total)
        if not 0 <= index < total:
            raise ValueError
    except (ValueError, TypeError) as exc:
        raise pytest.UsageError('CI_SHARD_INDEX must be in [0, CI_SHARD_TOTAL)') from exc
    selected, deselected = [], []
    for item in items:
        (selected if shard_for(item.nodeid, total) == index else deselected).append(item)
    items[:] = selected
    config.hook.pytest_deselected(items=deselected)
