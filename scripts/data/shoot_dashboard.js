#!/usr/bin/env node
/**
 * shoot_dashboard.js — capture the live dashboard for the README + social cards.
 * Extracted from screenshot-refresh.yml (2026-05-30) so it's version-controlled and
 * runnable locally:
 *
 *   npm install playwright@1.60.0 && npx playwright install --with-deps chromium
 *   node scripts/data/shoot_dashboard.js
 *   python3 scripts/data/assemble_dashboard_gif.py   # assembles the GIF from frames
 *
 * Env overrides: URL (default live Pages), OUT_DIR (assets/), FRAME_DIR (.gifframes/),
 *                TMP_DIR (intermediates), CHROME_EXE (explicit browser binary).
 *
 * Outputs (all refresh weekly via the Action, so nothing drifts):
 *   assets/shadow-backtest.png   v2 cumulative win-rate chart (all / active / 50% ref)
 *   assets/social-card.png       1280x640 OG / Twitter card (headline + shot)
 *   assets/dashboard.gif         built from FRAME_DIR by assemble_dashboard_gif.py
 *   TMP_DIR/dashboard-preview.png  intermediate — embedded into the social card, not shipped
 *   .gifframes/f{0..5}.png       per-tab mobile frames → assemble_dashboard_gif.py
 *
 * assets/ is the one place shipped images live: README, Pages and the OG card all
 * point there, and _config.yml includes it. docs/ used to hold four PNGs of which
 * two were orphans re-committed weekly (architecture.png alone was 1.4MB) and one
 * was only ever an input to the social card. The architecture diagram is authored
 * as assets/architecture.svg and README embeds that SVG directly, so rendering it
 * to PNG produced a file nobody read.
 *
 * Notes:
 *   • deviceScaleFactor 2 → retina-crisp PNGs.
 *   • waits for the Hero panel to populate + every <canvas> to have real size before
 *     shooting — never captures mid-animation / blank charts.
 *   • the social card embeds the screenshot as a base64 data-URI (not file://) so it
 *     renders under snap-confined Chromium too.
 */
const { chromium, devices } = require('playwright');
const fs = require('fs');
const path = require('path');

const URL = process.env.URL || 'https://kcnyu.github.io/clawock/';
const ROOT = path.resolve(__dirname, '../..');
const OUT_DIR = process.env.OUT_DIR || path.join(ROOT, 'assets');
const FRAME_DIR = process.env.FRAME_DIR || path.join(ROOT, '.gifframes');
// Intermediate only: the social card inlines it as a data-URI, so it never ships.
const TMP_DIR = process.env.TMP_DIR || path.join(ROOT, '.gifframes');
const CHROME_EXE = process.env.CHROME_EXE || undefined;
const TABS = ['hero', 'drill', 'risk', 'market', 'plan', 'reflect'];

