import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_reflect_cards_disclose_their_own_dates():
    subprocess.run(['node', '-e', r'''
const fs = require('node:fs');
const assert = require('node:assert/strict');
const source = fs.readFileSync('site/assets/js/dashboard.render.js', 'utf8');
function run(name, data) {
  const begin = source.indexOf('  function ' + name + '()');
  const end = source.indexOf('\n  function ', begin + 1);
  const nodes = new Map();
  const document = { getElementById(id) {
    if (!nodes.has(id)) nodes.set(id, {style: {}});
    return nodes.get(id);
  }};
  new Function('document', 'DATA', 'safe', source.slice(begin, end) + `;${name}();`)(
    document, data, (data, key) => data[key]);
  return nodes;
}
assert.match(run('renderDecisionAudit', {decision_audit: {as_of: '2026-10-03'}}).get('audit-asof').textContent, /2026-10-03/);
assert.match(run('renderLedger', {evidence: {built_at: '2026-10-04'}}).get('ledger-asof').textContent, /台账生成 2026-10-04/);
assert.match(run('renderLedger', {evidence: {generated_at: '2026-10-02'}}).get('ledger-asof').textContent, /2026-10-02.*台账生成时刻未记录/);
'''], cwd=ROOT, check=True)


def test_reflect_artifacts_are_in_freshness_policy():
    from clawock.publish.dashboard import _FRESHNESS_POLICY
    assert {'evidence.json', 'decision_audit.json'} <= _FRESHNESS_POLICY.keys()
