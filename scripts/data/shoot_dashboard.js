#!/usr/bin/env node
/**
 * shoot_dashboard.js — capture desktop + mobile screenshots of the live dashboard
 * for the README preview. Extracted from screenshot-refresh.yml (2026-05-30) so it's
 * version-controlled and runnable locally:
 *
 *   npm install playwright@1.60.0 && npx playwright install --with-deps chromium
 *   node scripts/data/shoot_dashboard.js
 *
 * Env overrides: URL (default live Pages), OUT_DIR (default docs/).
 *
 * Improvements over the old inline version:
 *   • deviceScaleFactor: 2 → retina-crisp PNGs (the old 1x looked soft on HiDPI)
 *   • waits for an ECharts <canvas> to actually render, then a short settle — instead of
 *     a blind 3.5s timeout that could fire mid-animation on a slow runner
 */
const { chromium, devices } = require('playwright');

const URL = process.env.URL || 'https://kcnyu.github.io/clawock/';
const OUT_DIR = process.env.OUT_DIR || 'docs';

async function settle(page) {
  // 1) Wait for the data to populate the Hero panel (don't key off <canvas>: the
  //    Hero tab has no chart since charts lazy-load — that wait would hang 45s).
  await page.waitForFunction(
    () => { const h = document.querySelector('[data-panel=hero]'); return h && h.textContent.trim().length > 200; },
    { timeout: 45000 },
  ).catch(() => {});
  // 2) On desktop the grid shows all panels at once → all charts draw on load; wait
  //    for every <canvas> to have real size so none is captured blank. On mobile only
  //    the (chart-less) Hero tab is visible, so don't wait (charts are lazy per tab).
  await page.waitForFunction(
    () => {
      if (!window.matchMedia('(min-width: 1024px)').matches) return true;
      const cs = [...document.querySelectorAll('canvas')];
      return cs.length > 0 && cs.every(c => c.width > 50);
    },
    { timeout: 15000 },
  ).catch(() => {});
  await page.waitForTimeout(2500);
}

(async () => {
  const browser = await chromium.launch();
  try {
    // Desktop 1440x900 @2x
    const desk = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      deviceScaleFactor: 2,
    });
    const dp = await desk.newPage();
    await dp.goto(URL, { waitUntil: 'networkidle', timeout: 45000 });
    await settle(dp);
    await dp.screenshot({ path: `${OUT_DIR}/dashboard-preview.png`, fullPage: false });
    await desk.close();

    // Mobile iPhone 12 (already @3x via device descriptor)
    const mob = await browser.newContext({ ...devices['iPhone 12'] });
    const mp = await mob.newPage();
    await mp.goto(URL, { waitUntil: 'networkidle', timeout: 45000 });
    await settle(mp);
    await mp.screenshot({ path: `${OUT_DIR}/dashboard-mobile.png`, fullPage: true });

    console.log(`✓ shot ${OUT_DIR}/dashboard-{preview,mobile}.png from ${URL}`);
  } finally {
    await browser.close();
  }
})().catch((e) => { console.error(e); process.exit(1); });
