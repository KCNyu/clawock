"""Run the actual Reflect renderer on missing versus genuinely zero P&L."""
import subprocess
from pathlib import Path


def test_total_return_requires_both_pnl_inputs_and_positive_capital():
    subprocess.run(['node', '-e', r'''
const fs = require('node:fs');
const assert = require('node:assert/strict');
const core = fs.readFileSync('site/assets/js/dashboard.core.js', 'utf8');
const source = fs.readFileSync('site/assets/js/dashboard.render.js', 'utf8');
const renderer = source.match(/^  function renderReflectKpi\(\) \{.*?^  \}$/ms)[0];
const owner = ['MINUS', 'fixed'].map(name => core.match(new RegExp('^  const ' + name + ' = .*$', 'm'))[0]).join('\n');
const formatters = ['fmtMoney', 'fmtPct'].map(name => core.match(new RegExp('^  const ' + name + ' = .*?^  \\};$', 'ms'))[0]).join('\n');
const cases = [
  [{realized: null, unrealized: null}, 100, '—'],
  [{realized: null, unrealized: -20}, 100, '—'],
  [{realized: 20, unrealized: null}, 100, '—'],
  [{}, 100, '—'],
  [{realized: 0, unrealized: 0}, 100, '+0.00%'],
  [{realized: 10, unrealized: -30}, 100, '−20.00%'],
  [{realized: 10, unrealized: 0}, 100, '+10.00%'],
  [{realized: 10, unrealized: 0}, null, '—'],
  [{realized: 10, unrealized: 0}, 0, '—'],
  [{realized: 10, unrealized: 0}, -100, '—'],
  [{realized: NaN, unrealized: 0}, 100, '—'],
  [{realized: 10, unrealized: Infinity}, 100, '—'],
];
for (const [combined, capital, expected] of cases) {
  const nodes = Object.fromEntries(['kpi-totalret', 'kpi-totalret-abs'].map(id => [id, {textContent: '', classList: {remove(){}, add(){}}}]));
  const environment = {
    DATA: {fx: {usdhkd: 7.8}, realized_vs_unrealized: {combined_usd: combined}, capital_deployed: {combined_usd: capital}},
    document: {getElementById: id => nodes[id] || null},
    safe: (data, ...keys) => keys.reduce((node, key) => node == null ? undefined : node[key], data),
    collapseSameSession: rows => rows, sessionDailyPnl: () => [],
    pnlClass: () => 'neutral', DASH: '—',
  };
  new Function(...Object.keys(environment), owner + '\n' + formatters + '\n' + renderer + '\nrenderReflectKpi();')(...Object.values(environment));
  assert.equal(nodes['kpi-totalret'].textContent, expected, JSON.stringify([combined, capital]));
  if (expected === '—') assert.ok(!nodes['kpi-totalret-abs'].textContent.includes('÷ 100'));
}
'''], cwd=Path(__file__).resolve().parents[1], check=True)
