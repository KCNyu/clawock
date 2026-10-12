import subprocess
from pathlib import Path


def test_weight_axis_contains_current_positions_and_ghosts():
    subprocess.run(['node', '-e', r'''
const fs = require('node:fs');
const assert = require('node:assert/strict');
const source = fs.readFileSync('site/assets/js/dashboard.charts.js', 'utf8');
const begin = source.indexOf('  function placeBubbleLabels(');
const end = source.indexOf('\n  }', source.indexOf('  function renderWeightConfidence()')) + 4;
for (const weight of [0, 57, 86.64, 100]) {
  for (const confidence of [null, 0.71]) {
    let option;
    const echarts = {init: () => ({setOption: o => {option = o;}}), color: {modifyAlpha: () => ''}};
    const environment = {
      document: {getElementById: () => ({})}, window: {echarts}, echarts, charts: {},
      DATA: {weight_confidence: [{ticker: 'TEST', weight_pct: weight, avg_confidence: confidence, region: 'us', n_actions: confidence == null ? 0 : 6}]},
      safe: (data, key) => data[key], getCSS: () => '', baseChartOpts: () => ({}),
      chartTooltip: () => ({}), chartAxis: x => x,
      chartGridColor: () => '', chartLabelColor: () => '', chartTextColor: () => '',
    };
    new Function(...Object.keys(environment), source.slice(begin, end) + '\n;renderWeightConfidence();')(...Object.values(environment));
    assert.equal(option.series[0].data.length, 1);
    const point = option.series[0].data[0];
    const tip = option.tooltip.formatter({data: point, value: point.value});
    assert.ok(tip.includes(confidence == null ? 'conf: n/a' : 'conf: 71.0%'));
    assert.equal(point.value[1], confidence == null ? 50 : 71);
    assert.ok(tip.includes(confidence == null ? 'n_actions: 0' : 'n_actions: 6'));
    assert.ok(option.xAxis.max >= weight / 0.8);
    assert.equal(option.series[0].markArea.data[0][1].xAxis, option.xAxis.max);
  }
}
'''], cwd=Path(__file__).resolve().parents[1], check=True)
