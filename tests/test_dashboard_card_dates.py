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
  new Function('document', 'DATA', 'safe', source.slice(begin, end) + `
;${name}();`)(
    document, data, (data, key) => data[key]);
  return nodes;
}
assert.match(run('renderDecisionAudit', {decision_audit: {as_of: '2026-10-03'}}).get('audit-asof').textContent, /2026-10-03/);
assert.match(run('renderLedger', {evidence: {built_at: '2026-10-04'}}).get('ledger-asof').textContent, /台账生成 2026-10-04/);
assert.match(run('renderLedger', {evidence: {generated_at: '2026-10-02'}}).get('ledger-asof').textContent, /2026-10-02.*台账生成时刻未记录/);
// Machine stamps are printed the way the rest of the page prints them (#2522).
assert.equal(run('renderDecisionAudit', {decision_audit: {as_of: '2026-10-03T04:06:02+08:00'}}).get('audit-asof').textContent, ' · 数据 2026-10-03');
assert.equal(run('renderLedger', {evidence: {built_at: '2026-10-03T20:04:41.123456+00:00'}}).get('ledger-asof').textContent, '台账生成 2026-10-04 04:04 HKT');
assert.equal(run('renderLedger', {evidence: {generated_at: '2026-10-02T04:04:41+08:00'}}).get('ledger-asof').textContent, '参考数据 2026-10-02（择时诊断日期；台账生成时刻未记录）');
'''], cwd=ROOT, check=True)


def test_reflect_artifacts_are_in_freshness_policy():
    from clawock.publish.dashboard import _FRESHNESS_POLICY
    assert {'evidence.json', 'decision_audit.json'} <= _FRESHNESS_POLICY.keys()


def test_drill_cards_date_what_they_quote():
    """#2641 / #2645: a mover's note and the campaign's run card are older than
    the numbers printed beside them; each now says when it was written."""
    subprocess.run(['node', '-e', r'''
const fs = require('node:fs');
const assert = require('node:assert/strict');
const source = fs.readFileSync('site/assets/js/dashboard.render.js', 'utf8');
function run(name, data) {
  const begin = source.indexOf('  function ' + name + '()');
  const end = source.indexOf('\n  function ', begin + 1);
  const nodes = new Map();
  const known = {
    document: { getElementById(id) {
      if (!nodes.has(id)) nodes.set(id, {style: {}, classList: {add() {}, remove() {}, toggle() {}}});
      return nodes.get(id);
    }},
    DATA: data,
    safe: (root, ...keys) => keys.reduce((node, key) => (node == null ? node : node[key]), root),
  };
  // Every other helper the renderer calls prints its first argument.
  const scope = new Proxy(known, {
    has: (target, key) => typeof key === 'string' && !(key in globalThis),
    get: (target, key) => (key in target ? target[key] : (value => String(value ?? ''))),
  });
  new Function('scope', 'with (scope) {' + source.slice(begin, end) + `;${name}(); }`)(scope);
  return nodes;
}
const movers = run('renderMovers', {today_movers: [
  {ticker: 'SPCX', today_change_pct: 7.63, current_price: 171.09, note: '现价 167.07 在高位',
   note_at: '2026-10-05T18:33:55Z'},
  {ticker: 'SPCH', today_change_pct: 14.98, current_price: 12.74, note: '纯杠杆放大'}]});
const cards = movers.get('movers-scroll').innerHTML.split('mover-card').slice(1);
assert.match(cards.find(card => card.includes('SPCX')), /02:33 HKT 注 · 现价 167\.07/);
assert.doesNotMatch(cards.find(card => card.includes('SPCH')), /HKT 注/);

const campaign = run_card => run('renderAddCampaign', {brief_projection: {add_campaign: {
  status: 'collecting', packet_generated_at: '2026-10-05T08:04:35+08:00', families: [], rows: [],
  run_card}}}).get('add-campaign-evidence').innerHTML;
assert.match(campaign({run_id: 'add_alpha_walkforward-20260813-3a918d77',
                       generated_at: '2026-08-13T14:21:11+00:00'}), /生成 2026-08-13/);
assert.match(campaign({run_id: 'undated'}), /生成 日期未记录/);
'''], cwd=ROOT, check=True)
