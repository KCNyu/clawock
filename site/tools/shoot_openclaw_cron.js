#!/usr/bin/env node
/**
 * shoot_openclaw_cron.js — render this host's real `openclaw cron list --json`
 * into site/assets/openclaw-cron.png, the OpenClaw row of the README's harness
 * section.
 *
 * Same idea as claude-code-terminal.png: the frame is drawn, the content is not.
 * Every row is a job the live OpenClaw daemon holds, with its own cron
 * expression, the clawock lifecycle commands its prompt runs, and the status and
 * duration of its last run. Only clawock jobs are shown (a job whose prompt never
 * calls `clawock` is someone else's), and nothing that identifies a person is
 * copied: job ids, delivery targets and the prompts themselves stay on the host.
 * Manual refresh — a CI runner has no OpenClaw daemon.
 *
 *   node site/tools/shoot_openclaw_cron.js
 *
 * Env: CRON_JSON (a saved `openclaw cron list --json` instead of running it),
 *      PLAYWRIGHT_CORE (module path), CHROME_EXE, OUT.
 */
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const { chromium } = require(process.env.PLAYWRIGHT_CORE || 'playwright-core');
const ROOT = path.resolve(__dirname, '../..');
const OUT = process.env.OUT || path.join(ROOT, 'site/assets/openclaw-cron.png');
const CHROME_EXE = process.env.CHROME_EXE
  || '/root/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome';
const WIDTH = 1000;
const DSF = 2;

function jobs() {
  const raw = process.env.CRON_JSON
    ? fs.readFileSync(process.env.CRON_JSON, 'utf8')
    : execFileSync('openclaw', ['cron', 'list', '--json'], { encoding: 'utf8', cwd: '/tmp' });
  return JSON.parse(raw.slice(raw.indexOf('{'))).jobs;
}

// `clawock brief preflight` + `clawock brief postflight` → `clawock brief pre → post`
function lifecycle(message) {
  const seen = [...message.matchAll(/clawock (brief|report|intraday) (preflight|postflight)/g)];
  const kinds = [...new Set(seen.map((m) => m[1]))];
  return kinds.map((k) => `clawock ${k} preflight → postflight`).join(', ');
}

function took(ms) {
  if (!ms) return '—';
  const s = Math.round(ms / 1000);
  return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`;
}

function ago(ms) {
  if (!ms) return '—';
  const h = (Date.now() - ms) / 3600000;
  if (h < 1) return `${Math.round(h * 60)}m ago`;
  if (h < 48) return `${Math.round(h)}h ago`;
  return `${Math.round(h / 24)}d ago`;
}

const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;');

function html(rows) {
  const body = rows.map((r) => `<tr>
      <td class="name">${esc(r.name)}</td><td class="cron">${esc(r.cron)}</td>
      <td class="cmd">${esc(r.cmd)}</td>
      <td class="${r.status === 'ok' ? 'ok' : 'bad'}">${esc(r.status)}</td>
      <td class="dim">${esc(r.last)}</td><td class="dim num">${esc(r.took)}</td></tr>`).join('');
  return `<!doctype html><html><head><meta charset="utf-8"><style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { width: ${WIDTH}px; padding: 20px; background: #f3f4f6;
  font: 13px/1.55 ui-monospace, SFMono-Regular, Menlo, "DejaVu Sans Mono", "Noto Sans Mono CJK SC", monospace; }
.win { background: #1f2024; border-radius: 12px; overflow: hidden;
  box-shadow: 0 2px 6px rgba(0,0,0,.06), 0 14px 36px rgba(0,0,0,.16); }
.bar { height: 38px; display: flex; align-items: center; padding: 0 14px; background: #26272c;
  border-bottom: 1px solid #34353b; position: relative; }
.dot { width: 12px; height: 12px; border-radius: 50%; margin-right: 8px; }
.title { position: absolute; left: 0; right: 0; text-align: center; color: #9a9ca3;
  font: 13px -apple-system, "Segoe UI", "Noto Sans CJK SC", sans-serif; }
.term { padding: 22px 26px 24px; color: #c9ccd3; }
.prompt { color: #e8e9ec; margin-bottom: 12px; } .prompt b { color: #5fd7a7; font-weight: 400; }
table { border-collapse: collapse; width: 100%; }
th { text-align: left; color: #7d808a; font-weight: 400; padding: 0 14px 6px 0; }
td { padding: 3px 14px 3px 0; white-space: nowrap; }
.name { color: #e8e9ec; font-family: "Noto Sans CJK SC", "PingFang SC", sans-serif; }
.cron { color: #e5c07b; } .cmd { color: #7cc4f8; } .ok { color: #5fd7a7; } .bad { color: #f07178; }
.dim { color: #8b8e96; } .num { text-align: right; }
.foot { margin-top: 14px; color: #7d808a; }
</style></head><body><div class="win">
  <div class="bar"><span class="dot" style="background:#ff5f57"></span><span class="dot" style="background:#febc2e"></span><span class="dot" style="background:#28c840"></span>
    <span class="title">OpenClaw — the live desk's scheduled clawock jobs</span></div>
  <div class="term">
    <div class="prompt"><b>❯</b> openclaw cron list</div>
    <table><tr><th>job</th><th>cron · Asia/Shanghai</th><th>runs</th><th>last</th><th></th><th class="num">took</th></tr>${body}</table>
    <div class="foot">${rows.length} clawock jobs · ids, delivery targets and prompts omitted</div>
  </div></div></body></html>`;
}

async function main() {
  const rows = jobs()
    .filter((j) => j.enabled && /clawock (brief|report|intraday) preflight/.test((j.payload || {}).message || ''))
    .sort((a, b) => (a.state.nextRunAtMs || 0) - (b.state.nextRunAtMs || 0))
    .map((j) => ({
      name: j.name,
      cron: j.schedule.expr,
      cmd: lifecycle(j.payload.message),
      status: j.state.lastRunStatus || j.state.lastStatus || '—',
      last: ago(j.state.lastRunAtMs),
      took: took(j.state.lastDurationMs),
    }));
  if (!rows.length) throw new Error('no clawock jobs in `openclaw cron list`');
  const browser = await chromium.launch({ executablePath: CHROME_EXE });
  const page = await browser.newPage({ viewport: { width: WIDTH, height: 400 }, deviceScaleFactor: DSF });
  await page.setContent(html(rows));
  await page.evaluate(() => document.fonts.ready);
  await page.locator('body').screenshot({ path: OUT });
  await browser.close();
  console.log(`wrote ${OUT} (${rows.length} jobs)`);
}

main().catch((err) => { console.error(err); process.exit(1); });
