"""Bounded, generation-scoped transport for scheduled market context."""

import hashlib
import json
import re
import shutil
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from clawock.safe_io import safe_write_text

# Below OpenClaw read's 32 KiB adaptive page floor, with room for tool metadata.
PART_BYTES = 24 * 1024
MAX_PARTS = 6
KEEP_SECONDS = 2 * 24 * 60 * 60


def packet_dir(tmp, market, context_id):
    if market not in {'hk', 'us'} or not re.fullmatch(r'[A-Za-z0-9_-]+', context_id or ''):
        raise ValueError('invalid market or context_id')
    return Path(tmp) / 'intraday-packets' / f'{market}-{context_id}'


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def _fragments(path, value, budget):
    encoded = _json([path, value])
    if len(encoded.encode()) <= budget:
        yield encoded
    elif isinstance(value, dict) and value:
        for key, child in value.items():
            yield from _fragments([*path, key], child, budget)
    elif isinstance(value, list) and value:
        for index, child in enumerate(value):
            yield from _fragments([*path, index], child, budget)
    else:
        raise ValueError(f'core value exceeds the part budget at {path!r}')


def _parts(packet, identity):
    # Field paths let a large dictionary/list span parts without changing its
    # values. The usual case is one record per top-level field.
    header = _json(identity)[:-1] + ',"fields":['
    overhead = len(header.encode()) + len(']}\n')
    budget = PART_BYTES - overhead
    parts, batch, size = [], [], 0
    for key, value in packet.items():
        for fragment in _fragments([key], value, budget):
            length = len(fragment.encode())
            if size + length + bool(batch) > budget:
                parts.append(header + ','.join(batch) + ']}\n')
                if len(parts) == MAX_PARTS:
                    raise ValueError(f'core exceeds {MAX_PARTS} parts of {PART_BYTES} bytes')
                batch, size = [], 0
            size += length + bool(batch)
            batch.append(fragment)
    parts.append(header + ','.join(batch) + ']}\n')
    return parts


def _expire_packets(current):
    cutoff = time.time() - KEEP_SECONDS
    for entry in current.parent.iterdir():
        if entry == current or not re.fullmatch(r'(hk|us)-[0-9a-f]{12}', entry.name):
            continue
        try:
            if entry.is_dir() and entry.stat().st_mtime < cutoff:
                shutil.rmtree(entry, ignore_errors=True)
        except FileNotFoundError:
            pass


def write_packet(tmp, packet, audit_payload):
    """Expose all parts in one rename, then return a small ready receipt.

    The audit copy is a same-generation reference source even when another
    preflight replaces both latest and the compatibility by-minute archive.
    """
    index = packet['index']
    identity = {key: packet[key] for key in ('context_id', 'market', 'date')}
    identity['slot'] = index['slot']
    # Put the slot, quote health, guards and candidate levels before evidence.
    first = ('status', 'delivery_mode', 'always_full', 'quote_coverage',
             'holding_policies', 'strategy_checks', 'risk_debts', 'risk_debts_error',
             'risk_followups', 'watch_levels', 'trigger_prices', 'plan_triggers', 'index',
             'plan_context')
    ordered = {key: packet[key] for key in first if key in packet}
    ordered.update(packet)
    target = packet_dir(tmp, identity['market'], identity['context_id'])
    entries = publish_parts(target, ordered, identity, audit_payload)
    return {'status': 'ok', **identity, 'delivery_mode': packet['delivery_mode'],
            'part_bytes_max': PART_BYTES, 'parts_max': MAX_PARTS, 'parts': entries,
            'complete': True,
            'prose_path': str(target / f"intraday-prose-{identity['market']}.md"),
            'sidecar_path': str(target / f"intraday-insights-{identity['date']}.json")}


def publish_parts(target, packet, identity, audit_payload):
    """Write a complete bounded generation before returning any read paths."""
    parts = _parts(packet, identity)
    entries = [
        {'path': str(target / f'core-{number}.json'), 'bytes': len(part.encode()),
         'sha256': hashlib.sha256(part.encode()).hexdigest()}
        for number, part in enumerate(parts, start=1)
    ]
    target.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=target.parent, prefix='.staging-') as staging:
        staged = Path(staging) / target.name
        staged.mkdir()
        for part, entry in zip(parts, entries, strict=True):
            safe_write_text(staged / Path(entry['path']).name, part)
        safe_write_text(staged / 'context.json', audit_payload)
        try:
            staged.rename(target)
        except OSError:
            # Identical generation may be handed out again. A missing or
            # damaged part never yields a successful receipt.
            if not target.is_dir() or (target / 'context.json').read_text() != audit_payload:
                raise
            for part, entry in zip(parts, entries, strict=True):
                if Path(entry['path']).read_text() != part:
                    raise ValueError('published core part differs from its generation')
    _expire_packets(target)
    return entries
