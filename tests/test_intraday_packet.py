"""The scheduled core is a complete, bounded, generation-pinned transfer."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from clawock.context import intraday_packet as transport
from clawock.harness import intraday_preflight as pre
from clawock.tools.context_tools import IntradayReference


def _context(context_id):
    return {
        'status': 'ok', 'market': 'us', 'context_id': context_id,
        'date': '2026-11-24', 'generated_at': '2026-11-24T00:03:14+08:00',
        'heartbeat': {'job': '美股盘中盯盘-overnight', 'slot': '2026-11-24T00:00:00+08:00'},
        'delivery_mode': 'full_delta', 'always_full': True,
        'semantic_state': {'session': 'us:2026-11-23'},
        'quote_coverage': {'unrefreshed': ['TEST']},
        'plan_context': {'plan_date': '2026-11-23', 'open': []},
        'risk_debts': [{'ticker': 'TEST'}],
        'strategy_checks': [{'ticker': 'TEST', 'status': 'unavailable'}],
        'information': {'live': {'TEST': [
            {'title': '盘中消息🧾' * 900, 'status': 'fresh'},
            {'title': '第二条消息' * 1350, 'status': 'degraded'},
        ]}, 'sources': {'reuters': {'status': 'failed'}}},
        'peer_scan': {'TEST': {'detail': context_id}},
    }


def _read_core(receipt):
    core = {}
    for entry in receipt['parts']:
        raw = Path(entry['path']).read_bytes()
        assert len(raw) == entry['bytes'] <= transport.PART_BYTES
        assert hashlib.sha256(raw).hexdigest() == entry['sha256']
        part = json.loads(raw)
        for key in ('market', 'slot', 'date', 'context_id'):
            assert part[key] == receipt[key]
        for path, value in part['fields']:
            target = core
            for current, next_key in zip(path, path[1:]):
                child = [] if isinstance(next_key, int) else {}
                if isinstance(target, list):
                    if current == len(target):
                        target.append(child)
                    target = target[current]
                else:
                    target = target.setdefault(current, child)
            if isinstance(target, list):
                assert len(target) == path[-1]
                target.append(value)
            else:
                assert path[-1] not in target
                target[path[-1]] = value
    return core


def test_core_round_trips_in_bounded_utf8_parts(tmp_path):
    ctx = _context('ab1234567890')
    packet = pre.judgment_packet(ctx)
    receipt = transport.write_packet(tmp_path, packet, json.dumps(ctx))
    assert receipt['complete'] and 1 < len(receipt['parts']) <= transport.MAX_PARTS
    assert len(json.dumps(receipt).encode()) < 4096
    assert _read_core(receipt) == packet
    first = json.loads(Path(receipt['parts'][0]['path']).read_text())
    assert {'plan_context', 'quote_coverage', 'risk_debts', 'strategy_checks'} <= {
        path[0] for path, _ in first['fields']}


def test_missing_part_and_budget_failure_never_return_ready(tmp_path, monkeypatch):
    ctx = _context('ab1234567890')
    packet = pre.judgment_packet(ctx)
    payload = json.dumps(ctx)
    receipt = transport.write_packet(tmp_path, packet, payload)
    Path(receipt['parts'][1]['path']).unlink()
    with pytest.raises(FileNotFoundError):
        transport.write_packet(tmp_path, packet, payload)
    another = _context('ab1234567891')
    monkeypatch.setattr(transport, 'MAX_PARTS', 1)
    with pytest.raises(ValueError, match='core exceeds'):
        transport.write_packet(tmp_path, pre.judgment_packet(another), json.dumps(another))
    assert not transport.packet_dir(tmp_path, 'us', another['context_id']).exists()


def test_concurrent_generations_resolve_references_after_latest_replaced(tmp_path):
    tmp = tmp_path / 'memory' / '.tmp'
    contexts = [_context('ab1234567890'), _context('ab1234567891')]

    def publish(ctx):
        return transport.write_packet(tmp, pre.judgment_packet(ctx), json.dumps(ctx))

    with ThreadPoolExecutor(3) as pool:
        first, retry, next_slot = list(pool.map(publish, [*contexts[:1], *contexts]))
    assert first == retry
    assert _read_core(first) == pre.judgment_packet(contexts[0])
    assert Path(first['prose_path']) != Path(next_slot['prose_path'])
    (tmp / 'intraday-context-us-latest.json').write_text(json.dumps(contexts[1]))
    (tmp / 'intraday-context-us-2026-11-24_0003.json').write_text(json.dumps(contexts[1]))
    assert json.loads(IntradayReference().execute(
        tmp_path, market='us', context_id=first['context_id'], entry='peer_scan')) == (
        contexts[0]['peer_scan'])
