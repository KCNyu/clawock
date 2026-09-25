"""The intraday delta gate stays switchable after the quiet-slot contract.

The 2026-09-24 review supersedes #532/#533's user-visible receipt: a healthy
unchanged slot records a heartbeat and exact-slot marker without delivery.
`always_full` remains an explicit override for every-slot full cards.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from clawock.harness import intraday_preflight


def _module(monkeypatch, workspace):
    """Point the module's workspace at a scratch dir.

    Deliberately not a module reload: import validates the instrument registry,
    so a reload would make these tests about registry fixtures instead of about
    the toggle.
    """
    monkeypatch.setattr(intraday_preflight, 'WS', workspace)
    return intraday_preflight


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / 'config').mkdir()
    return tmp_path


def test_no_config_file_leaves_the_gate_on(monkeypatch, workspace):
    """The reviewed default must survive an absent toggle."""
    assert _module(monkeypatch, workspace).always_full_intraday() is False


def test_the_toggle_turns_every_slot_into_a_full_block(monkeypatch, workspace):
    (workspace / 'config' / 'intraday-delivery.json').write_text(
        json.dumps({'always_full': True}))
    assert _module(monkeypatch, workspace).always_full_intraday() is True


def test_a_broken_or_ambiguous_toggle_falls_back_to_the_gate(monkeypatch, workspace):
    """A runtime switch must fail back to the reviewed behaviour.

    Not to whatever a typo produces: "true", 1 and a truncated file all mean
    "somebody meant something and it did not parse", and the safe reading of
    that is the default the contract was written for.
    """
    path = workspace / 'config' / 'intraday-delivery.json'
    for content in ('{not json', '{}', json.dumps({'always_full': 'true'}),
                    json.dumps({'always_full': 1}), json.dumps({'always_full': False})):
        path.write_text(content)
        assert _module(monkeypatch, workspace).always_full_intraday() is False, content


def test_the_live_workspace_toggle_sends_every_slot():
    """kcn 2026-09-25: 「我不要那个静默忽略」— every intraday slot sends."""
    doc = json.loads((ROOT / 'config' / 'intraday-delivery.json').read_text())
    assert doc['always_full'] is True
    assert doc['set_at'] == '2026-09-25' and '静默' in doc['note']
