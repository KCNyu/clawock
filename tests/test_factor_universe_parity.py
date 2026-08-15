"""factor-universe.json must cover every AI-factor instrument (#625).

The cross-factor ranking consumes factor-universe.json; a registered AI name
missing from its sector group is a silent blind spot in the ranking. This
parity test makes the two registries drift-locked: any instruments.json entry
with factor=CHINA_AI must be a member of the hk_ai_models group.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name):
    return json.loads((ROOT / 'config' / name).read_text(encoding='utf-8'))


def test_every_china_ai_instrument_is_in_hk_ai_models_group():
    instruments = _load('instruments.json')['instruments']
    universe = _load('factor-universe.json')

    members = {s['ticker'] for s in universe['symbols']
               if s.get('sector') == 'hk_ai_models'}
    ai = {code for code, meta in instruments.items()
          if meta.get('factor') == 'CHINA_AI' and meta.get('region') == 'HK'}

    missing = ai - members
    assert not missing, (
        f'CHINA_AI 标的缺 factor-universe hk_ai_models 组: {sorted(missing)}')

    # The #556 pair is registered; 03317 迅策 was the concrete gap (#625).
    assert {'00100', '02513', '03317'} <= members
