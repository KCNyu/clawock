"""The intraday agent contract names its gates; a gate it names must exist.

docs/architecture/intraday-agent.md is updated in the same PR as the code it
describes (kcn 2026-09-25: 不许文档漂移). The cheapest drift to catch is the
doc citing a test or check that was renamed or removed — then the compliance
table claims a gate that no longer guards anything.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / 'docs' / 'architecture' / 'intraday-agent.md'


def _source():
    return '\n'.join(p.read_text(encoding='utf-8')
                     for p in [*ROOT.glob('tests/*.py'), *ROOT.glob('src/clawock/**/*.py')])


def test_every_gate_the_contract_names_exists():
    doc = DOC.read_text(encoding='utf-8')
    names = set(re.findall(r'`((?:test|check)_[a-z0-9_]+)`', doc))
    assert names, 'the contract names no gate'
    source = _source()
    missing = sorted(n for n in names if not re.search(rf'\bdef {n}\b', source))
    assert not missing, f'contract cites gates that do not exist: {missing}'
