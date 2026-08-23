#!/usr/bin/env node
/**
 * Render the "decision card" example into site/assets/decision-card-example.png
 * for the plugin README: the receipt card an agent hands back after one
 * investment-decision run. It is a *styled example* of the printed template in
 * skills/investment-decision/SKILL.md, not a capture of a live run — the label
 * on the card says so, and the README caption says so.
 *
 *   node site/tools/shoot_decision_card.js
 */
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '../..');
const OUT = process.env.OUT || path.join(ROOT, 'site/assets/decision-card-example.png');
const WIDTH = 980;
const HEIGHT = 560;
const DSF = 1.5;
const CHROME_EXE = process.env.CHROME_EXE
  || '/root/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome';

const html = `<!doctype html>
<html><head><meta charset="utf-8"><style>
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { width: ${WIDTH}px; height: ${HEIGHT}px; overflow: hidden; }
body {
  font: 16px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  background: linear-gradient(160deg, #eef2f8 0%, #e8edf6 60%, #e6ecf7 100%);
  display: flex; align-items: center; justify-content: center;
  -webkit-font-smoothing: antialiased;
}
.frame {
  width: 880px; padding: 34px 40px 30px;
  background: #ffffff; border: 1px solid rgba(17,24,39,.08);
  border-radius: 18px;
  box-shadow: 0 4px 12px rgba(0,0,0,.02), 0 12px 32px rgba(0,0,0,.08);
}
.tag {
  display: inline-block; font-size: 11px; font-weight: 600; letter-spacing: .08em;
  color: #9aa3af; text-transform: uppercase; margin-bottom: 14px;
}
.head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 4px; }
.head .subj { font-size: 20px; font-weight: 700; letter-spacing: -.01em; color: #15171b; }
.head .subj b { color: #4176e6; }
.head .id { margin-left: auto; font: 11px ui-monospace, SFMono-Regular, Menlo, monospace; color: #adb2b8; }
.row { display: flex; gap: 12px; padding: 13px 2px; border-top: 1px solid rgba(17,24,39,.05); align-items: baseline; }
.row .k { flex: none; width: 86px; font-size: 12px; font-weight: 600; color: #81858c; letter-spacing: .03em; }
.row .v { font-size: 14.5px; color: #2a2e35; }
.row .cite { flex: none; margin-left: auto; font-size: 11px; color: #adb2b8; font-variant-numeric: tabular-nums; }
.cta { display: flex; gap: 10px; align-items: center; margin-top: 18px; padding-top: 16px; border-top: 1px solid rgba(17,24,39,.08); }
.pill { display: inline-block; padding: 5px 12px; border-radius: 999px; font-size: 12.5px; font-weight: 600; }
.pill.ok { background: #e6faed; color: #1b8644; }
.pill.brand { background: rgba(65,118,230,.08); color: #4176e6; }
.note { font-size: 11.5px; color: #9aa3af; margin-left: auto; }
</style></head>
<body>
<div class="frame">
  <div class="tag">Clawock receipt · example output — 决策卡 · 示例,非真实结算</div>
  <div class="head">
    <span class="subj">Subject <b>00100</b> (HK/HKD) 加仓评估</span>
    <span class="id">decision_id&nbsp;example-2026-08-08</span>
  </div>
  <div class="row"><span class="k">Bull 看多</span><span class="v">营收 YoY +159%,入通与海外霸榜催化,主仓增持信号</span><span class="cite">[2 citing]</span></div>
  <div class="row"><span class="k">Bear 看空</span><span class="v">估值高于五年区间,净利率为负,资不抵债</span><span class="cite">[1 citing]</span></div>
  <div class="row"><span class="k">Thesis 论点</span><span class="v">增长真实,但价格不补偿风险——先观察,不追</span></div>
  <div class="row"><span class="k">Invalidation</span><span class="v">站回 340 企稳 / 缩量</span></div>
  <div class="cta">
    <span class="pill ok">Confidence 0.70</span>
    <span class="pill brand">Action watch · 观望</span>
    <span class="note">模型不能自评——价格、账本、战绩由 Python 独立结算</span>
  </div>
</div>
</body></html>`;

(async () => {
  const browser = await chromium.launch({
    executablePath: fs.existsSync(CHROME_EXE) ? CHROME_EXE : undefined,
    args: ['--no-sandbox'],
  });
  try {
    const page = await browser.newPage({
      viewport: { width: WIDTH, height: HEIGHT },
      deviceScaleFactor: DSF,
    });
    await page.setContent(html, { waitUntil: 'load' });
    await page.waitForTimeout(300);
    fs.mkdirSync(path.dirname(OUT), { recursive: true });
    await page.screenshot({ path: OUT });
    console.log(`wrote ${path.relative(ROOT, OUT)} — ${WIDTH}x${HEIGHT} @${DSF}x, ${fs.statSync(OUT).size} bytes`);
  } finally {
    await browser.close();
  }
})().catch((err) => { console.error(err); process.exit(1); });