async function settle(page) {
  // 1) Hero panel populated (don't key off <canvas>: Hero has no chart → would hang).
  await page.waitForFunction(
    () => { const h = document.querySelector('[data-panel=hero]'); return h && h.textContent.trim().length > 200; },
    { timeout: 45000 },
  ).catch(() => {});
  // 2) Desktop shows every panel at once → all charts draw on load; wait for real size.
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

// Social card: dark panel with the honesty hook on the left, the screenshot framed on
// the right. Screenshot passed in as a base64 data-URI so no file:// read is needed.
function cardHTML(shotDataUri) {
  return `<!doctype html><html><head><meta charset="utf-8"><style>
  * { margin:0; padding:0; box-sizing:border-box; }
  html,body { width:1280px; height:640px; overflow:hidden; }
  body { font-family:-apple-system,"Segoe UI","Helvetica Neue","Noto Sans CJK SC",sans-serif;
    background:radial-gradient(120% 120% at 0% 0%,#16203a 0%,#0b1020 55%,#070a14 100%);
    color:#eef2fb; display:flex; align-items:center; position:relative; }
  .left { width:560px; padding:64px 0 64px 70px; flex:none; z-index:2; }
  .brand { display:flex; align-items:center; gap:12px; margin-bottom:30px; }
  .brand .dot { width:16px; height:16px; border-radius:50%;
    background:radial-gradient(circle at 35% 30%,#4fd18b,#1f9d63); box-shadow:0 0 18px #2fbd7a88; }
  .brand .name { font-size:30px; font-weight:800; letter-spacing:-.5px; }
  .brand .tag { font-size:15px; color:#8aa0c6; font-weight:600; }
  h1 { font-size:45px; line-height:1.13; font-weight:800; letter-spacing:-1px; margin-bottom:20px; max-width:490px; }
  h1 .hl { color:#ffca4a; }
  .sub { font-size:19px; line-height:1.5; color:#aebbd6; font-weight:500; max-width:455px; }
  .sub b { color:#e7edf9; font-weight:700; }
  .chips { display:flex; gap:10px; margin-top:34px; flex-wrap:wrap; }
  .chip { font-size:14.5px; font-weight:650; color:#cdd8ee; background:#ffffff12;
    border:1px solid #ffffff22; padding:7px 13px; border-radius:999px; }
  .repo { position:absolute; left:68px; bottom:44px; font-size:19px; font-weight:700; color:#7fb2ff;
    display:flex; align-items:center; gap:9px; }
  .repo .star { color:#ffca4a; }
  .shot { position:absolute; right:-30px; top:50%; transform:translateY(-50%) rotate(-2deg);
    width:690px; height:500px; border-radius:16px; overflow:hidden;
    box-shadow:0 40px 90px #000a,0 0 0 1px #ffffff1a; background:#fff; }
  .shot .bar { height:34px; background:#eef1f6; display:flex; align-items:center; gap:8px; padding:0 14px;
    border-bottom:1px solid #e2e6ee; }
  .shot .bar i { width:11px; height:11px; border-radius:50%; display:inline-block; }
  .shot .bar i:nth-child(1){background:#ff5f57} .shot .bar i:nth-child(2){background:#febc2e} .shot .bar i:nth-child(3){background:#28c840}
  .shot img { width:100%; height:466px; object-fit:cover; object-position:0 0; display:block; }
  .fade { position:absolute; right:0; top:0; bottom:0; width:180px; z-index:1;
    background:linear-gradient(90deg,rgba(11,16,32,0) 0%,rgba(7,10,20,0.4) 100%); pointer-events:none; }
</style></head><body>
  <div class="left">
    <div class="brand"><span class="dot"></span><span class="name">clawock</span><span class="tag">autonomous AI trading desk</span></div>
    <h1>It argues both sides, gates the risk — then <span class="hl">grades its own calls.</span></h1>
    <div class="sub">A daily bull-vs-bear LLM debate on <b>real HK + US money</b> — and a scorecard that <b>publishes its own record, unedited.</b></div>
    <div class="chips"><span class="chip">🗣️ bull-vs-bear swarm</span><span class="chip">🛡️ hard risk gates</span><span class="chip">🪞 self-grading</span><span class="chip">🤖 fully autonomous</span></div>
    <div class="repo"><span class="star">★</span> github.com/KCNyu/clawock</div>
  </div>
  <div class="shot"><div class="bar"><i></i><i></i><i></i></div><img src="${shotDataUri}"></div>
  <div class="fade"></div>
</body></html>`;
}

(async () => {
  [OUT_DIR, FRAME_DIR, TMP_DIR].forEach(d => fs.mkdirSync(d, { recursive: true }));
  const browser = await chromium.launch(CHROME_EXE ? { executablePath: CHROME_EXE, args: ['--no-sandbox'] } : {});
  try {
    // 1) Desktop 1440x900 @2x
    const desk = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 });
    const dp = await desk.newPage();
    await dp.goto(URL, { waitUntil: 'networkidle', timeout: 45000 });
    await settle(dp);
    await dp.screenshot({ path: `${TMP_DIR}/dashboard-preview.png`, fullPage: false });
    // Shoot the win-rate chart, not the whole card. The card used to be a money
    // curve and this shot was its portrait; the money view is gone (it summed
    // calls that were never executed against drifting marks) and what remains of
    // the card is mostly the note explaining its absence — a paragraph of prose
    // is not a README preview. The directional hit rate is the live claim.
    const shadow = dp.locator('#chart-ai-winrate');
    await shadow.waitFor({ state: 'visible', timeout: 45000 });
    await shadow.scrollIntoViewIfNeeded();
    await dp.waitForTimeout(900);
    await shadow.screenshot({ path: `${OUT_DIR}/shadow-backtest.png` });
    await desk.close();

    // 2) Social card (1280x640, matching index.html's og:image:width/height) —
    //    embeds the fresh desktop shot as a data-URI
    const shotUri = 'data:image/png;base64,' + fs.readFileSync(`${TMP_DIR}/dashboard-preview.png`).toString('base64');
    // dsf 1 → exactly 1280x640 (GitHub Social preview's ideal size + its 1MB limit;
    // 2x doubled it to 2560x1280 / >1MB and the upload wouldn't fit). Still crisp: the
    // embedded dashboard shot is downscaled from the 2x desktop capture.
    const cardCtx = await browser.newContext({ viewport: { width: 1280, height: 640 }, deviceScaleFactor: 1 });
    const cp = await cardCtx.newPage();
    await cp.setContent(cardHTML(shotUri), { waitUntil: 'networkidle' });
    await cp.waitForTimeout(300);
    await cp.screenshot({ path: `${OUT_DIR}/social-card.png` });
    await cardCtx.close();

    // 4) Per-tab mobile frames for the animated GIF (assembled by the python step).
    //    The panels scroll inside an internal container (body is fixed, so fullPage ==
    //    viewport). So we locate that container and screenshot the viewport at several
    //    scroll positions top→bottom → real vertical-scroll frames, then move to the
    //    next tab (the assembler adds the horizontal swipe between tabs).
    const VSCROLL = 5;   // scroll frames per tab (skipped when the tab barely scrolls)
    const gifCtx = await browser.newContext({ viewport: { width: 400, height: 860 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
    const gp = await gifCtx.newPage();
    await gp.goto(URL, { waitUntil: 'networkidle', timeout: 45000 });
    await gp.waitForFunction(() => { const h = document.querySelector('[data-panel=hero]'); return h && h.textContent.trim().length > 200; }, { timeout: 45000 }).catch(() => {});
    await gp.waitForTimeout(1500);
    const counts = [];
    for (let i = 0; i < TABS.length; i++) {
      await gp.click(`[data-tab=${TABS[i]}]`).catch(() => {});
      await gp.waitForTimeout(400);
      await gp.waitForFunction((tab) => {
        const panel = document.querySelector(`[data-panel=${tab}]`);
        if (!panel) return false;
        const cs = [...panel.querySelectorAll('canvas')];
        return cs.length === 0 || cs.every(c => c.width > 50);
      }, TABS[i], { timeout: 12000 }).catch(() => {});
      // find + remember the most-scrollable element around the active panel
      const over = await gp.evaluate((tab) => {
        const panel = document.querySelector(`[data-panel=${tab}]`);
        const scope = [];
        if (panel) { scope.push(panel); panel.querySelectorAll('*').forEach(e => scope.push(e)); }
        [document.scrollingElement, document.documentElement, document.body].forEach(e => e && scope.push(e));
        let best = null, mx = 0;
        for (const el of scope) { const o = el.scrollHeight - el.clientHeight; if (o > mx) { mx = o; best = el; } }
        window.__scrollEl = best;
        return mx;
      }, TABS[i]);
      const steps = over > 120 ? VSCROLL : 0;
      await gp.evaluate(() => { const el = window.__scrollEl; if (el) el.scrollTop = 0; else window.scrollTo(0, 0); });
      await gp.waitForTimeout(700);
      await gp.screenshot({ path: `${FRAME_DIR}/f${i}_0.png` });
      for (let j = 1; j <= steps; j++) {
        await gp.evaluate((frac) => { const el = window.__scrollEl; el.scrollTop = Math.round((el.scrollHeight - el.clientHeight) * frac); }, j / steps);
        await gp.waitForTimeout(320);
        await gp.screenshot({ path: `${FRAME_DIR}/f${i}_${j}.png` });
      }
      counts.push(steps + 1);
    }
    await gifCtx.close();

    console.log('gif frames per tab:', counts.join(','));

    console.log(`✓ win-rate chart + social card; ${TABS.length} gif frames → ${FRAME_DIR}`);
  } finally {
    await browser.close();
  }
})().catch((e) => { console.error(e); process.exit(1); });
