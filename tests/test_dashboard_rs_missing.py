"""The first-paint RS row retains both legs even without a session return."""
import json
import re
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).resolve().parents[1] / 'site/assets/js'


@pytest.mark.parametrize('us,hk', [(None, -2.44), (None, None), (0, 0)])
def test_rs_keeps_both_legs_and_missing_session(us, hk):
    core = (JS / 'dashboard.core.js').read_text()
    hero = (JS / 'dashboard.hero.js').read_text()
    render = re.search(r'^  function renderMarketSnapshot\(\) \{.*?^  \}', hero, re.M | re.S)[0]
    helpers = '\n'.join(re.findall(
        r'^  (?:const fmtPct = .*?^  \};|function deltaSession\(.*?^  \})', core, re.M | re.S))
    data = {'delta': {'us': {'today_pct': us, 'session_date': '2026-10-12'},
                      'hk': {'today_pct': hk, 'session_date': '2026-10-13'}},
            'indices': {'SPX': {'change_pct': 0}, 'HSI': {'change_pct': -0.37}}}
    script = '''const DASH = '—'; const MARKET_INDICES = [];
const safe = (obj, ...keys) => keys.reduce((o, k) => o?.[k], obj);
const escapeHtml = s => String(s).replaceAll('<', '&lt;');
const nodes = {}; const document = {getElementById: id => nodes[id] ||= {}};
''' + 'const DATA = ' + json.dumps(data) + ';\n' + helpers + '\n' + render + '''
renderMarketSnapshot(); process.stdout.write(nodes['market-rs'].innerHTML);
'''
    text = subprocess.check_output(['node', '-e', script], text=True)
    assert 'US' in text and 'HK' in text
    for leg, value in [('us', us), ('hk', hk)]:
        if value is None:
            assert data['delta'][leg]['session_date'] in text
            assert '—' in text
    if us == hk == 0:
        assert '0.00%' in text and 'pp' in text
