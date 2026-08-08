#!/usr/bin/env node
/**
 * shoot_dashboard.js — capture the live dashboard for the README + social cards.
 * Extracted from screenshot-refresh.yml (2026-05-30) so it's version-controlled and
 * runnable locally:
 *
 *   npm install playwright@1.60.0 && npx playwright install --with-deps chromium
 *   node site/tools/shoot_dashboard.js
 *   python3 site/tools/assemble_dashboard_gif.py   # assembles the GIF from frames
 *
 * Env overrides: URL (default live Pages), OUT_DIR (site/assets/), FRAME_DIR (.gifframes/),
 *                TMP_DIR (intermediates), CHROME_EXE (explicit browser binary).
 *
 * Outputs:
 *   site/assets/shadow-backtest.png   v2 cumulative win-rate chart (all / active / 50% ref)
 *   site/assets/social-card.png       1280x640 pearl editorial card + fresh Hero dashboard
 *   site/assets/dashboard.gif         manual dispatch only; built from FRAME_DIR
 *   TMP_DIR/dashboard-preview.png  focused light Hero crop embedded into the social card
 *   .gifframes/f{0..5}.png       per-tab mobile frames → assemble_dashboard_gif.py
 *
 * site/assets/ is the one place shipped images live: README, Pages and the OG card all
 * point there, and site/_config.yml includes it. docs/ used to hold four PNGs of which
 * two were orphans re-committed weekly (architecture.png alone was 1.4MB) and one
 * was only ever an input to the social card. The architecture diagram is authored
 * as site/assets/architecture.svg and README embeds that SVG directly, so rendering it
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
const BRAND_MARK_SVG = fs.readFileSync(path.join(ROOT, 'site/assets/logo-mark.svg'), 'utf8')
  .replace('<svg ', '<svg class="brand-mark" ');
const OUT_DIR = process.env.OUT_DIR || path.join(ROOT, 'site/assets');
const FRAME_DIR = process.env.FRAME_DIR || path.join(ROOT, '.gifframes');
// Intermediate only: the social card inlines it as a data-URI, so it never ships.
const TMP_DIR = process.env.TMP_DIR || path.join(ROOT, '.gifframes');
const CHROME_EXE = process.env.CHROME_EXE || undefined;
const CAPTURE_GIF = process.env.CAPTURE_GIF !== '0';
const TABS = ['hero', 'drill', 'risk', 'market', 'plan', 'reflect'];

async function settle(page) {
  // 1) Hero panel populated (don't key off <canvas>: Hero has no chart → would hang).
  await page.waitForFunction(
    () => { const h = document.querySelector('[data-panel=hero]'); return h && h.textContent.trim().length > 200; },
    { timeout: 45000 },
  ).catch(() => {});
  // 2) Both desktop and mobile now show ONE tab at a time (2026-07 redesign), so
  //    only the active panel's charts are drawn. Wait for the active panel's
  //    canvases to have real size — and pass immediately when it has none (Hero).
  await page.waitForFunction(
    () => {
      const active = document.querySelector('.panel.active');
      if (!active) return false;
      const cs = [...active.querySelectorAll('canvas')];
      return cs.length === 0 || cs.every(c => c.width > 50);
    },
    { timeout: 15000 },
  ).catch(() => {});
  await page.waitForTimeout(2500);
}

// Retained only as an earlier code-native fallback; socialCardHTML() below owns
// the current pearl editorial card and embeds the live UI directly.
function legacyCardHTML(shotDataUri) {
  void shotDataUri;
  return `<!doctype html><html><head><meta charset="utf-8"><style>
  * { margin:0; padding:0; box-sizing:border-box; }
  html,body { width:1280px; height:640px; overflow:hidden; }
  body {
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Helvetica Neue","PingFang SC",sans-serif;
    background:
      radial-gradient(circle at 86% 14%,rgba(92,222,203,.16),transparent 25%),
      radial-gradient(circle at 17% 104%,rgba(83,119,255,.14),transparent 34%),
      #071018;
    color:#f3f6f8; position:relative;
  }
  body::before {
    content:""; position:absolute; inset:0; pointer-events:none; opacity:.18;
    background-image:
      linear-gradient(rgba(184,217,225,.12) 1px,transparent 1px),
      linear-gradient(90deg,rgba(184,217,225,.12) 1px,transparent 1px);
    background-size:40px 40px;
    mask-image:linear-gradient(90deg,transparent 0%,#000 50%,#000 100%);
  }
  .frame { position:absolute; inset:30px; border:1px solid rgba(184,217,225,.17); }
  .brand {
    position:absolute; left:70px; top:56px; display:flex; align-items:center; gap:13px;
    font-size:28px; font-weight:780; letter-spacing:-.7px;
  }
  .mark { width:23px; height:23px; position:relative; }
  .mark i { position:absolute; display:block; border-radius:99px; }
  .mark i:nth-child(1) { width:23px; height:7px; left:0; top:0; background:#63dfce; }
  .mark i:nth-child(2) { width:15px; height:7px; left:0; top:8px; background:#79a7ff; }
  .mark i:nth-child(3) { width:8px; height:7px; left:0; top:16px; background:#f3c969; }
  .eyebrow {
    position:absolute; left:70px; top:129px; color:#8fa5ae;
    font-size:12px; font-weight:750; letter-spacing:.2em; text-transform:uppercase;
  }
  h1 {
    position:absolute; left:68px; top:166px; width:720px;
    font-size:58px; line-height:1.055; font-weight:760; letter-spacing:-2.8px;
  }
  h1 .quiet { color:#9aabb2; }
  h1 .honest { color:#63dfce; }
  .sub {
    position:absolute; left:72px; top:425px; width:660px;
    color:#aab9bf; font-size:17px; line-height:1.55; font-weight:470;
  }
  .sub b { color:#e9f0f2; font-weight:680; }
  .repo {
    position:absolute; left:70px; bottom:57px; display:flex; align-items:center; gap:12px;
    color:#dce7ea; font-size:16px; font-weight:680; letter-spacing:.01em;
  }
  .repo::before { content:""; width:32px; height:1px; background:#63dfce; }
  .protocol {
    position:absolute; right:72px; top:72px; width:372px; height:496px;
    border:1px solid rgba(184,217,225,.22); background:rgba(8,20,29,.72);
    box-shadow:0 28px 80px rgba(0,0,0,.3); backdrop-filter:blur(8px);
  }
  .protocol::before {
    content:"HONESTY PROTOCOL"; position:absolute; top:-1px; right:-1px;
    padding:9px 13px; background:#63dfce; color:#071018;
    font-size:10px; font-weight:850; letter-spacing:.16em;
  }
  .rail { position:absolute; left:51px; top:69px; bottom:57px; width:1px; background:rgba(184,217,225,.26); }
  .step {
    position:relative; height:144px; padding:45px 31px 22px 88px;
    border-bottom:1px solid rgba(184,217,225,.14);
  }
  .step:last-child { border-bottom:0; }
  .node {
    position:absolute; left:37px; top:55px; width:29px; height:29px;
    border:1px solid currentColor; border-radius:50%; background:#0a1720;
    box-shadow:0 0 0 6px #0a1720;
  }
  .node::after { content:""; position:absolute; inset:8px; border-radius:50%; background:currentColor; }
  .argue { color:#79a7ff; }
  .gate { color:#f3c969; }
  .grade { color:#63dfce; }
  .verb { color:#f4f7f8; font-size:30px; line-height:1; font-weight:770; letter-spacing:-1px; }
  .desc { margin-top:9px; color:#879ba4; font-size:13px; font-weight:560; letter-spacing:.025em; }
  .opposition { display:flex; align-items:center; gap:8px; margin-top:12px; width:192px; }
  .opposition span { height:4px; border-radius:4px; flex:1; }
  .opposition span:first-child { background:#79a7ff; }
  .opposition span:last-child { background:#ec7f88; }
  .opposition i { width:7px; height:7px; border:1px solid #d6e1e4; transform:rotate(45deg); }
  .gate-line { display:flex; gap:5px; margin-top:12px; }
  .gate-line i { width:8px; height:8px; border:1px solid rgba(243,201,105,.7); }
  .gate-line i:nth-child(3) { background:#f3c969; }
  .loop { width:56px; height:12px; margin-top:10px; border:1px solid #63dfce;
    border-top-color:transparent; border-radius:0 0 30px 30px; position:relative; }
  .loop::after { content:""; position:absolute; right:-2px; top:-4px; width:7px; height:7px;
    border-top:2px solid #63dfce; border-right:2px solid #63dfce; transform:rotate(18deg); }
  .micro {
    position:absolute; right:18px; bottom:15px; color:#60757e;
    font:650 9px/1 ui-monospace,SFMono-Regular,Menlo,monospace; letter-spacing:.12em;
  }
</style></head><body>
  <div class="frame"></div>
  <div class="brand"><span class="mark"><i></i><i></i><i></i></span>clawock</div>
  <div class="eyebrow">a transparent, autonomous AI desk</div>
  <h1>It argues both sides,<br><span class="quiet">gates the risk — then</span><br><span class="honest">grades its own calls.</span></h1>
  <div class="sub">A bull-vs-bear desk on <b>real HK + US money</b>, with hard risk gates and a public scorecard that <b>publishes the record unedited.</b></div>
  <div class="repo">github.com/KCNyu/clawock</div>
  <div class="protocol">
    <div class="rail"></div>
    <div class="step argue"><span class="node"></span><div class="verb">ARGUE</div><div class="desc">bull thesis meets bear thesis</div><div class="opposition"><span></span><i></i><span></span></div></div>
    <div class="step gate"><span class="node"></span><div class="verb">GATE</div><div class="desc">risk rules decide what survives</div><div class="gate-line"><i></i><i></i><i></i><i></i><i></i></div></div>
    <div class="step grade"><span class="node"></span><div class="verb">GRADE</div><div class="desc">every call returns to the record</div><div class="loop"></div></div>
    <div class="micro">DEBATE / DISCIPLINE / RECEIPTS</div>
  </div>
</body></html>`;
}

function socialCardHTML(shotDataUri) {
  return `<!doctype html><html><head><meta charset="utf-8"><style>
  * { margin:0; padding:0; box-sizing:border-box; }
  html,body { width:1280px; height:640px; overflow:hidden; }
  body {
    font-family:-apple-system,"Segoe UI","Helvetica Neue","Noto Sans CJK SC",sans-serif;
    color:#141a21; display:flex; align-items:center; position:relative;
    background:
      radial-gradient(42% 60% at 84% 6%, rgba(110,170,220,.22), transparent 68%),
      radial-gradient(46% 58% at 4% 0%, rgba(255,255,255,.96), transparent 66%),
      radial-gradient(70% 90% at 26% 128%, rgba(206,220,232,.55), transparent 60%),
      linear-gradient(125deg,#fcfdfe 0%,#f4f6f9 54%,#e8eef3 100%);
  }
  /* hairline inner frame + faint top sheen for depth */
  body::before {
    content:""; position:absolute; inset:0; pointer-events:none; z-index:5;
    box-shadow: inset 0 0 0 1px rgba(120,140,158,.10);
    background: linear-gradient(180deg, rgba(255,255,255,.35), transparent 12%);
  }
  .left { width:588px; padding:56px 0 60px 72px; flex:none; z-index:3; }
  .brand { display:flex; align-items:center; gap:12px; margin-bottom:30px; }
  .brand-mark { width:30px; height:30px; flex:none; }
  .brand .name { font-size:30px; font-weight:800; letter-spacing:-.5px; }
  .eyebrow { margin-bottom:16px; color:#6a7885; font-size:12px; font-weight:800;
    letter-spacing:.17em; }
  h1 { font-size:42px; line-height:1.1; font-weight:820; letter-spacing:-1.2px;
    margin-bottom:22px; }
  h1 .hl {
    background:linear-gradient(92deg,#1f2a34 8%,#4d708a 96%);
    -webkit-background-clip:text; background-clip:text; -webkit-text-fill-color:transparent;
  }
  .sub { font-size:18px; line-height:1.5; color:#5f6d79; font-weight:500; max-width:452px; }
  .sub b { color:#1e2831; font-weight:750; }
  .proof { display:flex; align-items:center; gap:9px; margin-top:28px;
    color:#4c5d6b; font:800 11px/1 ui-monospace,SFMono-Regular,Menlo,monospace;
    letter-spacing:.1em; }
  .proof i { width:22px; height:1px; background:linear-gradient(90deg,#aeb9c3,#6ea0c6); }
  .repo { position:absolute; left:72px; bottom:38px; font-size:17px; font-weight:700;
    color:#334653; display:flex; align-items:center; gap:11px; }
  .repo::before { content:""; width:22px; height:2px; border-radius:2px; background:#6d9fc5; }
  .shot {
    position:absolute; right:-30px; top:50%; transform:translateY(-50%) rotate(-2deg);
    width:706px; height:512px; border-radius:16px; overflow:hidden;
    box-shadow:
      0 40px 90px rgba(41,58,73,.20),
      0 0 0 1px rgba(88,110,128,.14),
      0 2px 10px rgba(41,58,73,.08);
    background:#fff; z-index:2;
  }
  .shot .bar { height:34px; background:linear-gradient(180deg,#fafbfc,#eef2f6);
    display:flex; align-items:center; gap:7px; padding:0 15px;
    border-bottom:1px solid #e3e8ee; }
  .shot .bar i { width:10px; height:10px; border-radius:50%; display:inline-block; }
  .shot .bar i:nth-child(1){background:#ff5f57}
  .shot .bar i:nth-child(2){background:#febc2e}
  .shot .bar i:nth-child(3){background:#28c840}
  .shot .address { width:150px; height:8px; margin-left:12px; border-radius:99px;
    background:#dae1ea; }
  .shot img { width:100%; height:478px; object-fit:cover; object-position:left top; display:block; }
</style></head><body>
  <div class="left">
    <div class="brand">
      ${BRAND_MARK_SVG}
      <span class="name">clawock</span>
    </div>
    <div class="eyebrow">DECISION WORKFLOWS · ANY AGENT · LIVE PROOF</div>
    <h1>Install decision<br><span class="hl">intelligence into<br>any agent.</span></h1>
    <div class="sub">Portable <b>evidence + opposition</b>, deterministic reconciliation, and outcome-linked improvement — proven on a real <b>HK + US desk.</b></div>
    <div class="proof"><span>EVIDENCE</span><i></i><span>OPPOSE</span><i></i><span>RECONCILE</span><i></i><span>IMPROVE</span></div>
    <div class="repo">github.com/KCNyu/clawock</div>
  </div>
  <div class="shot"><div class="bar"><i></i><i></i><i></i><span class="address"></span></div><img src="${shotDataUri}" alt=""></div>
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
    // Shoot the win-rate chart, not the whole card. The card used to be a money
    // curve and this shot was its portrait; the money view is gone (it summed
    // calls that were never executed against drifting marks) and what remains of
    // the card is mostly the note explaining its absence — a paragraph of prose
    // is not a README preview. The directional hit rate is the live claim.
    // It lives on the Reflect tab, which desktop renders lazily now → open it first.
    await dp.click('[data-tab=reflect]').catch(() => {});
    await dp.waitForFunction(() => {
      const c = document.querySelector('#chart-ai-winrate canvas');
      return c && c.width > 50;
    }, { timeout: 45000 }).catch(() => {});
    const shadow = dp.locator('#chart-ai-winrate');
    await shadow.waitFor({ state: 'visible', timeout: 45000 });
    await shadow.scrollIntoViewIfNeeded();
    await dp.waitForTimeout(900);
    await shadow.screenshot({ path: `${OUT_DIR}/shadow-backtest.png` });
    await desk.close();

    // 2) Social card: a pearl/graphite editorial field with one restrained blue
    //    accent and a real light dashboard in a tilted browser.
    const socialDesk = await browser.newContext({
      viewport: { width: 1200, height: 760 },
      deviceScaleFactor: 2,
      colorScheme: 'light',
    });
    const sp = await socialDesk.newPage();
    await sp.goto(URL, { waitUntil: 'networkidle', timeout: 45000 });
    await settle(sp);
    await sp.screenshot({
      path: `${TMP_DIR}/dashboard-preview.png`,
      clip: { x: 0, y: 0, width: 1200, height: 760 },
    });
    await socialDesk.close();

    const shotUri = 'data:image/png;base64,' + fs.readFileSync(`${TMP_DIR}/dashboard-preview.png`).toString('base64');
    const cardCtx = await browser.newContext({ viewport: { width: 1280, height: 640 }, deviceScaleFactor: 1 });
    const cp = await cardCtx.newPage();
    await cp.setContent(socialCardHTML(shotUri), { waitUntil: 'networkidle' });
    await cp.waitForTimeout(300);
    await cp.screenshot({ path: `${OUT_DIR}/social-card.png` });
    await cardCtx.close();

    // 3) Per-tab mobile frames for the animated GIF (manual refresh only).
    //    The panels scroll inside an internal container (body is fixed, so fullPage ==
    //    viewport). So we locate that container and screenshot the viewport at several
    //    scroll positions top→bottom → real vertical-scroll frames, then move to the
    //    next tab (the assembler adds the horizontal swipe between tabs).
    if (CAPTURE_GIF) {
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
      console.log(`✓ win-rate chart + social card; ${TABS.length} gif tabs → ${FRAME_DIR}`);
    } else {
      console.log('✓ win-rate chart + social card; GIF frame capture skipped');
    }
  } finally {
    await browser.close();
  }
})().catch((e) => { console.error(e); process.exit(1); });
