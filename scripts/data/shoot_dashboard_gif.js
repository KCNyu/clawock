/*
 * shoot_dashboard_gif.js — record a smooth scroll-through of the LIVE dashboard
 * as a webm video, for the README hero GIF. The workflow (dashboard-gif.yml)
 * converts the webm → optimized GIF with ffmpeg.
 *
 * Why a GIF: a static screenshot undersells a live, scrolling dashboard. An
 * animated scroll-through is the single highest-converting README hero for an
 * interactive project.
 *
 * Tuning (env): URL, VID_DIR, plus W/H for the recorded viewport. Scroll is
 * bounded (MAX_SCROLL_PX) so the GIF stays small enough to embed.
 */
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const URL = process.env.URL || 'https://kcnyu.github.io/clawock/';
const VID_DIR = process.env.VID_DIR || '/tmp/clawock-vid';
const W = parseInt(process.env.W || '900', 10);
const H = parseInt(process.env.H || '620', 10);
const MAX_SCROLL_PX = parseInt(process.env.MAX_SCROLL_PX || '2600', 10);
const SCROLL_STEPS = 60;      // frames of scroll
const STEP_MS = 130;          // ~8s total scroll travel

// Resolve a usable chromium: env override → system chromium → Playwright bundled.
// (On the local box Playwright's pinned build may not match the cached one, so
// fall back to the system binary; in CI the bundled one exists.)
function chromiumOpts() {
  const cands = [process.env.CHROME_PATH, '/usr/bin/chromium-browser',
                 '/usr/bin/chromium', '/snap/bin/chromium'].filter(Boolean);
  for (const p of cands) {
    try { if (fs.existsSync(p)) return { executablePath: p }; } catch (_) { /* */ }
  }
  return {};  // let Playwright use its bundled browser
}

(async () => {
  fs.mkdirSync(VID_DIR, { recursive: true });
  const browser = await chromium.launch(chromiumOpts());
  const ctx = await browser.newContext({
    viewport: { width: W, height: H },
    deviceScaleFactor: 1,
    recordVideo: { dir: VID_DIR, size: { width: W, height: H } },
  });
  const page = await ctx.newPage();
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 60000 });
  await page.waitForSelector('canvas', { timeout: 45000 }).catch(() => {});
  await page.waitForTimeout(3000);          // let ECharts paint

  const maxScroll = await page.evaluate(
    (cap) => Math.max(0, Math.min(document.body.scrollHeight - window.innerHeight, cap)),
    MAX_SCROLL_PX);

  const video = page.video();
  await page.waitForTimeout(900);            // dwell on the hero
  for (let i = 0; i <= SCROLL_STEPS; i++) {
    const y = Math.round((maxScroll * i) / SCROLL_STEPS);
    await page.evaluate((_y) => window.scrollTo(0, _y), y);
    await page.waitForTimeout(STEP_MS);
  }
  await page.waitForTimeout(900);            // dwell at the bottom

  await ctx.close();                          // finalizes the webm
  const vp = await video.path();
  await browser.close();

  fs.writeFileSync(path.join(VID_DIR, 'video-path.txt'), vp);
  console.log('recorded video:', vp);
})().catch((e) => { console.error('gif recorder failed:', e); process.exit(1); });
