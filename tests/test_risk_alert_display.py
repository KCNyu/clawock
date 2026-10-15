import subprocess
from pathlib import Path


def test_risk_alerts_share_metric_precision_and_preserve_thresholds():
    subprocess.run(['node', '-e', r'''
const fs = require('node:fs'), assert = require('node:assert/strict');
const source = fs.readFileSync('site/assets/js/dashboard.render.js', 'utf8');
const core = fs.readFileSync('site/assets/js/dashboard.core.js', 'utf8');
const signOwner = core.match(/^  const MINUS = .*$/m)[0] + '\n' + core.match(/^  const fixed = .*$/m)[0] + '\n';
const begin = source.indexOf('  function renderRiskMetrics()');
const end = source.indexOf('\n  }', begin) + 4;
const nodes = new Map();
const document = {getElementById(id) {if(!nodes.has(id)) nodes.set(id, {}); return nodes.get(id);}};
const DATA = {risk: {us: {beta_spx: 3.6674}, combined: {sharpe_30d: -1.1805}, alerts: [
  {type: 'high_beta', detail: 'US β = 3.6674 (> 3.0)'},
  {type: 'negative_sharpe', detail: 'Combined Sharpe = -1.1805 (< 0)'},
  {type: 'future_alert', detail: 'Threshold (< 0.005)'},
]}};
new Function('document','DATA','safe','DASH','escapeHtml', signOwner + source.slice(begin,end) + '\n;renderRiskMetrics();')(
  document, DATA, (data,key)=>data[key], '—', text=>text);
const html = nodes.get('risk-alerts').innerHTML;
assert.match(html, /高 β.*3\.67 \(> 3\.0\)/);
assert.match(html, /负夏普.*−1\.18 \(< 0\)/);
assert.match(html, /future_alert.*Threshold \(< 0\.005\)/);
assert.ok(html.includes(nodes.get('risk-beta-us').textContent));
assert.ok(html.includes(nodes.get('risk-sharpe').textContent));
assert.ok(!html.includes('3.6674') && !html.includes('-1.1805'));
'''], cwd=Path(__file__).resolve().parents[1], check=True)


def test_us_beta_is_painted_against_the_published_policy_line():
    """The cell's colour and the high_beta alert read one line (#2989)."""
    subprocess.run(['node', '-e', r'''
const fs = require('node:fs'), assert = require('node:assert/strict');
const source = fs.readFileSync('site/assets/js/dashboard.render.js', 'utf8');
const core = fs.readFileSync('site/assets/js/dashboard.core.js', 'utf8');
const signOwner = core.match(/^  const MINUS = .*$/m)[0] + '\n' + core.match(/^  const fixed = .*$/m)[0] + '\n';
const begin = source.indexOf('  function renderRiskMetrics()');
const end = source.indexOf('\n  }', begin) + 4;
const paint = (risk, guardrail) => {
  const nodes = new Map();
  const document = {getElementById(id) {if(!nodes.has(id)) nodes.set(id, {}); return nodes.get(id);}};
  const DATA = {risk: Object.assign({alerts: []}, risk), risk_guardrail: guardrail};
  new Function('document','DATA','safe','DASH','escapeHtml', signOwner + source.slice(begin,end) + '\n;renderRiskMetrics();')(
    document, DATA, (data,key)=>data[key], '—', text=>text);
  return id => nodes.get(id).className;
};
const caps = us_beta_max => ({caps: {us_beta_max}});
// 2026-10-15: β 5.0055 under the 6.0 line — no alert, so no red.
assert.equal(paint({us: {beta_spx: 5.0055}}, caps(6.0))('risk-beta-us'), 'val warn-text');
assert.equal(paint({us: {beta_spx: 6.2}}, caps(6.0))('risk-beta-us'), 'val neg');
assert.equal(paint({us: {beta_spx: 3.5}}, caps(6.0))('risk-beta-us'), 'val');
// The line moves with the published cap, not a literal.
assert.equal(paint({us: {beta_spx: 3.5}}, caps(3.0))('risk-beta-us'), 'val neg');
// Without a published line there is no policy colour.
for (const guardrail of [undefined, {}, caps(null), caps(0)])
  assert.equal(paint({us: {beta_spx: 9}}, guardrail)('risk-beta-us'), 'val');
// HK β has no cap and keeps its own bands.
assert.equal(paint({hk: {beta_hsi: 3.5}}, caps(6.0))('risk-beta-hk'), 'val neg');
'''], cwd=Path(__file__).resolve().parents[1], check=True)
