#!/usr/bin/env node
/**
 * shoot_dsh_plugin.js — capture the Decision Mind tab running inside a live
 * DeepSeek Harness, for README.md / README.zh.md.
 *
 * Why this one is not in `screenshot-refresh.yml` like the dashboard shots:
 * the picture's whole claim is "this plugin is running inside DSH, on a real
 * desk" — the harness chrome (workspace sidebar, Chat / Trajectory / Decision
 * Mind tab strip) is the evidence. A CI runner has no DSH and no desk, so it
 * can only be shot from a host that runs both. That makes it a *manual*
 * refresh, and this file exists so the next refresh is one command instead of
 * a re-derived Playwright script:
 *
 *   ops/host/install_dsh_plugin.sh --restart      # live plugin = the checkout
 *   node site/tools/shoot_dsh_plugin.js           # → site/assets/dsh-decision-mind.png
 *   clawock validate-sidecar screenshots          # same gate CI runs
 *
 * Re-shoot it whenever the tab's layout changes; a stale shot is worse than no
 * shot, because it advertises a UI the package no longer ships (the 2026-08-16
 * capture outlived three layout PRs before anyone noticed).
 *
 * Env: DSH_URL (default http://127.0.0.1:3081/ — the loopback origin, which
 *      skips Tailscale/nginx/HTTPS entirely), SESSION (substring of the
 *      session title to open), ROW (which fill to unfold, default the third),
 *      OUT (output path), CHROME_EXE, WIDTH/HEIGHT/DSF.
 */
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '../..');
const URL = process.env.DSH_URL || 'http://127.0.0.1:3081/';
const SESSION = process.env.SESSION || '';
const OUT = process.env.OUT || path.join(ROOT, 'site/assets/dsh-decision-mind.png');
// 1150x900 at 1.5x lands on ~1725x1320 — the width README renders at 860, with
// enough pixels left for the text to stay crisp on a retina screen.
const WIDTH = Number(process.env.WIDTH || 1150);
const HEIGHT = Number(process.env.HEIGHT || 900);
const DSF = Number(process.env.DSF || 1.5);
// Playwright's bundled Chromium; this host has no system Chrome since the snap
// was removed (2026-08-17).
const CHROME_EXE = process.env.CHROME_EXE
  || '/root/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome';

async function main() {
  const browser = await chromium.launch({
    executablePath: fs.existsSync(CHROME_EXE) ? CHROME_EXE : undefined,
    args: ['--no-sandbox'],
  });
  const page = await browser.newPage({
    viewport: { width: WIDTH, height: HEIGHT },
    deviceScaleFactor: DSF,
  });
  // `networkidle` never fires here: /plugins/events is a heartbeat-free SSE
  // stream, so the network is never idle. Wait on the DOM instead.
  await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(7000);

  // Open a session: the landing page is a workspace tree, and the session
  // title is the one handle that survived the 0.1.1-rc.2 sidebar rewrite.
  const session = SESSION
    ? page.getByText(SESSION, { exact: false }).first()
    : page.locator('aside a, aside li, [class*="session"]').first();
  await session.click({ timeout: 30000 });
  await page.waitForTimeout(6000);

  await page.getByText('Decision Mind', { exact: false }).first().click({ timeout: 30000 });
  await page.waitForTimeout(4000);

  // Reveal a couple more day groups, then open the newest fill so the capture
  // shows both halves of the view: the folded ledger rows and one unfolded
  // plan → fill → T+1 → P&L timeline.
  const more = page.getByText('显示更早的', { exact: false }).first();
  if (await more.count()) {
    await more.click().catch(() => {});
    await page.waitForTimeout(1200);
  }
  // [data-cell=trace] is a deliberate contract (class names are CSS-module
  // hashes and would break on every build).
  const rows = page.locator('[data-cell=trace]');
  const count = await rows.count();
  if (!count) throw new Error('no [data-cell=trace] rows — is CLAWOCK_WORKSPACE pointing at a desk?');
  // Not the first row: opening one further down keeps a few folded ledger rows
  // above the unfolded one, so the shot shows both states at once.
  await rows.nth(Math.min(Number(process.env.ROW || 2), count - 1)).click();
  await page.waitForTimeout(1200);
  // Park the pointer in the corner: a hovered row would ship a hover tint that
  // reads as a selected state nobody selected.
  await page.mouse.move(WIDTH - 2, HEIGHT - 2);
  await page.waitForTimeout(400);

  // Clip above the floating composer — it is the app's, not the plugin's, and
  // it covers the bottom rows.
  const composerTop = await page.evaluate(() => {
    const seats = [...document.querySelectorAll('textarea')];
    const box = seats.length ? seats[seats.length - 1].closest('div')?.getBoundingClientRect() : null;
    return box ? Math.round(box.top) : null;
  });
  const height = Math.max(400, Math.min(HEIGHT, (composerTop ?? HEIGHT) - 8));
  fs.mkdirSync(path.dirname(OUT), { recursive: true });
  await page.screenshot({ path: OUT, clip: { x: 0, y: 0, width: WIDTH, height } });
  const bytes = fs.statSync(OUT).size;
  console.log(`wrote ${path.relative(ROOT, OUT)} — ${WIDTH}x${height} @${DSF}x, ${bytes} bytes`);
  await browser.close();
}

main().catch((error) => { console.error(error); process.exit(1); });
