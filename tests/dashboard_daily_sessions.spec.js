const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../site/assets/js/dashboard.core.js'), 'utf8');
const helper = source.slice(source.indexOf('  function sessionDailyPnl('));
const run = (rows, view = 'combined', fx = 2) => {
  const ctx = { rows, view, fx }; vm.createContext(ctx);
  return JSON.parse(vm.runInContext(helper + '\nJSON.stringify(sessionDailyPnl(rows, view, fx))', ctx));
};

test('daily flow counts each leg session once, keeping its latest reading', () => {
  const rows = [
    { date: '2026-10-07', us_asof: '2026-10-07', hk_asof: '2026-10-07', us_today_change: -194.31, hk_today_change: -1547.6 },
    { date: '2026-10-08', us_asof: '2026-10-07', hk_asof: '2026-10-08', us_today_change: -231.5, hk_today_change: -5810.4 },
    { date: '2026-10-09', us_asof: '2026-10-07', hk_asof: '2026-10-08', us_today_change: -231.5, hk_today_change: -5810.4 },
  ];
  const before = JSON.stringify(rows);
  assert.deepEqual(run(rows), [{ date: '2026-10-07', pnl: -1005.3 }, { date: '2026-10-08', pnl: -2905.2 }]);
  assert.deepEqual(run(rows, 'us'), [{ date: '2026-10-07', pnl: -231.5 }]);
  assert.deepEqual(run(rows, 'hk'), [{ date: '2026-10-07', pnl: -1547.6 }, { date: '2026-10-08', pnl: -5810.4 }]);
  assert.equal(JSON.stringify(rows), before);
});

test('missing stamps do not erase equal moves; missing FX stays unknown', () => {
  const rows = [{ date: 'a', us_today_change: 5 }, { date: 'b', us_today_change: 5 }];
  assert.equal(run(rows).length, 2);
  assert.deepEqual(run(rows, 'combined', null).map(r => r.pnl), [null, null]);
  assert.deepEqual(run([{ date: 'a', us_today_change: 0 }]), [{ date: 'a', pnl: 0 }]);
});
