import subprocess
from pathlib import Path


def test_risk_alerts_share_metric_precision_and_preserve_thresholds():
    subprocess.run(['node', '-e', r'''
const fs = require('node:fs'), assert = require('node:assert/strict');
const source = fs.readFileSync('site/assets/js/dashboard.render.js', 'utf8');
const begin = source.indexOf('  function renderRiskMetrics()');
const end = source.indexOf('\n  }', begin) + 4;
const nodes = new Map();
const document = {getElementById(id) {if(!nodes.has(id)) nodes.set(id, {}); return nodes.get(id);}};
const DATA = {risk: {us: {beta_spx: 3.6674}, combined: {sharpe_30d: -1.1805}, alerts: [
  {type: 'high_beta', detail: 'US β = 3.6674 (> 3.0)'},
  {type: 'negative_sharpe', detail: 'Combined Sharpe = -1.1805 (< 0)'},
  {type: 'future_alert', detail: 'Threshold (< 0.005)'},
]}};
new Function('document','DATA','safe','DASH','escapeHtml', source.slice(begin,end) + '\n;renderRiskMetrics();')(
  document, DATA, (data,key)=>data[key], '—', text=>text);
const html = nodes.get('risk-alerts').innerHTML;
assert.match(html, /高 β.*3\.67 \(> 3\.0\)/);
assert.match(html, /负夏普.*-1\.18 \(< 0\)/);
assert.match(html, /future_alert.*Threshold \(< 0\.005\)/);
assert.ok(html.includes(nodes.get('risk-beta-us').textContent));
assert.ok(html.includes(nodes.get('risk-sharpe').textContent));
assert.ok(!html.includes('3.6674') && !html.includes('-1.1805'));
'''], cwd=Path(__file__).resolve().parents[1], check=True)
