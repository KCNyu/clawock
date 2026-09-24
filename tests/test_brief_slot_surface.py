"""The current brief slot shown by help and reference copy follows scheduling."""
import re
import subprocess
from pathlib import Path

from clawock.scheduling import BRIEF_SLOT_HKT

ROOT = Path(__file__).resolve().parents[1]
SURFACES = (
    'src/clawock/decision/plans.py',
    'config/information-layers.json',
    'docs/reference/commands.md',
    'docs/reference/tool-operations.md',
    'docs/operations/research-cadence.md',
)


def test_current_brief_slot_in_help_and_reference_copy():
    for name in SURFACES:
        text = (ROOT / name).read_text(encoding='utf-8')
        slots = re.findall(r'08:\d{2}', text)
        assert slots, name
        assert BRIEF_SLOT_HKT in slots, (name, slots)
        assert '08:00' not in slots, (name, slots)


def test_fallback_preflight_propagates_fatal_but_allows_warnings():
    text = (ROOT / '.github/workflows/brief-fallback.yml').read_text()
    step = text.split('- name: Run preflight (collect deterministic data)', 1)[1]
    step = step.split('\n      - name:', 1)[0]
    assert 'clawock brief preflight 2>&1 | tail -50' in step
    run = step.split('run: |\n', 1)[1]
    script = '\n'.join(line[10:] for line in run.splitlines() if line.strip())
    for code, expected in ((0, 0), (1, 0), (2, 2)):
        stub = f'clawock() {{ echo preflight-output; return {code}; }}\n'
        result = subprocess.run(['bash', '-e', '-c', stub + script], capture_output=True,
                                text=True)
        assert result.returncode == expected, (code, result.stderr)
